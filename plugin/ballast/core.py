"""Cache inspection, exact minimum-regret planning and fail-closed execution."""
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import time

from .registry import CATALOG, DENIED, WARNINGS

DATALESS = getattr(stat, 'SF_DATALESS', 0x40000000)
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
MIN_PLAN_BYTES = 1_000_000


class Refused(ValueError):
    pass


def scan_home(value, real_home, hermes_home):
    if not isinstance(value, (str, Path)) or not Path(value).is_absolute():
        raise Refused('scan_home must be an existing absolute directory owned by you.')
    try:
        home = Path(value).resolve(strict=True)
        info = home.stat()
    except (OSError, RuntimeError) as exc:
        raise Refused('Cannot resolve scan_home to an existing directory.') from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise Refused('scan_home must be a directory owned by you.')
    system = ('/Applications', '/Library', '/System', '/bin', '/sbin', '/usr', '/etc',
              '/var', '/private', '/dev', '/Volumes', '/cores', '/opt')
    protected = {Path(p).resolve() for p in system} | {Path(hermes_home).resolve()}
    protected |= {Path(real_home).resolve() / p for p in DENIED}
    if home == Path('/') or any(home == p or home.is_relative_to(p) for p in protected):
        raise Refused('scan_home may not be a system, personal or Hermes directory.')
    return home


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def target_bytes(value):
    if type(value) is int and 0 < value <= 2**63 - 1:
        return value
    if isinstance(value, str):
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\s*', value, re.I)
        if match:
            unit = match[2].upper()
            power = {'B': 0, 'KB': 1, 'MB': 2, 'GB': 3, 'TB': 4,
                     'KIB': 1, 'MIB': 2, 'GIB': 3, 'TIB': 4}[unit]
            size = float(match[1]) * (1024 if 'I' in unit else 1000) ** power
            if math.isfinite(size) and 0 < size <= 2**63 - 1:
                return math.ceil(size)
    raise Refused('Use positive target_bytes or a size such as "15 GB" (decimal) or "15 GiB".')


def minimum_regret(items, target):
    """Exact integer-cost DP: for each regret retain the most allocated bytes."""
    items = sorted(items, key=lambda item: item['id'])
    states = {0: (0, ())}
    for index, item in enumerate(items):
        additions = {}
        for cost, (size, chosen) in states.items():
            key = cost + item['regret']
            candidate = (size + item['size_bytes'], chosen + (index,))
            old = additions.get(key, states.get(key))
            if old is None or candidate[0] > old[0] or (candidate[0] == old[0] and candidate[1] < old[1]):
                additions[key] = candidate
        states.update(additions)
        # A cheaper state holding at least as much space dominates any dearer one.
        maximum = -1
        frontier = {}
        for cost, value in sorted(states.items()):
            if value[0] > maximum:
                frontier[cost] = value
                maximum = value[0]
            if value[0] >= target:
                break
        states = frontier
    feasible = [(cost, value) for cost, value in states.items() if value[0] >= target]
    if not feasible:
        return items, False
    _, (_, selected) = min(feasible)
    return [items[i] for i in selected], True


