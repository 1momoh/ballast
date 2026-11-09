"""Fresh human receipts from supported Hermes lifecycle hooks; never model arguments."""
import secrets
import json
import threading
import time

from .core import Refused


class HumanGate:
    def __init__(self, engine, cron=lambda: None, clock=time.time):
        self.engine, self.cron, self.clock = engine, cron, clock
        self.pending = {}
        self.lock = threading.Lock()

    def before_tool(self, tool_name='', args=None, task_id='', **kwargs):
        if tool_name != 'ballast_apply' or not isinstance(args, dict) or args.get('dry_run', True) is not False:
            return None
        try:
            if self.cron() is not None:
                raise Refused('Scheduled cleanup is refused; an interactive human must approve.')
            token = args.get('plan_token')
            engine = self.engine()
            with engine.locked():
                plan = engine.load_plan(token)
            if not plan['reachable'] or not plan['chosen']:
                raise Refused('Target unreachable or empty; create a reachable plan first.')
            key = 'ballast:' + secrets.token_hex(24)
            with self.lock:
                self.pending = {k: v for k, v in self.pending.items() if v['expires'] > self.clock()}
                self.pending[(token, task_id)] = dict(pattern='plugin_rule:' + key, requested=False,
                                                       approved=False, expires=plan['expires_at'])
            actions = '\n'.join(f"{json.dumps(i['id'])}: {json.dumps(i['path'])} — {i['size_bytes']} allocated bytes; {i['action']}" for i in plan['chosen'])
            return dict(action='approve', rule_key=key,
                        message=f"Permanently remove Ballast plan {plan['id']} ({plan['projected_freed']} projected bytes).\n{actions}\nRe-download/rebuild required; APFS may free less. A fresh human answer is mandatory.")
        except (Refused, OSError, ValueError) as exc:
            return dict(action='block', message=str(exc))

    def request(self, pattern_key='', surface='', coalesced=False, **kwargs):
        with self.lock:
            for value in self.pending.values():
                if value['pattern'] == pattern_key and not coalesced and surface in ('cli', 'gateway'):
                    value['requested'] = True

    def response(self, pattern_key='', choice='', surface='', **kwargs):
        with self.lock:
            for value in self.pending.values():
                if value['pattern'] == pattern_key:
                    value['approved'] = value['requested'] and surface in ('cli', 'gateway') and choice in ('once', 'session', 'always')

    def take(self, token, task_id=''):
        with self.lock:
            value = self.pending.pop((token, task_id), None)
        return bool(value and value['expires'] > self.clock() and value['approved'])
