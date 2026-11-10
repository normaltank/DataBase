"""Real frontend event seams; browser checks own visual evidence."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node is required for frontend event checks')
class MaintenanceUiTests(unittest.TestCase):
    def test_actual_frontend_events(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run(['node',str(root/'tests/maintenance_ui.cjs')],cwd=root,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
