"""HTTP bridge integration with real engine execution and browser-origin guards."""
import importlib.util
import json
from pathlib import Path
import threading
import unittest
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bridge', ROOT / 'workbench/server.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class WorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = bridge.ThreadingHTTPServer(('127.0.0.1', 0), bridge.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        if bridge.ENGINE:
            bridge.ENGINE.stdin.close()
            bridge.ENGINE.wait(timeout=3)
            bridge.ENGINE.stdout.close()

    def command(self, command, argument='', origin=None):
        request = urllib.request.Request(self.origin + '/api/command',
            data=json.dumps({'command':command,'argument':argument}).encode(),
            headers={'Origin':origin or self.origin,'Content-Type':'application/json'})
        return json.load(urllib.request.urlopen(request, timeout=5))

    def test_full_browser_protocol(self):
        self.assertEqual(self.command('launch', 'ledger')['state'], 'stopped')
        self.command('break', 'main')
        result = self.command('continue')
        self.assertEqual(result['source']['name'], 'ledger.cpp')
        self.assertTrue(result['disassembly'])
        self.assertIn(result['registers']['rip'][2:], result['disassembly'][0])
        before = result['source']['line']
        result = self.command('source-step')
        self.assertNotEqual(result['source']['line'], before)
        self.assertEqual(result['stack'][0]['name'], 'main')
        result = self.command('continue')
        self.assertIn('Settlement: 976', result['output'])

    def test_foreign_origin_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.command('launch', 'ledger', 'http://untrusted.example')
        self.assertEqual(error.exception.code, 403)

    def test_source_line_breakpoint(self):
        self.command('launch','ledger')
        self.command('break','ledger.cpp:17')
        result=self.command('continue')
        self.assertIn('Breakpoint',result['reason'])
        self.assertEqual(result['source']['line'],17)
        self.command('delete','ledger.cpp:17')
        self.assertIn('code 0',self.command('continue')['reason'])

    def test_pie_source_mapping_and_disassembly_use_runtime_addresses(self):
        launched = self.command('launch', 'pie_crash')
        self.assertGreater(int(launched['load_bias'], 16), 0)
        self.command('break', 'crash.cpp:10')
        stopped = self.command('continue')
        self.assertEqual(stopped['source']['line'], 10)
        self.assertEqual(stopped['registers']['rip'], stopped['breakpoints'][0])
        self.assertIn(stopped['registers']['rip'][2:], stopped['disassembly'][0])
        crashed = self.command('continue')
        self.assertEqual(crashed['source']['line'], 4)
        self.assertEqual(crashed['signal_name'], 'SIGSEGV')

    def test_unmapped_source_line_reports_error(self):
        self.command('launch','ledger')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.command('break','ledger.cpp:9999')
        self.assertEqual(error.exception.code,400)

    def test_launch_path_escape_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.command('launch', '../examples/ledger.cpp')
        self.assertEqual(error.exception.code, 400)

    def test_incident_reports_cover_fault_corpus_and_group_repeats(self):
        with urllib.request.urlopen(self.origin + '/', timeout=5) as response:
            page = response.read().decode()
        self.assertIn('id="incidentPanel"', page)
        self.assertIn('Download handoff report', page)
        cases = {
            'crash': ('SIGSEGV', 'SEGV_MAPERR'),
            'pie_crash': ('SIGSEGV', 'SEGV_MAPERR'),
            'crash_write': ('SIGSEGV', 'SEGV_MAPERR'),
            'bounds': ('SIGSEGV', 'SEGV_ACCERR'),
            'divide': ('SIGFPE', 'FPE_INTDIV'),
        }
        signatures = {}
        for target, (signal_name, code_name) in cases.items():
            with self.subTest(target=target):
                self.assertEqual(self.command('launch', target)['state'], 'stopped')
                stopped = self.command('continue')
                self.assertEqual(stopped['signal_name'], signal_name)
                self.assertEqual(stopped['signal_code_name'], code_name)
                self.assertTrue(stopped['build_id'])
                self.assertIsNotNone(stopped['incident'])
                signatures[target] = stopped['incident']['signature']
                with urllib.request.urlopen(self.origin + '/api/incident-report.md', timeout=5) as response:
                    self.assertIn('text/markdown', response.headers['Content-Type'])
                    self.assertIn('attachment;', response.headers['Content-Disposition'])
                    report = response.read().decode()
                for expected in (signatures[target], signal_name, code_name, '## Stack', '## Registers',
                                 '## Instructions at RIP', '## Source context', '## Captured output'):
                    self.assertIn(expected, report)
                self.assertIn(stopped['build_id'], report)
                if target == 'crash':
                    rebuilt = dict(stopped, build_id='different-elf-build')
                    self.assertNotEqual(bridge.incident_for(rebuilt)['signature'], signatures[target])
        self.assertEqual(len(set(signatures.values())), len(cases))
        self.command('launch', 'crash')
        repeated = self.command('continue')
        self.assertEqual(repeated['incident']['signature'], signatures['crash'])

if __name__ == '__main__':
    unittest.main()
