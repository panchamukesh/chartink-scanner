#!/bin/bash
# Deploy / update MarketScan Pro on the Google Cloud VM
set -e

REMOTE_USER="priya141ch"
REMOTE_HOST="35.184.92.9"
REMOTE_DIR="/home/priya141ch/chartink-scanner"
REPO="https://github.com/panchamukesh/chartink-scanner.git"
SERVICE="chartink-scanner"
PORT=5002

ssh "${REMOTE_USER}@${REMOTE_HOST}" bash << EOF
  set -e

  # Clone on first run, pull on subsequent runs
  if [ ! -d "${REMOTE_DIR}" ]; then
    git clone "${REPO}" "${REMOTE_DIR}"
  else
    cd "${REMOTE_DIR}" && git pull
  fi

  # Write systemd service if not present
  if [ ! -f /etc/systemd/system/${SERVICE}.service ]; then
    sudo tee /etc/systemd/system/${SERVICE}.service > /dev/null << 'UNIT'
[Unit]
Description=MarketScan Pro NSE Scanner
After=network.target

[Service]
User=${REMOTE_USER}
WorkingDirectory=${REMOTE_DIR}
ExecStart=/usr/bin/python3 ${REMOTE_DIR}/server.py
Restart=always
RestartSec=5
Environment=PORT=${PORT}

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl daemon-reload
    sudo systemctl enable ${SERVICE}
  fi

  sudo systemctl restart ${SERVICE}
  echo "✅ MarketScan Pro running at http://${REMOTE_HOST}:${PORT}"
EOF
