#!/usr/bin/env python3
"""Bind an explicitly supplied Google desktop OAuth client to native Keychain."""
import argparse
import json
import webbrowser
from ai_foundation.klm_drive_auth import authorize
from ai_foundation.macos_keychain import MacOSKeychain


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--client', required=True)
    args = p.parse_args()
    try:
        result = authorize(args.client, MacOSKeychain(), open_browser=webbrowser.open)
    except Exception as exc:
        print(json.dumps({'status': 'AUTH_NOT_BOUND', 'error_type': type(exc).__name__}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
