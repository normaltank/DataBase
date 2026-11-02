"""Frozen pre-stage application generates nonempty synthetic upgrade fixtures."""
import hashlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_app.store import CURRENT_SCHEMA_VERSION
from platform_app.web import create_app
from platform_app.maintenance import restore_backup
from scripts.check_collaboration_recovery import login

BASELINE = "c33aaddea6de997da44caed938ef01ce0de7c40f"
SEED = r'''
import io,json,sys
from pathlib import Path
from platform_app.web import create_app
app=create_app(Path(sys.argv[1]),testing=True)
def login(name):
    c=app.test_client(); token=c.get('/api/session').json['csrf']
    assert c.post('/api/login',json={'username':name,'password':'LocalDemo2026!'},headers={'X-CSRF-Token':token}).status_code==200
    return c
clients={n:login(n) for n in ('admin','researcher','colleague')}
def call(path,data=None,who='researcher',raw=None,method='POST'):
    c=clients[who]; opts={'headers':{'X-CSRF-Token':c.get('/api/session').json['csrf']}}
    opts.update({'json':data or {}} if raw is None else {'data':{'data':json.dumps(data),'file':(io.BytesIO(raw),'synthetic.txt')}})
    r=c.open(path,method=method,**opts);r.request.close();assert r.status_code in (200,201),(path,r.status_code,r.json)
    return r
call('/api/collaboration/qualifications/researcher',{'version':0,'enabled':True},'admin',method='PUT')
cases={}
for kind in ('empty','note','attachment','assigned','withdrawn','draft','returned','final','summary_then_new_draft'):
    tid=call('/api/collaboration/topics',{'theme':'旧期 '+kind,'participant_ids':['colleague']}).json['id'];root='/api/collaboration/topics/'+tid
    if kind!='empty':
        rows=[] if kind in ('note','attachment') else [{'title':'站外合成文章','author_id':'colleague','source':'https://example.invalid/article'}]
        call(root+'/meetings',{'request_id':'legacy-meeting-01','topic_version':1,'version':0,'note':'会议材料','assignments':rows},raw=b'legacy meeting bytes' if kind=='attachment' else None)
    if kind=='withdrawn':call(root+'/meetings',{'request_id':'legacy-meeting-02','topic_version':1,'version':1,'note':'撤下全部分工，历史保留','assignments':[]})
    if kind in ('draft','returned','final','summary_then_new_draft'):
        aid=clients['colleague'].get(root+'/workflow').json['assignments'][0]['id']
        sid=call(root+'/assignments/'+aid+'/submissions',{'request_id':'legacy-draft-01','topic_version':1,'meeting_version':1,'version':0},'colleague',b'legacy original v1').json['id']
        if kind=='returned':call(root+'/assignments/'+aid+'/returns',{'request_id':'legacy-return-01','topic_version':1,'meeting_version':1,'submission_id':sid,'note':'退回原意见'})
        if kind in ('final','summary_then_new_draft'):
            fid=call(root+'/assignments/'+aid+'/finals',{'request_id':'legacy-final-01','topic_version':1,'meeting_version':1,'submission_id':sid,'version':1,'status':'pending'}).json['id']
            if kind=='summary_then_new_draft':
                call(root+'/summaries',{'request_id':'legacy-summary-01','topic_version':1,'version':0,'author_id':'researcher','final_ids':[fid]},raw=b'legacy summary fixed adoption v1')
                call(root+'/assignments/'+aid+'/submissions',{'request_id':'legacy-draft-02','topic_version':1,'meeting_version':1,'version':1},'colleague',b'legacy new original v2')
    workflow=clients['colleague'].get(root+'/workflow').json
    candidates=clients['colleague'].get(root+'/candidates').json
    history=clients['colleague'].get(root+'/history').json
    files={}
    for item in workflow['meetings']+workflow['summaries']+[s for a in workflow['assignments'] for key in ('submissions','returns','finals') for s in a[key]]:
        if item.get('file_url'):files[item['file_url']]=clients['colleague'].get(item['file_url']).data.hex()
    cases[kind]={'id':tid,'workflow':workflow,'candidates':candidates,'history':history,'files':files}
Path(sys.argv[2]).write_text(json.dumps(cases,ensure_ascii=False),encoding='utf-8')
Path(sys.argv[3]).write_bytes(call('/api/backup',who='admin').data)
'''


def request(client, path, data):
    response = client.post(path, json=data, headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]})
    assert response.status_code in (200, 201), (path, response.status_code, response.json)
    return response


def compare_legacy(client, cases):
    for kind, case in cases.items():
        root = "/api/collaboration/topics/" + case["id"]
        topic = client.get(root).json
        expected = "selection" if kind in ("empty", "note", "attachment") else "compilation"
        assert topic["stage"] == expected, (kind, topic)
        assert topic["stage_origin"]["kind"] == "legacy_migration" and not topic["stage_events"]
        assert client.get(root + "/history").json == case["history"]
        assert client.get(root + "/candidates").json == case["candidates"]
        current = client.get(root + "/workflow").json
        # Compare the original public historical fields and exact file bytes.
        for old, new in zip(case["workflow"]["meetings"], current["meetings"]):
            for key, value in old.items():
                if key == "assignments":
                    for old_a, new_a in zip(value, new[key]):
                        assert all(new_a[k] == v for k, v in old_a.items())
                else:
                    assert new[key] == value
        for key in ("summaries", "meeting_version"):
            assert current[key] == case["workflow"][key]
        for old, new in zip(case["workflow"]["assignments"], current["assignments"]):
            assert all(new[k] == v for k, v in old.items()), (kind, old, new)
        for url, raw in case["files"].items():
            assert client.get(url).data.hex() == raw


