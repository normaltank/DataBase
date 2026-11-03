"""Include the public page-event regression in synthetic discovery when Node is present."""
from pathlib import Path
import shutil
import subprocess
import unittest


class IngestionPageEventTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for collection page-event checks')
    def test_collection_page_events(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', str(root / 'tests/ingestion_ui.cjs')], cwd=root,
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
