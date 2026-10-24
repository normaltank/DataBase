"""Rebuild the synthetic v5 fixture from its fixed, pre-person implementation.

Run manually from this repository; normal tests use the checked-in SQL and JSON.
All content is invented, and the accounts are the public local demo accounts.
"""
import io
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

BASE = "b7b6c69f83f6efe85d4418ccac547d95ce5a0a5b"
ROOT = Path(__file__).resolve().parents[2]

BUILD = r'''
import io, json, sqlite3
from contextlib import closing
from pathlib import Path
from platform_app.web import create_app
app=create_app(Path("synthetic"),testing=True)
client=app.test_client()
token=client.get("/api/session").json["csrf"]
token=client.post("/api/login",json={"username":"researcher","password":"LocalDemo2026!"},headers={"X-CSRF-Token":token}).json["csrf"]
def post(path,data,method="POST",file=False):
    args={"json":data}
    if file: args={"data":{"data":json.dumps(data),"file":(io.BytesIO(b"Synthetic legacy attachment.\n"),"legacy.txt")}}
    response=client.open(path,method=method,headers={"X-CSRF-Token":token},**args)
    assert response.status_code in (200,201), response.json
    return response.json
source=post("/api/sources",{"name":"Synthetic v5 institution","kind":"institution"})["id"]
raw=post("/api/records",{"kind":"report","title":"Synthetic v5 original","authors":"A. Smith; Synthetic Institute","source_id":source,"body_html":"<p>Original evidence</p>","sharing_confirmed":True},file=True)["id"]
post("/api/records/"+raw,{"version":1,"title":"Synthetic v5 revised original"},"PUT")
attachment=client.get("/api/records/"+raw).json["attachments"][0]
note=post("/api/records",{"kind":"research_note","title":"Synthetic v5 note","evidence_record_id":raw,"evidence_attachment_id":attachment["id"],"quote":"Original evidence","locator":"page 7"})["id"]
report=post("/api/records",{"kind":"research_report","title":"Synthetic v5 research","evidence_ids":[note],"linked_ids":[raw],"body_html":"<p>Independent interpretation</p>"})["id"]
collection=post("/api/collections",{"name":"Synthetic v5 collection","visibility":"shared"})["id"]
post("/api/collections/"+collection+"/items",{"record_id":report})
expected={"baseline":BASE,"records":{},"history":{},"source":client.get("/api/sources/"+source).json,"collection":client.get("/api/collections/"+collection).json,"files":{}}
for rid in [raw,note,report]:
    expected["records"][rid]=client.get("/api/records/"+rid).json
    expected["history"][rid]=client.get("/api/history/record/"+rid).json
for file in Path("synthetic/uploads").iterdir():expected["files"][file.name]=file.read_text(encoding="utf-8")
with closing(sqlite3.connect("synthetic/platform.sqlite3")) as db:
    (OUTPUT/"people_v5.sql").write_text("-- Synthetic fixture from "+BASE+"; contains only public demo accounts.\n"+"\n".join(db.iterdump())+"\n",encoding="utf-8")
(OUTPUT/"people_v5.json").write_text(json.dumps(expected,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
'''


def main():
    with tempfile.TemporaryDirectory(prefix="wiki-v5-fixture-") as directory:
        archive = subprocess.run(["git", "archive", "--format=zip", BASE, "platform_app"], cwd=ROOT, check=True, capture_output=True)
        with zipfile.ZipFile(io.BytesIO(archive.stdout)) as bundle:
            bundle.extractall(directory)
        script = "from pathlib import Path\nBASE=" + repr(BASE) + "\nOUTPUT=Path(" + repr(str(Path(__file__).parent)) + ")\n" + BUILD
        environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        subprocess.run([sys.executable, "-c", script], cwd=directory, env=environment, check=True)


if __name__ == "__main__":
    main()
