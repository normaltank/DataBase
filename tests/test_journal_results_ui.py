"""Actual journal page-event checks, independent of HTTP and browser layout."""
from pathlib import Path
import shutil
import subprocess
import unittest


class JournalResultsPageEventTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node is required for page-event checks')
    def test_journal_result_page_events(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run(['node',str(root/'tests/journal_results_ui.cjs')],cwd=root,
                              capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
