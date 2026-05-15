#!/bin/bash
# Gate: verify policy file is valid JSON with required fields
set -euo pipefail
POLICY="${1:-policies/default.policy.json}"
python3 -c "
import json, sys
p = json.load(open('$POLICY'))
for k in ['version','default_mode','dangerous_actions','blocked_paths','allowed_project_roots']:
    assert k in p, f'Missing: {k}'
print('✅ Policy valid')
"
