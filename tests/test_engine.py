"""Integration tests: real ptrace children, no mocked process execution."""
import json
import os
from pathlib import Path
import select
import subprocess
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.proc = subprocess.Popen([str(ROOT / 'build/stillpoint')], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True)

    def tearDown(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=3)
        self.proc.stdout.close()

    def command(self, line):
        self.proc.stdin.write(line + '\n')
        self.proc.stdin.flush()
        ready, _, _ = select.select([self.proc.stdout], [], [], 4)
        self.assertTrue(ready, 'Engine command exceeded four seconds')
        return json.loads(self.proc.stdout.readline())

    def launch(self, name='ledger'):
        result = self.command('launch ' + str(ROOT / 'build' / name))
        self.assertEqual(result['error'], '')
        self.assertEqual(result['state'], 'stopped')
        return result

    def test_breakpoint_restore_step_and_exit(self):
        result = self.launch()
        main = next(s['address'] for s in result['symbols'] if s['name'] == 'main')
        self.assertEqual(self.command('break main')['breakpoints'], [main])
        result = self.command('continue')
        self.assertEqual(result['registers']['rip'], main)
        self.assertIn('Breakpoint', result['reason'])
        result = self.command('step')
        self.assertNotEqual(result['registers']['rip'], main)
        self.assertEqual(result['breakpoints'], [main])
        result = self.command('continue')
        self.assertEqual(result['state'], 'exited')
        self.assertIn('code 0', result['reason'])
        self.assertIn('Settlement: 976', result['output'])

    def test_continue_from_breakpoint_executes_original_instruction(self):
        self.launch()
        self.command('break main')
        self.command('continue')
        self.assertIn('code 0', self.command('continue')['reason'])

    def test_delete_at_breakpoint(self):
        self.launch()
        self.command('break main')
        self.command('continue')
        self.assertEqual(self.command('delete main')['breakpoints'], [])
        self.assertIn('code 0', self.command('continue')['reason'])

    def test_crash_is_inspectable_and_signal_is_delivered(self):
        self.launch('crash')
        result = self.command('continue')
        self.assertEqual(result['state'], 'stopped')
        self.assertIn('signal 11', result['reason'])
        self.assertEqual(result['signal_name'], 'SIGSEGV')
        self.assertEqual(result['signal_code_name'], 'SEGV_MAPERR')
        self.assertEqual(result['signal_address'], '0x0')
        self.assertTrue(result['frames'])
        self.assertTrue(result['memory'])
        result = self.command('continue')
        self.assertEqual(result['state'], 'exited')
        self.assertIn('signal 11', result['reason'])

    def test_fault_corpus_captures_distinct_kernel_diagnostics(self):
        cases = {
            'crash_write': ('SIGSEGV', 'SEGV_MAPERR', '0x0'),
            'bounds': ('SIGSEGV', 'SEGV_ACCERR', None),
            'divide': ('SIGFPE', 'FPE_INTDIV', None),
        }
        for target, (signal_name, code_name, address) in cases.items():
            with self.subTest(target=target):
                self.launch(target)
                result = self.command('continue')
                self.assertEqual(result['state'], 'stopped')
                self.assertEqual(result['signal_name'], signal_name)
                self.assertEqual(result['signal_code_name'], code_name)
                self.assertTrue(result['signal_address'])
                if address is not None:
                    self.assertEqual(result['signal_address'], address)
                if target == 'bounds':
                    self.assertNotEqual(result['signal_address'], '0x0')

    def test_pie_load_bias_relocates_symbols_and_software_breakpoints(self):
        result = self.launch('pie_crash')
        bias = int(result['load_bias'], 16)
        self.assertGreater(bias, 0)
        main = next(int(symbol['address'], 16) for symbol in result['symbols'] if symbol['name'] == 'main')
        self.assertGreater(main, bias)
        self.command('break main')
        result = self.command('continue')
        self.assertEqual(result['registers']['rip'], hex(main))
        self.assertIn('Breakpoint', result['reason'])
        result = self.command('continue')
        self.assertEqual(result['signal_name'], 'SIGSEGV')
        self.assertEqual(result['signal_address'], '0x0')

    def test_running_process_can_be_paused(self):
        self.launch('loop')
        result = self.command('continue')
        self.assertEqual(result['state'], 'running')
        result = self.command('pause')
        self.assertEqual(result['state'], 'stopped')
        self.assertEqual(self.command('stop')['state'], 'idle')

    def test_invalid_commands_do_not_destroy_session(self):
        self.launch()
        self.assertTrue(self.command('break not_a_symbol')['error'])
        self.assertEqual(self.command('status')['state'], 'stopped')

    def test_end_kills_and_reaps_tracee(self):
        pid = self.launch()['pid']
        self.command('stop')
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_adjacent_breakpoints_preserve_other_bytes(self):
        result = self.launch()
        addr = int(next(s['address'] for s in result['symbols'] if s['name']=='main'),16)
        original = int(self.command('memory main')['memory'][0]['value'],16)
        self.command('break main')
        self.command('break ' + hex(addr+1))
        patched = int(self.command('memory main')['memory'][0]['value'],16)
        self.assertEqual(patched & 0xffff, 0xcccc)
        self.command('delete main')
        restored = int(self.command('memory main')['memory'][0]['value'],16)
        self.assertEqual(restored & 0xff, original & 0xff)
        self.assertEqual(restored & 0xff00, 0xcc00)
        self.command('delete ' + hex(addr+1))
        self.assertEqual(int(self.command('memory main')['memory'][0]['value'],16), original)

    def test_invalid_memory_read_preserves_session(self):
        self.launch()
        self.assertTrue(self.command('memory 0x1')['error'])
        self.assertEqual(self.command('memory rsp')['state'], 'stopped')

    def test_launch_arguments_are_passed_without_a_shell(self):
        result=self.command('launch '+str(ROOT/'build/arguments')+'\thello world\t$(echo unsafe)')
        self.assertEqual(result['error'],'')
        result=self.command('continue')
        self.assertIn('argv[1] = hello world',result['output'])
        self.assertIn('argv[2] = $(echo unsafe)',result['output'])

    def test_reject_non_elf(self):
        result = self.command('launch ' + str(ROOT / 'examples/ledger.cpp'))
        self.assertTrue(result['error'])
        self.assertEqual(result['state'], 'idle')


if __name__ == '__main__':
    unittest.main()
