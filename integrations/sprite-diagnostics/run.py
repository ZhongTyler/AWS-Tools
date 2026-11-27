"""Fixed Ludo sprite diagnostics shared by Toolbox and the local Studio."""
import argparse
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from PIL import Image, PngImagePlugin

HERE = Path(__file__).resolve().parent
MAX_IMAGE = 4 * 1024 * 1024
MAX_PIXELS = 4 * 1024 * 1024
MAX_DIMENSION = 4096
MAX_FRAMES = 64
TIMEOUT = 20
ACTIONS = ("metrics", "loop", "slice", "export")
LOADED_ADAPTER = sha256(Path(__file__).read_bytes() + (HERE / "offline.mjs").read_bytes()).hexdigest()
OPTION_FIELDS = {"columns", "rows", "pivot", "durations_ms", "loop"}
WARNINGS = [
    "Feet, root motion and quality labels are heuristic suggestions. Review the animation in its intended use.",
    "Formal timing, events, sockets, rights and project adoption remain in the original asset workflow.",
]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate input field")
        result[key] = value
    return result


def fixed_runtime():
    if sha256(Path(__file__).read_bytes() + (HERE / "offline.mjs").read_bytes()).hexdigest() != LOADED_ADAPTER:
        raise ValueError("Offline adapter changed; reload this worker before running")
    lock = json.loads((HERE / "upstream-lock.json").read_bytes())
    vendor = HERE / "vendor"
    inventory = {p.relative_to(vendor).as_posix() for p in vendor.rglob("*") if p.is_file()}
    if inventory != lock["files"].keys() or any(
        (vendor / name).is_symlink() or sha256((vendor / name).read_bytes()).hexdigest() != value
        for name, value in lock["files"].items()
    ):
        raise ValueError("Fixed Ludo files changed; restore version 0.4.2 before use")
    node = shutil.which("node")
    if not node:
        raise ValueError("Existing Node 24+ runtime required")
    version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    if not version.startswith("v") or int(version[1:].split(".")[0]) < 24:
        raise ValueError("Existing Node 24+ permission runtime required")
    return node, version, sha256(canonical(lock)).hexdigest()


