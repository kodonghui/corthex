"""TC-122/123/124/128/130 partial: loopback/accounting and controlled-time retries."""
from html import escape
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from _common import ROOT
import test_memory_model_transport as transport_fixture
import test_memory_model_usage as usage_fixture
from test_memory_model_stream import SCHEMA, start, block, end, event
sys.path.insert(0,str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, configuration, locks, model_access, model_client, model_request, model_transport, model_usage

KEY = transport_fixture.KEY
DOCUMENT = '<request kind="curate" instructions="curate-3"><turns><entry id="e_sample">Keep the choice.</entry></turns></request>'
# One minimal document for each curator instruction set.
DOCUMENTS = {'curate-3': DOCUMENT,
             'merge-2': '<request kind="merge" instructions="merge-2"><items><item id="i_sample" kind="decision">Keep the choice.</item></items></request>',
             'state-2': '<request kind="state" instructions="state-2"><state><line id="l_sample">Keep the choice.</line></state></request>'}
RELEASE = json.loads((ROOT/'plugins/corthex-memory/.codex-plugin/plugin.json').read_text(encoding='utf-8'))['version']


class ModelRequestTest(unittest.TestCase):
    def setUp(self):self.credentials=model_access.Credentials.read({'CORTHEX_MEMORY_ANTHROPIC_API_KEY':KEY})

    def build(self,source=DOCUMENT,environment=None,schema=SCHEMA):
        return model_request.build(config={},instructions='curate-3',source=source,schema=schema,
            credentials=self.credentials,environment={} if environment is None else environment)

    def test_fixed_body_headers_and_no_metadata_passthrough(self):
        wire,sent=self.build();body=wire['body']
        self.assertEqual(set(body),{'model','max_tokens','stream','thinking','output_config','system','messages'})
        self.assertEqual((body['model'],body['max_tokens'],body['stream']),('claude-haiku-5-5',64000,True))
        self.assertEqual(body['thinking'],{'type':'adaptive'})
        self.assertEqual(body['output_config']['effort'],'xhigh')
        self.assertEqual(wire['url'],'https://api.anthropic.com/v1/messages')
        self.assertEqual(wire['headers']['x-api-key'],KEY)
        self.assertEqual(body['messages'],[{'role':'user','content':sent}])

    def test_complete_document_larger_than_c1_entry_is_never_clipped(self):
        text='a'*(520*1024)+'<private>hidden ending</private> preserved ending'
        xml='<request kind="curate" instructions="curate-3"><entry>'+escape(text)+'</entry></request>'
        _,sent=self.build(xml)
        entry=ET.fromstring(sent).find('entry').text
        self.assertGreater(len(entry),512*1024)
        self.assertTrue(entry.endswith('[redacted:private] preserved ending'))
        self.assertNotIn('hidden ending',sent)

    def test_entity_encoded_new_keys_are_masked_in_text_and_attributes(self):
        secret='new&<"environment-value-17b6'
        xml='<request kind="curate" instructions="curate-3"><quote said="'+escape(secret,quote=True)+'">'+escape(secret)+'</quote></request>'
        _,sent=self.build(xml,{'OPENAI_API_KEY':secret});entry=ET.fromstring(sent).find('quote')
        self.assertEqual((entry.text,entry.get('said')),('[redacted:environment]',)*2)

    def test_rotated_original_key_is_still_masked_and_escaped_tags_stay_data(self):
        content=KEY+' </entry><entry>injected</entry>'
        xml='<request kind="curate" instructions="curate-3"><entry>'+escape(content)+'</entry></request>'
        _,sent=self.build(xml,{'CORTHEX_MEMORY_ANTHROPIC_API_KEY':'rotated-key-38b6'})
        self.assertNotIn(KEY,sent);self.assertEqual(len(list(ET.fromstring(sent))),1)
        self.assertIn('</entry><entry>injected</entry>',ET.fromstring(sent).find('entry').text)

    def test_dtd_declarations_unknown_tags_and_deep_nesting_are_refused(self):
        for xml in ['<!DOCTYPE x [<!ENTITY secret "private">]>'+DOCUMENT,'<?xml version="1.0"?>'+DOCUMENT,
                    DOCUMENT.replace('<turns>','<script>').replace('</turns>','</script>'),
                    '<request kind="curate" instructions="curate-3">'+'<entry>'*18+'x'+'</entry>'*18+'</request>']:
            with self.assertRaises(ValueError):self.build(xml)

    def test_unicode_input_cannot_smuggle_encoded_dtd_or_nul(self):
        xml='<!DOCTYPE request [<!ENTITY probe "bounded-fixture-entity">]><request kind="curate" instructions="curate-3"><entry>&probe;</entry></request>'
        for encoding in ('utf-16-le','utf-16-be','utf-32-le','utf-32-be'):
            carrier=xml.encode(encoding).decode('latin-1')
            with self.subTest(encoding=encoding),self.assertRaises(ValueError):self.build(carrier)
        with self.assertRaises(ValueError):self.build(DOCUMENT.replace('Keep the choice.','invalid'+chr(0)+'data'))

    def test_invalid_explicit_override_never_falls_back_to_provider(self):
        for url in ('','http://example.invalid','https://user:password@example.com','https://example.invalid?x=1',
                    'https://example.invalid:notaport','file:///private','https://[::1'):
            with self.subTest(url=url),self.assertRaises(ValueError):
                self.build(environment={'CORTHEX_MEMORY_ANTHROPIC_BASE_URL':url})

    def test_tc132_https_and_loopback_http_overrides_are_used_as_given(self):
        for base in ('https://test.example','http://localhost:8080','http://127.0.0.1:8080','http://[::1]:8080/'):
            with self.subTest(base=base):
                wire,_=self.build(environment={'CORTHEX_MEMORY_ANTHROPIC_BASE_URL':base})
                self.assertEqual(wire['url'],base.rstrip('/')+'/v1/messages')

    def test_authentication_cannot_be_reflected_by_schema_even_when_json_escaped(self):
        self.credentials=model_access.Credentials.read({'CORTHEX_MEMORY_ANTHROPIC_API_KEY':'credential&"private'})
        with self.assertRaises(ValueError):self.build(schema=dict(SCHEMA,description='credential&"private'))

    def test_unknown_metadata_attributes_are_not_passed_through(self):
        for attribute in ('project','device','user','metadata'):
            xml=DOCUMENT.replace('<turns>','<turns '+attribute+'="fixture">')
            with self.subTest(attribute=attribute),self.assertRaises(ValueError):self.build(xml)


class ModelClientTest(unittest.TestCase):
    def setUp(self):
        self.transport=transport_fixture.ModelTransportTest();self.transport.setUp();self.addCleanup(self.transport.doCleanups)
        self.usage=usage_fixture.ModelUsageTest();self.usage.setUp();self.addCleanup(self.usage.doCleanups)
        self.environment=mock.patch.dict(os.environ,{'CORTHEX_MEMORY_ANTHROPIC_API_KEY':KEY,
            'CORTHEX_MEMORY_OPENAI_API_KEY':'','ANTHROPIC_API_KEY':'general-fixture-key-380f',
            'CORTHEX_MEMORY_ANTHROPIC_BASE_URL':'http://127.0.0.1:'+str(self.transport.server.server_port)})
        self.environment.start();self.addCleanup(self.environment.stop)

    def send(self,**options):
        arguments=dict(project='sample',instructions='curate-3',source=DOCUMENT,schema=SCHEMA,config={},check=lambda:None)
        arguments.update(options);return model_client.send(self.usage.memory,**arguments)

    def rows(self):
        return [json.loads(line) for path in (self.usage.folder/'logs').glob('usage-*.jsonl') for line in path.read_bytes().splitlines()]

    def response(self,code=None,retry=None,pending=False):
        return model_transport.Response('{"answer":"safe"}' if code is None else '',{},None,
            None if code is None else model_access.classify('anthropic',reason=code),None,retry,pending)

    def test_actual_loopback_stream_appends_one_point0055_usage_line(self):
        self.transport.reply=lambda h:self.transport.send(h,start(usage={'input_tokens':40000})+block()+end(output=3000))
        result=self.send()
        self.assertIsNone(result.response.failure);self.assertEqual((result.attempts,result.logged),(1,1))
        row,=self.rows();self.assertEqual((row['input'],row['output'],row['cost']),(40000,3000,.0055))
        self.assertEqual(row['instructions'],'curate-3');self.assertNotIn(KEY,json.dumps(row))
        taken=configuration.prepare({},temporary=False).values['prices']['taken']
        self.assertEqual((row['project'],row['call'],row['model'],row['result'],row['prices'],row['request']),
                         ('sample','curate','claude-haiku-5-5','ok',taken,'req_fixture'))
        self.assertRegex(row['at'],r'\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z\Z')
        self.assertLessEqual(0,row['first_ms']);self.assertLessEqual(row['first_ms'],row['total_ms'])
        self.assertEqual(len(self.transport.requests),1)
        self.assertEqual(self.transport.requests[0][2]['messages'][0]['content'],result.document)

    def test_missing_dedicated_key_creates_no_attempt_child_or_usage_line(self):
        with mock.patch.dict(os.environ,{'CORTHEX_MEMORY_ANTHROPIC_API_KEY':''}), \
                mock.patch.object(model_usage.Attempt,'start',side_effect=AssertionError('no attempt')):
            with self.assertRaises(model_client.MissingKey):self.send()
        self.assertEqual(self.transport.requests,[]);self.assertEqual(self.rows(),[])

    def test_passing_failures_have_three_attempts_and_10_60_second_backoffs(self):
        now,waits=[clock.now()],[]
        def wait(seconds,deadline,check):waits.append(seconds);now[0]+=seconds;check();return True
        answers=[self.response('network'),self.response('api_error'),self.response()]
        with mock.patch.object(clock,'now',side_effect=lambda:now[0]), \
                mock.patch.object(model_client,'_wait',side_effect=wait), \
                mock.patch.object(model_transport,'once',side_effect=answers) as once:
            result=self.send()
        self.assertEqual(waits,[10,60]);self.assertEqual((result.attempts,result.logged),(3,3))
        self.assertEqual(len({call.kwargs['deadline'] for call in once.call_args_list}),1)
        self.assertEqual([r['result'] for r in self.rows()],['failed','failed','ok'])

    def test_tc121_spec018_first_criterion_529_twice_then_200_succeeds_after_two_retries(self):
        replies=[lambda h:self.transport.send(h,b'{"error":{"type":"overloaded_error"}}',status=529,mime='application/json')]*2
        replies.append(lambda h:self.transport.send(h,start(usage={'input_tokens':40000})+block()+end(output=3000)))
        self.transport.reply=lambda h:replies[len(self.transport.requests)-1](h)
        waits=[]
        with mock.patch.object(model_client,'_wait',side_effect=lambda pause,*args:waits.append(pause) or True):
            result=self.send()
        self.assertIsNone(result.response.failure);self.assertEqual(json.loads(result.response.text),{'answer':'가나'})
        self.assertEqual((result.attempts,result.logged,len(self.transport.requests),waits),(3,3,3,[10,60]))
        rows=self.rows()
        self.assertEqual([(r['result'],r.get('error')) for r in rows],
                         [('failed','overloaded_error'),('failed','overloaded_error'),('ok',None)])
        self.assertEqual((rows[-1]['input'],rows[-1]['output'],rows[-1]['cost']),(40000,3000,.0055))

    def test_tc125_refusal_output_limit_and_empty_answers_of_every_curator_request(self):
        endings=(('refusal',start()+block()+end('refusal'),True,'refused'),
                 ('max-tokens',start()+block('{"answer":"가')+end('max_tokens'),True,'limit'),
                 ('empty-answer',start()+end(),False,'failed'))
        for instructions,source in DOCUMENTS.items():
            call='curate' if instructions=='curate-3' else 'consolidate'
            for code,wire,lasting,usage in endings:
                before,requests,waits=len(self.rows()),len(self.transport.requests),[]
                self.transport.reply=lambda h,w=wire:self.transport.send(h,w)
                with self.subTest(instructions=instructions,code=code), \
                        mock.patch.object(model_client,'_wait',side_effect=lambda pause,*args:waits.append(pause) or True):
                    result=self.send(instructions=instructions,source=source)
                    failure,attempts=result.response.failure,1 if lasting else 3
                    self.assertEqual((failure.code,failure.lasting,failure.result),(code,lasting,usage))
                    self.assertEqual(result.response.text,'')
                    self.assertEqual((result.attempts,result.logged,len(self.transport.requests)-requests),(attempts,)*3)
                    self.assertEqual(waits,[] if lasting else [10,60])
                    self.assertEqual([(r['call'],r['instructions'],r['result'],r['error'],r['output']) for r in self.rows()[before:]],
                                     [(call,instructions,usage,code,7)]*attempts)
                    self.assertEqual(self.transport.requests[-1][2]['messages'][0]['content'],result.document)

    def test_tc128_a_stream_error_event_is_retried_like_its_http_row(self):
        marker='PRIVATE_STREAM_ERROR_MARKER_2d7a'
        self.transport.reply=lambda h:self.transport.send(h,start()+event('error',error={'type':'overloaded_error','message':marker}))
        waits=[]
        with mock.patch.object(model_client,'_wait',side_effect=lambda pause,*args:waits.append(pause) or True):
            result=self.send()
        self.assertEqual((result.response.failure.code,result.response.failure.lasting),('overloaded_error',False))
        self.assertEqual((result.attempts,result.logged,len(self.transport.requests),waits),(3,3,3,[10,60]))
        rows=self.rows()
        self.assertEqual([(r['result'],r['error'],r['input']) for r in rows],[('failed','overloaded_error',4)]*3)
        self.assertNotIn(marker,json.dumps(rows)+repr(result))

    def test_tc131_anthropic_requests_carry_only_their_own_key_and_no_identity(self):
        openai,error,project='PRIVATE_OPENAI_KEY_MARKER_41d0','PRIVATE_PROVIDER_ERROR_MARKER_8e2a','project-marker-7d1c'
        self.transport.reply=lambda h:self.transport.send(h,json.dumps({'error':{'type':'overloaded_error','message':error}}).encode(),
                                                         status=529,mime='application/json')
        launched,real=[],subprocess.Popen
        def popen(arguments,*args,**options):
            launched.append((arguments,dict(options.get('env') or {})));return real(arguments,*args,**options)
        with mock.patch.dict(os.environ,{'CORTHEX_MEMORY_OPENAI_API_KEY':openai}), \
                mock.patch.object(model_client,'_wait',return_value=True), \
                mock.patch.object(model_transport.subprocess,'Popen',side_effect=popen):
            result=self.send(project=project)
        self.assertEqual((result.attempts,len(self.transport.requests),len(launched)),(3,3,3))
        for path,headers,body in self.transport.requests:
            headers={name.lower():value for name,value in headers.items()}
            self.assertEqual((path,headers['content-type'],headers['user-agent'],headers['x-api-key']),
                             ('/v1/messages','application/json','corthex-memory/'+RELEASE,KEY))
            self.assertNotIn('authorization',headers)
            self.assertFalse({'metadata','user'}&set(body))
            sent=json.dumps([headers,body],ensure_ascii=False)
            for value in (openai,project,usage_fixture.DEVICE):self.assertNotIn(value,sent)
        stored=b''.join(path.read_bytes() for path in sorted(self.usage.folder.rglob('*')) if path.is_file())
        commands=json.dumps(launched)
        for value in (KEY,openai,error):
            self.assertNotIn(value.encode(),stored);self.assertNotIn(value,commands)

    def test_tc133_thinking_pings_and_split_bytes_reach_only_the_text_and_every_counter(self):
        hidden,text='PRIVATE_THINKING_MARKER_5c1e','{"answer":"가나"}'
        wire=(start(usage={'input_tokens':1200,'output_tokens':1,'cache_creation_input_tokens':300,'cache_read_input_tokens':500})+
              event('ping')+event('content_block_start',index=0,content_block={'type':'thinking','thinking':''})+
              event('content_block_delta',index=0,delta={'type':'thinking_delta','thinking':hidden})+
              event('content_block_delta',index=0,delta={'type':'signature_delta','signature':hidden})+
              event('content_block_stop',index=0)+event('content_block_start',index=1,content_block={'type':'text','text':''})+
              b''.join(event('content_block_delta',index=1,delta={'type':'text_delta','text':part})
                       for part in (text[:7],text[7:12],text[12:]))+
              event('ping')+event('content_block_stop',index=1)+end(output=55))
        def reply(handler):
            handler.send_response(200);handler.send_header('Content-Type','text/event-stream')
            handler.send_header('request-id','req_fixture');handler.end_headers()
            # One byte at a time, so lines, events and UTF-8 characters arrive split.
            for index in range(len(wire)):handler.wfile.write(wire[index:index+1]);handler.wfile.flush()
        self.transport.reply=reply
        result=self.send()
        self.assertIsNone(result.response.failure);self.assertEqual(result.response.text,text)
        row,=self.rows()
        self.assertEqual({name:row[name] for name in ('input','output','cache_write','cache_read','request','result')},
                         dict(input=1200,output=55,cache_write=300,cache_read=500,request='req_fixture',result='ok'))
        self.assertLessEqual(0,row['first_ms']);self.assertLessEqual(row['first_ms'],row['total_ms'])
        self.assertNotIn(hidden,json.dumps(row)+repr(result))

    def test_retry_after_lasting_failure_and_cleanup_uncertainty_stop_retries(self):
        for answer in (self.response('authentication_error'),self.response('network',301),self.response('network',pending=True)):
            with mock.patch.object(model_transport,'once',return_value=answer) as once, \
                    mock.patch.object(model_client,'_wait',side_effect=AssertionError('no wait')):
                result=self.send();self.assertEqual((result.attempts,once.call_count),(1,1))

    def test_retry_after_longer_than_default_is_used_but_not_past_deadline(self):
        waits=[]
        with mock.patch.object(model_client,'_wait',side_effect=lambda seconds,*args:waits.append(seconds) or True), \
                mock.patch.object(model_transport,'once',side_effect=[self.response('api_error',75),self.response()]):
            self.send()
        self.assertEqual(waits,[75])
        with mock.patch.object(model_transport,'once',return_value=self.response('api_error',75)) as once:
            self.assertEqual(self.send(deadline=clock.now()+30).attempts,1);self.assertEqual(once.call_count,1)

    def test_a_request_is_tried_again_only_while_its_caller_says_it_may_still_go(self):
        asked,answers=[],[True,False]
        def still():asked.append(once.call_count);return answers[len(asked)-1]
        with mock.patch.object(model_transport,'once',return_value=self.response('api_error')) as once, \
                mock.patch.object(model_client,'_wait',return_value=True):
            result=self.send(still=still)
            self.assertEqual((result.response.failure.code,result.attempts,result.logged,asked),('api_error',2,2,[1,2]))
            # A caller that never says no changes nothing, and one answer asks nothing.
            self.assertEqual(self.send(still=lambda:True).attempts,3)
            once.return_value=self.response()
            self.assertEqual(self.send(still=mock.Mock(side_effect=AssertionError)).attempts,1)
            calls=once.call_count
            with self.assertRaises(TypeError):self.send(still=True)
            self.assertEqual(once.call_count,calls)
        self.assertEqual([r['result'] for r in self.rows()],['failed']*5+['ok'])

    def test_lost_original_check_during_wait_propagates_without_retry(self):
        original=locks.LostLock();active=[True]
        def check():
            if not active[0]:raise original
        def wait(*args):active[0]=False;check()
        with mock.patch.object(model_transport,'once',return_value=self.response('network')) as once, \
                mock.patch.object(model_client,'_wait',side_effect=wait):
            with self.assertRaises(locks.LostLock) as caught:self.send(check=check)
        self.assertIs(caught.exception,original);self.assertEqual(once.call_count,1)

    def test_logging_failure_never_retries_a_successful_call(self):
        with mock.patch.object(model_usage.Attempt,'record',side_effect=RuntimeError('unavailable')):
            result=self.send()
        self.assertIsNone(result.response.failure);self.assertEqual((result.attempts,result.logged),(1,0))
        self.assertEqual(len(self.transport.requests),1)

    def test_stalled_error_body_keeps_301_second_header_and_sends_no_retry(self):
        def stall(handler):
            self.transport.send(handler,b'',status=500,headers={'retry-after':'301'});time.sleep(5)
        self.transport.reply=stall
        result=self.send(deadline=clock.now()+4)
        self.assertEqual(result.response.retry_after,301);self.assertEqual(result.attempts,1)
        self.assertEqual(len(self.transport.requests),1)

    def test_original_cancellation_keeps_partial_billing_without_provider_error(self):
        reached=threading.Event();original=locks.LostLock()
        def reply(handler):
            self.transport.send(handler,start(usage={'input_tokens':40000}));reached.set();time.sleep(.6)
        self.transport.reply=reply
        def check():
            if reached.is_set():raise original
        with self.assertRaises(locks.LostLock) as caught:self.send(check=check)
        self.assertIs(caught.exception,original)
        row,=self.rows();self.assertEqual(row['result'],'failed');self.assertNotIn('error',row)
        self.assertEqual(len(self.transport.requests),1)

    def test_non_none_check_and_expired_deadline_send_nothing(self):
        with self.assertRaises(TypeError):self.send(check=lambda:True)
        result=self.send(deadline=clock.now()-1)
        self.assertEqual((result.attempts,result.logged),(0,0));self.assertEqual(self.transport.requests,[])

    def test_endpoint_auth_and_config_stay_original_while_new_environment_keys_are_redacted(self):
        seen=[];source=DOCUMENT.replace('Keep the choice.','newly-set-environment-token-9b72')
        def once(payload,**kwargs):
            seen.append(payload)
            os.environ.update(CORTHEX_MEMORY_ANTHROPIC_API_KEY='rotated-authentication-token-63bf',
                CORTHEX_MEMORY_ANTHROPIC_BASE_URL='https://other.example.invalid',
                OPENAI_API_KEY='newly-set-environment-token-9b72')
            return self.response('network') if len(seen)==1 else self.response()
        with mock.patch.dict(os.environ,{},clear=False),mock.patch.object(model_transport,'once',side_effect=once), \
                mock.patch.object(model_client,'_wait',return_value=True):
            self.send(source=source)
        self.assertEqual(seen[0]['url'],seen[1]['url'])
        self.assertEqual(seen[1]['headers']['x-api-key'],KEY)
        self.assertNotIn('newly-set-environment-token-9b72',seen[1]['body']['messages'][0]['content'])

    def test_expired_during_redaction_reports_no_document_as_sent(self):
        now=[clock.now()];real=model_request.build
        def build(**kwargs):now[0]+=2;return real(**kwargs)
        with mock.patch.object(clock,'now',side_effect=lambda:now[0]),mock.patch.object(model_request,'build',side_effect=build):
            result=self.send(deadline=now[0]+1)
        self.assertEqual((result.attempts,result.document),(0,''));self.assertEqual(self.transport.requests,[])

    def test_actual_error_table_uses_closed_codes_and_one_line_per_attempt(self):
        cases=((400,'invalid_request_error',True),(401,'authentication_error',True),
               (402,'billing_error',True),(403,'permission_error',True),(404,'not_found_error',True),
               (409,'conflict_error',False),(413,'request_too_large',True),(429,'rate_limit_error',False),
               (500,'api_error',False),(504,'timeout_error',False),(529,'overloaded_error',False))
        for status,code,lasting in cases:
            before=len(self.rows());requests=len(self.transport.requests);waits=[]
            self.transport.reply=lambda h,s=status:self.transport.send(h,
                b'{"error":{"message":"fixture-error-body-must-not-be-logged"}}',status=s,mime='application/json')
            with self.subTest(status=status),mock.patch.object(model_client,'_wait',side_effect=lambda pause,*args:waits.append(pause) or True):
                result=self.send();attempts=1 if lasting else 3
                self.assertEqual((result.response.failure.code,result.attempts,result.logged),(code,attempts,attempts))
                self.assertEqual(len(self.rows())-before,attempts)
                self.assertEqual(len(self.transport.requests)-requests,attempts)
                self.assertEqual(waits,[] if lasting else [10,60])
                self.assertNotIn('fixture-error-body-must-not-be-logged',json.dumps(self.rows()))


if __name__=='__main__':unittest.main()
