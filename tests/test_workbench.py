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

    def test_unmapped_source_line_reports_error(self):
        self.command('launch','ledger')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.command('break','ledger.cpp:9999')
        self.assertEqual(error.exception.code,400)

    def test_launch_path_escape_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.command('launch', '../examples/ledger.cpp')
        self.assertEqual(error.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
