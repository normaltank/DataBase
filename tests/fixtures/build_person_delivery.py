"""Freeze one synthetic history through the real schema-6/7/8/9 applications.

Run manually from a clone containing the fixed commits. Tests consume the SQL
and JSON; rebuilding needs Git, but normal regression runs need no network/Git.
The files and accounts are invented or the public local demonstration accounts.
"""
import io
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASES = {6: "86031c59290c3f52b39c4fe1e568ed5b8a9fbb09",
         7: "75654bdc5fef76f0bd7b530d30ced2fcb407a2fc",
         8: "32a60f5786b379cbafe4256a5a5b24fb60663c4c",
         9: "b7af13d698c6ecdf8dd75d7577caa7346852fffa"}

BUILD = r'''
import base64, hashlib, io, json, sqlite3
from contextlib import closing
from PIL import Image
from platform_app.web import create_app
app=create_app(DATA, testing=True)
client=app.test_client()
token=client.get('/api/session').json['csrf']
token=client.post('/api/login',json={'username':'researcher','password':'LocalDemo2026!'},headers={'X-CSRF-Token':token}).json['csrf']
def call(path, values, method='POST', file=None):
    args={'json':values}
    if file:
        args={'data':{'data':json.dumps(values),'file':(io.BytesIO(file[1]),file[0])}}
    response=client.open(path,method=method,headers={'X-CSRF-Token':token},**args)
    assert response.status_code in (200,201), (path,response.status_code,response.json)
    return response.json
def get(path):
    response=client.get(path)
    assert response.status_code==200, (path,response.json)
    return response.json
def image(color):
    out=io.BytesIO();Image.new('RGB',(16,16),color).save(out,format='PNG');return out.getvalue()
if VERSION==6:
    ids={}
    ids['person']=call('/api/people',{'name':'Synthetic historical person','change_note':'Synthetic profile','avatar_source':'Synthetic blue portrait'},file=('blue.png',image('blue')))['id']
    ids['other']=call('/api/people',{'name':'Synthetic other person','change_note':'Separate identity'})['id']
    call('/api/people/'+ids['person'],{'version':1,'change_note':'Replace synthetic portrait','avatar_source':'Synthetic red portrait','introduction_html':'<p>Profile before removal</p>'},'PUT',('red.png',image('red')))
    call('/api/people/'+ids['person'],{'version':2,'change_note':'Remove current portrait, retain both historical files','remove_avatar':True},'PUT')
    ids['institution']=call('/api/sources',{'name':'Synthetic historical institution','kind':'institution'})['id']
    ids['journal']=call('/api/sources',{'name':'Synthetic historical journal','kind':'journal'})['id']
    ids['work']=call('/api/records',{'kind':'journal_article','title':'Synthetic historical article','authors':'A. Synthetic; Institute; Unknown','source_id':ids['institution'],'serial_id':ids['journal'],'body_html':'<p>Immutable synthetic original.</p>','sharing_confirmed':True},file=('historical.txt',b'Synthetic original file.\n'))['id']
    call('/api/records/'+ids['work'],{'version':1,'title':'Synthetic revised historical article'},'PUT')
    attachment=get('/api/records/'+ids['work'])['attachments'][0]['id']
    ids['note']=call('/api/records',{'kind':'research_note','title':'Synthetic fixed evidence note','body_html':'<p>Independent note.</p>','evidence_record_id':ids['work'],'evidence_attachment_id':attachment,'quote':'Immutable synthetic original.','locator':'page 8'})['id']
    ids['report']=call('/api/records',{'kind':'research_report','title':'Synthetic fixed report','body_html':'<p>Report stays fixed.</p>','evidence_ids':[ids['note']],'linked_ids':[ids['work']]})['id']
    ids['collection']=call('/api/collections',{'name':'Synthetic history collection','visibility':'shared'})['id']
    call('/api/collections/'+ids['collection']+'/items',{'record_id':ids['report']})
    (DATA.parent/'ids.json').write_text(json.dumps(ids),encoding='utf-8')
else:
    ids=json.loads((DATA.parent/'ids.json').read_text(encoding='utf-8'))
if VERSION==7:
    note=get('/api/records/'+ids['note'])
    subjects=[{'subject_type':'person','subject_id':ids['person']},{'subject_type':'person','subject_id':ids['other']},{'subject_type':'institution','subject_id':ids['institution']},{'subject_type':'journal','subject_id':ids['journal']}]
    call('/api/records/'+ids['note']+'/research-subjects',{'version':note['version'],'research_subjects':subjects},'PUT')
    note=get('/api/records/'+ids['note'])
    call('/api/records/'+ids['note']+'/research-subjects',{'version':note['version'],'research_subjects':[row for row in note['research_subjects'] if row['subject_id']!=ids['other']]},'PUT')
if VERSION==8:
    state=get('/api/records/'+ids['work']+'/bylines')
    state.update(change_note='Synthetic article header',items=[{'raw_name':'A. Synthetic','target_type':'person','target_id':ids['person'],'status':'confirmed','evidence':'Synthetic author page'}, {'raw_name':'Institute','target_type':'institution','target_id':ids['institution'],'status':'confirmed','evidence':'Synthetic institutional signature'}, {'raw_name':'Unknown','status':'pending'}])
    current=call('/api/records/'+ids['work']+'/bylines',state,'PUT')
    current.update(change_note='Remove an uncertain signature, retain its history',items=current['items'][:2])
    call('/api/records/'+ids['work']+'/bylines',current,'PUT')
if VERSION==9:
    current=call('/api/people/'+ids['person']+'/employments',{'version':0,'change_note':'Synthetic employment archive','items':[{'institution_id':ids['institution'],'role':'Researcher','start_date':'2018','end_date':'2020','evidence':'Synthetic role source'}, {'institution_id':ids['institution'],'role':'Visiting fellow','start_date':'','end_date':'','evidence':'Synthetic concurrent role source'}]},'PUT')
    current.update(change_note='Correct role, remove mistaken concurrent employment',items=[{**current['items'][0],'role':'Senior researcher'}])
    call('/api/people/'+ids['person']+'/employments',current,'PUT')
    state=get('/api/records/'+ids['work']+'/affiliations')
    rows=get('/api/records/'+ids['work']+'/bylines')['items']
    state.update(change_note='Synthetic article units',items=[{'byline_id':row['id'],'institution_id':ids['institution'],'evidence':'Synthetic article unit '+str(index)} for index,row in enumerate(rows)])
    current=call('/api/records/'+ids['work']+'/affiliations',state,'PUT')
    current.update(change_note='Remove a mistaken unit, keep tombstone',items=current['items'][:1])
    call('/api/records/'+ids['work']+'/affiliations',current,'PUT')
paths=['/api/people/'+ids['person'], '/api/people/'+ids['person']+'/history', '/api/people/'+ids['other'], '/api/collections/'+ids['collection']]
for key in ['work','note','report']:
    paths+=['/api/records/'+ids[key],'/api/history/record/'+ids[key]]
if VERSION>=7:paths+=['/api/records/'+ids['note']+'/research-subjects/history']
if VERSION>=8:paths+=['/api/records/'+ids['work']+'/bylines','/api/records/'+ids['work']+'/bylines/history']
if VERSION>=9:paths+=['/api/people/'+ids['person']+'/employments','/api/people/'+ids['person']+'/employments/history','/api/records/'+ids['work']+'/affiliations','/api/records/'+ids['work']+'/affiliations/history']
expected={'baseline':BASE,'schema':VERSION,'provenance':'Authenticated HTTP against the fixed historical application; synthetic records and images.','ids':ids,'responses':{path:get(path) for path in paths},'files':{}}
for folder in ['uploads','avatars']:
    for file in (DATA/folder).iterdir():
        expected['files'][folder+'/'+file.name]={'base64':base64.b64encode(file.read_bytes()).decode(),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
with closing(sqlite3.connect(DATA/'platform.sqlite3')) as db:
    db.execute("UPDATE settings SET value='/synthetic/historical-backup.zip' WHERE key LIKE '%migration_backup'")
    db.commit()
    (OUTPUT/('person_delivery_v'+str(VERSION)+'.sql')).write_text('-- Synthetic schema '+str(VERSION)+' from '+BASE+' via authenticated HTTP.\n'+'\n'.join(db.iterdump())+'\n',encoding='utf-8')
(OUTPUT/('person_delivery_v'+str(VERSION)+'.json')).write_text(json.dumps(expected,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'schema':VERSION,'baseline':BASE,'responses':len(paths),'files':len(expected['files'])}))
'''


def main():
    with tempfile.TemporaryDirectory(prefix="wiki-delivery-legacy-build-") as directory:
        root = Path(directory)
        for version, base in BASES.items():
            code = root / ("code-" + str(version))
            code.mkdir()
            archive = subprocess.run(["git", "archive", "--format=zip", base, "platform_app"], cwd=ROOT, capture_output=True, check=True)
            with zipfile.ZipFile(io.BytesIO(archive.stdout)) as bundle:
                bundle.extractall(code)
            script = ("from pathlib import Path\nVERSION=" + repr(version) + "\nBASE=" + repr(base) +
                      "\nDATA=Path(" + repr(str(root / "synthetic")) + ")\nOUTPUT=Path(" + repr(str(Path(__file__).parent)) + ")\n" + BUILD)
            subprocess.run([sys.executable, "-B", "-c", script], cwd=code,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=True)


if __name__ == "__main__":
    main()
