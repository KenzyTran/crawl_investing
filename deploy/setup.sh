#!/bin/bash
# Setup script - chạy 1 lần trên EC2 instance
set -e

echo "=== Cài đặt dependencies ==="
pip3 install -r requirements.txt
pip3 install boto3

echo "=== Copy systemd service files ==="
sudo cp deploy/crawl-api.service /etc/systemd/system/
sudo cp deploy/crawl-watchdog.service /etc/systemd/system/

echo "=== Reload systemd ==="
sudo systemctl daemon-reload

echo "=== Enable services (tự start khi boot) ==="
sudo systemctl enable crawl-api
sudo systemctl enable crawl-watchdog

echo "=== Start services ==="
sudo systemctl start crawl-api
sudo systemctl start crawl-watchdog

echo ""
echo "✓ Done! Kiểm tra status:"
echo "  sudo systemctl status crawl-api"
echo "  sudo systemctl status crawl-watchdog"
echo "  tail -f watchdog.log"
echo ""
echo "⚠ QUAN TRỌNG: Sửa file /etc/systemd/system/crawl-watchdog.service"
echo "  - EC2_INSTANCE_ID: ID instance của bạn"
echo "  - N8N_BASE_URL: URL n8n của bạn"
echo "  - N8N_API_KEY: API key n8n"
echo "  Sau khi sửa, chạy: sudo systemctl daemon-reload && sudo systemctl restart crawl-watchdog"
