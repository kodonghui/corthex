"""Pure SSE component fixtures only; actual HTTPS/retry integration remains later."""
import json
import sys
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, model_stream

SECRET = 'fixture-provider-private-text-850c'
SCHEMA = {'type': 'object', 'properties': {'answer': {'type': 'string'}},
          'required': ['answer'], 'additionalProperties': False}


def event(kind, **data):
    return ('event: '+kind+'\ndata: '+json.dumps(dict(type=kind, **data), ensure_ascii=False)+'\n\n').encode('utf-8')


def start(**changes):
    message = dict(type='message', role='assistant', content=[],
                   usage={'input_tokens': 4, 'output_tokens': 1, 'cache_creation_input_tokens': 2, 'cache_read_input_tokens': 3})
    message.update(changes)
    return event('message_start', message=message)


def block(text='{"answer":"가나"}', index=0):
    return (event('content_block_start', index=index, content_block={'type': 'text', 'text': ''})+
            event('content_block_delta', index=index, delta={'type': 'text_delta', 'text': text})+
            event('content_block_stop', index=index))


def end(reason='end_turn', output=7):
    return event('message_delta', delta={'stop_reason': reason}, usage={'output_tokens': output})+event('message_stop')


class ModelStreamTest(unittest.TestCase):
    def decode(self, wire, **limits):
        decoder = model_stream.Decoder(started=clock.now(), **limits)
        decoder.feed(wire)
        return decoder, decoder.finish(schema=SCHEMA)

    def test_complete_structured_text_and_provider_counters(self):
        decoder, answer = self.decode(start()+block()+end())
        self.assertIsNone(answer.failure)
        self.assertEqual(answer.value, {'answer': '가나'})
        self.assertEqual(answer.usage, {'input_tokens': 4, 'output_tokens': 7,
                                      'cache_creation_input_tokens': 2, 'cache_read_input_tokens': 3})
        self.assertEqual(answer.text, '{"answer":"가나"}')
        self.assertIsNotNone(answer.first_ms)
        self.assertNotIn('가나', repr(answer))

    def test_every_utf8_byte_boundary_and_split_crlf(self):
        decoder = model_stream.Decoder(started=clock.now())
        wire=b'\xef\xbb\xbf'+(start()+block()+end()).replace(b'\n', b'\r\n')
        for byte in wire:decoder.feed(bytes((byte,)))
        self.assertEqual(decoder.finish(schema=SCHEMA).value, {'answer': '가나'})

    def test_cr_only_and_multiline_json_data_frames(self):
        wire=start()+block()+end()
        d, result=self.decode(wire.replace(b'\n',b'\r'))
        self.assertIsNone(result.failure)
        head=json.dumps({'type':'message_start','message':{'type':'message','role':'assistant','content':[],
                         'usage':{'input_tokens':2}}},indent=2)
        frame=('event: message_start\n'+''.join('data: '+s+'\n' for s in head.splitlines())+'\n').encode()
        self.assertEqual(self.decode(frame+block()+end())[1].value, {'answer':'가나'})

    def test_ping_comments_and_unknown_events_discard_their_contents(self):
        unknown=b'event: future_event\ndata: '+SECRET.encode()+b' not JSON\n\n'
        decoder, answer=self.decode(b': comment\n\n'+start()+event('ping')+unknown+block()+end())
        self.assertIsNone(answer.failure)
        self.assertNotIn(SECRET,repr(decoder.__dict__))

    def test_thinking_signature_and_future_block_data_never_become_text(self):
        hidden=(event('content_block_start',index=0,content_block={'type':'thinking','thinking':SECRET})+
                event('content_block_delta',index=0,delta={'type':'thinking_delta','thinking':SECRET})+
                event('content_block_delta',index=0,delta={'type':'signature_delta','signature':SECRET})+
                event('content_block_stop',index=0))
        decoder, answer=self.decode(start()+hidden+block(index=1)+end())
        self.assertIsNone(answer.failure)
        self.assertNotIn(SECRET,repr(decoder.__dict__))
        self.assertNotIn(SECRET,answer.text)

    def test_cumulative_usage_overwrites_instead_of_adding(self):
        wire=start()+block()+event('message_delta',delta={},usage={'output_tokens':10})+end(output=12)
        self.assertEqual(self.decode(wire)[1].usage['output_tokens'],12)

    def test_only_documented_action_kind_enums_are_canonicalized(self):
        schema={'type':'object','properties':{'action':{'enum':['add','withdraw']},
                'kind':{'$ref':'#/$defs/kind'},'text':{'type':'string'}},
                'required':['action','kind','text'],'additionalProperties':False,'$defs':{'kind':{'enum':['decision','lesson']}}}
        decoder=model_stream.Decoder(started=clock.now())
        decoder.feed(start()+block('{"action":"ADD","kind":"DECISION","text":"KEEP CASE"}')+end())
        answer=decoder.finish(schema=schema)
        self.assertIsNone(answer.failure)
        self.assertEqual(json.loads(answer.text),{'action':'add','kind':'decision','text':'KEEP CASE'})

    def test_first_token_time_is_the_first_nonempty_text_not_ping_or_thinking(self):
        decoder=model_stream.Decoder(started=10)
        with mock.patch.object(clock,'now',return_value=10.125):
            decoder.feed(start()+event('ping')+block()+end())
        self.assertEqual(decoder.finish(schema=SCHEMA).first_ms,125)

    def test_refusal_and_output_limit_discard_partial_answers_but_keep_usage(self):
        for reason, result in (('refusal','refused'),('max_tokens','limit')):
            answer=self.decode(start()+block(SECRET)+end(reason))[1]
            self.assertEqual(answer.failure.result,result)
            self.assertTrue(answer.failure.lasting)
            self.assertEqual(answer.text,'')
            self.assertIsNone(answer.value)
            self.assertEqual(answer.usage['output_tokens'],7)

    def test_empty_bad_json_schema_and_unknown_stop_reasons(self):
        for text,code in (('', 'empty-answer'),(' \n','empty-answer'),('bad','bad-answer'),
                          ('[]','bad-answer'),('{}','bad-answer'),('{"answer":5}','bad-answer'),
                          ('{"answer":"a","answer":"b"}','bad-answer'),('{"answer":NaN}','bad-answer')):
            with self.subTest(text=text):self.assertEqual(self.decode(start()+block(text)+end())[1].failure.code,code)
        decoder, answer=self.decode(start()+block()+end(SECRET))
        self.assertEqual(answer.failure.code,'bad-answer')
        self.assertNotIn(SECRET,repr(decoder.__dict__))

    def test_known_and_unknown_stream_error_kinds_do_not_retain_provider_text(self):
        for kind,code in (('overloaded_error','overloaded_error'),(SECRET,'api_error')):
            decoder, answer=self.decode(start()+event('error',error={'type':kind,'message':SECRET}))
            self.assertEqual(answer.failure.code,code)
            self.assertNotIn(SECRET,repr(decoder.__dict__))
            self.assertEqual(answer.usage['input_tokens'],4)

    def test_every_incomplete_final_boundary_is_a_bad_answer(self):
        parts=[start(),event('content_block_start',index=0,content_block={'type':'text','text':''}),
               event('content_block_delta',index=0,delta={'type':'text_delta','text':'{"answer":"a"}'}),
               event('content_block_stop',index=0),event('message_delta',delta={'stop_reason':'end_turn'},usage={'output_tokens':2}),
               event('message_stop')]
        for stop in range(len(parts)):
            self.assertEqual(self.decode(b''.join(parts[:stop]))[1].failure.code,'bad-answer')
        for cut in (1,2,3,8):self.assertEqual(self.decode(b''.join(parts)[:-cut])[1].failure.code,'bad-answer')

    def test_order_indices_duplicate_end_and_mismatched_event_type_refuse(self):
        malformed=[start()+start(),event('message_stop'),start()+event('message_stop'),
                   start()+block(index=1)+end(),start()+block(index=True)+end(),
                   start()+event('content_block_stop',index=0),
                   start()+event('content_block_start',index=0,content_block={'type':'text','text':''})+end(),
                   start()+block()+end()+event('message_stop'),
                   b'event: message_start\ndata: {"type":"ping"}\n\n']
        malformed.append(start()+event('content_block_start',index=0,content_block={'type':'text','text':''})+
                         event('content_block_start',index=1,content_block={'type':'text','text':''}))
        for wire in malformed:self.assertEqual(self.decode(wire)[1].failure.code,'bad-answer')

    def test_invalid_usage_and_utf8_and_nonfinite_json_fail_safely(self):
        for wire in (start(usage=None),start(usage={'input_tokens':True}),start(usage={'output_tokens':-1}),
                     b'event: message_start\ndata: \xff\n\n',
                     b'event: message_start\ndata: {"type":"message_start","message":NaN}\n\n'):
            self.assertEqual(self.decode(wire)[1].failure.code,'bad-answer')

    def test_event_and_text_limits_are_enforced_for_unknown_content_too(self):
        for wire,limits in ((b'event: unknown\ndata: '+b'x'*200,{'event_bytes':100}),
                            (start()+block()+end(),{'text_bytes':2}),
                            (b':'+b'x'*200+b'\n\n',{'event_bytes':100})):
            self.assertEqual(self.decode(wire,**limits)[1].failure.code,'bad-answer')

    def test_detected_failure_cannot_be_reset_by_a_later_complete_message(self):
        decoder=model_stream.Decoder(started=clock.now())
        decoder.feed(event('message_stop'))
        decoder.feed(start()+block()+end())
        self.assertEqual(decoder.finish(schema=SCHEMA).failure.code,'bad-answer')
