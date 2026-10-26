"""Human review facts stored with their immutable revision, separate from restored text."""
from flask import abort

SCOPES = {'metadata_only': '题录', 'fulltext_and_bylines': '原文与署名',
          'argument_and_translation': '论证与译文'}
ACTION = '完成信息核对'


def validate(data):
    scope, note = data.get('review_scope'), data.get('review_note')
    if not isinstance(scope, str) or scope not in SCOPES:
        abort(400, '请选择核对范围：题录、原文与署名或论证与译文。')
    if not isinstance(note, str) or not note.strip() or len(note) > 40000:
        abort(400, '请填写核对依据与说明（最多 40000 字）。')
    return {'review_scope': scope, 'review_note': note.strip()}


def last_modifier(db, kind, target_id):
    # A review changes the record version but does not make its reviewer a text author.
    return db.execute("""SELECT r.actor_id,u.name,r.created_at FROM revisions r
        JOIN users u ON u.id=r.actor_id WHERE target_type=? AND target_id=?
        AND action NOT IN (?, '导入初始版本') ORDER BY r.id DESC LIMIT 1""",
        (kind, target_id, ACTION)).fetchone()


def facts(db, kind, row, actor, data):
    result = validate(data)
    modifier = last_modifier(db, kind, row['id'])
    submitted = db.execute("SELECT actor_id FROM revisions WHERE target_type=? AND target_id=? AND action='提交来源' ORDER BY id LIMIT 1", (kind, row['id'])).fetchone() if kind == 'source' else None
    submitter = row['owner_id'] if kind == 'record' else submitted['actor_id'] if submitted else None
    author = row['author_id'] if kind == 'record' else None
    return {**result, 'submitter_id': submitter, 'author_id': author,
            'last_modifier_id': modifier['actor_id'] if modifier else None,
            'same_as_submitter': actor['id'] == submitter if submitter else None,
            'same_as_author': actor['id'] == author if author else None,
            'same_as_last_modifier': actor['id'] == modifier['actor_id'] if modifier else None}


def summary(db, kind, target_id, visible=None):
    """Only factual event metadata is readable here; historical bodies keep their ACL."""
    import json
    from . import identity
    ids = identity.origins(db, 'records' if kind == 'record' else 'sources', target_id)
    if kind == 'record' and visible:
        ids = [rid for rid in ids if visible(db.execute('SELECT * FROM records WHERE id=?', (rid,)).fetchone())]
    rows = db.execute(f"""SELECT r.*,u.name AS actor_name FROM revisions r
        JOIN users u ON u.id=r.actor_id WHERE target_type=? AND target_id IN
        ({','.join('?' for _ in ids)}) AND action=? ORDER BY r.id DESC""", (kind, *ids, ACTION))
    events = []
    for row in rows:
        snapshot = json.loads(row['snapshot_json'])
        event = snapshot.get('review_event') or {}
        events.append({'revision_id': row['id'], 'target_id': row['target_id'],
                       'version': snapshot['version'], 'actor_id': row['actor_id'],
                       'actor_name': row['actor_name'], 'created_at': row['created_at'],
                       **{key: event.get(key) for key in ['review_scope', 'review_note', 'submitter_id',
                           'author_id', 'last_modifier_id', 'same_as_submitter', 'same_as_author',
                           'same_as_last_modifier']}})
    return {'last_verified': events[0] if events else None, 'review_history': events}


def text(event):
    if not event:
        return '未登记实际核对。'
    def relation(key):
        value = event.get(key)
        return '历史未注明' if value is None else '同人' if value else '不同账号'
    return (f"最后实际核对基线：{event['target_id']} · 版本 {event['version']}\n"
            f"核对人：{event['actor_name']} · {event['actor_id']} · {event['created_at']}\n"
            f"核对范围：{SCOPES.get(event.get('review_scope'), '历史未注明')}\n"
            f"依据与说明：{event.get('review_note') or '历史未注明'}\n"
            f"与提交者：{relation('same_as_submitter')}；与负责作者：{relation('same_as_author')}；"
            f"与当时最后内容修改者：{relation('same_as_last_modifier')}\n"
            '账号关系只记录事实，不证明独立研究复核或研究结论成立。')


def html(item):
    import html as escape
    return ('<section><h2>核对记录</h2><p>当前状态：' + ('已核对' if item['status'] == 'verified' else '待核对')
            + f" · 当前版本 {item['version']}</p><pre>" + escape.escape(text(item.get('last_verified'))) + '</pre></section>')
