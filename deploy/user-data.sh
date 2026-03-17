#!/bin/bash
# User Data script - chạy tự động mỗi khi instance mới được launch
set -e

LOG="/var/log/crawl-setup.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== Setup started at $(date) ==="

# ──────── CẤU HÌNH ────────
REPO_URL="https://github.com/YOUR_USERNAME/crawl_investing.git"
APP_DIR="/home/ec2-user/crawl_investing"
N8N_BASE_URL="https://your-n8n-domain.com"
N8N_API_KEY="your-n8n-api-key"
N8N_VARIABLE_KEY="CRAWL_SERVER_IP"
APP_PORT=5000

# ──────── Cài đặt dependencies ────────
yum update -y
yum install -y python3 python3-pip git

# ──────── Clone repo ────────
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR" && git pull
else
    git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

pip3 install -r requirements.txt
pip3 install boto3 requests

# ──────── Lấy metadata ────────
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/public-ipv4)
INSTANCE_ID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/instance-id)
REGION=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/placement/region)

echo "Instance: $INSTANCE_ID | IP: $PUBLIC_IP | Region: $REGION"

# ──────── Tạo systemd service cho app ────────
cat > /etc/systemd/system/crawl-api.service <<EOF
[Unit]
Description=Crawl Investing API
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 app.py
Restart=always
RestartSec=5
Environment=APP_PORT=$APP_PORT

[Install]
WantedBy=multi-user.target
EOF

# ──────── Tạo systemd service cho watchdog ────────
cat > /etc/systemd/system/crawl-watchdog.service <<EOF
[Unit]
Description=Crawl API Watchdog
After=crawl-api.service
Requires=crawl-api.service

[Service]
Type=simple
User=ec2-user
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 watchdog.py
Restart=always
RestartSec=10
Environment=EC2_INSTANCE_ID=$INSTANCE_ID
Environment=AWS_REGION=$REGION
Environment=N8N_BASE_URL=$N8N_BASE_URL
Environment=N8N_API_KEY=$N8N_API_KEY
Environment=N8N_VARIABLE_KEY=$N8N_VARIABLE_KEY
Environment=WATCHDOG_INTERVAL=60
Environment=WATCHDOG_MAX_FAILURES=3
Environment=WATCHDOG_COOLDOWN=300
Environment=APP_PORT=$APP_PORT
Environment=WATCHDOG_MODE=spot

[Install]
WantedBy=multi-user.target
EOF

# ──────── Start services ────────
systemctl daemon-reload
systemctl enable crawl-api crawl-watchdog
systemctl start crawl-api
sleep 3
systemctl start crawl-watchdog

# ──────── Cập nhật IP lên n8n ────────
if [ -n "$N8N_BASE_URL" ] && [ -n "$N8N_API_KEY" ]; then
    python3 - <<PYEOF
import requests, json, sys

base = "${N8N_BASE_URL}".rstrip("/")
headers = {"X-N8N-API-KEY": "${N8N_API_KEY}", "Content-Type": "application/json"}
key = "${N8N_VARIABLE_KEY}"
value = "http://${PUBLIC_IP}:${APP_PORT}"

try:
    resp = requests.get(f"{base}/api/v1/variables", headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data", resp.json()) if isinstance(resp.json(), dict) else resp.json()
    existing = next((v for v in data if v.get("key") == key), None)

    if existing:
        r = requests.patch(f"{base}/api/v1/variables/{existing['id']}",
                          headers=headers, json={"key": key, "value": value}, timeout=10)
        r.raise_for_status()
        print(f"Updated n8n variable: {key} = {value}")
    else:
        r = requests.post(f"{base}/api/v1/variables",
                         headers=headers, json={"key": key, "value": value}, timeout=10)
        r.raise_for_status()
        print(f"Created n8n variable: {key} = {value}")
except Exception as e:
    print(f"Warning: Could not update n8n: {e}", file=sys.stderr)
PYEOF
fi

echo "=== Setup completed at $(date) ==="
echo "App running at http://$PUBLIC_IP:$APP_PORT"
