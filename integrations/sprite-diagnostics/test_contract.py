"""Behavioral contracts for the fixed offline producer and Studio download boundary."""
import base64
from hashlib import sha256
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

spec = importlib.util.spec_from_file_location("sprite_diagnostics_under_test", Path(__file__).with_name("run.py"))
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def png(last_pixels=16):
    picture = Image.new("RGBA", (16, 8))
    for x in range(4):
        for y in range(4):
            picture.putpixel((x + 1, y + 1), (255, 30, 40, 255))
    for n in range(last_pixels):
        picture.putpixel((9 + n % 4, 1 + n // 4), (255, 30, 40, 255))
    out = BytesIO()
    picture.save(out, format="PNG")
    return out.getvalue()


class SpriteDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.raw = png()
        self.options = {"columns": 2, "rows": 1, "durations_ms": [80, 80], "pivot": [4, 8], "loop": False}

    def tearDown(self):
        self.tmp.cleanup()

    def test_fixed_real_actions_pixel_roundtrip_and_once_export(self):
        for action in engine.ACTIONS:
            target = self.root / action
            receipt = engine.execute(action, self.raw, self.options, target)
            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(receipt["guard"], {"attempts": []})
            self.assertEqual(receipt["input_sha256"], sha256(self.raw).hexdigest())
            self.assertEqual(receipt["measurements"]["grid"]["frames"], 2)
            self.assertEqual(json.loads((target / "receipt.json").read_bytes()), receipt)
        for i, path in enumerate(sorted((self.root / "slice").glob("*.png"))):
            with Image.open(BytesIO(self.raw)) as source, Image.open(path) as frame:
                self.assertEqual(frame.convert("RGBA").tobytes(),
                                 source.crop((8 * i, 0, 8 * (i + 1), 8)).convert("RGBA").tobytes())
        exported = self.root / "export"
        self.assertIn('"loop": false', (exported / "input.tres").read_text())
        self.assertIn('"speed": 12.5', (exported / "input.tres").read_text())
        self.assertIn("offset = Vector2(0, -4)", (exported / "input.tscn").read_text())

    def test_sparse_trailing_frames_reject_inference_but_slice_keeps_every_pixel(self):
        for count in (0, 1, 3):
            raw = png(count)
            for action in ("metrics", "loop", "export"):
                target = self.root / (action + str(count))
                with self.assertRaisesRegex(ValueError, "fewer frames|action failed"):
                    engine.execute(action, raw, self.options, target)
                self.assertFalse(target.exists())
            target = self.root / ("slice" + str(count))
            result = engine.execute("slice", raw, self.options, target)
            self.assertEqual(len(result["artifacts"]), 2)
            with Image.open(target / "input-02.png") as frame, Image.open(BytesIO(raw)) as source:
                self.assertEqual(frame.convert("RGBA").tobytes(), source.crop((8, 0, 16, 8)).convert("RGBA").tobytes())

    def test_preflight_rejects_lossy_or_unbounded_requests(self):
        cases = [
            ("export", dict(self.options, durations_ms=[80, 240])),
            ("export", {"columns": 2, "rows": 1}),
            ("slice", dict(self.options, columns=3)),
            ("slice", dict(self.options, rows=True)),
            ("slice", dict(self.options, columns=65)),
            ("slice", dict(self.options, pivot=[-1, 0])),
            ("metrics", dict(self.options, command="account")),
            ("login", self.options),
        ]
        for i, (action, options) in enumerate(cases):
            target = self.root / ("invalid-" + str(i))
            with self.assertRaises(ValueError):
                engine.execute(action, self.raw, options, target)
            self.assertFalse(target.exists())
        for raw in (b"", b"not a PNG", b"x" * (engine.MAX_IMAGE + 1)):
            with self.assertRaises((ValueError, OSError)):
                engine.prepare("metrics", raw, self.options)
        large = BytesIO()
        Image.new("RGBA", (4097, 2)).save(large, format="PNG")
        with self.assertRaises(ValueError):
            engine.prepare("metrics", large.getvalue(), {"columns": 1, "rows": 1})

    def test_timeout_existing_destination_and_input_retention(self):
        source = self.root / "original.png"
        source.write_bytes(self.raw)
        target = self.root / "timeout"
        with self.assertRaisesRegex(ValueError, "timed out"):
            engine.execute("metrics", self.raw, self.options, target, timeout=0.00001)
        self.assertFalse(target.exists())
        self.assertEqual(source.read_bytes(), self.raw)
        target.mkdir()
        (target / "owned.txt").write_text("keep")
        with self.assertRaises(ValueError):
            engine.execute("metrics", self.raw, self.options, target)
        self.assertEqual((target / "owned.txt").read_text(), "keep")
        result = engine.execute("metrics", source.read_bytes(), self.options, self.root / "retry")
        self.assertEqual(result["status"], "complete")

    def test_node_permissions_and_actual_network_guard(self):
        node, _, _ = engine.fixed_runtime()
        job = self.root / "node"
        job.mkdir()
        (job / "artifacts").mkdir()
        (job / "input.png").write_bytes(self.raw)
        (job / "operation.json").write_text(json.dumps(dict(self.options, action="metrics")))
        outside = self.root / "outside.txt"
        outside.write_text("private")
        probe = (
            "import fs from 'node:fs';import {connect} from 'node:net';import cp from 'node:child_process';"
            "import {lookup,Resolver} from 'node:dns';import {connect as h2} from 'node:http2';"
            "let denied=0;"
            "for(const fn of [()=>fs.readFileSync(" + json.dumps(str(outside)) + "),"
            "()=>fs.writeFileSync(" + json.dumps(str(outside)) + ",'changed'),"
            "()=>connect(9,'127.0.0.1'),()=>cp.spawnSync(process.execPath,['--version']),"
            "()=>lookup('example.test',()=>{}),()=>new Resolver().resolve4('example.test',()=>{}),"
            "()=>h2('http://127.0.0.1:9')])"
            "{try{fn()}catch{denied++}}if(denied!==7)process.exitCode=3;"
        )
        command = [node, "--permission", "--allow-fs-read=" + str(engine.HERE),
                   "--allow-fs-read=" + str(job), "--allow-fs-write=" + str(job),
                   "--import", (engine.HERE / "offline.mjs").as_uri(), "--input-type=module", "-e", probe]
        result = subprocess.run(command, cwd=job, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outside.read_text(), "private")




if __name__ == "__main__":
    unittest.main()
