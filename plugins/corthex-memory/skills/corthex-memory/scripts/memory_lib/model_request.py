"""Closed curator requests with complete-field redaction, never apply authority."""
import copy
import json
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from . import configuration, model_prompts, redaction

_LIMIT = 6*1024*1024
AGENT = 'corthex-memory/0.2.1'
_BASES = {'anthropic': ('CORTHEX_MEMORY_ANTHROPIC_BASE_URL', 'https://api.anthropic.com'),
          'openai': ('CORTHEX_MEMORY_OPENAI_BASE_URL', 'https://api.openai.com')}
_TAGS = frozenset('request state line items item title text conflicts conflict turns session turn entry quote'.split())
_KINDS = {model_prompts.CURATE: 'curate', model_prompts.MERGE: 'merge', model_prompts.STATE: 'state'}
_ATTRS = dict(request={'kind','instructions','group'},state=set(),line={'id','part','cites'},
    items={'form'},item={'id','kind','speaker','date'},title=set(),text=set(),
    conflicts={'omitted'},conflict={'id','items','since'},turns=set(),
    session={'log','host','started','ended'},turn={'seq','part','parts'},
    entry={'id','speaker','at'},quote={'n','speaker','said'})


def _redact(text, environment, credentials):
    text = redaction._unicode(text)
    if len(text.encode('utf-8')) > _LIMIT:raise ValueError('memory request too large')
    text, _ = redaction._replace(text, redaction.PRIVATE, 'private', None)
    text, _ = redaction._replace(text, redaction.COMPILED[0][1], 'private-key', None)
    text, _ = redaction._environment(text, environment, None)
    for secret in sorted((v for v in credentials._values if v), key=len, reverse=True):
        text = text.replace(secret, '[redacted:memory-key]')
    for kind, pattern in redaction.COMPILED[1:]:
        text, _ = redaction._replace(text, pattern, kind, None)
    if not credentials.safe(text):raise ValueError('unsafe memory request')
    return text


def document(text, *, instructions, environment, credentials):
    """Re-escape decoded data fields; never unescape XML into active markup."""
    if (not isinstance(text, str) or len(text.encode('utf-8', 'surrogatepass')) > _LIMIT or
            '\x00' in text or '<!' in text or '<?' in text or instructions not in _KINDS):
        raise ValueError('invalid memory request document')
    try:root = ET.fromstring(text)
    except ET.ParseError:raise ValueError('invalid memory request document') from None
    expected = {'kind': _KINDS[instructions], 'instructions': instructions}
    if root.tag != 'request' or any(root.attrib.get(k) != v for k,v in expected.items()):
        raise ValueError('invalid memory request context')
    pending, count = [(root, 0)], 0
    while pending:
        node, depth = pending.pop(); count += 1
        if node.tag not in _TAGS or depth > 16 or count > 100000 or set(node.attrib)-_ATTRS[node.tag]:
            raise ValueError('invalid memory request structure')
        for key,value in list(node.attrib.items()):
            if not isinstance(key, str) or not key.isascii() or not key.replace('_','').isalnum():
                raise ValueError('invalid memory request attribute')
            node.set(key, _redact(value, environment, credentials))
        if node.text is not None:node.text = _redact(node.text, environment, credentials)
        if node.tail is not None:node.tail = _redact(node.tail, environment, credentials)
        pending.extend((child, depth+1) for child in node)
    if any(root.attrib.get(k) != v for k,v in expected.items()):raise ValueError('unsafe memory request context')
    result = ET.tostring(root, encoding='unicode', short_empty_elements=True)
    if len(result.encode('utf-8')) > _LIMIT:raise ValueError('memory request too large')
    return result


def endpoint(environment, provider, path):
    """The API's address: the provider's, or the test server that the base URL variable sets.

    An explicitly set invalid value refuses the call; it never falls back to the provider.
    """
    name, default = _BASES[provider]
    base_url = environment.get(name, default)
    if not isinstance(base_url, str) or not base_url or any(not 33 <= ord(c) <= 126 for c in base_url):
        raise ValueError('invalid memory API base URL')
    try:
        target = urlsplit(base_url)
        target.port
    except ValueError:
        raise ValueError('invalid memory API base URL') from None
    if (target.scheme not in {'http','https'} or not target.hostname or target.username is not None or
            target.password is not None or target.query or target.fragment or
            target.scheme == 'http' and target.hostname not in {'localhost','127.0.0.1','::1'}):
        raise ValueError('invalid memory API base URL')
    return base_url.rstrip('/')+path


def build(*, config, instructions, source, schema, credentials, environment):
    """Return fixed wire data and the exact sent XML; do not read keys or files."""
    if instructions not in _KINDS or not isinstance(schema, dict):raise ValueError('invalid memory request')
    settings = configuration.prepare(config, temporary=False).values
    url = endpoint(environment, 'anthropic', '/v1/messages')
    sent = document(source, instructions=instructions, environment=environment, credentials=credentials)
    system = _redact(model_prompts.PROMPTS[instructions], environment, credentials)
    body = dict(model=settings['models']['curator'], max_tokens=64000, stream=True,
        thinking={'type':'adaptive'}, output_config={'effort':settings['models']['effort'],
            'format':{'type':'json_schema','schema':copy.deepcopy(schema)}},
        system=system, messages=[{'role':'user','content':sent}])
    pending = [body]
    while pending:
        value = pending.pop()
        if isinstance(value,str) and not credentials.safe(value):raise ValueError('unsafe memory request')
        if isinstance(value,dict):pending.extend(value); pending.extend(value.values())
        elif isinstance(value,list):pending.extend(value)
    encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(encoded) > _LIMIT or not credentials.safe(encoded):raise ValueError('unsafe memory request')
    headers = credentials.headers('anthropic')
    if headers is None:raise ValueError('dedicated memory API key missing')
    headers.update({'anthropic-version':'2026-10-21','content-type':'application/json','user-agent':AGENT})
    return dict(url=url, headers=headers, body=body, schema=copy.deepcopy(schema)), sent
