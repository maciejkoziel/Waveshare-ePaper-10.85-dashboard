#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
USER=$(whoami)

# --- dashboard.service ---
cat > /tmp/dashboard.service << EOF
[Unit]
Description=Waveshare ePaper Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# --- dashboard-message.service ---
cat > /tmp/dashboard-message.service << EOF
[Unit]
Description=Waveshare ePaper Dashboard Message Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/message_server.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo mv /tmp/dashboard.service /etc/systemd/system/dashboard.service
sudo mv /tmp/dashboard-message.service /etc/systemd/system/dashboard-message.service
sudo systemctl daemon-reload
sudo systemctl enable dashboard dashboard-message
sudo systemctl restart dashboard dashboard-message
echo "--- dashboard ---"
systemctl status dashboard --no-pager
echo "--- dashboard-message ---"
systemctl status dashboard-message --no-pager
