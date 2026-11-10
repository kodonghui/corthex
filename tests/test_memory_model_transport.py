"""Actual loopback HTTP and private child lifetime; no external API or user data."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import select
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, locks, model_transport, model_wire
from test_memory_model_stream import SCHEMA, start, block, end, event

KEY = 'fixture-private-memory-api-key-38bc'


class ModelTransportTest(unittest.TestCase):
    def setUp(self):
        self.requests, self.children = [], []
        self.reply = lambda h: self.send(h, start()+block()+end())
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                outer.requests.append((self.path, dict(self.headers), json.loads(body)))
                try:outer.reply(self)
                except (OSError, ValueError):pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        def cleanup():
            self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=3)
        self.addCleanup(cleanup)
        values = {k: '' for k in ('HTTPS_PROXY','HTTP_PROXY','ALL_PROXY','https_proxy','http_proxy','all_proxy')}
        values.update(NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1')
        self.environment = mock.patch.dict(os.environ, values)
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.payload = dict(url='http://127.0.0.1:'+str(self.server.server_port)+'/v1/messages',
            headers={'x-api-key': KEY, 'anthropic-version': '2026-10-21', 'content-type': 'application/json',
                     'user-agent': 'corthex-memory/0.2.1'}, body={'model': 'fixture-model','stream': True}, schema=SCHEMA)

    def send(self, handler, body, status=200, headers=None, mime='text/event-stream'):
        handler.send_response(status)
        handler.send_header('Content-Type', mime)
        handler.send_header('request-id', 'req_fixture')
        for k,v in (headers or {}).items():handler.send_header(k,v)
        handler.end_headers()
        handler.wfile.write(body); handler.wfile.flush()

    def once(self, *, seconds=30, gap=10, check=lambda:None, payload=None, connect=30):
        begun = clock.now(); popen = subprocess.Popen
        def spawn(*args, **kwargs):
            self.assertNotIn(KEY, repr(args))
            self.assertFalse(any(k in kwargs['env'] for k in ('ANTHROPIC_API_KEY','OPENAI_API_KEY','CORTHEX_MEMORY_ANTHROPIC_API_KEY')))
            self.assertEqual(kwargs['stderr'],subprocess.DEVNULL)
            child=popen(*args,**kwargs); self.children.append(child); return child
        with mock.patch.object(subprocess,'Popen',side_effect=spawn):
            answer=model_transport.once(payload or self.payload,deadline=begun+seconds,started=begun,
                                         connect=connect,gap=gap,check=check)
        self.assertTrue(all(c.poll() is not None for c in self.children))
        return answer

    def test_actual_http_uses_only_auth_header_and_returns_safe_stream_accounting(self):
        answer=self.once()
        self.assertIsNone(answer.failure)
        self.assertEqual(json.loads(answer.text),{'answer':'가나'})
        self.assertEqual(answer.usage['output_tokens'],7)
        self.assertIsNotNone(answer.first_ms)
        self.assertEqual(answer.request,'req_fixture')
        self.assertFalse(answer.cleanup_pending)
        self.assertEqual(len(self.requests),1)
        path,headers,body=self.requests[0]
        self.assertEqual(path,'/v1/messages')
        self.assertEqual(headers['X-Api-Key'],KEY)
        self.assertNotIn(KEY,json.dumps(body))
        self.assertNotIn(KEY,repr(answer))

    def test_http_error_discards_body_and_normalizes_unknown_type(self):
        self.reply=lambda h:self.send(h,json.dumps({'error':{'type':KEY,'message':KEY}}).encode(),
                                     status=418,mime='application/json',headers={'retry-after':KEY})
        answer=self.once()
        self.assertEqual((answer.failure.code,answer.failure.lasting),('invalid_request_error',True))
        self.assertIsNone(answer.retry_after)
        self.assertNotIn(KEY,repr(answer))

    def test_known_http500_timeout_type_is_preserved(self):
        self.reply=lambda h:self.send(h,b'{"error":{"type":"timeout_error","message":"private"}}',
                                     status=500,mime='application/json',headers={'retry-after':'301'})
        answer=self.once()
        self.assertEqual((answer.failure.code,answer.failure.lasting,answer.retry_after),('timeout_error',False,301))

    def test_actual_http_status_table_and_bounded_retry_after(self):
        cases=((400,'invalid_request_error',True),(401,'authentication_error',True),
               (402,'billing_error',True),(403,'permission_error',True),(404,'not_found_error',True),
               (409,'conflict_error',False),(413,'request_too_large',True),(429,'rate_limit_error',False),
               (500,'api_error',False),(504,'timeout_error',False),(529,'overloaded_error',False))
        for status,code,lasting in cases:
            with self.subTest(status=status):
                self.reply=lambda h,s=status:self.send(h,b'{"error":{"message":"private"}}',status=s,
                                            mime='application/json',headers={'retry-after':'10'})
                answer=self.once()
                self.assertEqual((answer.failure.code,answer.failure.lasting,answer.failure.status),(code,lasting,status))
                self.assertEqual(answer.retry_after,10)
        for raw,expected in (('-2',0),('300',300),('350',301),('NaN',None),
                             ('Wed, 01 Jan 2030 00:00:00 GMT',301),(KEY,None)):
            self.reply=lambda h,r=raw:self.send(h,b'{}',status=429,mime='application/json',headers={'retry-after':r})
            self.assertEqual(self.once().retry_after,expected)
        self.assertEqual(len(self.requests),len(cases)+6)

    def test_redirect_is_not_followed(self):
        self.reply=lambda h:self.send(h,b'',status=307,headers={'location':self.payload['url']})
        answer=self.once()
        self.assertEqual(answer.failure.code,'invalid_request_error')
        self.assertTrue(answer.failure.lasting)
        self.assertEqual(len(self.requests),1)

    def test_plain_loopback_does_not_send_api_auth_to_an_environment_proxy(self):
        # Port zero is unreachable: honoring this proxy would fail the call.
        with mock.patch.dict(os.environ,{'HTTP_PROXY':'http://127.0.0.1:0','http_proxy':'http://127.0.0.1:0',
                                         'NO_PROXY':'','no_proxy':''}):
            self.assertIsNone(self.once().failure)
        self.assertEqual(len(self.requests),1)

    def test_missing_duplicate_or_extra_auth_headers_make_no_request(self):
        original=dict(self.payload['headers'])
        variants=[{k:v for k,v in original.items() if k!='x-api-key'},
                  dict(original,**{'X-Api-Key':'other-fixture-credential'}),
                  dict(original,metadata='private'),dict(original,**{'x-api-key':KEY+'\r\nprivate'})]
        for headers in variants:
            self.assertIsNotNone(self.once(payload=dict(self.payload,headers=headers)).failure)
        self.assertEqual(self.requests,[])

    def test_byte_gap_timeout_keeps_already_reported_usage_and_request_id(self):
        def reply(h):
            self.send(h,start())
            time.sleep(1)
        self.reply=reply
        answer=self.once(gap=.15)
        self.assertEqual(answer.failure.code,'timeout')
        self.assertEqual(answer.usage['input_tokens'],4)
        self.assertEqual(answer.request,'req_fixture')

    def test_continuous_pings_never_renew_the_whole_deadline(self):
        def reply(h):
            self.send(h,start())
            for _ in range(60):
                time.sleep(.05); h.wfile.write(event('ping')); h.wfile.flush()
        self.reply=reply; begun=time.monotonic()
        answer=self.once(seconds=1.25,gap=.3)
        self.assertLess(time.monotonic()-begun,2)
        self.assertEqual(answer.failure.code,'timeout')
        self.assertEqual(len(self.requests),1)
        self.assertEqual(answer.usage['input_tokens'],4)

    def test_settle_bounds_the_clean_up_and_a_thread_waits_for_the_child(self):
        # The answer never comes in time, and the killed child takes longer to end than the clean-up may wait, as
        # on a busy runner (TC-207): with `settle` the attempt returns that soon after its end and says so.
        self.reply=lambda h:time.sleep(2)
        popen=subprocess.Popen; real=popen.wait; waits=[]
        def wait(process,timeout=None):
            if timeout is None:
                return real(process)
            waits.append(timeout)
            time.sleep(timeout)
            raise subprocess.TimeoutExpired(process.args,timeout)
        for settle,least,most in ((.02,0,.2),(None,.15,None)):
            with self.subTest(settle=settle):
                children=[]; del waits[:]
                def spawn(*args,**kwargs):
                    child=popen(*args,**kwargs); children.append(child); return child
                begun=clock.now()
                with mock.patch.object(subprocess,'Popen',side_effect=spawn), \
                        mock.patch.object(popen,'wait',autospec=True,side_effect=wait):
                    answer=model_transport.once(self.payload,deadline=begun+.5,started=begun,connect=.5,gap=.5,
                                                check=lambda:None,settle=settle)
                    after=clock.now()-begun-.5
                    self.assertEqual((answer.failure.code,answer.cleanup_pending),('timeout',True))
                    self.assertGreaterEqual(after,least)
                    if most is not None:
                        self.assertLess(after,most)
                    self.assertLessEqual(sum(waits),.2 if settle is None else settle)
                    # A daemon thread waits for the killed child, so that it does not stay a zombie.
                    (child,)=children; until=clock.now()+5
                    while child.returncode is None and clock.now()<until:
                        time.sleep(.01)
                    self.assertIsNotNone(child.returncode)
        with self.assertRaises(ValueError):
            model_transport.once(self.payload,deadline=clock.now()+1,started=clock.now(),check=lambda:None,
                                 settle=-1)

    def test_a_waiting_thread_that_cannot_start_changes_neither_the_answer_nor_the_exception(self):
        self.reply=lambda h:time.sleep(2)
        popen=subprocess.Popen; real=popen.wait; thread=threading.Thread; children=[]
        def wait(process,timeout=None):
            if timeout is None:
                return real(process)
            raise subprocess.TimeoutExpired(process.args,timeout)
        def spawn(*args,**kwargs):
            child=popen(*args,**kwargs); children.append(child); return child
        def make(*args,**kwargs):
            if kwargs.get('target') is model_transport._reap:
                raise RuntimeError("can't start new thread")
            return thread(*args,**kwargs)
        expected=locks.LostLock(); sent=[]
        def check():
            if len(self.requests)>sent[-1]:raise expected
        for checked in (lambda:None,check):
            begun=clock.now(); sent.append(len(self.requests))
            with mock.patch.object(subprocess,'Popen',side_effect=spawn), \
                    mock.patch.object(popen,'wait',autospec=True,side_effect=wait), \
                    mock.patch.object(threading,'Thread',side_effect=make):
                if checked is check:
                    with self.assertRaises(locks.LostLock) as caught:
                        model_transport.once(self.payload,deadline=begun+5,started=begun,connect=5,gap=5,
                                             check=check,settle=.02)
                    self.assertIs(caught.exception,expected)
                else:
                    answer=model_transport.once(self.payload,deadline=begun+.5,started=begun,connect=.5,gap=.5,
                                                check=checked,settle=.02)
                    self.assertEqual((answer.failure.code,answer.cleanup_pending),('timeout',True))
        self.assertEqual(len(children),2)
        for child in children:
            child.wait(timeout=5)

    def test_original_check_loss_cancels_and_preserves_the_original_exception(self):
        def reply(h):time.sleep(1)
        self.reply=reply; expected=locks.LostLock()
        def check():
            if self.requests:raise expected
        with self.assertRaises(locks.LostLock) as caught:self.once(check=check)
        self.assertIs(caught.exception,expected)
        self.assertTrue(all(c.poll() is not None for c in self.children))

    def test_reflected_escaped_credential_and_wrong_mime_never_become_answers(self):
        encoded=''.join('\\u%04x'%ord(c) for c in KEY)
        self.reply=lambda h:self.send(h,start()+block('{"answer":"'+encoded+'"}')+end())
        answer=self.once()
        self.assertEqual(answer.failure.code,'bad-answer')
        self.assertEqual(answer.text,'')
        self.reply=lambda h:self.send(h,start()+block()+end(),mime='text/html')
        self.assertEqual(self.once().failure.code,'bad-answer')

    def test_expired_or_boolean_admission_starts_no_child_or_request(self):
        with mock.patch.object(subprocess,'Popen') as spawn:
            answer=model_transport.once(self.payload,deadline=clock.now()-1,started=clock.now()-2,check=lambda:None)
            self.assertEqual(answer.failure.code,'timeout')
            with self.assertRaises(TypeError):
                model_transport.once(self.payload,deadline=clock.now()+1,started=clock.now(),check=lambda:True)
        spawn.assert_not_called(); self.assertEqual(self.requests,[])

    def test_process_creation_failure_is_safe_and_rechecks_original_gate(self):
        begun=clock.now()
        with mock.patch.object(subprocess,'Popen',side_effect=OSError(KEY)):
            answer=model_transport.once(self.payload,deadline=begun+3,started=begun,check=lambda:None)
        self.assertEqual(answer.failure.code,'network')
        self.assertNotIn(KEY,repr(answer));self.assertEqual(self.requests,[])
        expected=locks.LostLock();calls=[]
        def check():
            calls.append(None)
            if len(calls)==3:raise expected
        with mock.patch.object(subprocess,'Popen',side_effect=OSError(KEY)):
            with self.assertRaises(locks.LostLock) as caught:
                model_transport.once(self.payload,deadline=begun+3,started=begun,check=check)
        self.assertIs(caught.exception,expected)

    def test_late_process_creation_sends_no_credentials_or_request(self):
        popen=subprocess.Popen;children=[]
        def late(*args,**kwargs):
            child=popen(*args,**kwargs);children.append(child);time.sleep(.2);return child
        begun=clock.now()
        with mock.patch.object(subprocess,'Popen',side_effect=late):
            answer=model_transport.once(self.payload,deadline=begun+.1,started=begun,check=lambda:None)
        self.assertEqual(answer.failure.code,'timeout')
        self.assertTrue(all(c.poll() is not None for c in children))
        self.assertEqual(self.requests,[])

    def certificate(self, names='DNS:localhost,IP:127.0.0.1'):
        program=shutil.which('openssl')
        if not program or not Path(program).is_absolute():self.skipTest('openssl is not on an absolute PATH')
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        folder=Path(temporary.name).resolve(); cert,key=folder/'cert.pem',folder/'key.pem'
        done=subprocess.run([program,'req','-x509','-newkey','rsa:2048','-keyout',str(key),'-out',str(cert),
                             '-days','1','-nodes','-subj','/CN=localhost','-addext','subjectAltName='+names],
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.assertEqual(done.returncode,0,'Fixture certificate generation failed')
        return cert,key

    def tls(self, cert, key):
        self.server.shutdown(); self.thread.join(timeout=3)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert),str(key))
        self.server.socket=context.wrap_socket(self.server.socket,server_side=True)
        self.thread=threading.Thread(target=lambda:self.server.serve_forever(poll_interval=.01),daemon=True)
        self.thread.start()
        self.payload['url']=self.payload['url'].replace('http://','https://')

    def test_actual_tls_requires_trust_and_uses_ssl_cert_file(self):
        client=model_wire._tls_context()
        self.assertGreaterEqual(client.minimum_version,ssl.TLSVersion.TLSv1_2)
        self.assertEqual(client.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(client.check_hostname)
        cert,key=self.certificate(); self.tls(cert,key)
        with mock.patch.dict(os.environ,{'SSL_CERT_FILE':''}):
            self.assertEqual(self.once().failure.code,'network')
        self.assertEqual(self.requests,[])
        with mock.patch.dict(os.environ,{'SSL_CERT_FILE':str(cert)}):
            self.assertIsNone(self.once().failure)
        self.assertEqual(len(self.requests),1)

    def test_actual_tls_rejects_wrong_hostname_even_with_a_trusted_ca(self):
        cert,key=self.certificate('DNS:elsewhere.invalid'); self.tls(cert,key)
        with mock.patch.dict(os.environ,{'SSL_CERT_FILE':str(cert)}):
            self.assertEqual(self.once().failure.code,'network')
        self.assertEqual(self.requests,[])

    def test_actual_https_connect_proxy_honors_environment_without_exposing_api_auth(self):
        cert,key=self.certificate(); self.tls(cert,key)
        seen=[]; target_port=self.server.server_port
        class Proxy(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_CONNECT(self):
                seen.append((self.path,dict(self.headers)))
                if self.path!='127.0.0.1:'+str(target_port):self.send_error(403); return
                try:
                    with socket.create_connection(('127.0.0.1',target_port),timeout=2) as peer:
                        self.send_response(200); self.end_headers()
                        sockets=(self.connection,peer); until=time.monotonic()+5
                        while time.monotonic()<until:
                            ready,_,_=select.select(sockets,[],[],.1)
                            for source in ready:
                                data=source.recv(65536)
                                if not data:return
                                (peer if source is self.connection else self.connection).sendall(data)
                except OSError:pass
        proxy=ThreadingHTTPServer(('127.0.0.1',0),Proxy); proxy.daemon_threads=True
        thread=threading.Thread(target=lambda:proxy.serve_forever(poll_interval=.01),daemon=True); thread.start()
        def cleanup():proxy.shutdown(); proxy.server_close(); thread.join(timeout=3)
        self.addCleanup(cleanup)
        address='http://127.0.0.1:'+str(proxy.server_port)
        with mock.patch.dict(os.environ,{'HTTPS_PROXY':address,'https_proxy':address,'NO_PROXY':'','no_proxy':'',
                                         'SSL_CERT_FILE':str(cert)}):
            self.assertIsNone(self.once().failure)
        self.assertEqual(len(seen),1)
        self.assertNotIn(KEY,repr(seen))
        self.assertEqual(len(self.requests),1)

    def test_blocked_resolver_child_is_killed_before_any_late_request(self):
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        folder=Path(temporary.name).resolve()
        library=Path(model_transport.__file__).parent
        copied=folder/'scripts/memory_lib'
        shutil.copytree(library,copied,ignore=shutil.ignore_patterns('__pycache__'))
        helper=copied/'model_wire.py'; raw=helper.read_text(encoding='utf-8'); marker=folder/'dns-entered'
        injection=('    original_lookup = socket.getaddrinfo\n'
                   '    def stalled_lookup(*args, **kwargs):\n'
                   '        import time\n'
                   '        Path('+repr(str(marker))+').write_text("entered", encoding="utf-8")\n'
                   '        time.sleep(5)\n'
                   '        return original_lookup(*args, **kwargs)\n'
                   '    socket.getaddrinfo = stalled_lookup\n')
        anchor='    reading = [False]\n'; self.assertEqual(raw.count(anchor),1)
        helper.write_text(raw.replace(anchor,injection+anchor),encoding='utf-8')
        begun=time.monotonic()
        with mock.patch.object(model_transport,'__file__',str(copied/'model_transport.py')):
            answer=self.once(seconds=3,connect=.8)
        self.assertTrue(marker.exists(),'The controlled resolver must actually be entered')
        self.assertEqual(answer.failure.code,'timeout')
        self.assertLess(time.monotonic()-begun,1.5)
        time.sleep(.1)
        self.assertEqual(self.requests,[])
