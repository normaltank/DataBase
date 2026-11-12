"""Immutable, bounded PDF text evidence; never trust the disposable search index."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from importlib.metadata import version,PackageNotFoundError
from pathlib import Path

RULE='pdf-text-v1'
MESSAGES={'ready':'已提取 PDF 文字；图像、扫描文字和排版可能未被提取，请对照原文件。',
    'empty':'PDF 无可提取文字（未执行 OCR），原文件已保留。',
    'limit':'PDF 超过文字提取限制，原文件已保留。',
    'failed':'PDF 文字提取失败，原文件已保留。'}


def extract(content):
    result={'status':'failed','segments':[]}
    try:parser='pypdf '+version('pypdf')
    except PackageNotFoundError:parser='pypdf unavailable'
    try:
        # Reuse the bounded parser contract in an isolated, timed
        # subprocess. No search cache, database text, or PDF script is executed.
        with tempfile.TemporaryDirectory(prefix='fulltext-pdf-') as temp:
            path=Path(temp)/'original.pdf';path.write_bytes(content)
            completed=subprocess.run([sys.executable,str(Path(__file__).with_name('attachment_worker.py')),str(path),'--fulltext-pdf'],
                capture_output=True,timeout=12,check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if completed.returncode==0 and len(completed.stdout)<=8*1024*1024:
                result=json.loads(completed.stdout)
        if result['status'] not in MESSAGES:
            raise ValueError()
        if result['status']=='ready' and (not result['segments'] or len(result['segments'])>1000
            or sum(len(s['text']) for s in result['segments'])>500000):
            result={'status':'limit','segments':[]}
    except subprocess.TimeoutExpired:
        result={'status':'limit','segments':[]}
    except (OSError,ValueError,KeyError,TypeError):
        result={'status':'failed','segments':[]}
    return {**result,'rule':RULE,'parser':parser,
        'sha256':hashlib.sha256(content).hexdigest(),'message':MESSAGES[result['status']]}


def material(original):
    value=json.loads(original['extraction_json'])
    if value.get('status')!='ready':return None
    text='';paragraphs=[]
    for segment in value['segments']:
        # Preserve PDF file page boundaries, then split bounded contiguous
        # paragraphs within each page. Never claim these are printed page labels.
        start=len(text);page_text=segment['text'];text+=page_text
        for part in page_text.splitlines(keepends=True):
            for offset in range(0,len(part),2000):
                body=part[offset:offset+2000]
                if body.strip():paragraphs.append({'start':start+offset,'end':start+offset+len(body),'original':body,
                    'page':segment['page'],'locator':segment['locator']})
            start+=len(part)
    if not paragraphs or len(paragraphs)>1000:return None
    return {'kind':'pdf_text','snapshot_id':original['id'],'snapshot_sha256':original['sha256'],
        'attachment_id':original['attachment_id'],'url':original['final_url'],
        'basis':'PDF 已提取文字 · '+value['parser']+' · '+value['rule']+'；仅覆盖可提取的文字，不表示图像或扫描内容已识别。',
        'pages_total':value['pages_total'],'pages_with_text':value['pages_with_text'],
        'text':text,'paragraphs':paragraphs,'rule':'fulltext-v1'}


def checked_bytes(data_dir, original, attachment):
    from .attachment_search import original_path
    path=original_path(data_dir,attachment)
    if not path or path.stat().st_size!=original['bytes'] or original['bytes']>20*1024*1024:
        raise ValueError('PDF 原文件缺失或字节数已变化。')
    content=path.read_bytes()
    if hashlib.sha256(content).hexdigest()!=original['sha256']:
        raise ValueError('PDF 原文件摘要值已变化。')
    return content
