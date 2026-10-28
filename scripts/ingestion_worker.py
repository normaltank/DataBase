"""Absolute-path launcher for identifying this checkout's detached worker."""
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_app.ingestion import main

if __name__ == '__main__':
    main()
