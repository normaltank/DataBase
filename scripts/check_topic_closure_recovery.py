"""Actual frozen v25/v23 -> closure migration, event packages and new-dir restore."""
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
from platform_app.web import create_app
from platform_app.maintenance import restore_backup
from scripts.check_collaboration_recovery import login
from scripts.check_topic_stages_recovery import SEED
from scripts.verify_work_materials import verify

OLD25 = "13dbe1fbdcf972249ab78947ee2d0bddbfa142c3"
OLD23 = "9032fed1800aab5b9e531a6d06f14437b89595ed"


def call(client, path, data, raw=None, method="POST", expected=201):
    options = {"headers": {"X-CSRF-Token": client.get("/api/session").json["csrf"]}}
    options.update({"json": data} if raw is None else {"data": {"data": json.dumps(data), "file": (io.BytesIO(raw), "synthetic.txt")}})
    response = client.open(path, method=method, **options)
    response.request.close()
    assert response.status_code == expected, (path, response.status_code, response.json)
    return response


def subset(old, current):
    if isinstance(old, dict):
        assert isinstance(current, dict)
        for key, value in old.items():
            subset(value, current[key])
    elif isinstance(old, list):
        assert len(old) == len(current)
        for left, right in zip(old, current):
            subset(left, right)
    else:
        assert old == current, (old, current)


