# Oracle Cloud (Always Free) deployment

This guide deploys the bot as a systemd service on Ubuntu in Oracle Cloud.

## 1) Create Oracle VM

- Shape: `VM.Standard.E2.1.Micro` (Always Free eligible)
- Image: Ubuntu 22.04 LTS (or 24.04 if available)
- Public IP: enabled
- Add your SSH public key

Security list / NSG:
- Allow inbound `22/tcp` from your IP only
- Do **not** open dashboard port to the internet unless you fully understand the risk

## 2) Copy repo to VM

```bash
ssh ubuntu@<VM_PUBLIC_IP>
git clone <your_repo_url> ~/crypto_dip_bot
cd ~/crypto_dip_bot
```

If this repo is local-only, copy it from your machine:

```bash
rsync -avz --delete /home/konstantin/dev/crypto_dip_bot/ ubuntu@<VM_PUBLIC_IP>:~/crypto_dip_bot/
```

## 3) Bootstrap host and install service

```bash
cd ~/crypto_dip_bot
sudo bash scripts/setup_oracle_ubuntu.sh ~/crypto_dip_bot /opt/crypto-dip-bot /etc/crypto-dip-bot.env
```

## 4) Configure bot secrets and runtime

```bash
sudo nano /etc/crypto-dip-bot.env
```

Minimum required values:

```dotenv
MEXC_API_KEY=...
MEXC_API_SECRET=...
DRY_RUN=false

# Dashboard defaults (recommended)
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8050
DASHBOARD_ALLOW_PUBLIC_NO_AUTH=false
```

Optional (if you want header/token auth):

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

Then add `DASHBOARD_TOKEN=<generated-value>` to `/etc/crypto-dip-bot.env`.

## 5) Start and verify

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-dip-bot
sudo systemctl status crypto-dip-bot --no-pager
sudo journalctl -u crypto-dip-bot -f
```

## 6) Dashboard access (safe options)

### Option A: SSH tunnel (recommended)

```bash
ssh -L 8050:127.0.0.1:8050 ubuntu@<VM_PUBLIC_IP>
```

Then open `http://127.0.0.1:8050/` in your browser.
If token auth is enabled, use request header `Authorization: Bearer <token>` (or disable token for browser-only SSH tunnel usage).

### Option B: Nginx reverse proxy + auth (advanced)

- Install nginx and TLS (for example with Let's Encrypt).
- Use `deploy/nginx-dashboard.conf` in your server config.
- Keep dashboard bound to localhost (`DASHBOARD_HOST=127.0.0.1`).

## Updating bot code

```bash
cd ~/crypto_dip_bot
git pull
sudo bash scripts/setup_oracle_ubuntu.sh ~/crypto_dip_bot /opt/crypto-dip-bot /etc/crypto-dip-bot.env
sudo systemctl restart crypto-dip-bot
```

## Troubleshooting

- Check env loading errors:

```bash
sudo journalctl -u crypto-dip-bot -n 200 --no-pager
```

- Validate Python deps:

```bash
/opt/crypto-dip-bot/venv/bin/python -m pip list
```

- If service does not start, verify file paths:
  - `/opt/crypto-dip-bot/run_bot.py`
  - `/opt/crypto-dip-bot/dip_bot_v24 1.py`
  - `/etc/crypto-dip-bot.env`


