"""One-shot per-attempt TBL-003 accounting, without model transport or retries."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, localcontext
import json
import math
import os
import re
import stat
import threading

from . import base, clock, configuration, curation, files, history_recovery, locks, model_access, store

_CALLS = frozenset('curate consolidate embed-prompt embed-items embed-search count-tokens'.split())
_MODEL = re.compile(r'[a-z0-9][a-z0-9.-]{0,63}\Z')
_REQUEST = re.compile(r'[A-Za-z0-9_-]{1,200}\Z')
_INSTRUCTIONS = frozenset(('curate-1', 'curate-2', 'merge-1', 'merge-2', 'state-1'))


def _count(value):
    if type(value) is not int or value < 0:
        raise ValueError('invalid memory usage count')
    return value


def parse(data):
    value = store.json_document(data)
    curation._shape(value, 'at project call model total_ms result cost prices',
                    'instructions input output cache_write cache_read first_ms error request')
    curation._time(value['at'])
    if not isinstance(value['project'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,59}', value['project']):
        raise ValueError('invalid memory usage project')
    if not isinstance(value['model'], str) or not _MODEL.fullmatch(value['model']):
        raise ValueError('invalid memory usage model')
    curation._choice(value['call'], _CALLS)
    curation._choice(value['result'], {'ok', 'failed', 'refused', 'limit'})
    for key in ('input', 'output', 'cache_write', 'cache_read', 'first_ms', 'total_ms'):
        if key in value:
            _count(value[key])
    if 'first_ms' in value and value['first_ms'] > value['total_ms']:
        raise ValueError('invalid memory usage timing')
    if 'error' in value:
        curation._choice(value['error'], model_access._KINDS)
    if 'instructions' in value:
        curation._choice(value['instructions'], _INSTRUCTIONS)
    if 'request' in value and (not isinstance(value['request'], str) or not _REQUEST.fullmatch(value['request'])):
        raise ValueError('invalid memory request ID')
    if not configuration.number(value['cost']) or not math.isfinite(value['cost']) or value['cost'] < 0:
        raise ValueError('invalid memory usage cost')
    if not isinstance(value['prices'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value['prices']):
        raise ValueError('invalid memory usage price date')
    datetime.strptime(value['prices'], '%Y-%m-%d')
    return value


def _tokens(call, usage):
    if usage is None:
        return {}
    if not isinstance(usage, dict):
        raise ValueError('invalid memory token counters')
    names = ({'input': 'input_tokens'} if call == 'count-tokens' else
             {'input': 'prompt_tokens'} if call.startswith('embed-') else
             {'input': 'input_tokens', 'output': 'output_tokens',
              'cache_write': 'cache_creation_input_tokens', 'cache_read': 'cache_read_input_tokens'})
    return {target: _count(usage[source]) for target, source in names.items() if source in usage}


def _cost(call, model, tokens, catalogue):
    prices = catalogue['models'].get(model)
    if call == 'count-tokens' or prices is None:
        return 0
    input_total = sum(tokens.get(name, 0) for name in ('input', 'cache_write', 'cache_read'))
    rate = dict(prices)
    if 'above' in rate and input_total > rate['above']['tokens']:
        rate.update({k: rate['above'][k] for k in ('input', 'output')})
    with localcontext() as context:
        context.prec = 64
        amount = sum(Decimal(tokens.get(k, 0)) * Decimal(str(rate.get(k, 0)))
                     for k in ('input', 'output', 'cache_write', 'cache_read')) / Decimal(1000000)
    cost = float(amount)
    if not math.isfinite(cost):
        raise ValueError('invalid memory usage cost')
    return cost


@dataclass(frozen=True)
class Attempt:
    at: str
    project: str
    call: str
    model: str
    instructions: object
    _prices: bytes = field(repr=False)
    _credentials: model_access.Credentials = field(repr=False)
    _started: float = field(repr=False)
    _pid: int = field(repr=False)
    _used: list = field(repr=False, compare=False)
    _mutex: object = field(default_factory=threading.Lock, repr=False, compare=False)

    @classmethod
    def start(cls, *, project, call, model, prices, credentials, instructions=None, when=None):
        if not isinstance(credentials, model_access.Credentials):
            raise ValueError('original memory credentials required')
        catalogue = configuration.prepare({'prices': prices}, temporary=False).values['prices']
        encoded = json.dumps(catalogue, ensure_ascii=False, allow_nan=False).encode('utf-8')
        value = cls(base.utc_time(when), project, call, model, instructions, encoded,
                    credentials, clock.now(), os.getpid(), [False])
        value.line()
        return value

    def line(self, *, usage=None, failure=None, first_ms=None, request_id=None):
        elapsed = (clock.now() - self._started) * 1000
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError('invalid memory usage clock')
        if failure is not None and (type(failure) is not model_access.Failure or
                failure.code not in model_access._KINDS):
            raise ValueError('invalid memory failure')
        tokens = _tokens(self.call, usage)
        prices = store.json_document(self._prices)
        row = dict(at=self.at, project=self.project, call=self.call, model=self.model, **tokens,
                   total_ms=int(elapsed), result='ok' if failure is None else failure.result,
                   cost=_cost(self.call, self.model, tokens, prices), prices=prices['taken'])
        if self.instructions is not None:
            row['instructions'] = self.instructions
        if failure is not None:
            row['error'] = failure.code
        if first_ms is not None:
            row['first_ms'] = first_ms
        if isinstance(request_id, str) and _REQUEST.fullmatch(request_id) and self._credentials.safe(request_id):
            row['request'] = request_id
        if any(not self._credentials.safe(v) for v in row.values() if isinstance(v, str)):
            raise ValueError('unsafe memory usage metadata')
        raw = base.json_bytes(row, 'TBL-003', compact=True)
        parse(raw)
        if not self._credentials.safe(raw):
            raise ValueError('unsafe memory usage metadata')
        return row

    def record(self, memory, deadline, **answer):
        """Exactly one best-effort append per attempt; a retry needs a new attempt."""
        if os.getpid() != self._pid:
            return False
        with self._mutex:
            if self._used[0]:
                return False
            self._used[0] = True
        try:
            return _append(memory, self.line(**answer), deadline)
        except Exception as error:
            # Never inspect error text, args, response bodies or custom names.
            try:
                memory.note(error, step='embed' if self.call.startswith('embed-') else 'curate')
                memory.flush()
            except Exception:
                pass
            return False


def _append(memory, row, deadline):
    memory.check(deadline, memory.held)
    folder = memory.folder / 'logs'
    path = folder / ('usage-' + row['at'][:7] + '.jsonl')
    backup = path.with_name(path.name + '.bak')
    info = memory.fence.check(folder)
    if info is None or not stat.S_ISDIR(info.st_mode):
        raise FileNotFoundError()
    directory = info.st_dev, info.st_ino
    original_fence, original_pin, original_root = memory.fence, memory.pin, memory.folder
    root_binding = original_fence.root, original_fence.identity
    revoked = [False]
    with memory.lease(folder / 'usage.lock', 'log', deadline) as lease:
        token, original_path, pid = lease.token, lease.path, os.getpid()
        owned = []
        for item in memory.held:
            observed = memory.fence.check(item.path)
            if observed is None or not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
                raise locks.LostLock()
            owned.append((item, item.token, item.path, item.device, item.pid,
                          (observed.st_dev, observed.st_ino), item.check))
        def guard():
            try:
                if revoked[0] or os.getpid() != pid or lease.token != token or lease.path != original_path:
                    raise locks.LostLock()
                if memory.fence is not original_fence or memory.pin != original_pin or memory.folder != original_root:
                    raise locks.LostLock()
                if (original_fence.root, original_fence.identity) != root_binding:
                    raise locks.LostLock()
                memory.check(deadline, memory.held)
                for item, nonce, target, device, owner_pid, identity, check in owned:
                    if (item.token, item.path, item.device, item.pid) != (nonce, target, device, owner_pid):
                        raise locks.LostLock()
                    current = memory.fence.check(target)
                    if (current is None or current.st_nlink != 1 or
                            (current.st_dev, current.st_ino) != identity):
                        raise locks.LostLock()
                    check()
                current = memory.fence.check(folder)
                if current is None or (current.st_dev, current.st_ino) != directory:
                    raise locks.LostLock()
                observed = [memory.fence.check(candidate) for candidate in (path, backup)]
                for value in observed:
                    if value is not None and not stat.S_ISREG(value.st_mode):
                        raise locks.LostLock()
                    if value is not None:
                        expected = sum(other is not None and (other.st_dev, other.st_ino) ==
                                       (value.st_dev, value.st_ino) for other in observed)
                        if value.st_nlink != expected:
                            raise locks.LostLock()
                lease.check()
            except Exception:
                revoked[0] = True
                raise
        guard()
        if memory.fence.check(path) is None and memory.fence.check(backup) is not None:
            if memory.fence.check(backup).st_nlink != 1:
                raise locks.LostLock()
            raw, stamp = history_recovery._read(memory, backup, deadline, guard)
            if not raw.endswith(b'\n') and raw:
                raise ValueError('invalid memory usage backup')
            for line in raw.splitlines():
                parse(line)
            def restore():
                guard()
                if memory.fence.check(path) is not None:
                    raise locks.LostLock()
                actual, current = history_recovery._read(memory, backup, deadline, guard)
                if actual != raw or current != stamp:
                    revoked[0] = True
                    raise locks.LostLock()
                guard()
                os.replace(str(backup), str(path))
            files._retry(restore, deadline)
        guard()
        flags = os.O_CREAT | os.O_RDWR | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        fd = files._retry(lambda: files._checked(guard, lambda: base.private_open(path, flags)), deadline)
        try:
            identity = os.fstat(fd).st_dev, os.fstat(fd).st_ino
            def opened():
                guard()
                named, live = memory.fence.check(path), os.fstat(fd)
                if (named is None or not stat.S_ISREG(live.st_mode) or
                        (named.st_dev, named.st_ino) != identity or (live.st_dev, live.st_ino) != identity):
                    revoked[0] = True
                    raise locks.LostLock()
                other = memory.fence.check(backup)
                links = 2 if other is not None and (other.st_dev, other.st_ino) == identity else 1
                if live.st_nlink != links or named.st_nlink != links or links == 2 and other.st_nlink != 2:
                    revoked[0] = True
                    raise locks.LostLock()
                guard()
            opened()
            size = os.fstat(fd).st_size
            raw = base.json_bytes(row, 'TBL-003', compact=True)
            if size:
                opened()
                os.lseek(fd, -1, os.SEEK_END)
                if os.read(fd, 1) != b'\n':
                    raw = b'\n' + raw
            opened()
            if os.write(fd, raw) != len(raw):
                opened()
                os.ftruncate(fd, size)
                raise OSError('short usage append')
            return True
        finally:
            os.close(fd)