def main():
    root = Path(__file__).resolve().parents[1]
    out = Path(tempfile.mkdtemp(prefix="database-topic-stages-recovery-"))
    (Path(tempfile.gettempdir()) / "database-topic-stages-recovery-latest.txt").write_text(str(out), encoding="utf-8")
    archive, source = out / "legacy-source.zip", out / "legacy-source"
    subprocess.run(["git", "archive", BASELINE, "platform_app", "-o", str(archive)], cwd=root, check=True, capture_output=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(source)
    subprocess.run([sys.executable, "-c", SEED, str(out / "legacy-data"), str(out / "before.json"), str(out / "legacy-backup.zip")], cwd=source, check=True, capture_output=True)
    cases = json.loads((out / "before.json").read_text(encoding="utf-8"))
    # Restore a real old-version backup first, then run the new migration.
    restored = out / "upgraded"
    restore_backup(out / "legacy-backup.zip", restored)
    app = create_app(restored, testing=True)
    compare_legacy(login(app, "colleague"), cases)
    pre_stage_backups = list((restored / "backups").glob("*.zip"))
    versions = []
    for index, backup in enumerate(pre_stage_backups):
        with zipfile.ZipFile(backup) as package:
            dbfile = out / f"migration-backup-{index}.sqlite3"
            dbfile.write_bytes(package.read("platform.sqlite3"))
        with closing(sqlite3.connect(dbfile)) as db:
            versions.append(int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]))
        before_stage = out / f"migration-backup-restored-{index}"
        restore_backup(backup, before_stage)
        compare_legacy(login(create_app(before_stage, testing=True), "colleague"), cases)
    assert sorted(versions) == list(range(24, CURRENT_SCHEMA_VERSION)), versions
    snapshots = [login(app, "researcher").get("/api/collaboration/topics").json]
    for _ in range(2):
        app = create_app(restored, testing=True)
        compare_legacy(login(app, "colleague"), cases)
        assert login(app, "researcher").get("/api/collaboration/topics").json == snapshots[0]
    # Fresh explicit transition survives complete backup/new-directory restore.
    lead = login(app, "researcher")
    tid = request(lead, "/api/collaboration/topics", {"theme": "新期显式转换", "participant_ids": ["colleague"]}).json["id"]
    url = f"/api/collaboration/topics/{tid}"
    request(lead, url + "/meetings", {"request_id": "new-stage-meeting", "topic_version": 1, "version": 0, "assignments": [{"title": "新文章", "author_id": "colleague"}]})
    request(lead, url + "/enter-compilation", {"request_id": "new-stage-enter", "topic_version": 1, "stage_version": 1, "meeting_version": 1})
    expected = lead.get(url).json
    admin = login(app, "admin")
    backup = request(admin, "/api/backup", {}).data
    (out / "complete-backup.zip").write_bytes(backup)
    complete = out / "complete-restored"
    restore_backup(out / "complete-backup.zip", complete)
    resumed = create_app(complete, testing=True)
    assert login(resumed, "researcher").get(url).json == expected
    compare_legacy(login(resumed, "colleague"), cases)
    author = login(resumed, "colleague")
    a = author.get(url + "/workflow").json["assignments"][0]
    response = author.post(url + f"/assignments/{a['id']}/submissions", data={"data": json.dumps({"request_id": "restored-new-draft", "version": 0, "topic_version": 1, "meeting_version": 1}), "file": (io.BytesIO(b"continued after restore"), "restored.txt")}, headers={"X-CSRF-Token": author.get("/api/session").json["csrf"]})
    assert response.status_code == 201, response.json
    # Hashes are deliberately rewritten to exercise semantic restore validation.
    rejected = []
    for name, sql in (("invalid-stage", "UPDATE topic_stages SET stage='closed'"),
                      ("dangling-basis", "UPDATE topic_stage_events SET meeting_id='missing'"),
                      ("event-chain", "UPDATE topic_stages SET version=9"),
                      ("wrong-basis", "UPDATE topic_stage_events SET topic_version=99")):
        with zipfile.ZipFile(io.BytesIO(backup)) as z:
            files = {n: z.read(n) for n in z.namelist()}
        dbfile = out / f"{name}.sqlite3"
        dbfile.write_bytes(files["platform.sqlite3"])
        with closing(sqlite3.connect(dbfile)) as db, db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(sql)
        files["platform.sqlite3"] = dbfile.read_bytes()
        manifest = json.loads(files["manifest.json"])
        manifest["files"]["platform.sqlite3"] = {"bytes": len(files["platform.sqlite3"]), "sha256": hashlib.sha256(files["platform.sqlite3"]).hexdigest()}
        files["manifest.json"] = json.dumps(manifest).encode()
        corrupt = out / f"{name}.zip"
        with zipfile.ZipFile(corrupt, "w") as z:
            for key, value in files.items():
                z.writestr(key, value)
        target = out / f"rejected-{name}"
        try:
            restore_backup(corrupt, target)
            raise AssertionError("Corruption accepted: " + name)
        except ValueError:
            assert not target.exists()
            rejected.append(name)
    result = {"baseline": BASELINE, "cases": list(cases), "restarts": 2, "old_backup_restore": True, "complete_restore_and_continue": True, "rejected": rejected, "evidence": str(out)}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
