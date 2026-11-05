"""Bounded Anthropic SSE decoding only; no transport, logging or apply authority."""
from dataclasses import dataclass, field
import json

from . import clock, command_result, model_access, model_usage, store

_EVENTS = frozenset('message_start content_block_start content_block_delta content_block_stop message_delta message_stop ping error'.split())
_TOKENS = {'input': 'input_tokens', 'output': 'output_tokens',
           'cache_write': 'cache_creation_input_tokens', 'cache_read': 'cache_read_input_tokens'}


def _fold(value, node, validator, name=None):
    if isinstance(node, bool):return value
    while '$ref' in node:node = validator._ref(node)
    if isinstance(value, str) and name in ('action', 'kind'):
        choices = [v for v in node.get('enum', ()) if isinstance(v, str) and v.lower() == value.lower()]
        return choices[0] if len(choices) == 1 else value
    if isinstance(value, dict):
        return {key: _fold(v, node.get('properties', {}).get(key, True), validator, key) for key, v in value.items()}
    if isinstance(value, list):return [_fold(v, node.get('items', True), validator) for v in value]
    return value


@dataclass(frozen=True)
class Answer:
    text: str = field(repr=False)
    value: object = field(repr=False)
    usage: dict
    first_ms: object
    failure: object


class Decoder:
    def __init__(self, *, started, event_bytes=1024*1024, text_bytes=8*1024*1024):
        if any(type(n) is not int or n < 1 for n in (event_bytes, text_bytes)):
            raise ValueError('invalid memory stream limit')
        self.started, self.event_bytes, self.text_bytes = started, event_bytes, text_bytes
        self.buffer, self.data, self.event, self.frame_bytes = b'', [], '', 0
        self.beginning, self.begun, self.done = True, False, False
        self.blocks, self.next_index, self.stop = {}, 0, None
        self.text, self.size, self.usage, self.first_ms, self.failure = [], 0, {}, None, None

    def _fail(self, code='bad-answer'):
        if self.failure is None:
            self.failure = model_access.classify('anthropic', reason=code)
        self.buffer, self.data, self.text = b'', [], []

    def feed(self, chunk):
        if self.failure is not None:
            return
        try:
            if not isinstance(chunk, (bytes, bytearray)):
                raise ValueError()
            self.buffer += bytes(chunk)
            while self.buffer:
                ends = [n for n in (self.buffer.find(b'\r'), self.buffer.find(b'\n')) if n >= 0]
                if not ends:
                    break
                end = min(ends)
                if self.buffer[end:] == b'\r':
                    break
                take = 2 if self.buffer[end:end+2] == b'\r\n' else 1
                raw, self.buffer = self.buffer[:end], self.buffer[end+take:]
                self.frame_bytes += len(raw)+take
                if self.frame_bytes > self.event_bytes:
                    raise ValueError()
                if self.beginning:
                    self.beginning = False
                    raw = raw[3:] if raw.startswith(b'\xef\xbb\xbf') else raw
                line = raw.decode('utf-8')
                if not line:
                    if self.data:
                        self._dispatch(self.event, '\n'.join(self.data))
                    self.data, self.event, self.frame_bytes = [], '', 0
                    if self.failure is not None:
                        self.buffer = b''
                        return
                elif not line.startswith(':'):
                    name, _, value = line.partition(':')
                    value = value[1:] if value.startswith(' ') else value
                    if name == 'event':self.event = value
                    elif name == 'data':self.data.append(value)
            if self.frame_bytes+len(self.buffer) > self.event_bytes:
                raise ValueError()
        except Exception:
            self._fail()

    def _usage(self, value):
        self.usage.update({_TOKENS[k]: n for k, n in model_usage._tokens('curate', value).items()})

    def _text(self, value):
        if not isinstance(value, str):
            raise ValueError()
        self.size += len(value.encode('utf-8'))
        if self.size > self.text_bytes:
            raise ValueError()
        if value:
            if self.first_ms is None:
                self.first_ms = max(0, int((clock.now()-self.started)*1000))
            self.text.append(value)

    def _dispatch(self, event, data):
        if event not in _EVENTS:
            return
        value = store.json_document(data.encode('utf-8'))
        if not isinstance(value, dict) or value.get('type') != event or self.done:
            raise ValueError()
        if event == 'ping':return
        if event == 'error':
            error = value.get('error')
            if not isinstance(error, dict):raise ValueError()
            self.failure = model_access.classify('anthropic', error_type=error.get('type'))
            self.text = []
            return
        if event == 'message_start':
            if self.begun:raise ValueError()
            message = value['message']
            if not isinstance(message, dict) or message.get('type') != 'message' or message.get('role') != 'assistant' or message.get('content') != []:
                raise ValueError()
            if not isinstance(message['usage'], dict):raise ValueError()
            self._usage(message['usage']); self.begun = True
            return
        if not self.begun:raise ValueError()
        if event.startswith('content_block_'):
            index = value['index']
            if type(index) is not int or index < 0 or self.stop is not None:raise ValueError()
            if event == 'content_block_start':
                if self.blocks or index != self.next_index:raise ValueError()
                block = value['content_block']
                if not isinstance(block, dict) or not isinstance(block.get('type'), str):raise ValueError()
                self.next_index += 1
                self.blocks[index] = block['type'] == 'text'
                if self.blocks[index]:self._text(block['text'])
            elif index not in self.blocks:raise ValueError()
            elif event == 'content_block_stop':del self.blocks[index]
            elif self.blocks[index]:
                delta = value['delta']
                if not isinstance(delta, dict) or delta.get('type') != 'text_delta':raise ValueError()
                self._text(delta['text'])
            return
        if self.blocks:raise ValueError()
        if event == 'message_delta':
            delta = value['delta']
            if not isinstance(delta, dict):raise ValueError()
            if delta.get('stop_reason') is not None:
                reason = delta['stop_reason']
                self.stop = reason if reason in ('end_turn', 'refusal', 'max_tokens') else 'bad-answer'
            self._usage(value.get('usage'))
        elif event == 'message_stop':
            if self.stop is None:raise ValueError()
            self.done = True

    def finish(self, *, schema):
        text, value = '', None
        try:
            if self.buffer.endswith(b'\r'):self.feed(b'\n')
            if self.failure is None:
                if not self.done or self.buffer or self.data or self.blocks:
                    raise ValueError()
                if self.stop != 'end_turn':self._fail('max-tokens' if self.stop == 'max_tokens' else self.stop)
                else:
                    text = ''.join(self.text)
                    if not text.strip():self._fail('empty-answer')
                    else:
                        value = store.json_document(text.encode('utf-8'))
                        validator = command_result._Validator(schema)
                        normalized = _fold(value, schema, validator)
                        if not isinstance(value, dict) or not validator.matches(normalized):
                            raise ValueError()
                        if normalized != value:
                            value = normalized
                            text = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        except Exception:
            self._fail()
        if self.failure is not None:text, value = '', None
        return Answer(text, value, dict(self.usage), self.first_ms, self.failure)
