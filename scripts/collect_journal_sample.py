"""Controller-only bounded real sample. No AI dispatch or unrelated source claim."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_app.ingestion import sample_journals


def main():
    parser = argparse.ArgumentParser(description='明确选择的三刊公开题录试采：每刊最多5条，无AI，使用既有worker锁')
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--source-id', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True, help='本地取得报告，不含原始长摘要')
    args = parser.parse_args()
    if not (args.data_dir/'platform.sqlite3').is_file():
        parser.error('请指定已初始化且已明确启用期刊的data目录。')
    try:
        report = sample_journals(args.data_dir, args.source_id)
    except (ValueError,OSError) as error:
        parser.exit(2, str(error)+'\n')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    if any(s['status']!='succeeded' for s in report['sources']):
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
