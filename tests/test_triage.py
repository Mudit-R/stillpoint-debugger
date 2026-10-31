"""Headless triage entry point tests against real traced fixture processes."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / 'workbench' / 'triage.py'
BUILD = ROOT / 'build'


class TriageCliTests(unittest.TestCase):
    def run_triage(self, target, *arguments):
        return subprocess.run(
            [sys.executable, str(TRIAGE), str(BUILD / target), *arguments],
            capture_output=True, text=True, timeout=8)

    def test_crash_generates_handoff_and_preserves_signal_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / 'artifacts' / 'crash.md'
            result = self.run_triage('crash', '--report', str(report_path))
            self.assertEqual(result.returncode, 139, result.stderr)
            report = report_path.read_text(encoding='utf-8')
            self.assertIn('SIGSEGV', report)
            self.assertIn('ELF build ID', report)
            self.assertIn('Instructions at RIP', report)
            self.assertIn('crash.cpp:4', report)

    def test_successful_target_passes_without_creating_a_crash_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / 'should-not-exist.md'
            result = self.run_triage('ledger', '--report', str(report_path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Settlement: 976', result.stdout)
            self.assertFalse(report_path.exists())

    def test_timeout_stops_a_nonterminating_target(self):
        result = self.run_triage('loop', '--timeout', '0.05')
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn('timed out', result.stderr)


if __name__ == '__main__':
    unittest.main()
