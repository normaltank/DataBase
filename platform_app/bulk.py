"""Explicit, permission-checked library selections and atomic batch additions."""
from flask import abort, jsonify

from .record_revisions import check_version
from .store import now, save_revision

LIMIT = 100


def register(app, ctx):
    def selected(data):
        ids = data.get("ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= LIMIT or any(not isinstance(rid, str) or not rid or len(rid) > 200 for rid in ids):
            abort(400, "请选择 1—100 条资料。")
        rows = []
        for rid in dict.fromkeys(ids):
            row = ctx.db().execute("SELECT * FROM records WHERE id=? AND merged_into IS NULL", (rid,)).fetchone()
            if not row or not ctx.visible(row):
                abort(404, "选中资料不存在或已无访问权限，请重新核对选择。")
            rows.append(row)
        return rows

    @app.post("/api/library/bulk/favorites")
    def add_favorites():
        connection = ctx.db()
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = selected(ctx.body())
            actor, added = ctx.user()["id"], 0
            for row in rows:
                added += connection.execute("INSERT OR IGNORE INTO favorites VALUES (?,?)", (actor, row["id"])).rowcount
        return jsonify(selected=len(rows), added=added, existing=len(rows) - added)

    @app.post("/api/library/bulk/export")
    def export_selection():
        connection = ctx.db()
        with connection:
            connection.execute("BEGIN")
            return ctx.export_csv(selected(ctx.body()), "research-selected-records.csv")

    @app.post("/api/library/bulk/collections/<cid>")
    def add_collection_items(cid):
        connection = ctx.db()
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            data = ctx.body()
            collection = ctx.get_collection(cid, edit=True)
            check_version(data, collection)
            rows = selected(data)
            existing = {r[0] for r in connection.execute("SELECT record_id FROM collection_items WHERE collection_id=?", (cid,))}
            new_ids = [r["id"] for r in rows if r["id"] not in existing]
            version = collection["version"]
            if new_ids:
                if not connection.execute("SELECT 1 FROM revisions WHERE target_type='collection' AND target_id=?", (cid,)).fetchone():
                    save_revision(connection, "collection", cid, "专题整理前版本", ctx.user()["id"])
                connection.executemany("INSERT INTO collection_items VALUES (?,?)", [(cid, rid) for rid in new_ids])
                version += 1
                connection.execute("UPDATE collections SET version=?,updated_at=? WHERE id=?", (version, now(), cid))
                save_revision(connection, "collection", cid, "批量加入专题资料", ctx.user()["id"])
        return jsonify(selected=len(rows), added=len(new_ids), existing=len(rows) - len(new_ids), version=version)
