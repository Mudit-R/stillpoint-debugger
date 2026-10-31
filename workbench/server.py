"""Loopback workbench. One serialized C++ tracer owns every ptrace operation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
LOCK = threading.Lock()
ENGINE = None
BINARY = None
HISTORY = []


def request_engine(command):
    global ENGINE
    if ENGINE is None or ENGINE.poll() is not None:
        ENGINE = subprocess.Popen([str(BUILD / 'stillpoint')], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    ENGINE.stdin.write(command + '\n')
    ENGINE.stdin.flush()
    line = ENGINE.stdout.readline()
    if not line:
        raise RuntimeError('Debugger engine exited')
    snapshot = json.loads(line)
    if BINARY and snapshot.get('state') == 'stopped':
        addresses = snapshot.get('frames', [])
        result = subprocess.run(['addr2line', '-f', '-C', '-e', str(BINARY), *addresses],
                                capture_output=True, text=True, timeout=3)
        lines = result.stdout.splitlines()
        snapshot['stack'] = []
        for i, address in enumerate(addresses):
            name = lines[i*2] if i*2 < len(lines) else 'unknown'
            location = lines[i*2+1] if i*2+1 < len(lines) else '??:0'
            snapshot['stack'].append({'address': address, 'name': name, 'location': location})
        if snapshot['stack']:
            location = snapshot['stack'][0]['location']
            path, _, number = location.rpartition(':')
            source = Path(path).resolve()
            if source.is_relative_to(ROOT / 'examples') and source.is_file():
                snapshot['source'] = {'name': source.name, 'line': int(number) if number.isdigit() else 0,
                                      'text': source.read_text()}
    snapshot['binary'] = BINARY.name if BINARY else None
    return snapshot


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def valid_host(self):
        return self.headers.get('Host', '') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def send(self, status, data, mime='application/json'):
        body = json.dumps(data).encode() if mime == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {'error': 'Use localhost'})
        if self.path in ('/', '/app.js', '/style.css'):
            name = 'index.html' if self.path == '/' else self.path[1:]
            mime = {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript', 'style.css': 'text/css'}[name]
            return self.send(200, (ROOT / 'workbench' / name).read_bytes(), mime)
        if self.path == '/api/status':
            with LOCK:
                try:
                    return self.send(200, request_engine('poll'))
                except Exception as error:
                    return self.send(500, {'error': str(error)})
        self.send(404, {'error': 'Not found'})

    def do_POST(self):
        global BINARY
        if not self.valid_host() or self.headers.get('Origin') != 'http://' + self.headers.get('Host', ''):
            return self.send(403, {'error': 'Invalid origin'})
        if self.path != '/api/command':
            return self.send(404, {'error': 'Not found'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 1 or size > 4096:
                raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(size))
            command = body.get('command', '')
            argument = body.get('argument', '')
            if command not in ('launch', 'break', 'delete', 'continue', 'step', 'pause', 'stop'):
                raise ValueError('Unsupported command')
            if not isinstance(argument, str) or '\n' in argument or '\r' in argument:
                raise ValueError('Invalid argument')
            with LOCK:
                if command == 'launch':
                    candidate = (BUILD / argument).resolve()
                    if not candidate.is_relative_to(BUILD.resolve()) or not candidate.is_file() or candidate.name == 'stillpoint':
                        raise ValueError('Choose an executable from the build directory')
                    BINARY = candidate
                    argument = str(candidate)
                snapshot = request_engine(command + (' ' + argument if argument else ''))
                return self.send(200, snapshot)
        except (ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
            self.send(400, {'error': str(error)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', default=8765, type=int)
    args = parser.parse_args()
    if not (BUILD / 'stillpoint').is_file():
        raise SystemExit('Build the engine first: cmake -S . -B build && cmake --build build')
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f'Stillpoint: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    finally:
        if ENGINE:
            ENGINE.stdin.close()
            ENGINE.wait(timeout=3)
