#!/usr/bin/env bash
# Syncs Claude OAuth tokens from Mac Keychain to Pi dashboard.
# Run when the display shows "CLAUDE RE-AUTH" alert.
#
# Side effect: Pi will use Mac's refresh token on next cycle,
# which invalidates Mac's copy. Mac's Claude Code CLI will re-auth
# automatically on next use.

set -euo pipefail

PI="maciej@192.168.12.175"
REMOTE_CREDS="~/Waveshare-ePaper-10.85-dashboard/claude_creds.json"

echo "Reading Claude tokens from Mac Keychain..."
TMPJSON=$(mktemp)
trap 'rm -f "$TMPJSON"' EXIT

security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null > "$TMPJSON" || {
    echo "Error: 'Claude Code-credentials' not found in Keychain."
    echo "Make sure you are logged in to Claude Code on this Mac."
    exit 1
}

echo "Syncing to Pi ($PI)..."
python3 -c "
import json, subprocess, sys

with open('$TMPJSON') as f:
    data = json.load(f)

oauth = data['claudeAiOauth']
creds = {
    'accessToken':  oauth['accessToken'],
    'refreshToken': oauth['refreshToken'],
    'expiresAt':    oauth['expiresAt'],
    'scopes':       oauth.get('scopes', ['user:inference', 'user:profile']),
}
payload = json.dumps(creds, indent=2)
cmd = 'cat > $REMOTE_CREDS && chmod 600 $REMOTE_CREDS'
result = subprocess.run(['ssh', '$PI', cmd], input=payload.encode())
if result.returncode != 0:
    print('Error: SSH failed.')
    sys.exit(1)
print('Credentials written to Pi.')
"

echo "Testing fetch on Pi..."
ssh "$PI" "cd ~/Waveshare-ePaper-10.85-dashboard && python3 claude.py && cat usage.json"
echo ""
echo "Triggering display refresh..."
ssh "$PI" 'kill -USR1 $(pgrep -f main.py | head -1)'
echo "Done. Display will update in ~12s."
