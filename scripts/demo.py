"""<90-second fake-HOME demonstration. Simulated approval events are test fixtures."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin'))
from ballast.core import Engine, Refused
from ballast.approval import HumanGate


def main():
    base = Path(tempfile.mkdtemp(prefix='demo-', dir=ROOT / 'tmp'))
    home = base / 'home'; home.mkdir()
    os.environ['HOME'] = str(home)
    os.environ['HERMES_HOME'] = str(base / 'hermes')
    sizes = {'.npm/_cacache': 8, '.cache/uv': 2, 'Library/Caches/pip': 4,
             'Library/Developer/Xcode/DerivedData/DemoProject': 12, '.ollama/models': 16}
    for relative, mb in sizes.items():
        directory = home / relative; directory.mkdir(parents=True)
        path = directory / 'fake-cache.bin'
        path.write_bytes(b'B' * (mb * 1024 * 1024))
        os.utime(path, (time.time() - 60 * 86400,) * 2)
    personal = home / 'Documents/precious.txt'; personal.parent.mkdir(); personal.write_text('keep')
    def forbidden_runner(*args, **kwargs):
        raise AssertionError('Demo never executes a cache command.')
    engine = Engine(home, base / 'data', base / 'hermes', which=lambda _: None, runner=forbidden_runner)
    print('FAKE-HOME DEMO — no real caches, commands, model or native approval UI.\nHOME=' + str(home))
    plan = engine.plan('10 MB')
    print('\nI need 10 MB.\nChosen:', ', '.join(i['id'] for i in plan['chosen']))
    print('Projected bytes:', plan['projected_freed'], '| Regret:', plan['total_regret'])
    print('Kept:', '; '.join(row['item']['id'] + ': ' + row['reason'] for row in plan['left_out'] if row['item']['size_bytes']))
    print('\nDefault preview:', json.dumps(engine.apply(plan['plan_token'])['actions'], indent=2))
    try: engine.apply(plan['plan_token'], False)
    except Refused as exc: print('\nUnattended refusal:', str(exc))
    gate = HumanGate(lambda: engine)
    directive = gate.before_tool('ballast_apply', dict(plan_token=plan['plan_token'], dry_run=False), task_id='demo-fixture')
    pattern = 'plugin_rule:' + directive['rule_key']
    print('\nSimulating Hermes human-request/once-response hooks against fake data only.')
    gate.request(pattern_key=pattern, surface='cli')
    gate.response(pattern_key=pattern, surface='cli', choice='once')
    result = engine.apply(plan['plan_token'], False, approval=lambda token: gate.take(token, 'demo-fixture'))
    print(json.dumps(result, indent=2))
    assert personal.read_text() == 'keep'
    assert (home / '.ollama/models/fake-cache.bin').exists()
    print('\nPersonal file and optional model preserved. Ledger:', base / 'data/ledger.jsonl')


if __name__ == '__main__': main()
