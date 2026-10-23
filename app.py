"""Local entrypoint. Use python app.py --help for options."""
import argparse
import os
from pathlib import Path

from platform_app.importer import DEFAULT_ROOT, import_thinktank
from platform_app.store import initialize
from platform_app.web import ROOT, create_app


def main():
    parser = argparse.ArgumentParser(description="研究中心共建共享资料平台（本地版）")
    parser.add_argument("--port", type=int, default=8848)
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("RESEARCH_DATA_DIR", ROOT / "data")))
    parser.add_argument("--source", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--no-import", action="store_true")
    args = parser.parse_args()
    initialize(args.data_dir)
    if not args.no_import:
        if args.source.is_dir():
            result = import_thinktank(args.data_dir, args.source)
            print("ThinkTank import:", {k: result[k] for k in ["records", "source_rows", "serial_rows", "already_imported"] if k in result}, flush=True)
        else:
            print("Source directory unavailable; starting with existing platform data.", flush=True)
    app = create_app(args.data_dir)
    print(f"Local: http://127.0.0.1:{args.port}", flush=True)
    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
