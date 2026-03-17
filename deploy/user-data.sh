#!/bin/bash
# User Data script - chạy tự động mỗi khi instance mới được launch
set -e

LOG="/var/log/crawl-setup.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== Setup started at $(date) ==="

# ──────── CẤU HÌNH ────────
REPO_URL="https://github.com/KenzyTran/crawl_investing.git"
APP_DIR="/home/ec2-user/crawl_investing"
APP_PORT=5000

# ──────── Lấy secrets từ SSM Parameter Store ────────
TELEGRAM_BOT_TOKEN=$(aws ssm get-parameter --name "/crawl-api/telegram-bot-token" --with-decryption --query "Parameter.Value" --output text --region ap-southeast-1)
TELEGRAM_CHAT_ID=$(aws ssm get-parameter --name "/crawl-api/telegram-chat-id" --with-decryption --query "Parameter.Value" --output text --region ap-southeast-1)
echo "Loaded secrets from SSM Parameter Store"

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
Environment=TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
Environment=TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
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

# ──────── Gửi IP qua Telegram ────────
if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    MSG="🟢 Crawl API Started
IP: $PUBLIC_IP
URL: http://$PUBLIC_IP:$APP_PORT
Instance: $INSTANCE_ID"
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="$TELEGRAM_CHAT_ID" \
        -d text="$MSG" \
        -d parse_mode="HTML"
    echo "Sent IP notification to Telegram"
fi

echo "=== Setup completed at $(date) ==="
echo "App running at http://$PUBLIC_IP:$APP_PORT"
