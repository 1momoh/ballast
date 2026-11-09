#!/bin/bash
# Restore only the populated Ballast demo home. Quit the isolated demo app first.
set -euo pipefail
exec /usr/bin/python3 -B - "$@" <<'PY'
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time

ROOT = Path('/Users/a87/Projects/Ballast')
TARGET = Path('/Users/a87/BallastDemoHome')
ARCHIVE = ROOT / 'tmp/demo-home-snapshot.tar'
parser = argparse.ArgumentParser(description='Restore exactly /Users/a87/BallastDemoHome from the verified local snapshot. Quit its users first.')
parser.add_argument('--check', action='store_true', help='Validate snapshot and target without restoring')
parser.add_argument('target', nargs='?', default=str(TARGET))
options = parser.parse_args()
# Compare the literal path too: aliases, symlinks and alternate targets are refused.
if options.target != str(TARGET) or TARGET.is_symlink() or TARGET.resolve() != TARGET:
    raise SystemExit('Refused: the only permitted target is /Users/a87/BallastDemoHome (no symlink).')
if not TARGET.is_dir() or TARGET.stat().st_uid != os.getuid():
    raise SystemExit('Refused: the demo target must be an existing directory owned by you.')
expected = (ARCHIVE.with_suffix('.tar.sha256')).read_text().split()[0]
digest = hashlib.sha256()
with ARCHIVE.open('rb') as stream:
    for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
        digest.update(chunk)
if digest.hexdigest() != expected:
    raise SystemExit('Refused: snapshot checksum mismatch.')
with tarfile.open(ARCHIVE) as archive:
    members = archive.getmembers()
    links = {m.name.rstrip('/') for m in members if m.issym() or m.islnk()}
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != TARGET.name:
            raise SystemExit('Refused: unsafe archive path.')
        if any(str(p) in links for p in path.parents):
            raise SystemExit('Refused: archive path traverses a link.')
        if not (member.isdir() or member.isfile() or member.issym() or member.islnk()):
            raise SystemExit('Refused: special archive entry.')
        if member.issym():
            dest = Path(os.path.normpath((TARGET.parent / str(path)).parent / member.linkname))
            if not dest.is_relative_to(TARGET):
                raise SystemExit('Refused: model/project link escapes the demo home.')
        if member.islnk():
            dest = PurePosixPath(member.linkname)
            if dest.is_absolute() or '..' in dest.parts or not dest.parts or dest.parts[0] != TARGET.name:
                raise SystemExit('Refused: hardlink escapes the snapshot.')
if options.check:
    print('PASS: exact owned target, snapshot SHA256, archive paths and links; no restore performed.')
    raise SystemExit(0)
# Extract before replacement so an extraction failure preserves the existing demo home.
staging = Path(tempfile.mkdtemp(prefix='demo-restore-', dir=ROOT / 'tmp'))
backup = staging / 'previous'
try:
    subprocess.run(['/usr/bin/tar', '-xpf', str(ARCHIVE), '-C', str(staging)], check=True,
                   env={'PATH':'/usr/bin:/bin', 'COPYFILE_DISABLE':'1'})
    restored = staging / TARGET.name
    if not restored.is_dir() or restored.is_symlink():
        raise RuntimeError('Snapshot did not produce the expected home.')
    info = restored.stat()
    # The writable root itself cannot be renamed: move only its children.
    backup.mkdir()
    moved_old, moved_new = [], []
    try:
        for child in sorted(TARGET.iterdir()):
            child.rename(backup / child.name)
            moved_old.append(child.name)
        for child in sorted(restored.iterdir()):
            child.rename(TARGET / child.name)
            moved_new.append(child.name)
    except BaseException:
        for name in reversed(moved_new):
            (TARGET / name).rename(restored / name)
        for name in reversed(moved_old):
            (backup / name).rename(TARGET / name)
        raise
    TARGET.chmod(stat.S_IMODE(info.st_mode))
    os.utime(TARGET, ns=(info.st_atime_ns, info.st_mtime_ns))
    # These are only the previous contents of the fixed demo target.
    shutil.rmtree(backup)
finally:
    if backup.exists():
        print('Previous demo home retained at', backup)
    else:
        shutil.rmtree(staging)
# Read a genuine safetensors header plus config, then refresh that model's atime.
model = TARGET / '.cache/huggingface/hub/models--Qwen--Qwen2.5-0.5B-Instruct'
config = next((model/'snapshots').glob('*/config.json'))
json.loads(config.read_text())
weights = next((model/'snapshots').glob('*/*.safetensors'))
with weights.open('rb') as stream:
    length = int.from_bytes(stream.read(8), 'little')
    if not 0 < length <= 16 * 1024 * 1024:
        raise RuntimeError('Unexpected safetensors header length.')
    json.loads(stream.read(length))
for path in (config, weights):
    info = path.stat()
    os.utime(path, ns=(max(time.time_ns(), info.st_mtime_ns), info.st_mtime_ns))
print('Restored exactly', TARGET, '; read Qwen config/safetensors header and refreshed last-touched time.')
print('Build new Ballast plans: restored inodes invalidate all older tokens.')
PY
