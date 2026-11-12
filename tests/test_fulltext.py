"""Explicit public originals and versioned reading through authenticated HTTP."""
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from tests.synthetic_ai import ENV,prepared_https_context
from tests import test_assisted_intake as fixture
PublicSocket = fixture.PublicSocket


class FulltextTests(unittest.TestCase):
    setUp = fixture.AssistedIntakeTests.setUp
    call = fixture.AssistedIntakeTests.call

    def record(self, **values):
        response = self.call('/api/records', {'kind':'report','title':'Synthetic original',
            'url':'https://example.org/original.pdf', **values})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json['id']

    def detail(self, rid, user='researcher'):
        response = self.clients[user].get('/api/records/'+rid)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def public(self, body=b'%PDF-1.4\nsynthetic bytes\n%%EOF', mime='application/pdf'):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch('socket.getaddrinfo', return_value=[(2,1,6,'',('93.184.216.34',443))]))
        stack.enter_context(patch('socket.create_connection', side_effect=lambda *a,**k: PublicSocket(body,mime)))
        stack.enter_context(patch('ssl.SSLContext.wrap_socket', side_effect=lambda sock,**k:sock))
        return stack

    @staticmethod
    def text_pdf(empty=False):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        writer=PdfWriter()
        for number in range(2):
            page=writer.add_blank_page(width=300,height=300)
            if not empty:
                font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
                page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
                stream=DecodedStreamObject();stream.set_data(('BT /F1 12 Tf 30 250 Td (Actual PDF page '+str(number+1)+'.) Tj ET').encode())
                page[NameObject('/Contents')]=writer._add_object(stream)
        output=io.BytesIO();writer.write(output);return output.getvalue()

    def test_explicit_file_save_is_byte_exact_evidenced_and_idempotent(self):
        rid = self.record()
        self.assertEqual(self.detail(rid)['attachments'], [])
        with self.public():
            response = self.call('/api/records/'+rid+'/original-file', {'url':'https://example.org/original.pdf'})
        self.assertEqual(response.status_code,201,response.json)
        aid = response.json['attachment_id']
        with self.clients['researcher'].get('/api/attachments/'+aid) as downloaded:
            self.assertEqual(downloaded.data,b'%PDF-1.4\nsynthetic bytes\n%%EOF')
        detail = self.detail(rid)
        self.assertEqual(detail['saved_originals'][0]['requested_url'],'https://example.org/original.pdf')
        self.assertEqual(detail['saved_originals'][0]['bytes'],len(b'%PDF-1.4\nsynthetic bytes\n%%EOF'))
        with patch('socket.create_connection') as network:
            repeat = self.call('/api/records/'+rid+'/original-file', {'url':'https://example.org/original.pdf'})
            self.assertEqual(repeat.json['attachment_id'],aid)
            network.assert_not_called()
        self.assertEqual(len(self.detail(rid)['attachments']),1)
        self.assertFalse(self.detail(rid)['fulltext']['available'])
        # Restoring a record version without the attachment may later lead to
        # another explicit retrieval. Preserve the first file's provenance.
        history=self.clients['researcher'].get('/api/history/record/'+rid).json['items']
        old=next(h for h in reversed(history) if h['version']==1)
        self.assertEqual(self.call('/api/history/'+str(old['id'])+'/restore',{'version':2}).status_code,200)
        with self.public(b'%PDF-1.4\nnew explicit retrieval\n%%EOF'):
            newer=self.call('/api/records/'+rid+'/original-file',{'url':'https://example.org/original.pdf'})
        self.assertEqual(newer.status_code,201,newer.json)
        evidence=self.detail(rid)['saved_originals']
        self.assertEqual(len(evidence),2)
        self.assertEqual(evidence[0]['attachment_id'],aid)
        self.assertFalse(evidence[0]['current']);self.assertTrue(evidence[1]['current'])

    def test_fulltext_requires_actual_body_and_reuses_same_snapshot(self):
        rid = self.record()
        response = self.call('/api/records/'+rid+'/fulltext')
        self.assertEqual(response.status_code,409,response.json)
        self.assertFalse(self.detail(rid)['fulltext']['available'])
        self.body(rid)
        response = self.call('/api/records/'+rid+'/fulltext')
        self.assertEqual(response.status_code,201,response.json)
        self.assertEqual(self.call('/api/records/'+rid+'/fulltext').json['id'],response.json['id'])
        version = self.detail(rid)['fulltext']['versions'][0]
        self.assertEqual([p['original'] for p in version['input']['paragraphs']],['First actual paragraph.\n\n','Second actual paragraph.'])

    def test_saved_pdf_actual_text_page_bindings_translate_and_restore_without_index_cache(self):
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        rid=self.record();content=self.text_pdf()
        with self.public(content):saved=self.call('/api/records/'+rid+'/original-file',{'url':'https://example.org/original.pdf'})
        self.assertEqual(saved.status_code,201,saved.json)
        detail=self.detail(rid)
        self.assertTrue(detail['fulltext']['available'])
        original=detail['fulltext']['original']
        self.assertEqual(original['kind'],'pdf_text')
        self.assertEqual(original['pages_total'],2)
        self.assertEqual([(p['page'],p['original']) for p in original['paragraphs']],[(1,'Actual PDF page 1.'),(2,'Actual PDF page 2.')])
        self.assertEqual(original['attachment_id'],saved.json['attachment_id'])
        self.call('/api/admin/ai/config',{'cap':'1','currency':'USD'},user='admin')
        self.assertEqual(self.call('/api/records/'+rid+'/fulltext',{'input_hash':detail['fulltext']['inputs'][0]['input_hash']}).status_code,201)
        with self.provider():self.worker()
        history=self.clients['researcher'].get('/api/history/record/'+rid).json['items']
        first=next(h for h in reversed(history) if h['version']==1)
        self.assertEqual(self.call('/api/history/'+str(first['id'])+'/restore',{'version':2}).status_code,200)
        self.assertTrue(self.detail(rid)['fulltext']['versions'][0]['stale'])
        original_id=detail['saved_originals'][0]['id']
        with self.clients['researcher'].get('/api/fulltext-originals/'+original_id) as response:
            self.assertEqual(response.data,content)
        with self.public(content.replace(b'Actual',b'Newer_')):
            self.assertEqual(self.call('/api/records/'+rid+'/original-file',{'url':'https://example.org/original.pdf'}).status_code,201)
        self.assertEqual(self.call('/api/records/'+rid+'/fulltext').status_code,201)
        expected=self.detail(rid)['fulltext']
        import zipfile
        export_path=Path(self.temp.name)/'content.zip'
        with self.clients['researcher'].get('/api/export/content') as response:export_path.write_bytes(response.data)
        from scripts.verify_content_export import verify
        verify(export_path)
        with zipfile.ZipFile(export_path) as archive:
            exported=json.loads(archive.read('content.json'))
            record=next(r for r in exported['records'] if r['id']==rid)
            self.assertEqual(record['fulltext'],expected)
            first_file=next(a for a in exported['attachments'] if a['id']==saved.json['attachment_id'])
            self.assertEqual(archive.read(first_file['path']),content)
            self.assertIn('PDF 第 2 页（文件页码）',archive.read(record['path']).decode())
        backup=Path(self.temp.name)/'pdf.zip'
        with self.call('/api/backup',user='admin') as response:backup.write_bytes(response.data)
        restored=restore_backup(backup,Path(self.temp.name)/'pdf-restored')
        client=create_app(restored,testing=True).test_client();csrf=client.get('/api/session').json['csrf']
        client.post('/api/login',json={'username':'researcher','password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf})
        self.assertEqual(client.get('/api/records/'+rid).json['fulltext'],expected)
        self.assertFalse((restored/'attachment-index').exists())
        blank=self.record(url='https://example.org/blank.pdf')
        with self.public(self.text_pdf(empty=True)):
            self.assertEqual(self.call('/api/records/'+blank+'/original-file',{'url':'https://example.org/blank.pdf'}).status_code,201)
        self.assertFalse(self.detail(blank)['fulltext']['available'])
        self.assertIn('无可提取文字',self.detail(blank)['fulltext']['reason'])
        self.assertEqual(self.call('/api/records/'+blank+'/fulltext').status_code,409)

    def test_pdf_extraction_tamper_is_rejected_and_schema30_failure_preserves_schema29(self):
        import zipfile,sqlite3
        from platform_app.maintenance import restore_backup,create_backup
        from platform_app.store import connect
        from platform_app.web import create_app
        rid=self.record()
        with self.public(self.text_pdf()):self.call('/api/records/'+rid+'/original-file',{'url':'https://example.org/original.pdf'})
        db=connect(self.app.config['DATA_DIR']/'platform.sqlite3')
        with db:
            value=json.loads(db.execute('SELECT extraction_json FROM saved_originals').fetchone()[0])
            value['segments'][0]['text']='Forged text with no basis in the file.'
            db.execute('UPDATE saved_originals SET extraction_json=?',(json.dumps(value),))
        db.close()
        backup=create_backup(self.app.config['DATA_DIR'])
        with self.assertRaisesRegex(ValueError,'全文'):restore_backup(backup,Path(self.temp.name)/'tampered-pdf')
        stage29=None
        for backup in (self.app.config['DATA_DIR']/'backups').glob('*.zip'):
            with zipfile.ZipFile(backup) as archive:
                path=Path(self.temp.name)/'probe.sqlite3';path.write_bytes(archive.read('platform.sqlite3'))
            probe=sqlite3.connect(path)
            version=probe.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0];probe.close()
            if version=='29':stage29=backup;break
        self.assertIsNotNone(stage29)
        legacy=restore_backup(stage29,Path(self.temp.name)/'legacy29')
        db=connect(legacy/'platform.sqlite3')
        with db:db.execute("CREATE TRIGGER reject30 BEFORE UPDATE ON settings WHEN OLD.key='schema_version' AND NEW.value='30' BEGIN SELECT RAISE(ABORT,'synthetic migration failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):create_app(legacy,testing=True)
        self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0],'29')
        self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='fulltext_jobs'").fetchone())
        with db:db.execute('DROP TRIGGER reject30')
        db.close()
        from platform_app.store import CURRENT_SCHEMA_VERSION
        self.assertEqual(create_app(legacy,testing=True).test_client().get('/health').json['schema'],CURRENT_SCHEMA_VERSION)

    def test_merged_pdf_keeps_original_job_input_and_resumes_without_duplicate_charge(self):
        from platform_app.maintenance import create_backup,restore_backup
        from platform_app.web import create_app
        rid=self.record();keep=self.record(title='Retained record',url='https://example.org/keep.pdf')
        with self.public(self.text_pdf()):self.call('/api/records/'+rid+'/original-file',{'url':'https://example.org/original.pdf'})
        self.call('/api/admin/ai/config',{'cap':'1','currency':'USD'},user='admin')
        jid=self.call('/api/records/'+rid+'/fulltext').json['id']
        with self.provider():self.worker(limit=1)
        result=self.call('/api/merge',{'type':'record','keep_id':keep,'duplicate_id':rid,'keep_version':1,'duplicate_version':2,'confirmed':True},user='admin')
        self.assertEqual(result.status_code,200,result.json)
        self.assertTrue(self.detail(keep)['fulltext']['available'])
        self.assertEqual(self.call('/api/records/'+keep+'/fulltext').json['id'],jid)
        with self.provider() as mock:
            self.worker('2090-11-12T00:10:00+00:00');self.assertEqual(mock.sent.call_count,1)
        expected=self.detail(keep)['fulltext']
        self.assertEqual(expected['versions'][0]['completed'],2)
        self.assertEqual(self.clients['researcher'].get('/api/fulltext/'+jid).status_code,200)
        # A PDF first requested after a merge must retain the old file's
        # immutable provenance while using the retained record's task scope.
        late=self.record(title='PDF before first request',url='https://example.org/late.pdf')
        later_keep=self.record(title='Second retained record',url='https://example.org/later-keep.pdf')
        with self.public(self.text_pdf()):self.call('/api/records/'+late+'/original-file',{'url':'https://example.org/late.pdf'})
        self.assertEqual(self.call('/api/merge',{'type':'record','keep_id':later_keep,'duplicate_id':late,'keep_version':1,'duplicate_version':2,'confirmed':True},user='admin').status_code,200)
        self.assertEqual(self.call('/api/records/'+later_keep+'/fulltext').status_code,201)
        with self.provider():self.worker('2090-11-12T00:15:00+00:00')
        restored=restore_backup(create_backup(self.app.config['DATA_DIR']),Path(self.temp.name)/'merged-restored')
        client=create_app(restored,testing=True).test_client();csrf=client.get('/api/session').json['csrf']
        client.post('/api/login',json={'username':'researcher','password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf})
        self.assertEqual(client.get('/api/records/'+keep).json['fulltext'],expected)

    def test_persistent_shared_worker_respects_paid_switch_and_stops_after_current_pdf_segment(self):
        import threading
        from contextlib import redirect_stdout
        from platform_app.ingestion import run_worker
        rid=self.record()
        with self.public(self.text_pdf()):self.call('/api/records/'+rid+'/original-file',{'url':'https://example.org/original.pdf'})
        self.call('/api/admin/ai/config',{'cap':'1','currency':'USD'},user='admin')
        self.call('/api/records/'+rid+'/fulltext')
        with self.provider() as mock,redirect_stdout(io.StringIO()):
            run_worker(self.app.config['DATA_DIR'],once=True,paid_enabled=lambda:False)
            self.assertEqual(mock.sent.call_count,0)
            respond=mock.sent.side_effect;stop=threading.Event()
            def finishing(request,**kwargs):
                response=respond(request,**kwargs);stop.set();return response
            mock.sent.side_effect=finishing
            with patch('platform_app.store.now',return_value='2090-11-12T00:05:00+00:00'),patch('platform_app.ai_gateway.now',return_value='2090-11-12T00:05:00+00:00'):
                run_worker(self.app.config['DATA_DIR'],once=True,stopping=stop.is_set)
                self.assertEqual(self.detail(rid)['fulltext']['versions'][0]['completed'],1)
                stop.clear();run_worker(self.app.config['DATA_DIR'],once=True,stopping=stop.is_set)
                self.assertEqual(self.detail(rid)['fulltext']['versions'][0]['completed'],2)
            self.assertEqual(mock.sent.call_count,2)

    def test_restoring_member_fields_keeps_latest_upstream_body_and_old_fulltext_binding(self):
        from platform_app.maintenance import create_backup,restore_backup
        rid=self.record();self.body(rid)
        self.call('/api/admin/ai/config',{'cap':'1','currency':'USD'},user='admin')
        old_id=self.call('/api/records/'+rid+'/fulltext').json['id']
        with self.provider():self.worker(limit=1)
        original=self.detail(rid)['fulltext']['versions'][0]
        self.body(rid,'Changed upstream paragraph.\n\nSecond actual paragraph.')
        revision=self.clients['researcher'].get('/api/history/record/'+rid).json['items'][-1]
        self.assertEqual(self.call('/api/history/'+str(revision['id'])+'/restore',{'version':1}).status_code,200)
        current=self.detail(rid)
        self.assertEqual(current['fulltext']['original']['paragraphs'][0]['original'],'Changed upstream paragraph.\n\n')
        self.assertTrue(current['fulltext']['versions'][0]['stale'])
        self.assertEqual(self.call('/api/fulltext/'+old_id+'/retry').status_code,409)
        self.assertEqual(self.call('/api/records/'+rid+'/fulltext').status_code,201)
        with self.provider() as mock:
            self.worker('2090-11-12T00:10:00+00:00');self.assertEqual(mock.sent.call_count,2)
        versions=self.detail(rid)['fulltext']['versions']
        self.assertEqual(versions[1]['input'],original['input'])
        self.assertEqual(versions[1]['segments'][0]['reading_text'],'第一段完整译文。')
        self.assertEqual(versions[0]['completed'],2)
        restore_backup(create_backup(self.app.config['DATA_DIR']),Path(self.temp.name)/'updated-body-restored')

    def body(self, rid, text='First actual paragraph.\n\nSecond actual paragraph.'):
        # Synthetic fixture only: the acquired-work contract is independently
        # checked by ingestion's existing raw-response restoration tests.
        from platform_app.store import connect
        db=connect(self.app.config['DATA_DIR']/'platform.sqlite3')
        with db:
            raw=json.loads(db.execute('SELECT raw_json FROM records WHERE id=?',(rid,)).fetchone()[0])
            import base64,hashlib
            from platform_app.workflow import clean_rich
            html,cleaned=clean_rich(''.join('<p>'+p+'</p>' for p in text.split('\n\n')))
            # clean_rich is the saved ingestion body contract, not expected translation.
            rawbytes=html.encode()
            snapshot={'id':'synthetic-'+hashlib.sha256(rawbytes).hexdigest()[:12],'sha256':hashlib.sha256(rawbytes).hexdigest(),
                'url':'https://example.org/article','work_body_available':True,'adapter':'synthetic-test',
                'retrieved_at':'2026-11-12T00:00:00+00:00','bytes':len(rawbytes),
                'raw_base64':base64.b64encode(rawbytes).decode(),'content_type':'text/html',
                'content_kind':'work_body','encoding':'utf-8','reason':'Synthetic actual body',
                'page_html':html,'page_text':cleaned,'pdf_links':['https://example.org/original.pdf'],
                'work_body_basis':'synthetic work body','work_body':{'text':text,'html':html}}
            # Use literal paragraph text in normal tests; other snapshots can model changes.
            snapshot['work_body']['text']=cleaned
            previous=raw.get('automatic_acquisition',{}).get('snapshots',[])
            raw['automatic_acquisition']={'snapshots':previous+[snapshot]}
            db.execute('UPDATE records SET raw_json=? WHERE id=?',(json.dumps(raw),rid))
        db.close()

    def provider(self, failing=None, unknown=False):
        def respond(request, **kwargs):
            value=json.loads(json.loads(request.data)['messages'][1]['content'])
            translated=['第一段完整译文。','第二段完整译文。'][value['paragraph']]
            output={'translation':translated}
            if failing and value['paragraph'] in failing:
                output={'wrong':'incomplete'}
            response=MagicMock();response.__enter__.return_value=response
            response.geturl.return_value=request.full_url
            response.read.return_value=json.dumps({'model':'deepseek-flash',
                **({} if unknown else {'usage':{'prompt_tokens':23,'completion_tokens':7,'total_tokens':30}}),
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]}).encode()
            return response
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(prepared_https_context())
        stack.enter_context(patch.dict('os.environ',{**ENV,'DEEPSEEK_API_KEY':'synthetic-only'}))
        sent=stack.enter_context(patch('urllib.request.OpenerDirector.open',side_effect=respond))
        stack.sent=sent
        return stack

    def worker(self, stamp='2090-11-12T00:05:00+00:00', limit=5, data_dir=None):
        from platform_app.fulltext import run_pending
        with patch('platform_app.store.now',return_value=stamp),patch('platform_app.ai_gateway.now',return_value=stamp):
            return run_pending(data_dir or self.app.config['DATA_DIR'],limit=limit)

    def test_partial_resume_human_conflict_old_version_export_and_restore(self):
        import zipfile
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        rid=self.record();self.body(rid)
        self.call('/api/admin/ai/config',{'cap':'1','currency':'USD'},user='admin')
        jid=self.call('/api/records/'+rid+'/fulltext').json['id']
        with self.provider(failing={1}) as mock:
            self.worker();self.assertEqual(mock.sent.call_count,2)
        version=self.detail(rid)['fulltext']['versions'][0]
        self.assertEqual((version['completed'],version['status']),(1,'paused'))
        self.assertEqual(self.call('/api/fulltext/'+jid+'/edit',{'paragraph':0,'revision':0,'text':'人工校订第一段。'}).status_code,200)
        self.assertEqual(self.call('/api/fulltext/'+jid+'/edit',{'paragraph':0,'revision':0,'text':'过期覆盖'}).status_code,409)
        with self.provider() as mock:
            self.worker('2090-11-12T00:10:00+00:00');self.assertEqual(mock.sent.call_count,1)
            self.worker('2090-11-12T00:11:00+00:00');self.assertEqual(mock.sent.call_count,1)
        version=self.detail(rid)['fulltext']['versions'][0]
        self.assertEqual([s['reading_text'] for s in version['segments']],['人工校订第一段。','第二段完整译文。'])
        with self.public():
            aid=self.call('/api/records/'+rid+'/original-file',{'url':'https://example.org/original.pdf'}).json['attachment_id']
        self.body(rid,'Updated first paragraph.\n\nSecond actual paragraph.')
        self.assertEqual(self.call('/api/fulltext/'+jid+'/retry').status_code,409)
        self.assertEqual(self.call('/api/records/'+rid+'/fulltext').status_code,201)
        version=self.detail(rid)['fulltext']['versions'][1]
        self.assertTrue(version['stale'])
        with zipfile.ZipFile(io.BytesIO(self.clients['researcher'].get('/api/export/content').data)) as archive:
            exported=next(r for r in json.loads(archive.read('content.json'))['records'] if r['id']==rid)
            self.assertEqual(exported['fulltext']['versions'][1],version)
            self.assertIn('人工校订第一段。',archive.read(exported['path']).decode())
        backup=Path(self.temp.name)/'complete.zip'
        with self.call('/api/backup',user='admin') as response:backup.write_bytes(response.data)
        restored=restore_backup(backup,Path(self.temp.name)/'restored')
        recovered=create_app(restored,testing=True).test_client();csrf=recovered.get('/api/session').json['csrf']
        recovered.post('/api/login',json={'username':'researcher','password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf})
        self.assertEqual(recovered.get('/api/records/'+rid).json['fulltext']['versions'][1],version)
        with recovered.get('/api/attachments/'+aid) as response:
            self.assertEqual(response.data,b'%PDF-1.4\nsynthetic bytes\n%%EOF')
        with self.provider() as mock:
            # Only the newly explicitly requested input is sent; the adopted
            # old version and its human correction remain immutable.
            self.worker('2090-11-12T00:15:00+00:00',limit=1,data_dir=restored)
            self.assertEqual(mock.sent.call_count,1)

    def test_public_file_rejects_hidden_redirect_size_format_and_changed_access(self):
        rid=self.record()
        url='https://example.org/original.pdf';endpoint='/api/records/'+rid+'/original-file'
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch('socket.create_connection') as network:
            self.assertEqual(self.call(endpoint,{'url':url}).status_code,422);network.assert_not_called()
        with self.public():
            with patch('socket.create_connection',return_value=PublicSocket(b'','application/pdf','302 Found','Location: http://127.0.0.1/private.pdf\r\n')):
                with patch('socket.getaddrinfo',side_effect=lambda host,*a,**k:[(2,1,6,'',(host if host=='127.0.0.1' else '93.184.216.34',443))]):
                    self.assertEqual(self.call(endpoint,{'url':url}).status_code,422)
        for content,mime in [(b'bad signature','application/pdf'),(b'<script>bad</script>','text/html')]:
            with self.public(content,mime):self.assertIn(self.call(endpoint,{'url':url}).status_code,{400,422})
        with self.public(),patch('platform_app.fulltext.MAX_BYTES',10):
            self.assertEqual(self.call(endpoint,{'url':url}).status_code,422)
        with self.public(),patch('platform_app.intake.MAX_SECONDS',0):
            self.assertEqual(self.call(endpoint,{'url':url}).status_code,422)
        def changed(*args,**kwargs):
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as pool:
                result=pool.submit(self.call,'/api/records/'+rid,{'version':1,'visibility':'restricted'},'researcher','PUT').result()
            self.assertEqual(result.status_code,200,result.json)
            return PublicSocket(b'%PDF-1.4\nsynthetic\n%%EOF','application/pdf')
        with self.public(),patch('socket.create_connection',side_effect=changed):
            self.assertEqual(self.call(endpoint,{'url':url},user='colleague').status_code,404)
        self.assertEqual(self.detail(rid)['attachments'],[])
        with patch('socket.create_connection') as network:
            self.assertEqual(self.call(endpoint,{'url':url},user='colleague').status_code,404);network.assert_not_called()

    def test_unknown_cost_survives_month_and_new_directory_without_resend(self):
        from platform_app.maintenance import restore_backup
        rid=self.record();self.body(rid)
        self.call('/api/admin/ai/config',{'cap':'1','currency':'USD'},user='admin')
        jid=self.call('/api/records/'+rid+'/fulltext').json['id']
        with self.provider(unknown=True) as mock:
            self.worker('2090-10-31T23:59:00+00:00');self.assertEqual(mock.sent.call_count,1)
        before=self.clients['admin'].get('/api/admin/ai').json
        self.assertEqual(before['attempts'][0]['status'],'unknown')
        self.assertGreater(before['attempts'][0]['reserved_units'],0)
        self.assertEqual(before['attempts'][0]['month'],'2090-10')
        backup=Path(self.temp.name)/'unknown.zip'
        with self.call('/api/backup',user='admin') as response:backup.write_bytes(response.data)
        restored=restore_backup(backup,Path(self.temp.name)/'unknown-restored')
        with self.provider() as mock:
            self.worker('2090-11-01T00:01:00+00:00',data_dir=restored)
            self.assertEqual(mock.sent.call_count,0)
        self.assertEqual(self.detail(rid)['fulltext']['versions'][0]['completed'],0)

    def test_lost_local_result_reuses_settled_attempt_and_permission_change_stops_worker(self):
        import sqlite3
        from platform_app.store import connect
        rid=self.record();self.body(rid)
        self.call('/api/admin/ai/config',{'cap':'1','currency':'USD'},user='admin')
        self.call('/api/records/'+rid+'/fulltext')
        db=connect(self.app.config['DATA_DIR']/'platform.sqlite3')
        with db:db.execute("CREATE TRIGGER fail_fulltext_save BEFORE UPDATE OF segments_json ON fulltext_jobs BEGIN SELECT RAISE(ABORT,'synthetic lost write'); END")
        with self.provider() as mock:
            with self.assertRaises(sqlite3.IntegrityError):self.worker(limit=1)
            self.assertEqual(mock.sent.call_count,1)
        with db:db.execute('DROP TRIGGER fail_fulltext_save')
        db.close()
        with self.provider() as mock:
            self.worker('2090-11-12T00:10:00+00:00',limit=1)
            self.assertEqual(mock.sent.call_count,0)
        self.assertEqual(self.detail(rid)['fulltext']['versions'][0]['completed'],1)
        # A shared record becoming restricted must stop even its owner's
        # previously requested public processing; no third-party resend.
        self.assertEqual(self.call('/api/records/'+rid,{'version':1,'visibility':'restricted'},method='PUT').status_code,200)
        with self.provider() as mock:
            self.worker('2090-11-12T00:11:00+00:00')
            self.assertEqual(mock.sent.call_count,0)
        self.assertEqual(self.detail(rid)['fulltext']['versions'][0]['status'],'failed')
        self.assertEqual(self.clients['colleague'].get('/api/records/'+rid).status_code,404)

    def test_month_budget_and_global_concurrent_reservations_apply_to_fulltext(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
        rid=self.record();self.body(rid)
        self.call('/api/admin/ai/config',{'cap':'0.000001','currency':'USD'},user='admin')
        self.call('/api/records/'+rid+'/fulltext')
        with self.provider() as mock:
            self.worker();self.assertEqual(mock.sent.call_count,0)
        self.assertIn('额度',self.detail(rid)['fulltext']['versions'][0]['reason'])
        self.call('/api/admin/ai/config',{'cap':'1','currency':'USD'},user='admin')
        for i in range(2):
            another=self.record(title='Additional '+str(i),url='https://example.org/'+str(i)+'.pdf')
            self.body(another);self.call('/api/records/'+another+'/fulltext')
        entered=threading.Event();release=threading.Event();lock=threading.Lock();count=[0]
        with self.provider() as mock:
            real_response=mock.sent.side_effect
            def hold(request,**kwargs):
                with lock:
                    count[0]+=1
                    if count[0]==2:entered.set()
                release.wait(8)
                return real_response(request,**kwargs)
            mock.sent.side_effect=hold
            from platform_app.fulltext import run_pending
            with patch('platform_app.store.now',return_value='2090-11-12T00:10:00+00:00'),patch('platform_app.ai_gateway.now',return_value='2090-11-12T00:10:00+00:00'):
                with ThreadPoolExecutor(max_workers=3) as executor:
                    pending=[executor.submit(run_pending,self.app.config['DATA_DIR'],limit=1) for i in range(3)]
                    try:
                        self.assertTrue(entered.wait(6));self.assertEqual(mock.sent.call_count,2)
                        done,remaining=wait(pending,timeout=6,return_when=FIRST_COMPLETED)
                        self.assertEqual(len(done),1)
                    finally:release.set()
                    for future in pending:future.result()
            self.assertEqual(mock.sent.call_count,2)

    def test_missing_table_and_cross_paragraph_ledger_tampering_are_rejected(self):
        import zipfile,sqlite3,hashlib
        from platform_app.maintenance import restore_backup
        rid=self.record();self.body(rid)
        self.call('/api/admin/ai/config',{'cap':'1','currency':'USD'},user='admin')
        self.call('/api/records/'+rid+'/fulltext')
        with self.provider():self.worker()
        with self.call('/api/backup',user='admin') as response:
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:originals={n:archive.read(n) for n in archive.namelist()}
        for case in ['table','binding']:
            files=dict(originals);database=Path(self.temp.name)/(case+'.sqlite3');database.write_bytes(files['platform.sqlite3'])
            db=sqlite3.connect(database)
            with db:
                if case=='table':db.execute('DROP TABLE fulltext_edits')
                else:
                    # A valid settled attempt for the same record/task/result is
                    # insufficient: it must bind to this precise paragraph input.
                    db.execute("UPDATE ai_attempts SET input_hash=? WHERE task='fulltext-v1'",('0'*64,))
            db.close();files['platform.sqlite3']=database.read_bytes()
            manifest=json.loads(files['manifest.json']);manifest['files']['platform.sqlite3']={'bytes':len(files['platform.sqlite3']),'sha256':hashlib.sha256(files['platform.sqlite3']).hexdigest()}
            files['manifest.json']=json.dumps(manifest).encode();backup=Path(self.temp.name)/(case+'.zip')
            with zipfile.ZipFile(backup,'w') as archive:
                for n,v in files.items():archive.writestr(n,v)
            with self.assertRaisesRegex(ValueError,'全文'):restore_backup(backup,Path(self.temp.name)/(case+'-restored'))


if __name__ == '__main__': unittest.main()
