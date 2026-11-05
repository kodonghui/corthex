"""Dedicated credentials and closed error kinds; no transport, retry or logging."""
from dataclasses import dataclass, field
import os

_NAMES = {'anthropic': 'CORTHEX_MEMORY_ANTHROPIC_API_KEY', 'openai': 'CORTHEX_MEMORY_OPENAI_API_KEY'}
_HTTP = {400: 'invalid_request_error', 401: 'authentication_error', 402: 'billing_error',
         403: 'permission_error', 404: 'not_found_error', 409: 'conflict_error',
         413: 'request_too_large', 429: 'rate_limit_error', 500: 'api_error',
         504: 'timeout_error', 529: 'overloaded_error'}
_LASTING = frozenset('invalid_request_error authentication_error billing_error permission_error '
                     'not_found_error request_too_large insufficient_quota refusal max-tokens'.split())
_KINDS = frozenset(_HTTP.values()) | _LASTING | frozenset(
    'network timeout empty-answer bad-answer bad-vector'.split())
_QUOTA = frozenset(('credit_balance_exhausted', 'organization_spend_limit_exceeded',
                    'project_spend_limit_exceeded', 'organization_usage_limit_exceeded'))
_PROVIDER_TYPES = frozenset(_HTTP.values()) | {'insufficient_quota'}


def _provider(provider):
    if not isinstance(provider, str) or provider not in _NAMES:
        raise ValueError('invalid memory provider')


@dataclass(frozen=True)
class Credentials:
    _values: tuple = field(repr=False)

    @classmethod
    def read(cls, environment=None):
        """Snapshot exactly the two dedicated variables, including for presence."""
        source = os.environ if environment is None else environment
        values = tuple(source.get(name) for name in _NAMES.values())
        if any(value is not None and not isinstance(value, str) for value in values):
            raise ValueError('invalid memory credentials')
        return cls(values)

    def presence(self):
        return {name: 'present' if value else 'missing' for name, value in zip(_NAMES, self._values)}

    def headers(self, provider):
        """Secrets leave this object only as the provider's authentication header."""
        _provider(provider)
        value = self._values[tuple(_NAMES).index(provider)]
        if not value:
            return None
        if len(value) > 8192 or any(not 33 <= ord(c) <= 126 for c in value):
            raise ValueError('invalid memory credential header')
        return {'x-api-key': value} if provider == 'anthropic' else {'Authorization': 'Bearer ' + value}

    def safe(self, data):
        """Use this original snapshot even when the process environment changes."""
        if not isinstance(data, (str, bytes)):
            raise ValueError('invalid memory metadata')
        text = data.decode('utf-8') if isinstance(data, bytes) else data
        return not any(value in text for value in self._values if value)


@dataclass(frozen=True)
class Failure:
    code: str
    lasting: bool
    status: object = None

    @property
    def result(self):
        return {'refusal': 'refused', 'max-tokens': 'limit'}.get(self.code, 'failed')


def classify(provider, *, status=None, error_type=None, error_code=None, reason=None):
    """Classify closed selectors only; unknown provider strings are discarded."""
    _provider(provider)
    if reason is not None:
        if not isinstance(reason, str) or reason not in _KINDS:
            raise ValueError('invalid memory failure reason')
        return Failure(reason, reason in _LASTING)
    if status is None:
        code = error_type if isinstance(error_type, str) and error_type in _PROVIDER_TYPES else 'api_error'
        return Failure(code, code in _LASTING)
    if type(status) is not int or not 400 <= status <= 599:
        raise ValueError('invalid memory HTTP status')
    if provider == 'openai' and status == 429 and (
            isinstance(error_type, str) and error_type == 'insufficient_quota' or
            isinstance(error_code, str) and error_code in _QUOTA):
        return Failure('insufficient_quota', True, status)
    code = ('overloaded_error' if provider == 'openai' and status == 503 else _HTTP.get(status))
    if code is None:
        code = error_type if isinstance(error_type, str) and error_type in _PROVIDER_TYPES else (
            'invalid_request_error' if status < 500 else 'api_error')
    return Failure(code, 400 <= status < 500 and status not in (409, 429), status)
