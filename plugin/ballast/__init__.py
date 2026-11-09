"""Hermes plugin entrypoint. Registration never scans caches or runs commands."""
import json
from pathlib import Path

from .approval import HumanGate
from .core import Engine, Refused


def runtime_engine():
    from plugins.plugin_storage import plugin_data_dir
    from hermes_constants import get_hermes_home
    from hermes_cli.config import load_config_readonly
    settings = load_config_readonly().get('plugins', {}).get('entries', {}).get('ballast', {}).get('settings', {})
    home = settings.get('scan_home', '')
    return Engine(Path.home() if home == '' else home, plugin_data_dir('ballast'), get_hermes_home())


PROPERTIES = {
    'scan': {},
    'plan': {'target_bytes': {'oneOf': [{'type': 'integer', 'minimum': 1}, {'type': 'string'}]},
             'exclude': {'type': 'array', 'items': {'type': 'string'}},
             'include_optional': {'type': 'array', 'items': {'type': 'string'}}},
    'apply': {'plan_token': {'type': 'string'}, 'dry_run': {'type': 'boolean', 'default': True}},
    'ledger': {}, 'status': {},
}
DESCRIPTIONS = {
    'scan': 'Read only: inspect known rebuildable macOS developer caches; never general personal files.',
    'plan': 'Choose the exact minimum total regeneration regret to meet target_bytes (for example "15 GB"). Returns a 15-minute signed plan; optional models need explicit opt-in.',
    'apply': 'Preview exact plan actions by default. dry_run=false permanently deletes caches ONLY after fresh human Hermes approval; unattended calls fail closed. Revalidate snapshot and record actual disk space.',
    'ledger': 'Read cleanup history and saved rebuild recipe locations.',
    'status': 'Read last plan, actual free space and cleanup history.',
}
SCHEMAS = {action: dict(name='ballast_' + action, description=DESCRIPTIONS[action],
                       parameters=dict(type='object', properties=properties, additionalProperties=False,
                                       required=['target_bytes'] if action == 'plan' else ['plan_token'] if action == 'apply' else []))
           for action, properties in PROPERTIES.items()}


def request(action, args, *, gate=None, task_id='', factory=runtime_engine):
    try:
        if action not in PROPERTIES or not isinstance(args, dict) or set(args) - set(PROPERTIES[action]):
            raise Refused('Unknown action or arguments.')
        engine = factory()
        if action == 'scan':
            reply = engine.scan()
            reply['sources'] = [engine.public_item(item) for item in reply['sources']]
        elif action == 'plan':
            reply = engine.plan(args.get('target_bytes'), args.get('exclude'), args.get('include_optional'))
        elif action == 'apply':
            reply = engine.apply(args.get('plan_token'), args.get('dry_run', True),
                                 approval=(lambda token: gate.take(token, task_id)) if gate else None)
        else:
            reply = getattr(engine, action)()
        return reply
    except (Refused, OSError, ValueError) as exc:
        return dict(ok=False, error=dict(code='refused', message=str(exc)))


def register(ctx):
    gate = HumanGate(runtime_engine, cron=ctx.current_cron_execution)
    ctx.register_hook('pre_tool_call', gate.before_tool)
    ctx.register_hook('pre_approval_request', gate.request)
    ctx.register_hook('post_approval_response', gate.response)
    for action, schema in SCHEMAS.items():
        def handler(args, _action=action, **kwargs):
            return json.dumps(request(_action, args, gate=gate, task_id=kwargs.get('task_id', '')))
        ctx.register_tool(name=schema['name'], toolset='ballast', schema=schema, handler=handler)

    def command(raw):
        try:
            if raw.lstrip().startswith('{'):
                body = json.loads(raw)
                if set(body) != {'action', 'args'} or body['action'] not in SCHEMAS:
                    raise Refused('Expected action and args.')
                if body['action'] == 'apply' and isinstance(body['args'], dict) and body['args'].get('dry_run', True) is not True:
                    raise Refused('Real cleanup requires a normal Hermes ballast_apply tool call so the human approval hooks execute. Slash commands can preview only.')
                return ctx.dispatch_tool('ballast_' + body['action'], body['args'])
            return ctx.dispatch_tool('ballast_plan', {'target_bytes': raw.strip()})
        except (ValueError, TypeError, AttributeError) as exc:
            return json.dumps(dict(ok=False, error=dict(code='invalid', message=str(exc))))
    ctx.register_command('ballast', command, description='Plan /ballast 15 GB, or inspect/preview with a JSON action. Real cleanup uses the normal tool approval flow.')
