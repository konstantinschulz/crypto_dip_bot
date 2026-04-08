#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   sudo bash scripts/setup_oracle_ubuntu.sh \
#     /home/ubuntu/crypto_dip_bot \
#     /opt/crypto-dip-bot \
#     /etc/crypto-dip-bot.env

SRC_DIR="${1:-}"
INSTALL_DIR="${2:-/opt/crypto-dip-bot}"
ENV_FILE="${3:-/etc/crypto-dip-bot.env}"

if [[ -z "$SRC_DIR" ]]; then
  echo "Usage: sudo bash $0 <source_repo_dir> [install_dir] [env_file]"
  exit 1
fi

if [[ ! -d "$SRC_DIR" ]]; then
  echo "Source directory not found: $SRC_DIR"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip git rsync ufw ca-certificates

if ! id -u bot >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin bot
fi

mkdir -p "$INSTALL_DIR"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.idea' \
  --exclude '__pycache__' \
  "$SRC_DIR"/ "$INSTALL_DIR"/

python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$INSTALL_DIR/.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE. Edit it before starting service."
fi

cp "$INSTALL_DIR/deploy/crypto-dip-bot.service" /etc/systemd/system/crypto-dip-bot.service
systemctl daemon-reload

chown -R bot:bot "$INSTALL_DIR"
chmod 640 "$ENV_FILE" || true

# Basic host firewall: keep SSH open; dashboard should stay local and not need inbound rule.
ufw allow OpenSSH || true
ufw --force enable || true

echo
echo "Setup complete. Next steps:"
echo "1) sudo nano $ENV_FILE"
echo "1a) sudo systemctl daemon-reload"
echo "1b) sudo systemctl restart crypto-dip-bot"
echo "2) sudo systemctl enable --now crypto-dip-bot"
echo "2a) sudo systemctl status crypto-dip-bot --no-pager"
echo "3) sudo journalctl -u crypto-dip-bot -f"


