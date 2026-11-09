"""All cache trees, HOME, state and command runners are disposable and local."""
import builtins
import copy
import itertools
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin'))
from ballast import request, register, runtime_engine
from ballast.approval import HumanGate
from ballast.core import DATALESS, Engine, Refused, Safety, minimum_regret, subprocess_runner, target_bytes
from ballast.registry import CATALOG, DENIED


class BallastTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp/test-temp')
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.environment = patch.dict(os.environ, {'HOME': str(self.home), 'TMPDIR': str(self.base)})
        self.environment.start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.environment.stop)
        self.now = 1900000000.
        self.commands = []
        self.engine = Engine(self.home, self.base / 'data', self.home / '.hermes',
                             which=lambda _: None, runner=self.fake_runner, clock=lambda: self.now)

    def fake_runner(self, argv, **kwargs):
        self.commands.append((argv, kwargs))
        return dict(returncode=0, stdout='stub only', stderr='')

    def seed(self, relative='.npm/_cacache', size=1048576, name='package'):
        directory = self.home / relative
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(b'B' * size)
        os.utime(path, (self.now - 86400 * 60, self.now - 86400 * 60))
        return directory, path

    def plan(self, target=1, **kwargs):
        return self.engine.plan(target, **kwargs)

    def human(self, plan, task='task'):
        gate = HumanGate(lambda: self.engine, clock=lambda: self.now)
        directive = gate.before_tool('ballast_apply', {'plan_token': plan['plan_token'], 'dry_run': False}, task_id=task)
        self.assertEqual(directive['action'], 'approve')
        pattern = 'plugin_rule:' + directive['rule_key']
        gate.request(pattern_key=pattern, surface='cli')
        gate.response(pattern_key=pattern, surface='cli', choice='once')
        return lambda token: gate.take(token, task)

    def test_registry_resolution_closed(self):
        roots = list(self.engine.resolved_roots())
        self.assertTrue(all(path.is_relative_to(self.home) for _, _, path in roots))
        self.assertFalse(any('.cargo/bin' in str(path) for _, _, path in roots))
        self.assertEqual({s['id'] for s in CATALOG} - {'huggingface', 'xcode-derived', 'xcode-device'}, {s['id'] for s, _, _ in roots})

    def test_denied_roots_and_home(self):
        for name in DENIED:
            with self.subTest(path=name), self.assertRaises(Refused):
                self.engine.safety.check(self.home / name / 'cache')
        for path in [Path('/'), self.home, self.base / 'elsewhere']:
            with self.assertRaises(Refused):
                self.engine.safety.check(path)

    def test_custom_hermes_deny(self):
        safety = Safety(self.home, self.home / 'private-hermes')
        for relative in ['private-hermes', 'private-hermes/file']:
            with self.assertRaises(Refused):
                safety.check(self.home / relative)

    def test_runtime_engine_uses_only_public_host_imports(self):
        storage = ModuleType('plugins.plugin_storage')
        storage.plugin_data_dir = lambda name: self.base / 'runtime-data' / name
        constants = ModuleType('hermes_constants')
        constants.get_hermes_home = lambda: self.home / 'custom-hermes'
        config = ModuleType('hermes_cli.config')
        config.load_config_readonly = lambda: {}
        public_imports = {'plugins.plugin_storage', 'hermes_constants', 'hermes_cli.config'}
        original_import = builtins.__import__
        seen = []

        def public_import(name, *args, **kwargs):
            seen.append(name)
            if name not in public_imports:
                raise AssertionError('Unexpected host import: ' + name)
            return original_import(name, *args, **kwargs)

        with patch.dict(sys.modules, {'plugins.plugin_storage': storage, 'hermes_constants': constants, 'hermes_cli.config': config}):
            with patch('ballast.Engine', wraps=Engine) as engine_factory:
                with patch('builtins.__import__', side_effect=public_import):
                    engine = runtime_engine()
        self.assertEqual(set(seen), public_imports)
        self.assertEqual(engine_factory.call_args.args, (self.home, storage.plugin_data_dir('ballast'), constants.get_hermes_home()))
        self.assertEqual(engine_factory.call_args.kwargs, {})
        with self.assertRaises(Refused):
            engine.safety.check(constants.get_hermes_home() / 'file')

    def test_demo_override_via_supported_config_and_real_home_untouched(self):
        _, real_payload = self.seed()
        before = real_payload.read_bytes(), real_payload.stat().st_mtime_ns
        demo = self.base / 'demo'; demo.mkdir()
        cache = demo / '.npm/_cacache'; cache.mkdir(parents=True)
        payload = cache / 'realistic-fixture'; payload.write_bytes(b'D' * 1048576)
        storage = ModuleType('plugins.plugin_storage')
        storage.plugin_data_dir = lambda _: self.base / 'demo-data'
        constants = ModuleType('hermes_constants'); constants.get_hermes_home = lambda: self.home / '.hermes'
        config = ModuleType('hermes_cli.config')
        config.load_config_readonly = lambda: {'plugins': {'entries': {'ballast': {'settings': {'scan_home': str(demo)}}}}}
        with patch.dict(sys.modules, {'plugins.plugin_storage': storage, 'hermes_constants': constants, 'hermes_cli.config': config}):
            engine = runtime_engine()
        engine.which = lambda _: None
        scan = engine.scan(); plan = engine.plan(1)
        for view in (scan, plan, engine.status()):
            self.assertEqual(view['scan_home'], str(demo))
            self.assertEqual(view['scanning'], 'Scanning: ' + str(demo))
            self.assertTrue(view['demo_home'])
            self.assertEqual(view['home_badge'], 'DEMO HOME')
        self.assertEqual([item['path'] for item in scan['sources'] if item['eligible']], [str(cache)])
        other = self.base / 'other-demo'; other.mkdir()
        changed = Engine(other, engine.data, self.home / '.hermes', which=lambda _: None)
        with self.assertRaises(Refused): changed.load_plan(plan['plan_token'], revalidate=False)
        self.assertFalse(changed.status()['last_plan']['ok'])
        engine.apply(plan['plan_token'], False, approval=lambda _: True)
        self.assertFalse(payload.exists())
        self.assertEqual((real_payload.read_bytes(), real_payload.stat().st_mtime_ns), before)

    def test_demo_override_validation_and_both_home_denylists(self):
        file = self.base / 'file'; file.write_text('not a directory')
        hermes = self.base / 'hermes'; hermes.mkdir()
        personal = self.home / 'Documents/demo'; personal.mkdir(parents=True)
        for value in ('relative', '/', '/System', '/usr', '/Library', '/private', str(file),
                      str(self.base / 'missing'), str(hermes), str(personal), None, False, 1):
            with self.subTest(value=value), self.assertRaises(Refused):
                Engine(value, self.base / 'invalid-data', hermes)
        demo = self.base / 'demo'; demo.mkdir()
        with patch('ballast.core.os.getuid', return_value=demo.stat().st_uid + 1):
            with self.assertRaises(Refused): Engine(demo, self.base / 'invalid-data', hermes)
        alias = self.base / 'alias'; alias.symlink_to(demo, target_is_directory=True)
        engine = Engine(alias, self.base / 'demo-data', hermes, which=lambda _: None)
        self.assertEqual(engine.home, demo)
        for root in (self.home, demo):
            for relative in DENIED:
                with self.assertRaises(Refused): engine.safety.check(root / relative / 'keep')
        (demo / '.cache').mkdir()
        (demo / '.cache/uv').symlink_to(self.home / 'Documents', target_is_directory=True)
        uv = next(i for i in engine.scan()['sources'] if i['id'] == 'uv')
        self.assertFalse(uv['eligible'])
        self.assertTrue(any('Symlink' in reason for reason in uv['reasons']))

    def test_root_symlink_escape_refused(self):
        outside = self.base / 'outside'
        outside.mkdir(); (outside / 'untouched').write_text('keep')
        (self.home / '.npm').mkdir()
        (self.home / '.npm/_cacache').symlink_to(outside, target_is_directory=True)
        item = next(i for i in self.engine.scan()['sources'] if i['id'] == 'npm')
        self.assertFalse(item['eligible'])
        self.assertIn('Symlink', item['reasons'][0])
        self.assertTrue((outside / 'untouched').exists())

    def test_internal_symlink_loop_unlinked_without_following(self):
        directory, _ = self.seed()
        (directory / 'loop').symlink_to('loop')
        item = next(i for i in self.engine.scan()['sources'] if i['id'] == 'npm')
        self.assertTrue(item['eligible'])
        plan = self.plan()
        self.assertTrue(self.engine.apply(plan['plan_token'], False, approval=self.human(plan))['ok'])
        self.assertFalse((directory / 'loop').is_symlink())

    def test_dataless_root_never_opened(self):
        self.seed()
        real_stat, real_open = os.stat, os.open
        class Stub:
            def __init__(self, original): self.original = original; self.st_flags = DATALESS
            def __getattr__(self, name): return getattr(self.original, name)
        def fake_stat(name, *args, **kwargs):
            result = real_stat(name, *args, **kwargs)
            return Stub(result) if name == '_cacache' else result
        with patch('ballast.core.os.stat', side_effect=fake_stat), patch('ballast.core.os.open', wraps=real_open) as opened:
            with self.assertRaises(Refused): self.engine.safety.inspect(self.home / '.npm/_cacache')
        self.assertFalse(any(call.args[0] == '_cacache' for call in opened.call_args_list))

    def test_internal_symlink_not_followed(self):
        directory, _ = self.seed()
        (directory / 'personal').symlink_to(self.home / 'Documents')
        result = self.engine.safety.inspect(directory)
        self.assertTrue(any('Symlink skipped: personal' in reason for reason in result['reasons']))
        self.assertFalse(next(i for i in self.engine.scan()['sources'] if i['id'] == 'npm')['eligible'])

    def test_dataless_stub_skipped_without_open(self):
        directory, path = self.seed()
        real_stat = os.stat
        class Stub:
            def __init__(self, original):
                self.original = original
                self.st_flags = DATALESS
            def __getattr__(self, name):
                return getattr(self.original, name)
        def fake_stat(name, *args, **kwargs):
            result = real_stat(name, *args, **kwargs)
            return Stub(result) if name == path.name else result
        with patch('ballast.core.os.stat', side_effect=fake_stat):
            result = self.engine.safety.inspect(directory)
        self.assertEqual(result['size_bytes'], 0)
        self.assertTrue(any('Dataless' in reason for reason in result['reasons']))

    def test_other_mount_skipped(self):
        directory, path = self.seed()
        real_stat = os.stat
        class OtherVolume:
            def __init__(self, original): self.original = original
            @property
            def st_dev(self): return self.original.st_dev + 1
            def __getattr__(self, name): return getattr(self.original, name)
        def fake_stat(name, *args, **kwargs):
            result = real_stat(name, *args, **kwargs)
            return OtherVolume(result) if name == path.name else result
        with patch('ballast.core.os.stat', side_effect=fake_stat):
            result = self.engine.safety.inspect(directory)
        self.assertEqual(result['size_bytes'], 0)
        self.assertTrue(any('volume' in reason for reason in result['reasons']))

    def test_hardlink_deduplication(self):
        directory, path = self.seed()
        os.link(path, directory / 'same-inode')
        result = self.engine.safety.inspect(directory)
        self.assertEqual(result['size_bytes'], path.stat().st_blocks * 512)

    def test_external_hardlink_counts_zero(self):
        directory, path = self.seed()
        os.link(path, self.base / 'outside-link')
        self.assertEqual(self.engine.safety.inspect(directory)['size_bytes'], 0)

    def test_allocated_bytes_not_logical_size(self):
        directory, path = self.seed(size=4097)
        result = self.engine.safety.inspect(directory)
        self.assertEqual(result['size_bytes'], path.stat().st_blocks * 512)

    def test_huggingface_per_model_not_blob_following(self):
        model = '.cache/huggingface/hub/models--org--one'
        root, blob = self.seed(model + '/blobs')
        snapshot = self.home / model / 'snapshots/rev'
        snapshot.mkdir(parents=True)
        (snapshot / 'weights').symlink_to('../../blobs/package')
        sources = self.engine.scan()['sources']
        item = next(i for i in sources if i['id'] == 'huggingface:models--org--one')
        self.assertEqual(item['size_bytes'], blob.stat().st_blocks * 512)
        self.assertTrue(item['eligible'])
        plan = self.plan()
        result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
        self.assertTrue(result['ok'])
        self.assertFalse(blob.exists())

    def test_optional_models_require_explicit_opt_in(self):
        self.seed('.ollama/models')
        plan = self.plan()
        self.assertFalse(plan['reachable'])
        self.assertTrue(any('opt-in' in row['reason'] for row in plan['left_out']))
        self.assertTrue(self.plan(include_optional=['ollama'])['reachable'])

    def test_plan_meets_target_and_explains_leftovers(self):
        self.seed('.npm/_cacache'); self.seed('Library/Caches/pip'); self.seed('Library/Developer/Xcode/DerivedData')
        plan = self.plan(20000)
        self.assertTrue(plan['reachable'])
        self.assertGreaterEqual(plan['projected_freed'], 20000)
        self.assertTrue(plan['left_out'])
        self.assertTrue(all(row['reason'] for row in plan['left_out']))

    def test_exact_planner_against_exhaustive_subsets(self):
        items = [dict(id=str(i), size_bytes=size, regret=cost) for i, (size, cost) in enumerate([(9, 8), (6, 3), (4, 2), (10, 7), (3, 1)])]
        for target in range(1, 34):
            chosen, reachable = minimum_regret(items, target)
            feasible = [sum(row['regret'] for row in subset) for length in range(6) for subset in itertools.combinations(items, length) if sum(row['size_bytes'] for row in subset) >= target]
            self.assertEqual(reachable, bool(feasible))
            if reachable: self.assertEqual(sum(row['regret'] for row in chosen), min(feasible))
            self.assertEqual(chosen, minimum_regret(list(reversed(items)), target)[0])

    def test_unreachable_is_not_silent_partial_cleanup(self):
        _, path = self.seed()
        plan = self.plan('15 GB')
        self.assertFalse(plan['reachable'])
        self.assertGreater(plan['shortfall_bytes'], 0)
        self.assertEqual(plan['max_reclaimable_bytes'], path.stat().st_blocks * 512)
        self.assertEqual(plan['shortfall_bytes'], 15_000_000_000 - plan['max_reclaimable_bytes'])
        with self.assertRaises(Refused):
            self.engine.apply(plan['plan_token'], False, approval=lambda _: True)
        self.assertTrue(path.exists())

    def test_tiny_cache_floor_and_empty_unreachable_totals(self):
        self.seed('.cache/uv', size=12288)
        plan = self.plan('15 GB')
        self.assertEqual(plan['chosen'], [])
        self.assertEqual(plan['max_reclaimable_bytes'], 0)
        self.assertEqual(plan['shortfall_bytes'], 15_000_000_000)
        tiny = next(row for row in plan['left_out'] if row['item']['id'] == 'uv')
        self.assertTrue(tiny['item']['eligible'])
        self.assertIn('1 MB planning floor', tiny['reason'])
        _, payload = self.seed()
        plan = self.plan(1)
        self.assertEqual([item['id'] for item in plan['chosen']], ['npm'])
        self.assertEqual(plan['max_reclaimable_bytes'], payload.stat().st_blocks * 512)
        self.assertEqual(plan['shortfall_bytes'], 0)

    def test_pnpm_versioned_projects_preserved_and_omitted_from_snapshot(self):
        tool = self.base / 'pnpm'; tool.write_text('never executed')
        self.engine.which = lambda name: str(tool) if name == 'pnpm' else None
        for root in ('Library/pnpm/store', '.pnpm-store'):
            for version in ('v10', 'v11'):
                with self.subTest(root=root, version=version):
                    directory, payload = self.seed(root + '/' + version + '/files')
                    projects = directory.parent / 'projects'; projects.mkdir()
                    _, sentinel = self.seed('Downloads/project', size=1234)
                    link = projects / 'hash'
                    link.symlink_to(os.path.relpath(sentinel.parent, projects))
                    retained = projects / 'metadata'; retained.write_bytes(b'R' * 1048576)
                    plan = self.plan()
                    item = plan['chosen'][0]
                    self.assertTrue(item['eligible'])
                    self.assertEqual(item['size_bytes'], payload.stat().st_blocks * 512)
                    self.assertEqual(item['action']['kind'], 'delete_contents')
                    self.assertEqual(item['action']['preserve'], ['v*/projects'])
                    stored = self.engine.load_plan(plan['plan_token'])['chosen'][0]
                    self.assertFalse(any('/projects' in row[0] for row in stored['snapshot']['entries']))
                    retained.write_text('registry changes are outside the candidate')
                    self.assertTrue(self.engine.apply(plan['plan_token'], False, approval=self.human(plan))['ok'])
                    self.assertFalse(payload.exists())
                    self.assertTrue(link.is_symlink())
                    self.assertEqual(sentinel.read_bytes(), b'B' * 1234)
                    self.assertEqual(retained.read_text(), 'registry changes are outside the candidate')
                    self.assertEqual(self.commands, [])

    def test_pnpm_escape_outside_projects_still_refused(self):
        directory, payload = self.seed('Library/pnpm/store/v11/files')
        _, sentinel = self.seed('Downloads/project')
        (directory / 'escape').symlink_to(sentinel.parent)
        item = next(i for i in self.engine.scan()['sources'] if i['id'] == 'pnpm:1')
        self.assertFalse(item['eligible'])
        self.assertIn('Symlink escape refused', ' '.join(item['reasons']))
        self.assertTrue(payload.exists()); self.assertTrue(sentinel.exists())

    def test_unknown_selection_refused(self):
        for kwargs in [dict(exclude=['../Documents']), dict(include_optional=['unknown'])]:
            with self.assertRaises(Refused): self.plan(**kwargs)

    def test_exclude_family_applies_all_roots(self):
        self.seed('.cargo/registry/cache'); self.seed('.cargo/registry/src')
        self.assertFalse(self.plan(exclude=['cargo'])['reachable'])

    def test_token_tamper_and_stored_plan_tamper(self):
        self.seed(); plan = self.plan(); token = plan['plan_token']
        wrong = token[:-1] + ('0' if token[-1] != '0' else '1')
        with self.assertRaises(Refused): self.engine.apply(wrong)
        stored = self.engine.read('plan-' + plan['id'] + '.json')
        stored['chosen'][0]['path'] = str(self.home / 'Documents')
        self.engine.write('plan-' + plan['id'] + '.json', stored)
        with self.assertRaises(Refused): self.engine.apply(token)

    def test_token_expiry(self):
        self.seed(); plan = self.plan(); self.now += 900
        with self.assertRaises(Refused): self.engine.apply(plan['plan_token'])

    def test_size_mtime_inode_and_new_file_drift(self):
        for drift in ('size', 'mtime', 'inode', 'newfile'):
            directory, path = self.seed()
            plan = self.plan()
            if drift == 'size': path.write_bytes(b'changed')
            if drift == 'mtime': os.utime(path, (self.now, self.now))
            if drift == 'inode':
                replacement = directory / 'replacement'; replacement.write_bytes(path.read_bytes()); os.replace(replacement, path)
            if drift == 'newfile': (directory / 'new').write_bytes(b'new')
            with self.subTest(drift=drift), self.assertRaises(Refused): self.engine.apply(plan['plan_token'])
            shutil.rmtree(directory)

    def test_root_replaced_by_symlink_after_plan(self):
        directory, _ = self.seed(); plan = self.plan()
        preserved = self.home / 'Documents'; preserved.mkdir()
        (preserved / 'keep').write_text('personal')
        shutil.rmtree(directory); directory.symlink_to(preserved)
        with self.assertRaises(Refused): self.engine.apply(plan['plan_token'], False, approval=lambda _: True)
        self.assertEqual((preserved / 'keep').read_text(), 'personal')

    def test_dry_run_is_default_and_does_not_mutate_cache(self):
        _, path = self.seed(); plan = self.plan()
        before = path.read_bytes()
        result = self.engine.apply(plan['plan_token'])
        self.assertTrue(result['dry_run'])
        self.assertTrue(result['actions'])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.engine.ledger()['entries'], [])

    def test_status_poll_does_not_rescan_cache_trees(self):
        self.seed(); plan = self.plan()
        with patch.object(self.engine.safety, 'inspect', side_effect=AssertionError('status must not rewalk caches')):
            self.assertEqual(self.engine.status()['last_plan']['id'], plan['id'])

    def test_unattended_apply_refused_even_with_model_approved_argument(self):
        _, path = self.seed(); plan = self.plan()
        with self.assertRaises(Refused): self.engine.apply(plan['plan_token'], False)
        result = request('apply', dict(plan_token=plan['plan_token'], dry_run=False, approved=True), factory=lambda: self.engine)
        self.assertFalse(result['ok'])
        self.assertTrue(path.exists())

    def test_fresh_human_apply_only_fake_cache_and_ledger(self):
        directory, path = self.seed()
        personal = self.home / 'Documents/precious.txt'; personal.parent.mkdir(); personal.write_text('keep')
        plan = self.plan()
        result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
        self.assertTrue(result['ok'])
        self.assertFalse(path.exists()); self.assertTrue(directory.exists())
        self.assertEqual(personal.read_text(), 'keep')
        self.assertTrue(Path(result['recipes']).exists())
        self.assertIn('npm install', Path(result['recipes']).read_text())
        self.assertIsInstance(result['actual_freed'], int)
        self.assertEqual([r['event'] for r in self.engine.ledger()['entries']], ['started', 'item', 'completed'])
        with self.assertRaises(Refused): self.engine.apply(plan['plan_token'], False, approval=lambda _: True)

    def test_drift_while_human_thinks_refused(self):
        _, path = self.seed(); plan = self.plan()
        def decision(token):
            path.write_text('new work'); return True
        with self.assertRaises(Refused): self.engine.apply(plan['plan_token'], False, approval=decision)
        self.assertEqual(path.read_text(), 'new work')

    def test_approval_receipt_deny_timeout_autoapproval_and_replay(self):
        self.seed(); plan = self.plan()
        for choice in ['deny', 'timeout', 'cancelled', 'notify_failed', 'smart_approved', '']:
            gate = HumanGate(lambda: self.engine, clock=lambda: self.now)
            directive = gate.before_tool('ballast_apply', dict(plan_token=plan['plan_token'], dry_run=False), task_id='a')
            pattern = 'plugin_rule:' + directive['rule_key']
            gate.request(pattern_key=pattern, surface='gateway')
            gate.response(pattern_key=pattern, surface='gateway', choice=choice)
            self.assertFalse(gate.take(plan['plan_token'], 'a'))
        gate = HumanGate(lambda: self.engine, clock=lambda: self.now)
        directive = gate.before_tool('ballast_apply', dict(plan_token=plan['plan_token'], dry_run=False), task_id='a')
        gate.response(pattern_key='plugin_rule:' + directive['rule_key'], surface='cli', choice='once')
        self.assertFalse(gate.take(plan['plan_token'], 'a'), 'response without request must not grant')
        receipt = self.human(plan)
        self.assertTrue(receipt(plan['plan_token']))
        self.assertFalse(receipt(plan['plan_token']))

    def test_receipt_scoped_to_task_and_cron_refused(self):
        self.seed(); plan = self.plan()
        approval = self.human(plan, 'original')
        self.assertTrue(approval(plan['plan_token']))
        gate = HumanGate(lambda: self.engine, cron=lambda: object(), clock=lambda: self.now)
        self.assertEqual(gate.before_tool('ballast_apply', dict(plan_token=plan['plan_token'], dry_run=False))['action'], 'block')
        self.assertFalse(gate.take(plan['plan_token'], 'other'))

    def test_clean_command_injected_runner_staging_and_sanitized_env(self):
        _, path = self.seed('.cache/uv')
        executable = self.base / 'uv-stub'; executable.write_text('stub, never executed')
        self.engine.which = lambda name: str(executable) if name == 'uv' else None
        self.engine.runner = lambda argv, **kwargs: {**self.fake_runner(argv, **kwargs), 'returncode': 2}
        plan = self.plan()
        action = plan['chosen'][0]['action']
        self.assertEqual(action['kind'], 'command')
        result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
        self.assertTrue(result['ok']); self.assertFalse(path.exists())
        self.assertEqual(len(self.commands), 1)
        argv, kwargs = self.commands[0]
        self.assertEqual(argv[0], str(executable.resolve()))
        self.assertIn('--no-config', argv)
        self.assertEqual(Path(argv[argv.index('--cache-dir') + 1]), path.parent)
        self.assertEqual(kwargs['env']['HOME'], str(self.engine.data / 'command-home'))
        self.assertEqual(kwargs['env']['UV_OFFLINE'], '1')
        self.assertNotIn('OPENAI_API_KEY', kwargs['env'])

    def test_all_official_command_variants_are_scoped_and_stubbed(self):
        variants = [('npm', '.npm/_cacache', 'npm'),
                    ('yarn', 'Library/Caches/Yarn', 'yarn'), ('pip', 'Library/Caches/pip', 'pip'),
                    ('go', 'Library/Caches/go-build', 'go-build'), ('go', 'go/pkg/mod', 'go-mod')]
        tool = self.base / 'tool-stub'; tool.write_text('stub')
        node = self.base / 'node-stub'; node.write_text('stub')
        for binary, path, source_id in variants:
            with self.subTest(source=source_id):
                _, payload = self.seed(path)
                self.engine.which = lambda name: str(tool) if name == binary else str(node) if name == 'node' else None
                self.engine.runner = lambda argv, **kwargs: {**self.fake_runner(argv, **kwargs), 'returncode': 2}
                plan = self.plan()
                self.assertEqual(plan['chosen'][0]['source_id'], source_id)
                action = plan['chosen'][0]['action']
                self.assertEqual(action['kind'], 'command')
                self.assertTrue(Path(action['staged_root']).is_relative_to(self.engine.data))
                result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
                self.assertTrue(result['ok']); self.assertFalse(payload.exists())
                argv, kwargs = self.commands[-1]
                self.assertTrue(Path(argv[0]).is_absolute())
                self.assertTrue(Path(kwargs['cwd']).is_relative_to(self.engine.data))

    def test_native_cleanup_runs_before_staging_and_handles_removed_root(self):
        for remove_root in (False, True):
            with self.subTest(remove_root=remove_root):
                directory, payload = self.seed('.cache/uv')
                tool = self.base / 'uv'; tool.write_text('stub')
                self.engine.which = lambda name: str(tool) if name == 'uv' else None
                def clean(argv, **kwargs):
                    self.assertTrue(payload.exists())
                    self.assertFalse((self.engine.data / 'staging').exists())
                    payload.unlink()
                    if remove_root:
                        directory.rmdir()
                    return dict(returncode=0, stdout='cleaned', stderr='')
                self.engine.runner = clean
                plan = self.plan()
                result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['results'][0]['outcome'], 'native clean ok')
                self.assertIsNone(result['results'][0]['fallback'])
                self.assertFalse((self.engine.data / 'staging').exists())
                self.assertEqual(self.engine.ledger()['entries'][-2]['result'], result['results'][0])

    def test_successful_native_cleanup_with_leftovers_does_not_stage(self):
        _, payload = self.seed('.cache/uv')
        tool = self.base / 'uv'; tool.write_text('stub')
        self.engine.which = lambda name: str(tool) if name == 'uv' else None
        plan = self.plan()
        result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
        self.assertFalse(result['ok'])
        self.assertTrue(payload.exists())
        self.assertIsNone(result['results'][0]['fallback'])
        self.assertFalse((self.engine.data / 'staging').exists())

    def test_npm_native_cleanup_uses_distinct_empty_configs(self):
        directory, payload = self.seed()
        tool = self.base / 'npm'; tool.write_text('stub')
        self.engine.which = lambda name: str(tool) if name == 'npm' else None
        def clean(argv, **kwargs):
            configs = [Path(argv[argv.index(flag) + 1]) for flag in ('--userconfig', '--globalconfig')]
            self.assertNotEqual(*configs)
            for config, key in zip(configs, ('npm_config_userconfig', 'npm_config_globalconfig')):
                self.assertEqual(config.read_bytes(), b'')
                self.assertEqual(kwargs['env'][key], str(config))
                self.assertTrue(config.is_relative_to(self.engine.data))
            self.assertEqual(Path(argv[argv.index('--cache') + 1]), directory.parent)
            self.assertTrue(payload.exists())
            self.assertFalse((self.engine.data / 'staging').exists())
            shutil.rmtree(directory)
            return dict(returncode=0, stdout='', stderr='')
        self.engine.runner = clean
        plan = self.plan()
        result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][0]['outcome'], 'native clean ok')

    def test_pip_no_matching_packages_is_success(self):
        for code, message in ((0, ''), (1, 'ERROR: No matching packages')):
            with self.subTest(returncode=code):
                _, payload = self.seed('Library/Caches/pip')
                tool = self.base / 'pip'; tool.write_text('stub')
                self.engine.which = lambda name: str(tool) if name == 'pip' else None
                def clean(argv, **kwargs):
                    self.assertEqual(Path(argv[argv.index('--cache-dir') + 1]), payload.parent)
                    self.assertTrue(payload.exists())
                    payload.unlink()
                    return dict(returncode=code, stdout='', stderr=message)
                self.engine.runner = clean
                plan = self.plan()
                result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
                self.assertTrue(result['ok'], result)
                item = result['results'][0]
                self.assertEqual(item['command']['returncode'], 0)
                self.assertEqual(item['outcome'], 'native clean ok')
                self.assertFalse((self.engine.data / 'staging').exists())

    def test_changed_executable_refused(self):
        self.seed('.cache/uv')
        executable = self.base / 'uv-stub'; executable.write_text('stub')
        self.engine.which = lambda name: str(executable) if name == 'uv' else None
        plan = self.plan(); executable.write_text('changed executable')
        with self.assertRaises(Refused): self.engine.apply(plan['plan_token'])

    def test_failed_clean_command_finishes_approved_deletion_and_ledgers_fallback(self):
        directory, payload = self.seed('.cache/uv')
        executable = self.base / 'uv-stub'; executable.write_text('stub')
        self.engine.which = lambda name: str(executable) if name == 'uv' else None
        def failed(*args, **kwargs):
            (directory / 'new-unapproved').write_text('keep new cache content')
            return dict(returncode=2, stdout='', stderr='stub error')
        self.engine.runner = failed
        plan = self.plan()
        result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
        self.assertTrue(result['ok'])
        self.assertFalse(payload.exists())
        self.assertEqual((directory / 'new-unapproved').read_text(), 'keep new cache content')
        self.assertIn('completed approved', result['results'][0]['fallback'])
        self.assertFalse((self.engine.data / 'staging').exists())
        self.assertEqual(self.engine.ledger()['entries'][-2]['result']['command']['returncode'], 2)
        self.assertEqual(self.engine.ledger()['entries'][-1]['event'], 'completed')

    def test_native_failure_partial_cleanup_and_changed_leftovers(self):
        for change in ('remove', 'modify', 'add'):
            with self.subTest(change=change):
                directory, payload = self.seed('.cache/uv/nested')
                child = directory / 'child'; child.mkdir()
                (child / 'file').write_text('approved')
                tool = self.base / 'uv'; tool.write_text('stub')
                self.engine.which = lambda name: str(tool) if name == 'uv' else None
                def clean(argv, **kwargs):
                    if change == 'remove':
                        shutil.rmtree(child)
                    elif change == 'modify':
                        payload.write_text('changed after approval')
                    else:
                        (directory / 'unapproved').write_text('new')
                    return dict(returncode=2, stdout='', stderr='partial cleanup')
                self.engine.runner = clean
                plan = self.plan()
                result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
                self.assertEqual(result['ok'], change == 'remove', result)
                self.assertEqual(payload.exists(), change != 'remove')
                self.assertFalse((self.engine.data / 'staging').exists())
                shutil.rmtree(self.home / '.cache/uv')

    def test_framework_symlink_chains_delete_without_following(self):
        relative = 'Library/Developer/Xcode/DerivedData/OldProject/Build/Foo.framework'
        framework = self.home / relative
        self.seed(relative + '/Versions/A/Headers')
        (framework / 'Versions/Current').symlink_to('A')
        (framework / 'Headers').symlink_to('Versions/Current/Headers')
        item = next(i for i in self.engine.scan()['sources'] if i['id'] == 'xcode-derived:OldProject')
        self.assertTrue(item['eligible'], item['reasons'])
        plan = self.plan()
        self.assertTrue(self.engine.apply(plan['plan_token'], False, approval=self.human(plan))['ok'])
        self.assertFalse(framework.exists())

    def test_relative_and_absolute_symlink_escapes_still_refused(self):
        directory, payload = self.seed()
        outside, sentinel = self.seed('.cache/elsewhere')
        for target in ('../../.cache/elsewhere', str(outside), '../_cacache/../../.cache/elsewhere'):
            with self.subTest(target=target):
                link = directory / 'escape'; link.symlink_to(target)
                self.assertFalse(next(i for i in self.engine.scan()['sources'] if i['id'] == 'npm')['eligible'])
                with self.engine.safety.open_root(directory) as fd:
                    with self.assertRaises(Refused): self.engine.safety.delete_contents(fd, directory)
                self.assertTrue(sentinel.exists()); self.assertTrue(payload.exists())
                link.unlink()

    def test_read_only_go_directories_writable_before_unlink(self):
        directory, payload = self.seed('go/pkg/mod/example@v1/nested')
        module = directory.parent; root = module.parent
        for path in (directory, module, root): path.chmod(0o555)
        self.addCleanup(lambda: [path.chmod(0o755) for path in (root, module, directory) if path.exists()])
        plan = self.plan()
        real_unlink = os.unlink
        def require_write(name, *args, **kwargs):
            if 'dir_fd' in kwargs:
                self.assertTrue(os.fstat(kwargs['dir_fd']).st_mode & stat.S_IWUSR)
            return real_unlink(name, *args, **kwargs)
        with patch('ballast.core.os.unlink', side_effect=require_write):
            result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
        self.assertTrue(result['ok']); self.assertFalse(payload.exists())

    def test_special_files_skipped_and_regular_contents_cleaned(self):
        directory, payload = self.seed('.gradle/caches/nested')
        fifo = directory / 'pipe'; os.mkfifo(fifo)
        # Socket creation is sandbox-blocked; inject socket metadata for a fake entry.
        (directory / 'sock').write_bytes(b'')
        real_stat = os.stat

        def socket_stat(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            if Path(path).name == 'sock':
                fields = {key: getattr(info, key) for key in dir(info) if key.startswith('st_')}
                fields['st_mode'] = stat.S_IFSOCK | 0o600
                return SimpleNamespace(**fields)
            return info

        stat_patch = patch('ballast.core.os.stat', side_effect=socket_stat)
        stat_patch.start()
        self.addCleanup(stat_patch.stop)
        item = next(i for i in self.engine.scan()['sources'] if i['id'] == 'gradle')
        self.assertTrue(item['eligible']); self.assertEqual(len(item['reasons']), 2)
        plan = self.plan()
        result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
        self.assertTrue(result['ok']); self.assertFalse(payload.exists())
        self.assertTrue(fifo.exists()); self.assertTrue((directory / 'sock').exists())
        self.assertEqual(len(result['results'][0]['skipped']), 2)

    def test_special_files_force_direct_deletion_instead_of_staging(self):
        directory, _ = self.seed('.cache/uv')
        os.mkfifo(directory / 'pipe')
        tool = self.base / 'uv'; tool.write_text('stub')
        self.engine.which = lambda name: str(tool) if name == 'uv' else None
        self.assertEqual(self.plan()['chosen'][0]['action']['kind'], 'delete_contents')

    def test_fd_traversal_keeps_nested_protected_paths_without_resolve(self):
        directory, payload = self.seed('.cache/uv')
        self.engine.safety.protected.add(payload)
        with self.assertRaises(Refused): self.engine.safety.inspect(directory)
        link = directory / 'forbidden-link'; link.symlink_to('package')
        self.engine.safety.protected.remove(payload)
        self.engine.safety.protected.add(link)
        with self.assertRaises(Refused): self.engine.safety.inspect(directory)
        with self.engine.safety.open_root(directory) as fd:
            with self.assertRaises(Refused): self.engine.safety.delete_contents(fd, directory)
        self.assertTrue(link.is_symlink()); link.unlink()
        self.engine.safety.protected.remove(link)
        safety = Safety(self.home, directory / 'private-hermes')
        safety.hermes_home.mkdir()
        with self.assertRaises(Refused): safety.inspect(directory)
        safety.hermes_home.rmdir()
        with patch.object(self.engine.safety, 'check', wraps=self.engine.safety.check) as checked:
            self.engine.safety.inspect(directory)
        self.assertEqual(checked.call_count, 1)

    def test_cleaner_native_shell_and_js_launchers(self):
        self.seed('.npm/_cacache')
        self.seed('Library/Caches/Yarn')
        node = self.base / 'node'; node.write_text('stub')
        for tool_name in ('npm', 'yarn'):
            for filename, content, needs_node in [('native', b'\xcf\xfa\xed\xfe', False), ('shim', b'#!/bin/sh\nexec tool "$@"', False),
                                                   ('entry', b'#!/usr/bin/env node\n// script', True), ('entry.js', b'// script', True)]:
                with self.subTest(tool=tool_name, launcher=filename):
                    tool = self.base / filename; tool.write_bytes(content)
                    self.engine.which = lambda name: str(tool) if name == tool_name else str(node) if name == 'node' else None
                    item = next(i for i in self.engine.scan()['sources'] if i['source_id'] == tool_name)
                    action = self.engine.action(item, 'a' * 32)
                    self.assertEqual(action['argv'][0], str(node) if needs_node else str(tool))
                    if needs_node:
                        self.assertEqual(action['argv'][1], str(tool))
                        self.assertEqual(len(action['executable_snapshot']), 2)

    def test_node_script_without_node_falls_back_to_delete(self):
        self.seed()
        tool = self.base / 'npm'; tool.write_text('#!/usr/bin/env node\n//stub')
        self.engine.which = lambda name: str(tool) if name == 'npm' else None
        self.assertEqual(self.plan()['chosen'][0]['action']['kind'], 'delete_contents')

    def test_pip_env_python_is_fixed_and_snapshot_bound_without_path_expansion(self):
        self.seed('Library/Caches/pip')
        tool = self.base / 'pip'; tool.write_text('#!/usr/bin/env python3\n#stub')
        interpreter = self.base / 'python3'; interpreter.symlink_to(sys.executable)
        self.engine.which = lambda name: str(tool) if name == 'pip' else None
        plan = self.plan(); action = plan['chosen'][0]['action']
        self.assertEqual(action['argv'][:2], [str(interpreter), str(tool)])
        self.assertEqual(len(action['executable_snapshot']), 2)
        self.assertNotIn(str(self.base), self.engine.command_env()['PATH'])
        interpreter.unlink(); interpreter.write_text('changed')
        with self.assertRaises(Refused): self.engine.apply(plan['plan_token'])

    def test_pip_missing_env_interpreter_falls_back(self):
        self.seed('Library/Caches/pip')
        tool = self.base / 'pip'; tool.write_text('#!/usr/bin/env python3\n#stub')
        self.engine.which = lambda name: str(tool) if name == 'pip' else None
        self.assertEqual(self.plan()['chosen'][0]['action']['kind'], 'delete_contents')

    def test_cleaner_timeout_and_spawn_error_finish_approved_deletion(self):
        for error in (subprocess.TimeoutExpired(['stub'], 120), OSError('cannot launch')):
            with self.subTest(error=error):
                _, payload = self.seed('.cache/uv')
                tool = self.base / 'uv'; tool.write_text('stub')
                self.engine.which = lambda name: str(tool) if name == 'uv' else None
                plan = self.plan()
                with patch.object(self.engine, 'runner', side_effect=error):
                    result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
                self.assertTrue(result['ok']); self.assertFalse(payload.exists())
                self.assertIn('completed approved', result['results'][0]['fallback'])

    def test_xcode_per_project_and_device_exclusion_and_unselected_drift(self):
        for family, root in [('xcode-derived', 'Library/Developer/Xcode/DerivedData'),
                             ('xcode-device', 'Library/Developer/Xcode/iOS DeviceSupport')]:
            with self.subTest(family=family):
                _, active = self.seed(root + '/Active')
                _, old = self.seed(root + '/Old')
                exclude = [family + ':Active'] + [s['id'] for s in CATALOG if s['id'] != family]
                plan = self.plan(exclude=exclude)
                self.assertEqual([i['id'] for i in plan['chosen']], [family + ':Old'])
                active.write_bytes(b'background build')
                result = self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
                self.assertTrue(result['ok']); self.assertTrue(active.exists()); self.assertFalse(old.exists())
                self.assertFalse(self.plan(exclude=[s['id'] for s in CATALOG])['reachable'])

    def test_prunes_expired_plans_and_only_empty_staging(self):
        self.seed(); old = self.plan()
        empty = self.engine.data / 'staging/empty/item/cache'; empty.mkdir(parents=True)
        retained = self.engine.data / 'staging/retained/cache'; retained.mkdir(parents=True)
        sentinel = retained / 'keep'; sentinel.write_text('keep')
        outside = self.base / 'outside'; outside.mkdir(); (outside / 'empty').mkdir()
        (retained / 'link').symlink_to(outside)
        self.now += 901
        new = self.plan()
        self.assertFalse((self.engine.data / ('plan-' + old['id'] + '.json')).exists())
        self.assertTrue((self.engine.data / ('plan-' + new['id'] + '.json')).exists())
        self.assertFalse((self.engine.data / 'staging/empty').exists())
        self.assertTrue(sentinel.exists()); self.assertTrue((outside / 'empty').exists())

    def test_status_uses_small_signed_summary_not_snapshot_or_full_ledger(self):
        self.seed(); plan = self.plan(include_optional=['ollama'])
        self.engine.status()  # Initialize the legacy ledger summary once.
        engine = Engine(self.home, self.engine.data, self.home / '.hermes', which=lambda _: None, clock=lambda: self.now)
        original_read = engine.read
        def small_only(name):
            self.assertFalse(name.startswith('plan-'))
            return original_read(name)
        with patch.object(engine, 'read', side_effect=small_only), patch.object(engine, 'ledger', side_effect=AssertionError('no full history')):
            for _ in range(3):
                state = engine.status()
                self.assertEqual(state['last_plan']['id'], plan['id'])
                self.assertEqual(state['last_plan']['include_optional'], ['ollama'])
        summary = engine.read('last-plan.json'); summary['view']['plan']['target_bytes'] += 1
        engine.write('last-plan.json', summary)
        self.assertFalse(engine.status()['last_plan']['ok'])

    def test_status_rejects_changed_expired_and_consumed_plans(self):
        self.seed(); plan = self.plan()
        path = self.engine.data / ('plan-' + plan['id'] + '.json')
        original = path.read_bytes(); path.write_bytes(original + b' ')
        self.assertFalse(self.engine.status()['last_plan']['ok'])
        path.write_bytes(original)
        plan = self.plan(); self.now += 901
        self.assertFalse(self.engine.status()['last_plan']['ok'])
        plan = self.plan()
        self.engine.apply(plan['plan_token'], False, approval=self.human(plan))
        self.assertFalse(self.engine.status()['last_plan']['ok'])
        self.assertEqual(self.engine.status()['ledger'][-1]['event'], 'completed')

    def test_subprocess_contract_no_shell_timeout_captured_output(self):
        with patch('ballast.core.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'out', 'err')) as run:
            result = subprocess_runner(['/fixed/tool', 'cache', 'clean'], env={'HOME': str(self.home)}, cwd=str(self.base))
        self.assertEqual(result['returncode'], 0)
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs['timeout'], 120)
        self.assertTrue(run.call_args.kwargs['capture_output'])
        self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)

    def test_docker_information_only_stub(self):
        executable = self.base / 'docker-stub'; executable.write_text('stub')
        self.engine.which = lambda name: str(executable) if name == 'docker' else None
        result = self.engine.scan()
        self.assertFalse(result['docker']['eligible'])
        self.assertEqual(self.commands[0][0][1:3], ['system', 'df'])
        self.assertEqual(result['docker']['stdout'], 'stub only')

    def test_size_parser_validation(self):
        for value, expected in [('15 GB', 15000000000), ('1.5 GiB', 1610612736), (123, 123)]:
            self.assertEqual(target_bytes(value), expected)
        for value in [True, False, 0, -1, 2**63, 'rm -rf ~', 'NaN GB', '0 B', 1.2]:
            with self.assertRaises(Refused): target_bytes(value)

    def test_registration_does_not_scan_and_declares_all_tools(self):
        class Context:
            def __init__(self): self.tools = {}; self.hooks = {}; self.commands = {}
            def current_cron_execution(self): return None
            def register_tool(self, **kwargs): self.tools[kwargs['name']] = kwargs
            def register_hook(self, name, handler): self.hooks[name] = handler
            def register_command(self, name, handler, **kwargs): self.commands[name] = handler
            def dispatch_tool(self, name, args): return dict(name=name, args=args)
        context = Context()
        with patch('ballast.runtime_engine', side_effect=AssertionError('registration may not inspect HOME')):
            register(context)
        self.assertEqual(len(context.tools), 5)
        self.assertEqual(set(context.hooks), {'pre_tool_call', 'pre_approval_request', 'post_approval_response'})
        self.assertEqual(context.commands['ballast']('15 GB'), dict(name='ballast_plan', args={'target_bytes': '15 GB'}))
        self.assertFalse(json.loads(context.commands['ballast'](json.dumps(dict(action='apply', args=dict(plan_token='anything', dry_run=False)))))['ok'])

    def test_api_unknown_args_and_nonboolean_dry_run(self):
        self.seed(); plan = self.plan()
        for args in [dict(plan_token=plan['plan_token'], dry_run='false'), dict(plan_token=plan['plan_token'], paths=['/'])]:
            self.assertFalse(request('apply', args, factory=lambda: self.engine)['ok'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