def prepare(action, raw, options):
    if action not in ACTIONS or not isinstance(options, dict) or options.keys() - OPTION_FIELDS:
        raise ValueError("Choose metrics, loop, slice or export with finite options")
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_IMAGE:
        raise ValueError("Choose one PNG up to 4 MiB")
    columns, rows = options.get("columns"), options.get("rows")
    if any(type(v) is not int or not 1 <= v <= MAX_FRAMES for v in (columns, rows)) or columns * rows > MAX_FRAMES:
        raise ValueError("Declare a grid of 1 to 64 frames")
    with Image.open(BytesIO(raw)) as image:
        width, height = image.size
        if (image.format != "PNG" or getattr(image, "n_frames", 1) != 1 or max(width, height) > MAX_DIMENSION
                or width * height > MAX_PIXELS or width % columns or height % rows):
            raise ValueError("Use a static PNG with an exactly divisible grid, at most 4096 per side and 4M pixels")
        image.load()
        pixels = image.convert("RGBA")
    frame = [width // columns, height // rows]
    pivot = options.get("pivot")
    if pivot is not None and (not isinstance(pivot, list) or len(pivot) != 2 or any(
        type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= frame[index]
        for index, value in enumerate(pivot)
    )):
        raise ValueError("Pivot must be explicit x/y pixels within one frame")
    durations = options.get("durations_ms")
    if durations is not None and (not isinstance(durations, list) or len(durations) != columns * rows or any(
        type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= 60000 for value in durations
    )):
        raise ValueError("Provide one finite duration in 1..60000 milliseconds per frame")
    if "loop" in options and type(options["loop"]) is not bool:
        raise ValueError("Loop must be a boolean")
    if action == "export" and (not durations or len(set(durations)) != 1 or pivot is None or "loop" not in options):
        raise ValueError("Simple Godot export requires equal frame durations, explicit pivot and loop; use the original atlas path for variable timing")
    normal = dict(options, columns=columns, rows=rows)
    return pixels, normal, frame


def split_interpretations(value, location=""):
    if isinstance(value, dict):
        values, interpretations = {}, []
        for key, entry in value.items():
            where = location + "/" + key
            if key in {"why", "verdict", "feet", "character", "kind", "pixels_per_unit"}:
                interpretations.append({"path": where, "value": entry})
            else:
                fixed, derived = split_interpretations(entry, where)
                values[key] = fixed
                interpretations.extend(derived)
        return values, interpretations
    if isinstance(value, list):
        values, interpretations = [], []
        for index, entry in enumerate(value):
            fixed, derived = split_interpretations(entry, location + "/" + str(index))
            values.append(fixed)
            interpretations.extend(derived)
        return values, interpretations
    return value, []


def execute(action, raw, options, output, *, timeout=TIMEOUT):
    image, normal, frame = prepare(action, raw, options)
    if type(timeout) not in (int, float) or not 0 < timeout <= TIMEOUT:
        raise ValueError("Offline timeout must be in (0,20] seconds")
    output = Path(output)
    if not output.is_absolute() or output.exists() or output.is_symlink() or output.parent.resolve() != output.parent:
        raise ValueError("Use a new absolute output directory under an existing physical parent")
    if not output.parent.is_dir():
        raise ValueError("Create the owned output parent first")
    node, node_version, fixed = fixed_runtime()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=".sprite-diagnostic-", dir=output.parent) as temp:
        job = Path(temp).resolve()
        (job / "artifacts").mkdir()
        # Keep upstream Godot project discovery inside this scratch root.
        (job / "project.godot").write_text('config_version=5\n[application]\nconfig/name="Sprite diagnostic"\n', encoding="utf-8")
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("ludo:grid", json.dumps({
            "cols": normal["columns"], "rows": normal["rows"], "frames": normal["columns"] * normal["rows"],
            "fps": 1000 / normal["durations_ms"][0] if normal.get("durations_ms") else 10,
            "loop": normal.get("loop", True),
        }))
        image.save(job / "input.png", pnginfo=metadata)
        (job / "operation.json").write_bytes(canonical(dict(normal, action=action)))
        env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH") if key in os.environ}
        env.update(HOME=str(job / "home"), USERPROFILE=str(job / "home"), TEMP=str(job), TMP=str(job),
                   LUDO_CONFIG_DIR=str(job / "config"), LUDO_CACHE_DIR=str(job / "cache"),
                   LUDO_TELEMETRY="0", DO_NOT_TRACK="1", LUDO_AUTO_UPDATE="0", LUDO_PREVIEW="0")
        command = [node, "--permission", "--allow-fs-read=" + str(HERE), "--allow-fs-read=" + str(job),
                   "--allow-fs-write=" + str(job), str(HERE / "offline.mjs")]
        try:
            process = subprocess.run(command, cwd=job, env=env, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ValueError("Offline action timed out; input preserved, retry with a new output") from None
        if process.returncode != 0:
            raise ValueError("Fixed offline action failed; input preserved: " + process.stderr.decode("utf-8", errors="replace")[:600])
        if len(process.stdout) > 1024 * 1024:
            raise ValueError("Offline report exceeds the response limit")
        result = json.loads(process.stdout, object_pairs_hook=unique_object)
        guard = json.loads((job / "guard.json").read_bytes())
        if guard != {"attempts": []}:
            raise ValueError("Offline action attempted an external operation")
        if result.get("grid", {}).get("frames") != normal["columns"] * normal["rows"]:
            raise ValueError("Upstream inferred fewer frames; use original atlas source for sparse or transparent trailing frames")
        result_paths = result.get("files", []) if action == "slice" else result.get("engine_files", [])
        if action == "export":
            result_paths = ["project.godot", "input.png", *result_paths]
        saved = []
        ready = job / "ready"
        ready.mkdir()
        for index, declared in enumerate(result_paths):
            source = Path(declared)
            source = source if source.is_absolute() else job / source
            source = source.absolute()
            if not source.is_relative_to(job) or source.resolve() != source or not source.is_file():
                raise ValueError("Upstream artifact escaped the owned output")
            name = source.name
            if any(entry["name"] == name for entry in saved):
                raise ValueError("Duplicate output filename")
            data = source.read_bytes()
            if len(data) > MAX_IMAGE * 4:
                raise ValueError("Output artifact exceeds the file limit")
            (ready / name).write_bytes(data)
            saved.append({"name": name, "sha256": sha256(data).hexdigest(), "bytes": len(data)})
        measurements, interpretations = split_interpretations(result)
        receipt = {
            "status": "complete", "action": action, "version": "ludo-offline-0.4.2-v1",
            "input_sha256": sha256(raw).hexdigest(), "input_pixels_sha256": sha256(image.tobytes()).hexdigest(),
            "options": normal, "frame_size": frame, "node": node_version, "upstream_identity": fixed, "adapter_identity": LOADED_ADAPTER,
            "measurements": measurements, "interpretations": interpretations, "artifacts": saved,
            "warnings": WARNINGS, "guard": guard, "elapsed_seconds": round(time.monotonic() - started, 4),
        }
        (ready / "receipt.json").write_bytes(canonical(receipt) + b"\n")
        if output.exists():
            raise ValueError("Output appeared concurrently; choose a new output")
        ready.rename(output)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=(*ACTIONS, "health"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "health":
            # Engineering inventory only. Do not start Node in default health.
            lock = json.loads((HERE / "upstream-lock.json").read_bytes())
            intact = all((HERE / "vendor" / key).is_file() and sha256((HERE / "vendor" / key).read_bytes()).hexdigest() == value
                         for key, value in lock["files"].items())
            if not intact:
                raise ValueError("Fixed vendor files changed")
            result = {"status": "pass", "version": lock["version"], "node_available": bool(shutil.which("node")),
                      "node_executed": False}
        else:
            if not args.input or not args.request or not args.output or args.input.is_symlink():
                raise ValueError("Provide a physical PNG, JSON options and new output directory")
            if args.input.stat().st_size > MAX_IMAGE or args.request.stat().st_size > 8192:
                raise ValueError("Input or options exceed the size limit")
            raw = args.input.read_bytes()
            result = execute(args.action, raw, json.loads(args.request.read_bytes(), object_pairs_hook=unique_object), args.output)
            if sha256(args.input.read_bytes()).hexdigest() != result["input_sha256"]:
                raise ValueError("Original input changed during processing")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
