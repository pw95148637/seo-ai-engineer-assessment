"""Resume this task's own pending OAuth after an interrupted CLI process.

Only caches the device challenge, never credentials. Token exchange and credential
storage remain entirely in the pinned official Hermes CLI. Runtime is excluded
from Git and deliverables. New challenges require --new explicitly.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--new', action='store_true')
    args = parser.parse_args()
    from hermes_cli import auth, auth_codex
    if auth.get_codex_auth_status().get('logged_in'):
        print('This task is already signed in; no new device code requested.')
        return
    pending = Path(os.environ['HERMES_HOME']) / 'pending-device-login.json'
    request = auth_codex._codex_request_device_code

    def own_challenge(issuer, client_id):
        if args.new:
            data = request(issuer, client_id)
            # Use the official polling window as a conservative local upper bound.
            ttl = min(900, int(data.get('expires_in', 900)))
            payload = {'expires_at': time.time() + ttl, 'device_data': data}
            pending.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(payload, stream)
            return data
        if not pending.exists():
            raise SystemExit('No pending login. Use --new when the user is ready.')
        payload = json.loads(pending.read_text())
        if time.time() >= payload['expires_at']:
            pending.unlink()
            raise SystemExit('Pending device code expired. Use --new when ready.')
        return payload['device_data']

    auth_codex._codex_request_device_code = own_challenge
    from hermes_cli.main import main as official_main
    sys.argv = ['hermes', 'auth', 'add', 'openai-codex']
    try:
        official_main()
    finally:
        if auth.get_codex_auth_status().get('logged_in'):
            pending.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
