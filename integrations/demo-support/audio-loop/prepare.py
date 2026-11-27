"""Clip, gain-limit and package an existing audio file for offline audition."""
import argparse
import base64
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf


def metrics(audio, rate):
    return {
        "frames": len(audio), "channels": audio.shape[1], "sample_rate": rate,
        "duration_seconds": len(audio) / rate,
        "rms_dbfs": 20 * math.log10(max(float(np.sqrt(np.mean(audio**2))), 1e-12)),
        "peak_dbfs": 20 * math.log10(max(float(np.max(np.abs(audio))), 1e-12)),
        "seam_jump": float(np.max(np.abs(audio[-1] - audio[0]))),
        "first_sample": audio[0].tolist(), "last_sample": audio[-1].tolist(),
        "finite": bool(np.isfinite(audio).all()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--duration", type=float, default=28.8)
    parser.add_argument("--target-rms-db", type=float, default=-20)
    parser.add_argument("--peak-limit-db", type=float, default=-1)
    args = parser.parse_args()
    if not all(math.isfinite(value) for value in (args.start, args.duration, args.target_rms_db, args.peak_limit_db)):
        raise ValueError("Audio parameters must be finite")
    if args.start < 0 or not 1 <= args.duration <= 90 or not -60 <= args.target_rms_db <= 0 or not -24 <= args.peak_limit_db <= 0:
        raise ValueError("Audio parameters outside declared bounds")
    source = args.input.resolve()
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError("Output version already exists; preserve it")
    with source.open("rb") as stream:
        source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    audio, rate = sf.read(source, dtype="float32", always_2d=True)
    if audio.shape[1] not in (1, 2) or not np.isfinite(audio).all():
        raise ValueError("Expected finite mono or stereo audio")
    start = round(args.start * rate)
    end = start + round(args.duration * rate)
    if end > len(audio):
        raise ValueError("Requested clip leaves source")
    clip = audio[start:end].copy()
    fade = round(0.08 * rate)
    weights = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
    crossfade = np.concatenate([clip[fade:-fade], clip[-fade:] * (1 - weights) + clip[:fade] * weights])
    output.mkdir(parents=True)
    records = {}
    assets = {}
    for name, candidate in (("direct", clip), ("crossfade", crossfade)):
        rms = float(np.sqrt(np.mean(candidate**2)))
        peak = float(np.max(np.abs(candidate)))
        if rms < 1e-8:
            raise ValueError("Silent clip cannot support audition")
        gain = min(10 ** (args.target_rms_db / 20) / rms, 10 ** (args.peak_limit_db / 20) / peak)
        path = output / f"{name}.ogg"
        with sf.SoundFile(path, "w", samplerate=rate, channels=candidate.shape[1], format="OGG", subtype="VORBIS") as stream:
            for offset in range(0, len(candidate), 4096):
                stream.write(candidate[offset:offset + 4096] * gain)
        decoded, decoded_rate = sf.read(path, dtype="float32", always_2d=True)
        if not np.isfinite(decoded).all() or np.max(np.abs(decoded)) >= 1:
            raise ValueError("Encoded signal clips or contains nonfinite values")
        encoded = path.read_bytes()
        records[name] = {**metrics(decoded, decoded_rate), "gain": gain, "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}
        assets[name] = {"base64": base64.b64encode(encoded).decode(), "frames": len(decoded), "sampleRate": decoded_rate}
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != source_hash:
            raise RuntimeError("Source changed during processing; preserve output for diagnosis")
    report = {
        "source": str(source), "source_sha256": source_hash,
        "source_metrics": metrics(audio, rate),
        "clip": {"start_seconds": args.start, "requested_duration_seconds": args.duration, "crossfade_seconds": 0.08},
        "target_rms_dbfs": args.target_rms_db, "peak_limit_dbfs": args.peak_limit_db,
        "outputs": records,
        "scope": "decoded signal and packaging checks; musical seam, loudness preference and game mix require listening",
    }
    (output / "analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    template = (Path(__file__).parent / "player-template.html").read_text(encoding="utf-8")
    if template.count("__ASSETS_JSON__") != 1:
        raise ValueError("Player embedding marker changed")
    (output / "player.html").write_text(template.replace("__ASSETS_JSON__", json.dumps(assets)), encoding="utf-8")
    print(json.dumps({"output": str(output), "variants": records}, ensure_ascii=False))


if __name__ == "__main__":
    main()
