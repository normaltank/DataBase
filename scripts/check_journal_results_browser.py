"""Direct journal archive flow on loopback, synthetic originals and fresh data.

Run normally for four responsive/200%-equivalent browser checks. --serve exposes
the same isolated fixture for human verification; never points at portable data.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_app.web import create_app
from scripts.check_collaboration_browser import login, no_overflow, original
from werkzeug.serving import make_server


def pdf():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
               b'<< /Length 65 >>\nstream\nBT /F1 18 Tf 30 220 Td (FICTIONAL JOURNAL RESULT - DEMO ONLY) Tj ET\nendstream',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    data = b'%PDF-1.4\n'
    offsets = [0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data))
        data += str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    xref = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'+b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return data+b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(xref).encode()+b'\n%%EOF\n'


def jr_title(name):
    return name+' · 2026 · 第1—2期（标题标注）'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve',action='store_true')
    parser.add_argument('--width',type=int,help='Debug one declared viewport')
    args=parser.parse_args()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    evidence=Path(tempfile.mkdtemp(prefix='database-journal-results-'))
    app=create_app(evidence/'data',testing=True,embedded_worker=False)
    server=make_server('127.0.0.1',0,app,threaded=True)
    base=f'http://127.0.0.1:{server.server_port}'
    print(json.dumps({'url':base+'/#compilations','evidence':str(evidence),'synthetic':True}),flush=True)
    if args.serve:
        from portable.demo_seed import login as http_login,call
        client=http_login(app,'researcher')
        call(client,'/api/journal-results',{'journal_name':'演示｜完全虚构的期刊成果','year':2026,'issue':'第1—2期（虚构）','request_id':'human-synthetic-first'},file=('虚构概览.docx',original('完全虚构的期刊成果，供人工试用。')))
        server.serve_forever()
        return
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    from playwright.sync_api import sync_playwright,expect
    errors,results=[],[]
    try:
        with sync_playwright() as p:
            executable=os.environ.get('DATABASE_BROWSER_EXECUTABLE')
            browser=p.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
            for width,dpr,label in [(1366,1,'desktop'),(900,1,'tablet'),(390,1,'phone'),(683,2,'200pct-equivalent')]:
                if args.width and width!=args.width:
                    continue
                from portable.demo_seed import login as http_login,call
                fixture_client=http_login(app,'researcher')
                jid=call(fixture_client,'/api/sources',{'kind':'journal','name':'虚构期刊档案 '+label})['id']
                article_title='虚构同刊文章 '+label
                call(fixture_client,'/api/records',{'kind':'journal_article','title':article_title,'serial_id':jid,'abstract':'仅用于关联查找的虚构摘要'})
                context=browser.new_context(viewport={'width':width,'height':900},device_scale_factor=dpr,accept_downloads=True)
                context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base) else route.abort())
                page=context.new_page()
                page.on('pageerror',lambda error:errors.append(str(error)))
                login(page,base,'researcher')
                toggle=page.get_by_role('button',name='打开导航',exact=True)
                if toggle.is_visible():toggle.click()
                page.get_by_role('button',name='中心成果',exact=True).click()
                expect(page.get_by_role('heading',name='中心成果',exact=True)).to_be_visible()
                page.get_by_role('link',name='保存一期成果',exact=True).click()
                name='虚构期刊 '+label
                page.get_by_label('刊名 *',exact=True).fill(name)
                page.get_by_label('年份 *',exact=True).fill('2026')
                page.get_by_label('成果期次 *',exact=True).fill('第1—2期（标题标注）')
                page.get_by_text('期刊档案关联与说明',exact=True).click()
                page.get_by_label('关联已有期刊（可选）',exact=True).select_option(jid)
                first=original('合成成果 '+label)
                page.get_by_label('首批成果文件 *',exact=True).set_input_files([
                    {'name':'概览.docx','mimeType':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','buffer':first},
                    {'name':'合成整期.pdf','mimeType':'application/pdf','buffer':pdf()}])
                page.get_by_role('button',name='保存一期成果',exact=True).click()
                expect(page.get_by_role('heading',name=name,exact=True)).to_be_visible()
                expect(page.locator('[data-jr-series]')).to_have_count(2)
                detail_url=page.url
                page.get_by_role('link',name='查找本刊文章',exact=True).click()
                expect(page.get_by_role('button',name=article_title,exact=True)).to_be_visible()
                page.go_back()
                expect(page.get_by_role('heading',name=name,exact=True)).to_be_visible()
                page.get_by_role('link',name='期刊档案',exact=True).click()
                expect(page.get_by_role('heading',name='虚构期刊档案 '+label,exact=True)).to_be_visible()
                expect(page.get_by_role('link',name=jr_title(name),exact=True)).to_be_visible()
                page.go_back()
                expect(page.get_by_role('heading',name=name,exact=True)).to_be_visible()
                word=page.locator('.journal-result-version').filter(has=page.get_by_role('heading',name='概览.docx v1',exact=True))
                word.get_by_role('button',name='预览',exact=True).click()
                expect(word.locator('.journal-result-preview')).to_have_text('合成成果 '+label)
                with page.expect_download() as download:
                    word.get_by_role('link',name='下载',exact=True).click()
                assert Path(download.value.path()).read_bytes()==first
                pdf_row=page.locator('.journal-result-version').filter(has=page.get_by_role('heading',name='合成整期.pdf v1',exact=True))
                pdf_row.get_by_role('button',name='预览',exact=True).click()
                preview=pdf_row.get_by_role('link',name='打开PDF预览',exact=True)
                expect(preview).to_be_visible()
                assert context.request.get(base+preview.get_attribute('href')).body()==pdf()
                page.get_by_text('添加另一份并列文件',exact=True).click()
                page.get_by_label('并列成果文件 *',exact=True).set_input_files({'name':'附录.docx','mimeType':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','buffer':original('并列附录')})
                page.get_by_role('button',name='添加并列文件',exact=True).click()
                expect(page.locator('[data-jr-series]')).to_have_count(3)
                word=page.locator('[data-jr-series]').filter(has=page.get_by_role('heading',name='概览.docx v1',exact=True))
                word.get_by_role('button',name='更新这份文件',exact=True).click()
                revised=original('修订后的合成成果 '+label)
                word.get_by_label('新版本文件 *',exact=True).set_input_files({'name':'概览修订.docx','mimeType':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','buffer':revised})
                word.get_by_label('文件说明',exact=True).fill('冲突后保留的修订说明')
                peer=context.new_page()
                peer.goto(detail_url+'&edit=1')
                peer.get_by_label('编译署名',exact=True).fill('合成并行编辑者')
                peer.get_by_role('button',name='保存期次信息',exact=True).click()
                expect(peer.get_by_role('heading',name=name,exact=True)).to_be_visible()
                word.get_by_role('button',name='保存这份文件的新版本',exact=True).click()
                expect(word.get_by_role('button',name='读取最新状态，保留当前输入',exact=True)).to_be_visible()
                expect(word.get_by_label('文件说明',exact=True)).to_have_value('冲突后保留的修订说明')
                assert word.locator('input[type=file]').evaluate('e=>e.files[0].name')=='概览修订.docx'
                word.get_by_role('button',name='读取最新状态，保留当前输入',exact=True).click()
                expect(word.locator('[data-jr-latest]')).to_contain_text('最新：')
                word.get_by_role('button',name='保存这份文件的新版本',exact=True).click()
                expect(page.get_by_role('heading',name='概览修订.docx v2',exact=True)).to_be_visible()
                expect(page.locator('[data-jr-series]')).to_have_count(3)
                current=page.locator('[data-jr-series]').filter(has=page.get_by_role('heading',name='概览修订.docx v2',exact=True))
                current.get_by_text('此前 1 个版本',exact=True).click()
                with page.expect_download() as download:
                    current.get_by_role('link',name='下载 v1',exact=True).click()
                assert Path(download.value.path()).read_bytes()==first
                current.get_by_role('button',name='恢复此版为新版本',exact=True).click()
                expect(page.get_by_role('heading',name='概览.docx v3',exact=True)).to_be_visible()
                page.get_by_text('期次修改历史与导出',exact=True).click()
                page.get_by_role('button',name='读取修改历史',exact=True).click()
                expect(page.locator('[data-jr-history-content]')).to_contain_text('恢复文件为新版本')
                with page.expect_download() as download:
                    page.get_by_role('link',name='导出本期及全部文件版本',exact=True).click()
                assert Path(download.value.path()).read_bytes().startswith(b'PK')
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(evidence/(label+'-detail.png')),full_page=True)
                layout=no_overflow(page)
                page.get_by_role('link',name='← 返回期刊成果',exact=True).click()
                page.get_by_label('刊名、期次或文件名',exact=True).fill(name)
                page.get_by_role('button',name='查找成果',exact=True).click()
                expect(page.locator('[data-jr-row]')).to_have_count(1)
                page.get_by_label('刊名、期次或文件名',exact=True).fill('未提交的查找输入')
                page.locator('[data-jr-row] a').click()
                expect(page.get_by_role('heading',name=name,exact=True)).to_be_visible()
                page.get_by_role('link',name='← 返回期刊成果',exact=True).click()
                expect(page.get_by_label('刊名、期次或文件名',exact=True)).to_have_value('未提交的查找输入')
                expect(page.locator('[data-jr-row] a')).to_be_focused()
                no_overflow(page)
                page.screenshot(path=str(evidence/(label+'-list.png')),full_page=True)
                peer.close()
                results.append({'viewport':label,'width':width,'dpr':dpr,'layout':layout,'checks':['main-entry','initial-multi-file','journal-articles','source-result-link','word-preview','pdf-preview','exact-download','parallel-file','explicit-update','conflict-preserves-file','restore','history','export','search','return-input-focus']})
                context.close()
            browser.close()
        assert not errors,errors
        report={'synthetic':True,'results':results,'page_errors':errors,'evidence':str(evidence)}
        (evidence/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False),flush=True)
    finally:
        server.shutdown()


if __name__=='__main__':
    main()
