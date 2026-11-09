"""Reproducible checks. Every child receives fake HOME and workspace-only state."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence'
OUT.mkdir(exist_ok=True)
ENV = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'SHELL', 'USER', 'LOGNAME', 'TERM') if key in os.environ}
ENV.update(HOME=str(ROOT / 'tmp/home'), HERMES_HOME=str(ROOT / 'tmp/hermes'),
           TMPDIR=str(ROOT / 'tmp/test-temp'), XDG_CACHE_HOME=str(ROOT / 'tmp/cache'),
           XDG_CONFIG_HOME=str(ROOT / 'tmp/config'), XDG_DATA_HOME=str(ROOT / 'tmp/data'),
           XDG_STATE_HOME=str(ROOT / 'tmp/state'), UV_CACHE_DIR=str(ROOT / 'tmp/uv-cache'),
           UV_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1')
for key in ('HOME', 'HERMES_HOME', 'TMPDIR', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'UV_CACHE_DIR'):
    Path(ENV[key]).mkdir(parents=True, exist_ok=True)
# A new isolated config disables credential adoption; no global profile is read.
(ROOT / 'tmp/hermes/config.yaml').write_text(json.dumps({'plugins': {'enabled': ['ballast'], 'isolation': 'host'},
    'auth': {'adopt_external_logins': False}, 'webapp': {'enabled': False}, 'updates': {'check': False}}))
CHECKS = [
    ('unit', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']),
    ('desktop-syntax', ['node', '--input-type=module', '--check'], ROOT / 'plugin/ballast/desktop/plugin.js'),
    ('desktop-render', ['node', '--experimental-vm-modules', 'tests/desktop.mjs']),
    ('runtime-integration', [sys.executable, 'scripts/runtime_probe.py']),
    ('demo', [sys.executable, 'scripts/demo.py']),
    ('hermes-version', ['/Users/a87/.local/bin/hermes', '--version']),
    ('hermes-validate', ['/Users/a87/.local/bin/hermes', 'plugins', 'validate', str(ROOT / 'plugin/ballast')]),
    ('hermes-doctor', ['/Users/a87/.local/bin/hermes', 'plugins', 'doctor', str(ROOT / 'plugin/ballast'), '--ci']),
]


def main():
    results = []
    for entry in CHECKS:
        name, argv = entry[:2]
        print('Running ' + name, flush=True)
        try:
            result = subprocess.run(argv, env=ENV, cwd=ROOT, text=True, input=entry[2].read_text() if len(entry) > 2 else None,
                                    capture_output=True, timeout=90)
            output = result.stdout + result.stderr
            code = result.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            output, code = str(exc), -1
        (OUT / (name + '.txt')).write_text(output)
        results.append(dict(name=name, argv=argv, stdin_file=str(entry[2]) if len(entry) > 2 else None,
                            exit_code=code, output=output))
        print(output[-6500:], flush=True)
    (OUT / 'checks.json').write_text(json.dumps(dict(environment=ENV, results=results), indent=2))
    return int(any(row['exit_code'] for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
