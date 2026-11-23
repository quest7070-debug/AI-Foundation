#!/bin/bash
set -euo pipefail
KLM_SETUP_ROOT="${HOME}/Library/Application Support/AI-Foundation/klm-drive/auth-helper"
export PYTHONPATH="${KLM_SETUP_ROOT}/src"
export PYTHONDONTWRITEBYTECODE=1
exec /opt/homebrew/bin/python3 -B -m ai_foundation.klm_auth_setup
