"""Start, inspect or stop the project-local dashboard independently of a terminal."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/bin/python'


def process_start(pid):
    try:
        return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def owned(state):
    pid = state.get('pid')
    if not isinstance(pid, int) or pid <= 1 or process_start(pid) != state.get('start_ticks'):
        return False
    try:
        cmd = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
        return (b'kronos_lab' in cmd and b'serve' in cmd
                and os.readlink(Path('/proc') / str(pid) / 'cwd') == str(ROOT))
    except OSError:
        return False


def health(port):
    try:
        with urlopen(f'http://127.0.0.1:{port}/health', timeout=1) as response:
            body = json.load(response)
            return response.status == 200 and body.get('service') == 'kronos-lab' and body.get('status') == 'ok'
    except (URLError, OSError, ValueError):
        return False


def read_state(path):
    try:
        state = json.loads(path.read_text())
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


@contextmanager
def control_lock(runtime):
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'control.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def show(state, log):
    ready = owned(state) and health(state['port'])
    print(json.dumps({'running': owned(state), 'ready': ready, 'pid': state.get('pid'),
        'url': f"http://127.0.0.1:{state['port']}" if state.get('port') else None,
        'device': state.get('device'), 'log': str(log)}, indent=2))
    return 0 if ready else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['start', 'status', 'stop'])
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--device', help='For example cuda:1 or cpu; otherwise preserve KRONOS_DEVICE')
    p.add_argument('--runtime-dir', type=Path, help='Separate process state/token directory for another instance')
    args = p.parse_args(argv)
    if not 1 <= args.port <= 65535:
        p.error('Port must be in 1..65535')
    runtime = args.runtime_dir.resolve() if args.runtime_dir else ROOT / '.cache/dashboard'
    token = runtime / 'api.token' if args.runtime_dir else ROOT / '.cache/api.token'
    state_path, log = runtime / 'process.json', runtime / 'server.log'
    with control_lock(runtime):
        state = read_state(state_path)
        if args.action == 'status':
            return show(state, log)
        if args.action == 'stop':
            if owned(state):
                os.kill(state['pid'], signal.SIGTERM)
                deadline = time.monotonic() + 20
                while owned(state) and time.monotonic() < deadline:
                    time.sleep(.1)
                if owned(state):
                    print('Shutdown is still draining active jobs; inspect ' + str(log), file=sys.stderr)
                    return 1
            state_path.unlink(missing_ok=True)
            print('Dashboard stopped; no unrelated process was terminated')
            return 0
        if owned(state):
            return show(state, log)
        if not PYTHON.is_file():
            p.error('Project environment is missing; run scripts/setup.sh first')
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', args.port)) == 0:
                p.error('Port is already in use by an unmanaged process; choose another port')
        token.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'w') as handle:
                handle.write(secrets.token_urlsafe(32))
        if len(token.read_text().strip()) < 16:
            p.error('Local API token is invalid; preserve/recreate it before starting')
        env = dict(os.environ)
        if args.device:
            env['KRONOS_DEVICE'] = args.device
        command = [str(PYTHON), '-m', 'kronos_lab', 'serve', '--token-file', str(token), '--port', str(args.port)]
        with os.fdopen(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'ab') as handle:
            child = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                stdout=handle, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
        state = {'pid': child.pid, 'start_ticks': process_start(child.pid), 'port': args.port,
                 'device': env.get('KRONOS_DEVICE', 'auto'), 'started_at': datetime.now(timezone.utc).isoformat()}
        state_path.write_text(json.dumps(state, indent=2) + '\n')
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if child.poll() is not None:
                print(f'Dashboard exited ({child.returncode}); inspect {log}', file=sys.stderr)
                return 1
            if health(args.port):
                return show(state, log)
            time.sleep(.2)
        print('Server has not become ready; inspect ' + str(log), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
