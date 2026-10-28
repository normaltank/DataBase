"""Current compatibility entrypoint after #61 removed dedicated research writing.

Historical acceptance remains in Git and work/. Run the current public browser
flows for finished reports, simple folders and retained legacy evidence.
"""
import unittest
from check_reports_browser import ReportsBrowserTests

if __name__ == '__main__':
    unittest.main(verbosity=2)
