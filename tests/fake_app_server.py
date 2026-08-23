"""
Fake App-Server Child
=====================

Scripted stand-in for ``codex app-server`` used by the transport tests.
Reads JSONL requests on stdin and answers per the ``--scenario`` flag.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ACCOUNT = {
    'account': {'type': 'chatgpt', 'email': 'user@example.com', 'planType': 'plus'},
    'requiresOpenaiAuth': True,
}
LIMITS = {
    'rateLimits': {
        'primary': {'usedPercent': 12, 'windowDurationMins': 300, 'resetsAt': 1752600000},
        'secondary': {'usedPercent': 29, 'windowDurationMins': 10080, 'resetsAt': 1753000000},
    },
}
# Synthetic transport-test error only. WIRE_NOTES.md proves that -32001 is not
# authentication evidence and the provider adapter must ship with no auth codes.
SYNTHETIC_RPC_ERROR = {'code': -32001, 'message': 'synthetic error'}


def emit(message: object) -> None:
    sys.stdout.write(json.dumps(message) + '\n')
    sys.stdout.flush()


def log_message(path: str, message: object) -> None:
    if not path:
        return

    with open(path, 'a', encoding='utf-8') as log_file:
        log_file.write(json.dumps(message) + '\n')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', default='normal')
    parser.add_argument('--log', default='')
    parser.add_argument('--state', default='')
    args = parser.parse_args()

    data_requests_seen = 0
    deferred_request: dict | None = None
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue

        log_message(args.log, message)
        method = message.get('method')
        request_id = message.get('id')

        if method == 'initialize':
            emit({'id': request_id, 'result': {'serverInfo': {'name': 'fake'}}})
            if args.scenario == 'die-after-init':
                return 1
            continue
        if method == 'initialized':
            continue
        if request_id is None:
            continue

        data_requests_seen += 1
        if args.scenario == 'die-on-first-request' and data_requests_seen == 1:
            return 1
        if args.scenario == 'slow':
            time.sleep(30)
            continue
        if args.scenario == 'malformed' and data_requests_seen == 1:
            sys.stdout.write('this is not json\n')
            sys.stdout.flush()
            continue
        if args.scenario == 'non-object' and data_requests_seen == 1:
            emit(['not', 'an', 'object'])
            continue
        if args.scenario == 'malformed-envelope' and data_requests_seen == 1:
            emit({'id': request_id, 'error': 'not an error object'})
            continue
        if args.scenario == 'server-request' and data_requests_seen == 1:
            emit({'id': 999, 'method': 'tools/confirm', 'params': {}})
            reply = json.loads(sys.stdin.readline())
            log_message(args.log, {'reply_to_999': reply})
        if args.scenario == 'notify' and data_requests_seen == 1:
            emit({'method': 'account/updated', 'params': {}})
        if args.scenario == 'noise' and data_requests_seen == 1:
            emit({'id': 424242, 'result': {'spurious': True}})
        if args.scenario == 'stderr':
            print(f'warning: config at {Path.home()}\\.codex', file=sys.stderr)
            print('token=abcdefghijklmnopqrstuvwxyz012345', file=sys.stderr)
            sys.stderr.flush()
        if args.scenario == 'reverse-responses':
            if deferred_request is None:
                deferred_request = message
                continue
            emit({'id': request_id, 'result': {'method': method}})
            emit({'id': deferred_request['id'], 'result': {'method': deferred_request['method']}})
            deferred_request = None
            continue

        if args.scenario == 'die-after-account-first-generation' and method == 'account/read' and args.state and not Path(args.state).exists():
            emit({'id': request_id, 'result': ACCOUNT})
            Path(args.state).touch()
            return 1

        if method == 'account/read':
            refresh = bool((message.get('params') or {}).get('refreshToken'))
            emit({'id': request_id, 'result': ACCOUNT})
            if args.scenario == 'die-after-refresh' and refresh:
                return 1
        elif method == 'account/rateLimits/read':
            if args.scenario in ('synthetic-rpc-error', 'die-after-refresh'):
                emit({'id': request_id, 'error': SYNTHETIC_RPC_ERROR})
            else:
                emit({'id': request_id, 'result': LIMITS})
        else:
            emit({'id': request_id, 'error': {'code': -32601, 'message': 'method not found'}})

    return 0


if __name__ == '__main__':
    sys.exit(main())


