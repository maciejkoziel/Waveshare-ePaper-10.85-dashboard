#!/usr/bin/env bash
# Syncs Claude OAuth tokens from Mac Keychain to Pi dashboard.
# Run when the display shows "CLAUDE RE-AUTH" alert.
#
# Side effect: Pi will use these tokens for the next refresh cycle,
# which invalidates Mac's copy. Mac's Claude Code CLI will prompt
# for re-auth automatically on next use.

set -euo pipefail

PI="maciej@192.168.12.175"
REMOTE_CREDS="~/Waveshare-ePaper-10.85-dashboard/claude_creds.json"

echo "Reading Claude tokens from Mac Keychain..."
RAW=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null || true)

if [ -z "$RAW" ]; then
    echo "Error: 'Claude Code-credentials' not found in Keychain."
    echo "Make sure you are logged in to Claude Code on this Mac."
    exit 1
fi

echo "Syncing to Pi ($PI)..."
echo "$RAW" | python3 - "$PI" "$REMOTE_CREDS" <<'PYEOF'
import json, sys, subprocess

raw = sys.stdin.read().strip()
pi, remote_path = sys.argv[1], sys.argv[2]

try:
    data = json.loads(raw)
    oauth = data["claudeAiOauth"]
except (json.JSONDecodeError, KeyError) as e:
    print(f"Error: Could not parse Keychain data: {e}")
    sys.exit(1)

creds = {
    "accessToken":  oauth["accessToken"],
    "refreshToken": oauth["refreshToken"],
    "expiresAt":    oauth["expiresAt"],
    "scopes":       oauth.get("scopes", ["user:inference", "user:profile"]),
}

payload = json.dumps(creds, indent=2)
cmd = f"cat > {remote_path} && chmod 600 {remote_path}"
proc = subprocess.run(["ssh", pi, cmd], input=payload.encode(), check=True)
print("Credentials written to Pi.")
PYEOF

echo "Testing fetch on Pi..."
ssh "$PI" "cd ~/Waveshare-ePaper-10.85-dashboard && python3 claude.py && cat usage.json"
echo ""
echo "Done. Triggering display refresh..."
ssh "$PI" 'kill -USR1 $(pgrep -f main.py | head -1)'
echo "Display will update in ~12s."
