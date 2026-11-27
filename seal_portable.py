"""Explicit maintenance step: hash the reviewed portable payload before the outer module seal."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

BASE = Path(__file__).resolve().parent

def seal(base=BASE, apply=False):
    base = base.resolve()
    profile = json.loads((base / 'portable-profile.json').read_text(encoding='utf-8'))
    tracked = set(subprocess.check_output(['git', '-C', str(base), '-c', 'core.quotepath=false', 'ls-files', '-z']).decode('utf-8').rstrip('\0').split('\0'))
    files = profile['files']
    if not isinstance(files, dict) or not files:
        raise ValueError('Empty portable payload')
    updated = {}
    for name in sorted(files):
        parts = PurePosixPath(name).parts
        if not parts or name.startswith('/') or '\\' in name or ':' in name or any(p in ('', '.', '..') for p in name.split('/')):
            raise ValueError('Invalid portable member: ' + name)
        path = base / name
        if name == 'portable-profile.json' or name == 'module-files.json' or name not in tracked:
            raise ValueError('Review and stage payload membership before sealing: ' + name)
        if any(p.is_symlink() or p.exists() and getattr(p.lstat(), 'st_file_attributes', 0) & 0x400 for p in [path, *path.parents]):
            raise ValueError('Linked payload is not supported: ' + name)
        if not path.resolve().is_relative_to(base) or not path.is_file():
            raise ValueError('Missing or escaping payload: ' + name)
        updated[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    changed = [name for name in updated if updated[name] != files[name]]
    if apply:
        profile['files'] = updated
        (base / 'portable-profile.json').write_bytes((json.dumps(profile, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    return {'files': len(updated), 'changed': changed, 'applied': apply,
            'next': 'Run toolbox health --integrity, then .module/module_manager.py seal --apply and verify'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(seal(apply=args.apply), ensure_ascii=False, indent=2))