class Safety:
    def __init__(self, home, hermes_home, real_home=None):
        self.home = Path(home).resolve()
        self.hermes_home = Path(hermes_home).resolve()
        self.device = self.home.stat().st_dev
        self.protected = {root / p for root in (self.home, Path(real_home or Path.home()).resolve()) for p in DENIED} | {self.hermes_home}

    def check(self, path):
        path = Path(path)
        if not path.is_absolute() or path == self.home or not path.is_relative_to(self.home):
            raise Refused('Path is not a cache root below HOME.')
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError):
            raise Refused('Cannot resolve path safely (possible symlink loop).')
        if resolved != path or not resolved.is_relative_to(self.home):
            raise Refused('Symlink or realpath escape refused.')
        for root in self.protected:
            if resolved == root or resolved.is_relative_to(root):
                raise Refused('Protected personal or Hermes path refused.')
        return path

    def check_entry(self, path):
        # Ancestors were checked by open_root/no-follow traversal; keep protected paths per entry.
        if any(path == root or path.is_relative_to(root) for root in self.protected):
            raise Refused('Protected personal or Hermes path refused.')

    def preserved_registry(self, path, candidate_root):
        roots = (self.home / 'Library/pnpm/store', self.home / '.pnpm-store')
        if candidate_root not in roots:
            return False
        parts = path.relative_to(candidate_root).parts
        return len(parts) == 2 and re.fullmatch(r'v\d+', parts[0]) is not None and parts[1] == 'projects'

    @contextmanager
    def open_root(self, path):
        path = self.check(path)
        fd = os.open(self.home, DIR_FLAGS)
        try:
            for part in path.relative_to(self.home).parts:
                info = os.stat(part, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode) or info.st_dev != self.device or getattr(info, 'st_flags', 0) & DATALESS:
                    raise Refused('Symlink, other volume or dataless directory refused before opening.')
                next_fd = os.open(part, DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = next_fd
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise Refused('Directory changed while opening.')
            yield fd
        finally:
            os.close(fd)

    def inspect_fd(self, fd, logical_root):
        entries, reasons, blocking_reasons, links = [], [], [], {}
        last_used = 0
        def visit(directory, prefix):
            nonlocal last_used
            for name in sorted(os.listdir(directory)):
                relative = f'{prefix}/{name}' if prefix else name
                path = logical_root / relative
                # Project registries are outside the pnpm candidate, including metadata.
                if self.preserved_registry(path, logical_root):
                    continue
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                flags = getattr(info, 'st_flags', 0)
                record = [relative, info.st_dev, info.st_ino, info.st_mode, info.st_size,
                          info.st_mtime_ns, info.st_blocks, info.st_nlink, flags]
                entries.append(record)
                if stat.S_ISREG(info.st_mode):
                    last_used = max(last_used, info.st_atime, info.st_mtime)
                self.check_entry(path)
                if stat.S_ISLNK(info.st_mode):
                    target = os.readlink(name, dir_fd=directory)
                    record.append(target)
                    try:
                        self.check_link(path, target, logical_root)
                    except (OSError, Refused) as exc:
                        blocking_reasons.append(f'Symlink skipped: {relative}: {exc}')
                    continue
                if info.st_dev != self.device:
                    blocking_reasons.append(f'Other volume skipped: {relative}')
                    continue
                if flags & DATALESS:
                    blocking_reasons.append(f'Dataless iCloud stub skipped: {relative}')
                    continue
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(name, DIR_FLAGS, dir_fd=directory)
                    try:
                        opened = os.fstat(child)
                        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                            raise Refused('Directory changed during scan.')
                        visit(child, relative)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    key = (info.st_dev, info.st_ino)
                    value = links.setdefault(key, [info.st_blocks * 512, info.st_nlink, 0])
                    value[2] += 1
                else:
                    reasons.append(f'Special file skipped: {relative}')
        root_info = os.fstat(fd)
        visit(fd, '')
        # Root survives cleanup; directory metadata allocation is conservatively omitted.
        size = sum(size for size, count, found in links.values() if count == found)
        snapshot = dict(root=[root_info.st_dev, root_info.st_ino, root_info.st_mtime_ns], entries=entries)
        return dict(size_bytes=size, last_used=last_used or max(root_info.st_atime, root_info.st_mtime),
                    snapshot=snapshot, reasons=blocking_reasons + reasons, blocking_reasons=blocking_reasons)

    def inspect(self, path):
        with self.open_root(path) as fd:
            return self.inspect_fd(fd, Path(path))

    def check_link(self, path, target, candidate_root):
        # Lexical containment allows framework chains/loops; unlink never follows targets.
        destination = Path(os.path.normpath(path.parent / target))
        if Path(target).is_absolute() or not destination.is_relative_to(candidate_root):
            raise Refused('Symlink escape refused.')

    def delete_contents(self, fd, logical_root, candidate_root=None):
        """Descriptor-relative deletion: never follow a replaced directory or symlink."""
        candidate_root = candidate_root or logical_root
        os.fchmod(fd, stat.S_IMODE(os.fstat(fd).st_mode) | stat.S_IWUSR)
        empty = True
        for name in sorted(os.listdir(fd)):
            path = logical_root / name
            if self.preserved_registry(path, candidate_root):
                empty = False
                continue
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if info.st_dev != self.device or getattr(info, 'st_flags', 0) & DATALESS:
                raise Refused('Mount or dataless entry appeared; stopped.')
            self.check_entry(path)
            if stat.S_ISLNK(info.st_mode):
                self.check_link(path, os.readlink(name, dir_fd=fd), candidate_root)
                os.unlink(name, dir_fd=fd)
                continue
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, DIR_FLAGS, dir_fd=fd)
                try:
                    opened = os.fstat(child)
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise Refused('Directory changed during deletion.')
                    child_empty = self.delete_contents(child, path, candidate_root)
                finally:
                    os.close(child)
                if child_empty:
                    os.rmdir(name, dir_fd=fd)
                else:
                    empty = False
            elif stat.S_ISREG(info.st_mode):
                os.unlink(name, dir_fd=fd)
            else:
                empty = False  # Leave sockets/FIFOs and their parent directories in place.
        return empty