def main():
    root = Path(__file__).resolve().parents[1]
    out = Path(tempfile.mkdtemp(prefix="database-topic-closure-recovery-"))
    (Path(tempfile.gettempdir()) / "database-topic-closure-recovery-latest.txt").write_text(str(out), encoding="utf-8")
    migrations = []
    for previous, baseline in ((25, OLD25), (23, OLD23)):
        area = out / f"old{previous}"
        area.mkdir()
        archive, source = area / "source.zip", area / "source"
        subprocess.run(["git", "archive", baseline, "platform_app", "-o", str(archive)], cwd=root, check=True, capture_output=True)
        with zipfile.ZipFile(archive) as z:
            z.extractall(source)
        seed = SEED.replace("'history':history,'files':files", "'history':history,'files':files,'topic':clients['colleague'].get(root).json")
        if previous == 25:
            # The v25 application itself confirms compilation; assigned-only stays selection.
            seed = seed.replace("    if kind=='withdrawn':", "    if kind not in ('empty','note','attachment','assigned'):\n        call(root+'/enter-compilation',{'request_id':'old25-explicit-enter','stage_version':1,'topic_version':1,'meeting_version':1})\n    if kind=='withdrawn':")
        seed += "\nassert clients['researcher'].get('/health').json['schema']==" + str(previous)
        subprocess.run([sys.executable, "-c", seed, str(area / "data"), str(area / "before.json"), str(area / "backup.zip")], cwd=source, check=True, capture_output=True)
        cases = json.loads((area / "before.json").read_text(encoding="utf-8"))
        target = area / "upgraded"
        restore_backup(area / "backup.zip", target)
        app = create_app(target, testing=True)
        direct = login(create_app(area / "data", testing=True), "researcher")
        assert all(t["lifecycle_state"] == "open" for t in direct.get("/api/collaboration/topics").json["items"])
        client = login(app, "colleague")
        for kind, case in cases.items():
            prefix = "/api/collaboration/topics/" + case["id"]
            topic = client.get(prefix).json
            assert topic["lifecycle_state"] == "open" and not topic["lifecycle_events"]
            if previous == 25:
                subset(case["topic"], topic)
                subset(case["workflow"], client.get(prefix + "/workflow").json)
            assert client.get(prefix + "/history").json == case["history"]
            for url, raw in case["files"].items():
                with client.get(url) as response:
                    assert response.data.hex() == raw
        # Restore the real automatic pre-v26 backup and upgrade it independently.
        backups = list((target / "backups").glob("*.zip"))
        with closing(sqlite3.connect(target / "platform.sqlite3")) as db:
            migration_backup = Path(db.execute("SELECT value FROM settings WHERE key='topic_closure_migration_backup'").fetchone()[0])
        assert migration_backup in backups
        pre = area / "pre-closure-restored"
        restore_backup(migration_backup, pre)
        restarted = login(create_app(pre, testing=True), "researcher")
        assert all(t["lifecycle_state"] == "open" for t in restarted.get("/api/collaboration/topics").json["items"])
        first = login(app, "researcher").get("/api/collaboration/topics").json
        for _ in range(2):
            app = create_app(target, testing=True)
            assert login(app, "researcher").get("/api/collaboration/topics").json == first
        migrations.append({"source_schema": previous, "baseline": baseline, "cases": len(cases), "pre_closure_backup_restore": True, "direct_instance_upgrade": True, "restarts": 2})
        if previous == 25:
            current_app, current_data, current_cases = app, target, cases
    lead, author, admin = [login(current_app, name) for name in ("researcher", "colleague", "admin")]
    tid = current_cases["summary_then_new_draft"]["id"]
    prefix = "/api/collaboration/topics/" + tid
    originals = author.get(prefix + "/workflow").json
    for cycle in range(2):
        preview = lead.get(prefix + "/closure-preview").json
        assert [(g["status"], g["submission_version"]) for g in preview["incomplete"]] == [("pending", 2)]
        call(lead, prefix + "/end", {"request_id": f"restore-end-{cycle}", "lifecycle_version": preview["lifecycle_version"], "basis_token": preview["basis_token"], "confirm": True})
        if cycle == 0:
            topic = lead.get(prefix).json
            call(lead, prefix + "/reopen", {"request_id": "restore-reopen-0", "lifecycle_version": topic["lifecycle_version"]})
    selection_id = current_cases["assigned"]["id"]
    preview = lead.get(f"/api/collaboration/topics/{selection_id}/closure-preview").json
    call(lead, f"/api/collaboration/topics/{selection_id}/end", {"request_id": "selection-end-1", "lifecycle_version": preview["lifecycle_version"], "basis_token": preview["basis_token"], "confirm": True})
    before = lead.get(prefix).json
    assert before["lifecycle_state"] == "closed" and len(before["lifecycle_events"]) == 3
    for who, client in (("lead", lead), ("author", author), ("admin", admin)):
        for scope in ("all", "products", "process"):
            with client.get(f"/api/collaboration/materials/topic/{tid}?scope={scope}") as response:
                assert response.status_code == 200
                package = out / f"{who}-{scope}.zip"
                package.write_bytes(response.data)
                verify(package)
    # Later revocation must not invalidate the authority of the saved old events.
    call(admin, "/api/collaboration/qualifications/researcher", {"version": 1, "enabled": False}, method="PUT", expected=200)
    with call(admin, "/api/backup", {}, expected=200) as response:
        backup = response.data
    backup_path = out / "closed-complete.zip"
    backup_path.write_bytes(backup)
    restored = out / "closed-restored"
    restore_backup(backup_path, restored)
    resumed = create_app(restored, testing=True)
    new_lead, new_author, new_admin = [login(resumed, name) for name in ("researcher", "colleague", "admin")]
    for key in ("stage", "lifecycle_state", "lifecycle_version", "closed_stage", "lifecycle_events"):
        assert new_author.get(prefix).json[key] == before[key]
    a = new_author.get(prefix + "/workflow").json["assignments"][0]
    call(new_author, prefix + f"/assignments/{a['id']}/submissions", {"request_id": "closed-restored-draft", "version": 2, "topic_version": 1, "meeting_version": 1}, b"must stay locked", expected=409)
    call(new_lead, prefix + "/reopen", {"request_id": "revoked-reopen", "lifecycle_version": 4}, expected=403)
    call(new_admin, "/api/collaboration/qualifications/researcher", {"version": 2, "enabled": True}, method="PUT", expected=200)
    call(new_lead, prefix + "/reopen", {"request_id": "restored-reopen", "lifecycle_version": 4})
    call(new_author, prefix + f"/assignments/{a['id']}/submissions", {"request_id": "restored-draft-3", "version": 2, "topic_version": 1, "meeting_version": 1}, b"restored legal next draft")
    after = new_author.get(prefix + "/workflow").json
    assert after["summaries"] == originals["summaries"]
    assert after["assignments"][0]["submissions"][1:] == originals["assignments"][0]["submissions"]
    rejected = []
    for name, sql in (("state", "UPDATE topic_closures SET state='bad'"),
                      ("stage", "UPDATE topic_closures SET closed_stage='selection' WHERE topic_id='" + tid + "'"),
                      ("chain", "UPDATE topic_closures SET version=99"),
                      ("basis", "UPDATE topic_closure_events SET basis_json=json_set(basis_json,'$.topic_version',999)"),
                      ("missing-material-basis", "UPDATE topic_closure_events SET basis_json=json_set(basis_json,'$.materials.topic_manuscripts',json('[\"unknown\"]'))"),
                      ("gaps", "UPDATE topic_closure_events SET incomplete_json='[]' WHERE action='end'")):
        with zipfile.ZipFile(io.BytesIO(backup)) as z:
            files = {n: z.read(n) for n in z.namelist()}
        database = out / f"bad-{name}.sqlite3"
        database.write_bytes(files["platform.sqlite3"])
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(sql)
        files["platform.sqlite3"] = database.read_bytes()
        manifest = json.loads(files["manifest.json"])
        manifest["files"]["platform.sqlite3"] = {"bytes": len(files["platform.sqlite3"]), "sha256": hashlib.sha256(files["platform.sqlite3"]).hexdigest()}
        files["manifest.json"] = json.dumps(manifest).encode()
        corrupt = out / f"bad-{name}.zip"
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
    for mode in ("original-bytes", "missing-original"):
        with zipfile.ZipFile(io.BytesIO(backup)) as z:
            files = {n: z.read(n) for n in z.namelist()}
        manifest = json.loads(files['manifest.json'])
        name = next(n for n in files if n.startswith('handoffs/'))
        if mode == 'missing-original':
            del files[name]
            del manifest['files'][name]
        else:
            files[name] = b'corrupt original with rewritten outer hash'
            manifest['files'][name] = {'bytes': len(files[name]), 'sha256': hashlib.sha256(files[name]).hexdigest()}
        files['manifest.json'] = json.dumps(manifest).encode()
        corrupt = out / (mode + '.zip')
        with zipfile.ZipFile(corrupt, 'w') as z:
            for key, value in files.items():
                z.writestr(key, value)
        target = out / ('rejected-' + mode)
        try:
            restore_backup(corrupt, target)
            raise AssertionError('Corruption accepted: ' + mode)
        except ValueError:
            assert not target.exists()
            rejected.append(mode)
    result = {"migrations": migrations, "closed_restore_after_revocation": True, "reopen_and_continue": True, "packages": 9, "rejected": rejected, "evidence": str(out)}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
