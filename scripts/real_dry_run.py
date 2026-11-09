"""Read-only real dry run: scan + plan only. Never calls apply or any cleaner."""
import json, sys, time, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin'))
from ballast.core import Engine

def runner(argv, *, env, cwd):
    # Only the read-only docker report is permitted.
    if len(argv) >= 3 and argv[1:3] == ['system', 'df']:
        from ballast.core import subprocess_runner
        return subprocess_runner(argv, env=env, cwd=cwd)
    raise RuntimeError('real dry run forbids command: %r' % (argv,))

out = ROOT / 'tmp' / 'real-dry-run'
eng = Engine(Path.home(), out / 'data', Path.home() / '.hermes', runner=runner, which=shutil.which)
t = time.time(); scan = eng.scan(); ts = time.time() - t
p15 = eng.plan('15 GB')
pall = eng.plan(10**15)
json.dump({'scan_seconds': ts, 'scan': scan, 'plan_15gb': p15, 'plan_all': pall}, open(out / 'result.json', 'w'), indent=1, default=str)
print('scan seconds', round(ts, 1))
