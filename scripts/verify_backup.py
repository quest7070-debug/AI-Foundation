#!/usr/bin/env python3
"""Read-only Foundation backup content verification; never restores or prunes."""
import argparse
import json

from ai_foundation.productization import BackupValidationError, verify_backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup_dir')
    args = parser.parse_args(argv)
    try:
        manifest = verify_backup(args.backup_dir)
    except BackupValidationError as error:
        result = {'status': 'INVALID_BACKUP', 'reason': error.code}
    except OSError:
        result = {'status': 'INVALID_BACKUP', 'reason': 'unreadable'}
    else:
        result = {'status': 'CONTENT_VERIFIED', 'schema_version': manifest['schema_version'],
            'verified_files': len(manifest['files'])}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'CONTENT_VERIFIED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
