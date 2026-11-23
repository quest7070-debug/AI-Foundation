#!/usr/bin/env python3
"""Read-only CI runner identity evidence. No network, models, signals or mutation."""
import json
import os
from pathlib import Path
import platform
import pwd
import subprocess

if __name__ == '__main__':
    ps = subprocess.run(['ps', '-axo', 'pid=,uid=,comm='], check=True,
                        text=True, capture_output=True, timeout=5)
    rows = []
    for line in ps.stdout.splitlines():
        values = line.strip().split(None, 2)
        if len(values) == 3 and Path(values[2]).name in ('Runner.Listener', 'Runner.Worker'):
            rows.append({'pid': int(values[0]), 'uid': int(values[1]), 'name': Path(values[2]).name})
    print(json.dumps({'schema':'host-compute-owner-observation/v1', 'platform':platform.platform(),
                      'uid':os.getuid(), 'login':pwd.getpwuid(os.getuid()).pw_name,
                      'runner_name':os.environ.get('RUNNER_NAME'),
                      'runner_os':os.environ.get('RUNNER_OS'), 'runner_arch':os.environ.get('RUNNER_ARCH'),
                      'run_id':os.environ.get('GITHUB_RUN_ID'), 'source_sha':os.environ.get('GITHUB_SHA'),
                      'runner_processes':rows,
                      'job_started_hook_configured_in_environment':bool(os.environ.get('ACTIONS_RUNNER_HOOK_JOB_STARTED')),
                      'job_completed_hook_configured_in_environment':bool(os.environ.get('ACTIONS_RUNNER_HOOK_JOB_COMPLETED')),
                      'scope':'Current process/runner observation, not proof that every runner participates'},sort_keys=True))
