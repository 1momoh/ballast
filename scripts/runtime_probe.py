"""Actual pinned Hermes hook/registry and ASGI checks, exclusively on a seeded fake HOME.

The test approval callback is a fixture, not a native human or model proof.
No Hermes core is patched. No cache command is launched.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('/Users/a87/Projects/PeelHere/tmp/compatibility/hermes-agent-ad4fa2f47cb689d4ca4a6ee465ab8d152b46cc73')
PYTHON = Path('/Users/a87/Projects/PeelHere/tmp/hermes/installs/ea094c1b20f774f5/environments/180d60ccd1e6488194208397c2b071e5/venv/bin/python')


def child():
    from hermes_cli.plugins import get_plugin_manager, resolve_pre_tool_block
    from tools.registry import registry
    from tools.approval_context import set_hermes_interactive_context, reset_hermes_interactive_context
    from tools.terminal_tool import set_approval_callback
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import importlib.util

    home = Path.home()
    assert home.is_relative_to(ROOT / 'tmp/runtime-probe')
    cache = home / 'Library/Developer/Xcode/DerivedData/ProbeProject'
    cache.mkdir(parents=True)
    payload = cache / 'fake-build.o'
    payload.write_bytes(b'B' * 1048576)
    personal = home / 'Documents/precious.txt'
    personal.parent.mkdir(); personal.write_text('keep me')
    manager = get_plugin_manager()
    manager.discover_and_load()
    def dispatch(action, args=None):
        result = registry.dispatch('ballast_' + action, args or {}, scope=manager.scope_key, task_id='runtime-fixture')
        return json.loads(result) if isinstance(result, str) else result
    assert dispatch('scan')['ok']
    plan = dispatch('plan', {'target_bytes': 1})
    assert plan['ok'] and plan['reachable']
    args = dict(plan_token=plan['plan_token'], dry_run=False)
    assert dispatch('apply', dict(plan_token=plan['plan_token']))['dry_run']
    assert not dispatch('apply', args)['ok'] and payload.exists()
    result = {'host': str(SOURCE), 'home': str(home), 'checks': []}
    result['checks'].append('Actual discovery and registered scan/plan/default dry-run; bare handler has no approval receipt and refuses')
    context = set_hermes_interactive_context(False)
    try:
        blocked = resolve_pre_tool_block('ballast_apply', args, task_id='runtime-fixture')
        assert blocked and payload.exists(), blocked
        result['checks'].append('Actual unattended host approval resolver refuses before mutation')
    finally:
        reset_hermes_interactive_context(context)
    context = set_hermes_interactive_context(True)
    try:
        set_approval_callback(lambda *a, **k: 'deny')
        assert resolve_pre_tool_block('ballast_apply', args, task_id='runtime-fixture') and payload.exists()
        result['checks'].append('Actual Hermes prompt callback deny leaves fake cache untouched')
        set_approval_callback(lambda *a, **k: 'once')
        blocked = resolve_pre_tool_block('ballast_apply', args, task_id='runtime-fixture')
        assert blocked is None, blocked
        applied = dispatch('apply', args)
        assert applied['ok'] and not payload.exists(), applied
        assert personal.read_text() == 'keep me'
        assert Path(applied['recipes']).exists()
        assert not dispatch('apply', args)['ok']
        result['checks'].append('Actual pre/request/post hooks + fixture once response + registered apply delete only fake data, consume token, write recipes and ledger')
    finally:
        set_approval_callback(None)
        reset_hermes_interactive_context(context)
    spec = importlib.util.spec_from_file_location('ballast_probe_api', Path(os.environ['HERMES_HOME']) / 'plugins/ballast/dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec); spec.loader.exec_module(api)
    app = FastAPI(); app.include_router(api.router, prefix='/api/plugins/ballast')
    with TestClient(app) as client:
        state = client.get('/api/plugins/ballast/status')
        assert state.status_code == 200 and state.json()['ledger'][-1]['event'] == 'completed'
        assert client.post('/api/plugins/ballast/apply', json=args).status_code == 404
        assert client.post('/api/plugins/ballast/preview', json={**args, 'approved': True}).json()['ok'] is False
        assert client.post('/api/plugins/ballast/plan', json={'target_bytes': 1, 'home': '/'}).json()['ok'] is False
        result['checks'].append('Real FastAPI router observes tool ledger; no REST apply route; forged approval and arbitrary roots rejected')
    result.update(ok=True, proof='pinned host hook resolver/registry + ASGI; simulated approval response; no model, live gateway or native Desktop')
    print(json.dumps(result, indent=2))


def main():
    base = ROOT / 'tmp/runtime-probe' / str(time.time_ns())
    home, hermes = base / 'home', base / 'hermes'
    (hermes / 'plugins').mkdir(parents=True)
    home.mkdir()
    shutil.copytree(ROOT / 'plugin/ballast', hermes / 'plugins/ballast')
    (hermes / 'config.yaml').write_text(json.dumps({'plugins': {'enabled': ['ballast'], 'isolation': 'host'},
        'auth': {'adopt_external_logins': False}, 'approvals': {'mode': 'manual'}}))
    for name in ['tmp', 'cache', 'empty-bin', 'config', 'data', 'state']:
        (base / name).mkdir()
    env = dict(PATH=str(base / 'empty-bin'), HOME=str(home), HERMES_HOME=str(hermes),
               PYTHONPATH=str(SOURCE), PYTHONDONTWRITEBYTECODE='1', UV_OFFLINE='1',
               TMPDIR=str(base / 'tmp'), XDG_CACHE_HOME=str(base / 'cache'),
               XDG_CONFIG_HOME=str(base / 'config'), XDG_DATA_HOME=str(base / 'data'),
               XDG_STATE_HOME=str(base / 'state'), LANG='en_US.UTF-8')
    argv = [str(PYTHON), str(Path(__file__).resolve()), '--child']
    result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=45)
    text = result.stdout + result.stderr
    (ROOT / 'evidence/runtime-probe.txt').write_text(text)
    (ROOT / 'evidence/runtime-probe-command.json').write_text(json.dumps(dict(argv=argv, environment=env, exit_code=result.returncode), indent=2))
    print(text)
    return result.returncode


if __name__ == '__main__':
    if '--child' in sys.argv: child()
    else: raise SystemExit(main())