def subprocess_runner(argv, *, env, cwd):
    result = subprocess.run(argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=120, check=False)
    return dict(returncode=result.returncode, stdout=result.stdout[-4000:], stderr=result.stderr[-4000:])


class Engine:
    def __init__(self, home, data_dir, hermes_home, *, runner=subprocess_runner,
                 which=shutil.which, clock=time.time):
        self.real_home = Path.home().resolve()
        self.home = scan_home(home, self.real_home, hermes_home)
        self.data = Path(data_dir)
        if self.data.is_symlink():
            raise Refused('Plugin data directory may not be a symlink.')
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data = self.data.resolve()
        self.data.chmod(0o700)
        self.safety = Safety(self.home, hermes_home, self.real_home)
        self.runner, self.which, self.clock = runner, which, clock

    def home_view(self):
        return dict(scan_home=str(self.home), real_home=str(self.real_home),
                    scanning='Scanning: ' + str(self.home), demo_home=self.home != self.real_home,
                    home_badge='DEMO HOME' if self.home != self.real_home else None)

    @contextmanager
    def locked(self):
        fd = os.open(self.data / 'state.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def write(self, name, value):
        temporary = self.data / ('.' + secrets.token_hex(12) + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as out:
            out.write(canonical(value)); out.flush(); os.fsync(out.fileno())
        os.replace(temporary, self.data / name)

    def read(self, name):
        fd = os.open(self.data / name, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'r') as stream:
            return json.load(stream)

    def key(self):
        path = self.data / 'plan-key'
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as stream:
                key = stream.read()
            if len(key) != 32:
                raise Refused('Invalid local plan signing key.')
            return key
        key = secrets.token_bytes(32)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(key); stream.flush(); os.fsync(stream.fileno())
        return key

    def prune_state(self):
        """Called under the state lock; never remove nonempty retained staging."""
        for path in self.data.glob('plan-*.json'):
            if re.fullmatch(r'plan-[0-9a-f]{32}\.json', path.name) and stat.S_ISREG(path.lstat().st_mode):
                try:
                    expired = self.read(path.name)['expires_at'] <= self.clock()
                except (OSError, ValueError, KeyError, TypeError):
                    continue
                if expired:
                    path.unlink()
        def empty_directories(fd):
            for name in os.listdir(fd):
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if (not stat.S_ISDIR(info.st_mode) or info.st_dev != self.safety.device
                        or getattr(info, 'st_flags', 0) & DATALESS):
                    continue
                try:
                    child = os.open(name, DIR_FLAGS, dir_fd=fd)
                except PermissionError:
                    continue
                try:
                    opened = os.fstat(child)
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise Refused('Staging changed during pruning.')
                    empty_directories(child)
                finally:
                    os.close(child)
                try:
                    os.rmdir(name, dir_fd=fd)
                except OSError as exc:
                    if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST, errno.EACCES, errno.EPERM):
                        raise
        try:
            fd = os.open(self.data / 'staging', DIR_FLAGS)
        except FileNotFoundError:
            return
        try:
            empty_directories(fd)
        finally:
            os.close(fd)

    def save_last_plan(self, plan, token):
        info = (self.data / ('plan-' + plan['id'] + '.json')).lstat()
        view = dict(plan=self.public_plan(plan, token),
                    fingerprint=[info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns])
        signature = hmac.new(self.key(), canonical(view), hashlib.sha256).hexdigest()
        self.write('last-plan.json', dict(view=view, signature=signature))

    def resolved_roots(self):
        for source in CATALOG:
            for index, relative in enumerate(source['paths']):
                root = self.home / relative
                if source['id'] in ('huggingface', 'xcode-derived', 'xcode-device'):
                    try:
                        with self.safety.open_root(root) as fd:
                            models = sorted(name for name in os.listdir(fd)
                                            if (source['id'] != 'huggingface' or name.startswith(('models--', 'datasets--', 'spaces--')))
                                            and (stat.S_ISDIR(mode := os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode)
                                                 or stat.S_ISLNK(mode)))
                        for name in models:
                            yield source, source['id'] + ':' + name, root / name
                    except FileNotFoundError:
                        pass
                    except (OSError, Refused) as exc:
                        yield {**source, 'root_error': str(exc)}, source['id'], root
                    continue
                id = source['id'] + (f':{index + 1}' if len(source['paths']) > 1 else '')
                yield source, id, root

    def scan(self):
        items = []
        for source, id, path in self.resolved_roots():
            item = {key: value for key, value in source.items() if key != 'paths'}
            item.update(id=id, source_id=source['id'], path=str(path), size_bytes=0,
                        last_used=None, reasons=[], eligible=False)
            try:
                if source.get('root_error'):
                    raise Refused(source['root_error'])
                info = self.safety.inspect(path)
                item.update(info)
                item['eligible'] = not info['blocking_reasons'] and info['size_bytes'] > 0
                if not info['size_bytes']:
                    item['reasons'].append('No exclusively reclaimable allocated file bytes.')
            except FileNotFoundError:
                item['reasons'] = ['Cache is not present.']
            except (OSError, Refused) as exc:
                item['reasons'] = [str(exc)]
            age = max(0, self.clock() - (item['last_used'] or self.clock())) / 86400
            recency = 100 if age < 1 else 45 if age < 7 else 15 if age < 30 else 0
            item['regret'] = max(1, math.ceil(source['regen_minutes'] * 10 + source['download_mb'] / 100
                                            + recency + (1 - source['confidence']) * 100))
            item['regen_download_class'] = 'none' if not source['download_mb'] else 'small' if source['download_mb'] < 500 else 'medium' if source['download_mb'] < 2000 else 'large'
            items.append(item)
        docker = self.which('docker')
        report = dict(id='docker', label='Docker reclaimable (information only)', eligible=False,
                      reasons=['Aggregate Docker figures cannot bind an exact cache-tree snapshot; use Docker manually.'])
        if docker:
            try:
                result = self.runner([str(Path(docker).resolve()), 'system', 'df', '--format', '{{json .}}'],
                                     env=self.command_env(), cwd=str(self.data))
                report.update(result)
            except (OSError, subprocess.SubprocessError) as exc:
                report['reasons'].append(str(exc))
        else:
            report['reasons'].append('Docker CLI is not available.')
        return dict(ok=True, **self.home_view(), sources=items, docker=report, warnings=WARNINGS,
                    free_bytes=shutil.disk_usage(self.home).free, total_bytes=shutil.disk_usage(self.home).total)

    @staticmethod
    def public_item(item):
        return {key: value for key, value in item.items() if key != 'snapshot'}

    def plan(self, target, exclude=None, include_optional=None):
        target = target_bytes(target)
        exclude = [] if exclude is None else exclude
        include_optional = [] if include_optional is None else include_optional
        for values in (exclude, include_optional):
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                raise Refused('Selections must be lists of registry IDs.')
        scan = self.scan()
        known = {item['id'] for item in scan['sources']} | {s['id'] for s in CATALOG}
        if (set(exclude) | set(include_optional)) - known:
            raise Refused('Unknown cache selection ID.')
        candidates, leftovers = [], []
        for item in scan['sources']:
            if not item['eligible']:
                reason = '; '.join(item['reasons'])
            elif item['id'] in exclude or item['source_id'] in exclude:
                reason = 'Excluded by you.'
            elif item['optional'] and item['id'] not in include_optional and item['source_id'] not in include_optional:
                reason = 'Expensive model re-download; explicit opt-in required.'
            elif item['size_bytes'] < MIN_PLAN_BYTES:
                reason = 'Below the 1 MB planning floor; kept to avoid regeneration regret for negligible space.'
            else:
                candidates.append(item)
                continue
            leftovers.append(dict(item=self.public_item(item), reason=reason))
        chosen, reachable = minimum_regret(candidates, target)
        ids = {item['id'] for item in chosen}
        leftovers += [dict(item=self.public_item(item), reason='Kept: target met with a lower total regeneration regret.')
                      for item in candidates if item['id'] not in ids]
        now = self.clock()
        plan = dict(id=secrets.token_hex(16), home=str(self.home), **self.home_view(), created_at=now, expires_at=now + 900,
                    include_optional=include_optional, exclude=exclude,
                    target_bytes=target, reachable=reachable, chosen=chosen, left_out=leftovers,
                    max_reclaimable_bytes=sum(item['size_bytes'] for item in candidates),
                    projected_freed=sum(item['size_bytes'] for item in chosen),
                    total_regret=sum(item['regret'] for item in chosen), consumed=False,
                    warnings=WARNINGS, free_before=scan['free_bytes'], total_bytes=scan['total_bytes'])
        # Freeze executable identities and exact argv before the human reviews the plan.
        for item in chosen:
            item['action'] = self.action(item, plan['id'])
        with self.locked():
            self.prune_state()
            token = plan['id'] + '.' + hmac.new(self.key(), canonical(plan), hashlib.sha256).hexdigest()
            self.write('plan-' + plan['id'] + '.json', plan)
            self.save_last_plan(plan, token)
        return self.public_plan(plan, token)

    def public_plan(self, plan, token):
        return {**plan, 'ok': True, 'plan_token': token, 'chosen': [self.public_item(item) for item in plan['chosen']],
                'shortfall_bytes': max(0, plan['target_bytes'] - plan['projected_freed'])}

    def load_plan(self, token, *, revalidate=True):
        if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{32}\.[0-9a-f]{64}', token):
            raise Refused('Invalid plan token.')
        try:
            plan = self.read('plan-' + token.split('.')[0] + '.json')
        except (OSError, ValueError):
            raise Refused('Plan is unavailable.')
        signature = hmac.new(self.key(), canonical(plan), hashlib.sha256).hexdigest()
        if plan.get('consumed'):
            raise Refused('Plan already used; scan and plan again.')
        if not hmac.compare_digest(signature, token.split('.')[1]):
            raise Refused('Plan signature mismatch.')
        if self.clock() >= plan['expires_at'] or plan['home'] != str(self.home) or plan.get('real_home') != str(self.real_home):
            raise Refused('Plan expired or HOME changed; scan and plan again.')
        if not revalidate:
            return plan
        allowed = {id: str(path) for _, id, path in self.resolved_roots()}
        for item in plan['chosen']:
            if allowed.get(item['id']) != item['path']:
                raise Refused('Registry root changed.')
            fresh = self.safety.inspect(item['path'])
            if fresh['blocking_reasons'] or fresh['snapshot'] != item['snapshot'] or fresh['size_bytes'] != item['size_bytes']:
                raise Refused('Cache snapshot drifted; scan and plan again (zero drift tolerance).')
            if self.action(item, plan['id']) != item['action']:
                raise Refused('Cleanup executable changed; plan again.')
        return plan

    def action(self, item, plan_id):
        fallback = dict(kind='delete_contents', path=item['path'], reason='No available, strictly scoped clean command; descriptor-relative deletion.')
        if item['source_id'] == 'pnpm':
            return {**fallback, 'preserve': ['v*/projects'],
                    'reason': 'Delete store contents except versioned projects registries; prune removes only unreferenced packages and cannot promise these bytes.'}
        if item.get('reasons'):
            return {**fallback, 'reason': 'Leave skipped special files in their original directories; delete approved regular contents only.'}
        command = item['command']
        tool = {'npm': 'npm', 'yarn cache clean': 'yarn',
                'uv': 'uv', 'pip': 'pip', 'go-build': 'go', 'go-mod': 'go'}.get(command)
        executable = self.which(tool) if tool else None
        if tool == 'pip' and not executable:
            executable = self.which('pip3')
        if not executable or self.data.stat().st_dev != self.safety.device:
            return fallback
        executable = str(Path(executable).resolve())
        info = os.stat(executable)
        identities = [[executable, info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size]]
        stage = self.data / 'staging' / plan_id / item['id']
        cache = Path(item['path']).parent if command == 'npm' else Path(item['path'])
        prefix = [executable]
        if tool in ('npm', 'yarn', 'pip'):
            with open(executable, 'rb') as stream:
                header = stream.read(256).split(b'\n', 1)[0]
            try:
                shebang = shlex.split(header[2:].decode()) if header.startswith(b'#!') else []
            except (UnicodeError, ValueError):
                return fallback
            entry = Path(shebang[0]).name if shebang else ''
            uses_env = entry == 'env'
            interpreter = shebang[1] if uses_env and len(shebang) == 2 else shebang[0] if not uses_env and shebang else ''
            name = Path(interpreter).name
            needs_node = tool != 'pip' and (name in ('node', 'nodejs') or Path(executable).suffix in ('.js', '.cjs', '.mjs'))
            needs_python = tool == 'pip' and re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', name)
            if needs_node or needs_python:
                if needs_node:
                    interpreter = self.which('node')
                elif uses_env:
                    adjacent = Path(executable).parent / name
                    interpreter = str(adjacent) if adjacent.is_file() and os.access(adjacent, os.X_OK) else self.which(name)
                if not interpreter or not Path(interpreter).is_absolute():
                    return fallback
                # Preserve Python venv symlink paths: resolving them changes sys.prefix.
                interpreter = str(Path(interpreter).absolute())
                interpreter_info = os.stat(interpreter)
                identities.append([interpreter, interpreter_info.st_dev, interpreter_info.st_ino,
                                   interpreter_info.st_mtime_ns, interpreter_info.st_size])
                prefix = [interpreter, executable] if uses_env or needs_node else [interpreter, *shebang[1:], executable]
            elif uses_env and tool == 'pip':
                return fallback
        if command == 'npm':
            argv = prefix + ['--cache', str(cache), '--logs-dir', str(self.data / 'command-home/npm-logs'),
                    '--userconfig', str(self.data / 'command-home/npm-user.conf'),
                    '--globalconfig', str(self.data / 'command-home/npm-global.conf'), 'cache', 'clean', '--force']
            staged_root = stage / 'cache'
        elif tool == 'yarn':
            argv = prefix + ['--no-default-rc', '--offline', '--cache-folder', str(cache), 'cache', 'clean']
            staged_root = stage / 'cache'
        elif command == 'uv':
            argv = [executable, '--no-config', '--cache-dir', str(cache), 'cache', 'clean']
            staged_root = stage / 'cache'
        elif command == 'pip':
            argv = prefix + ['--isolated', '--cache-dir', str(cache), 'cache', 'purge']
            staged_root = stage / 'cache'
        else:
            argv = [executable, 'clean', '-cache' if command == 'go-build' else '-modcache']
            staged_root = stage / 'cache'
        return dict(kind='command', path=item['path'], argv=argv, staged_root=str(staged_root),
                    executable_snapshot=identities,
                    reason='Run the scoped native cleaner first; stage approved leftovers only if it fails; no shell.')

    def command_env(self, cache=None, owner=None):
        command_home = self.data / 'command-home'
        env = dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin', HOME=str(command_home),
                   XDG_CACHE_HOME=str(command_home / '.cache'), TMPDIR=str(command_home / 'tmp'),
                   LANG='en_US.UTF-8', PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK='1',
                   UV_NO_CONFIG='1', UV_OFFLINE='1', npm_config_update_notifier='false', npm_config_offline='true',
                   npm_config_userconfig=str(command_home / 'npm-user.conf'),
                   npm_config_globalconfig=str(command_home / 'npm-global.conf'),
                   COREPACK_ENABLE_NETWORK='0', YARN_ENABLE_NETWORK='0',
                   GOENV='off', GOTOOLCHAIN='local', GOPROXY='off', GOSUMDB='off')
        if cache and owner in ('go-build', 'go-mod'):
            env['GOCACHE' if owner == 'go-build' else 'GOMODCACHE'] = str(cache)
        return env

    def execute(self, item, plan_id):
        path, action = Path(item['path']), item['action']
        with self.safety.open_root(path) as fd:
            if self.safety.inspect_fd(fd, path)['snapshot'] != item['snapshot']:
                raise Refused('Cache changed immediately before cleanup.')
            if action['kind'] == 'delete_contents':
                self.safety.delete_contents(fd, path)
                return dict(id=item['id'], action=action, ok=True, skipped=item.get('reasons', []))
            stage = Path(action['staged_root'])
            if self.data.stat().st_dev != os.fstat(fd).st_dev:
                raise Refused('Official cleaner staging requires the same volume as the cache.')
            for directory in (self.data / 'command-home', self.data / 'command-home/tmp'):
                directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            for name in ('npm-user.conf', 'npm-global.conf'):
                config_fd = os.open(self.data / 'command-home' / name,
                                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
                os.close(config_fd)
            try:
                result = self.runner(action['argv'], env=self.command_env(path, item['command']), cwd=str(self.data / 'command-home'))
            except (OSError, subprocess.SubprocessError) as exc:
                result = dict(returncode=None, stdout='', stderr=str(exc))
            if item['command'] == 'pip' and result['returncode'] == 1 and 'No matching packages' in (result['stdout'] + result['stderr']):
                result = {**result, 'native_returncode': 1, 'returncode': 0, 'empty_cache': True}
            remaining = self.safety.inspect_fd(fd, path)
            if remaining['reasons']:
                raise Refused('Unsafe entry after native cleanup; stopped.')
            if result['returncode'] == 0:
                if remaining['snapshot']['entries']:
                    return dict(id=item['id'], action=action, ok=False, command=result,
                                error='Native cleanup left contents; retained without staged deletion.', fallback=None)
                return dict(id=item['id'], action=action, ok=True, command=result,
                            outcome='native clean ok', fallback=None)
            if not remaining['snapshot']['entries']:
                return dict(id=item['id'], action=action, ok=True, command=result,
                            outcome='approved cleanup complete', fallback='Native cleanup left no contents; no staged deletion needed.')
            # Native cleaners may remove children and update directory metadata, never authorize new files.
            approved = {row[0]: row for row in item['snapshot']['entries']}
            names = {row[0].split('/')[0] for row in item['snapshot']['entries']}
            for row in remaining['snapshot']['entries']:
                if row[0].split('/')[0] not in names:
                    continue  # Concurrent new top-level entries stay in the cache.
                original = approved.get(row[0])
                indices = (0, 1, 2, 3, 8) if stat.S_ISDIR(row[3]) else range(len(row))
                if original is None or any(row[i] != original[i] for i in indices):
                    raise Refused('Cache changed during native cleanup; leftovers retained.')
            stage.mkdir(parents=True, mode=0o700, exist_ok=False)
            stage_fd = os.open(stage, DIR_FLAGS)
            try:
                os.fchmod(fd, stat.S_IMODE(os.fstat(fd).st_mode) | stat.S_IWUSR)
                for name in sorted(names.intersection(os.listdir(fd))):
                    os.rename(name, name, src_dir_fd=fd, dst_dir_fd=stage_fd)
                staged = self.safety.inspect_fd(stage_fd, path)
                expected = [row for row in remaining['snapshot']['entries'] if row[0].split('/')[0] in names]
                if staged['reasons'] or staged['snapshot']['entries'] != expected:
                    raise Refused('Staging snapshot mismatch; retained in ' + str(stage))
                self.safety.delete_contents(stage_fd, path)
                return dict(id=item['id'], action=action, ok=True, command=result,
                            outcome='approved staged cleanup ok',
                            fallback='Native cleanup incomplete; completed approved staged deletion.')
            finally:
                os.close(stage_fd)
                directory = stage
                while directory != self.data:
                    try:
                        directory.rmdir()
                    except FileNotFoundError:
                        pass
                    except OSError:
                        break
                    directory = directory.parent

    def append_ledger(self, entry):
        fd = os.open(self.data / 'ledger.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'ab') as stream:
            stream.write(canonical(entry) + b'\n'); stream.flush(); os.fsync(stream.fileno())
        if entry['event'] in ('started', 'completed'):
            entries = [row for row in self.status_ledger() if row['event'] != entry['event']]
            entries.append({key: value for key, value in entry.items() if key not in ('items', 'results')})
            self.write('ledger-status.json', entries)

    def status_ledger(self):
        try:
            return self.read('ledger-status.json')
        except FileNotFoundError:
            # Migrate older local history once; subsequent polls read only the small summary.
            history = self.ledger()['entries']
            entries = []
            for event in ('started', 'completed'):
                row = next((row for row in reversed(history) if row.get('event') == event), None)
                if row:
                    entries.append({key: value for key, value in row.items() if key not in ('items', 'results')})
            self.write('ledger-status.json', entries)
            return entries

    def recipes(self, plan):
        text = '# Ballast rebuild recipes\n\nDeletion is permanent; these recipes rebuild caches.\n\n'
        for item in plan['chosen']:
            text += f"## {item['id']}\n\nPath: `{item['path']}`\n\n{item['recipe']}\n\n"
        name = 'recipes-' + plan['id'] + '.md'
        fd = os.open(self.data / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        return str(self.data / name)

    def apply(self, token, dry_run=True, *, approval=None):
        if type(dry_run) is not bool:
            raise Refused('dry_run must be a boolean.')
        with self.locked():
            plan = self.load_plan(token)
            if dry_run:
                return dict(ok=True, dry_run=True, **{'plan': self.public_plan(plan, token)},
                            actions=[item['action'] for item in plan['chosen']])
        # Never hold the process lock while a human considers approval.
        if approval is None or approval(token) is not True:
            raise Refused('A fresh human approval through Hermes is required; unattended cleanup is refused.')
        with self.locked():
            plan = self.load_plan(token)
            if not plan['reachable']:
                raise Refused('Target is unreachable; choose a smaller target before cleanup.')
            if not plan['chosen']:
                raise Refused('Plan has no actions.')
            before = shutil.disk_usage(self.home).free
            recipes = self.recipes(plan)
            self.append_ledger(dict(event='started', plan_id=plan['id'], at=self.clock(),
                                    free_before=before, projected_freed=plan['projected_freed'], recipes=recipes,
                                    items=[self.public_item(i) for i in plan['chosen']]))
            plan['consumed'] = True
            self.write('plan-' + plan['id'] + '.json', plan)
            results = []
            for item in plan['chosen']:
                try:
                    result = self.execute(item, plan['id'])
                except (OSError, Refused, subprocess.SubprocessError) as exc:
                    result = dict(id=item['id'], ok=False, error=str(exc), action=item['action'])
                results.append(result)
                self.append_ledger(dict(event='item', plan_id=plan['id'], at=self.clock(), result=result))
                if not result['ok']:
                    break
            after = shutil.disk_usage(self.home).free
            entry = dict(event='completed', plan_id=plan['id'], at=self.clock(), ok=all(r['ok'] for r in results),
                         free_before=before, free_after=after, actual_freed=after - before,
                         projected_freed=plan['projected_freed'], results=results, recipes=recipes,
                         warnings=WARNINGS)
            self.append_ledger(entry)
            return entry

    def ledger(self):
        try:
            fd = os.open(self.data / 'ledger.jsonl', os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return dict(ok=True, entries=[])
        with os.fdopen(fd) as stream:
            entries = []
            for line in stream:
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    entries.append(dict(event='ledger_error', error='Incomplete ledger line; inspect local ledger.'))
        return dict(ok=True, entries=entries)

    def status(self):
        with self.locked():
            try:
                saved = self.read('last-plan.json')
                if 'view' not in saved:
                    token = saved['plan_token']
                    self.save_last_plan(self.load_plan(token, revalidate=False), token)
                    saved = self.read('last-plan.json')
                view = saved['view']
                signature = hmac.new(self.key(), canonical(view), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(signature, saved['signature']):
                    raise Refused('Plan summary signature mismatch.')
                last = view['plan']
                if self.clock() >= last['expires_at'] or last['home'] != str(self.home) or last.get('real_home') != str(self.real_home):
                    raise Refused('Plan expired or HOME changed; scan and plan again.')
                info = (self.data / ('plan-' + last['id'] + '.json')).lstat()
                if [info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns] != view['fingerprint']:
                    raise Refused('Plan changed or was used; scan and plan again.')
            except FileNotFoundError:
                last = None
            except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
                last = dict(ok=False, error=str(exc))
            ledger = self.status_ledger()
        disk = shutil.disk_usage(self.home)
        return dict(ok=True, **self.home_view(), last_plan=last, ledger=ledger,
                    free_bytes=disk.free, total_bytes=disk.total, warnings=WARNINGS)
