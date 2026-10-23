"""Apply the explicitly reviewed 2026-10-21 evidence to existing IDs, once."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_app.maintenance import create_backup
from platform_app.source_catalog import catalog, unpack, validate_metadata
from platform_app.store import connect, now, save_revision
from platform_app.web import SOURCE_FIELDS

KEY = 'source_catalog_evidence_20261021'
DATE = '2026-10-21'


def relationship(kind, target, evidence):
    return dict(type=kind, target_id=target, evidence=evidence, checked_on=DATE)


UPDATES = {
    'SRC-LU-PEAK': dict(institution_types=['think_tank','research_institute'], relationships=[relationship(
        'part_of','SRC-LU-FESS', '学院官方研究所目录明确列出 LV PEAK 为学院科研单位。\nhttps://eszf.lu.lv/en/research/scientific-institutes/\n智库称谓见 https://www.lvpeak.lu.lv/en/ 。不据此推断独立法人；关系起始日未知。')]),
    'SRC-LU-FESS': dict(institution_types=['faculty'], relationships=[relationship(
        'part_of','SRC-LU','大学官方学院介绍确认该学院属于拉脱维亚大学。\nhttps://www.lu.lv/en/about-us/faculties/faculty-of-economics-and-social-sciences/\n学院成立年份为 2024；这里的日期是核查日，不是关系生效日。')]),
    'SRC-LU': dict(institution_types=['university']),
    'SRC-BICEPS': dict(institution_types=['research_institute'], relationships=[relationship(
        'cooperates_with','SRC-SSE-RIGA','BICEPS 官网说明与 SSE Riga 紧密合作、共同举办研讨会及出版成果。\nhttps://biceps.org/about-us/\n不据共址或共同出版认定隶属、联合设立、当前治理权；合作起始精确日期未知。')]),
    'SER-DU-JTES': dict(host_country_status='auto', host_evidence=(
        '2026-10-21 官网核查：该刊副题明确是 Daugavpils University, Latvia 所属 UNESCO Chair on the Interplay of Tradition and Innovation in Education for Sustainable Development 之期刊。'
        '支持大学层级的机构办刊归属，不把 UNESCO 本身增加为主办方，也未进行法律 owner 审计。\nhttps://reference-global.com/journal/JTES\nhttps://du.lv/en/research/scientific-publications/'),
        international_status='yes',international_evidence='2026-10-21：官网 Aims and scope 明确自称 international peer-reviewed journal，面向波罗的海及其他国家研究者。证据类型：直接国际办刊自述。页面未标更新时间。\nhttps://reference-global.com/journal/JTES'),
    'SER-LKA-CC': dict(host_country_status='pending', international_status='yes',international_evidence=(
        '2026-10-21：官网明确自称 international peer-reviewed journal。证据类型：直接国际办刊自述。\nhttps://culturecrossroads.lv/index.php/cc/about\n'
        '出版者精确为学院下属 Institute of Arts and Cultural Studies，所在国拉脱维亚；研究所尚未匹配现有编号，本次不把它静默替换为学院。主办角色仍按原表明示待核处理。')),
    'SER-LU-LAW': dict(international_status='yes',international_evidence=(
        '2026-10-21：官网把促进拉脱维亚、欧盟及其他国家法律界交流明确列为办刊目标。按已确认的“有依据的国际办刊定位”口径采纳；证据类型为跨国交流办刊宗旨，非直接自称 international journal。'
        '不以英语语种推断。页面未标更新时间。\nhttps://journal.lu.lv/jull/about\n主办关系仍为已有登记层级，本轮未作独立主办角色重验；未重验不等于已证伪。')),
    'SER-SSE-BJE': dict(host_country_status='pending'),
}


def apply(data_dir):
    db=connect(Path(data_dir)/'platform.sqlite3')
    try:
        previous=db.execute('SELECT value FROM settings WHERE key=?',(KEY,)).fetchone()
        if previous:
            return dict(already_applied=True, report=json.loads(previous[0]))
        backup=create_backup(data_dir)
        changed, skipped=[],[]
        with db:
            db.execute('BEGIN IMMEDIATE')
            for sid, patch in UPDATES.items():
                row=db.execute('SELECT * FROM sources WHERE id=?',(sid,)).fetchone()
                if not row:
                    skipped.append(dict(id=sid,reason='现有编号未找到，未新建或猜测匹配'))
                    continue
                current=unpack(row);updates=dict(patch)
                if 'institution_types' in updates:
                    updates['institution_types']=list(dict.fromkeys([t for t in current['institution_types'] if t!='other']+updates['institution_types']))
                if 'relationships' in updates:
                    merged=list(current['relationships'])
                    for rel in updates['relationships']:
                        if not any((x['type'],x['target_id'])==(rel['type'],rel['target_id']) for x in merged):
                            merged.append(rel)
                    updates['relationships']=merged
                if sid=='SER-SSE-BJE':
                    updates['host_evidence']=current['host_evidence']+'\n2026-10-21 样本复核发现角色／年代差异：2022 官方说明列 SSE Riga 与 BICEPS 共同出版、Routledge 合作；原表合作文本另写 Baltic Economic Association。当前主办责任及唯一出版者未核清，保留原 ID 和登记，不更改为隶属。\nhttps://biceps.org/2022/02/08/baltic-journal-of-economics-bje/\nhttps://biceps.org/about-us/'
                values={k:row[k] for k in SOURCE_FIELDS}
                validate_metadata(db,updates,values,row)
                if not any(values[k]!=row[k] for k in values):
                    continue
                if not db.execute("SELECT 1 FROM revisions WHERE target_type='source' AND target_id=?",(sid,)).fetchone():
                    save_revision(db,'source',sid,'补充证据前版本','admin')
                values.update(version=row['version']+1,status='pending',updated_at=now())
                db.execute(f"UPDATE sources SET {','.join(k+'=?' for k in values)} WHERE id=?",[*values.values(),sid])
                save_revision(db,'source',sid,'采纳 2026-10-21 样本证据（仍待中心核对）','admin')
                changed.append(sid)
            journals=[s for s in catalog(db).values() if s['kind']=='journal']
            report=dict(checked_on=DATE,backup=str(backup),changed=changed,skipped=skipped,
                        journals=len(journals),national_recorded=sum(s['national_status']=='recorded' for s in journals),
                        national_pending=[s['id'] for s in journals if s['national_status']=='pending'],
                        international={k:sum(s['international_status']==k for s in journals) for k in ['yes','no','unknown']},
                        boundaries='登记推导与四本官网样本分层；三条机构关系。无联合设立生产事实；不写 ThinkTank，不变更原始国家/主办/出版编号和分类。')
            db.execute('INSERT INTO settings VALUES (?,?)',(KEY,json.dumps(report,ensure_ascii=False)))
        return report
    finally:
        db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='一次性采纳已审查来源样本；先备份，保留历史。')
    parser.add_argument('--data-dir',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(apply(args.data_dir),ensure_ascii=False,indent=2))
