"""Validate/doctor or inspect Ballast through the same isolated Desktop backend; no GUI/model calls."""
import argparse
import json
import subprocess
from launch_desktop_demo import ROOT, SOURCE, PYTHON, HERMES, check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan', action='store_true', help='Dispatch the registered read-only ballast_scan tool')
    parser.add_argument('--plan', metavar='TARGET', help='Dispatch read-only ballast_plan, e.g. "3 GB"')
    options = parser.parse_args()
    env = check()
    if options.scan or options.plan:
        code = '''import json, sys
from hermes_cli.plugins import get_plugin_manager
from tools.registry import registry
manager = get_plugin_manager()
manager.discover_and_load()
action, args = json.loads(sys.argv[1])
reply = registry.dispatch('ballast_' + action, args, scope=manager.scope_key)
result = json.loads(reply) if isinstance(reply, str) else reply
print(json.dumps(result, indent=2))
raise SystemExit(0 if result.get('ok') else 1)
'''
        action = ('plan', {'target_bytes': options.plan}) if options.plan else ('scan', {})
        return subprocess.call([str(PYTHON), '-B', '-c', code, json.dumps(action)], cwd=SOURCE, env=env)
    for action in ('validate', 'doctor'):
        argv = [str(PYTHON), '-B', '-m', 'hermes_cli.main', 'plugins', action, str(HERMES/'plugins/ballast')]
        if action == 'doctor':
            argv += ['--ci']
        result = subprocess.run(argv, cwd=SOURCE, env=env, capture_output=True, text=True, timeout=90)
        output = result.stdout + result.stderr
        (ROOT/'evidence/mac-demo'/('desktop-cli-' + action + '.txt')).write_text(output)
        print(output, end='', flush=True)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
