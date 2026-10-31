"""Run a binary under Stillpoint and emit a CI-friendly crash handoff."""
import argparse
from pathlib import Path
import re
import sys
import time

import server
from incidents import incident_report


def emit_target_output(snapshot):
    output = snapshot.get('output', '')
    if output:
        sys.stdout.write(output)
        if not output.endswith('\n'):
            sys.stdout.write('\n')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    target_args = []
    if '--' in argv:
        separator = argv.index('--')
        target_args = argv[separator + 1:]
        argv = argv[:separator]

    parser = argparse.ArgumentParser(
        description='Run a Linux x86-64 ELF binary and write a crash handoff when it faults.')
    parser.add_argument('binary', type=Path, help='debug executable (ET_EXEC or PIE)')
    parser.add_argument('--report', default='stillpoint-incident.md',
                        help='Markdown report path, or - for stdout (default: %(default)s)')
    parser.add_argument('--timeout', type=float, default=30,
                        help='maximum run time in seconds (default: %(default)s)')
    options = parser.parse_args(argv)

    binary = options.binary.expanduser().resolve()
    if not binary.is_file() or not binary.stat().st_mode & 0o111:
        parser.error('binary must be an executable file')
    if options.timeout <= 0 or options.timeout > 3600:
        parser.error('--timeout must be greater than 0 and at most 3600 seconds')
    if any(any(char in arg for char in '\t\r\n\0') for arg in target_args):
        parser.error('target arguments cannot contain tabs or control line breaks')

    server.BINARY = binary
    launch = 'launch ' + str(binary) + ''.join('\t' + arg for arg in target_args)
    started = time.monotonic()
    try:
        snapshot = server.request_engine(launch)
        if snapshot.get('error'):
            print(snapshot['error'], file=sys.stderr)
            return 2

        snapshot = server.request_engine('continue')
        deadline = started + options.timeout
        while snapshot.get('state') == 'running':
            if time.monotonic() >= deadline:
                snapshot = server.request_engine('stop')
                emit_target_output(snapshot)
                print(f"Stillpoint timed out after {options.timeout:g}s", file=sys.stderr)
                return 124
            time.sleep(0.02)
            snapshot = server.request_engine('poll')

        if snapshot.get('state') == 'stopped':
            emit_target_output(snapshot)
            report = incident_report(snapshot)
            if options.report == '-':
                sys.stdout.write(report)
            else:
                report_path = Path(options.report).expanduser().resolve()
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(report, encoding='utf-8')
                print(f"Stillpoint captured {snapshot.get('signal_name') or 'a stop'}; report: {report_path}",
                      file=sys.stderr)
            signal_number = int(snapshot.get('signal_number') or 0)
            return min(255, 128 + signal_number) if signal_number else 1

        match = re.search(r'Exited with code (\d+)', snapshot.get('reason', ''))
        if snapshot.get('state') == 'exited' and match:
            emit_target_output(snapshot)
            return int(match.group(1))
        print(snapshot.get('error') or snapshot.get('reason') or 'Target ended unexpectedly', file=sys.stderr)
        return 2
    except (OSError, RuntimeError, ValueError) as error:
        print(f'Stillpoint triage failed: {error}', file=sys.stderr)
        return 2
    finally:
        if server.ENGINE and server.ENGINE.poll() is None:
            try:
                server.request_engine('stop')
            except (OSError, RuntimeError, ValueError):
                pass
            try:
                server.ENGINE.stdin.close()
                server.ENGINE.wait(timeout=3)
            except (OSError, TimeoutError):
                server.ENGINE.kill()


if __name__ == '__main__':
    raise SystemExit(main())
