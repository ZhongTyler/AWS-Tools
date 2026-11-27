"""Check fixed demo support sources without importing audio dependencies."""
import hashlib
import json
from pathlib import Path


def inspect(root):
    root = root.resolve()
    lock = json.loads((root / "source-lock.json").read_text(encoding="utf-8"))
    issues = []
    for record in lock["files"]:
        path = (root / record["path"]).resolve()
        if not path.is_relative_to(root):
            issues.append({"path": record["path"], "issue": "outside tool root"})
        elif not path.is_file():
            issues.append({"path": record["path"], "issue": "missing"})
        elif hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            issues.append({"path": record["path"], "issue": "hash changed"})
    return {"status": "error" if issues else "pass", "files_checked": len(lock["files"]),
            "issues": issues, "writes": False, "model_loaded": False,
            "scope": "fixed source identity; game integration and audio listening remain project checks"}


if __name__ == "__main__":
    result = inspect(Path(__file__).parent)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result["issues"] else 0)
