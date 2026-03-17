"""
Watchdog - Tự động phát hiện server bị chặn và xử lý.

Mode "spot": Terminate instance → ASG tự tạo instance mới với IP mới
Thông báo IP mới qua Telegram.

Flow:
1. Gọi /health mỗi CHECK_INTERVAL giây
2. Nếu fail liên tiếp MAX_FAILURES lần → coi như bị chặn
3. Gửi thông báo Telegram → terminate instance
4. ASG launch instance mới → user-data gửi IP mới qua Telegram
"""

import os
import sys
import time
import logging
import requests
import boto3
from botocore.exceptions import ClientError

# ──────────────────── CẤU HÌNH ────────────────────
CHECK_INTERVAL = int(os.getenv("WATCHDOG_INTERVAL", "60"))
MAX_FAILURES = int(os.getenv("WATCHDOG_MAX_FAILURES", "3"))
APP_PORT = int(os.getenv("APP_PORT", "5000"))
HEALTH_URL = f"http://127.0.0.1:{APP_PORT}/health"

# AWS
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-1")
EC2_INSTANCE_ID = os.getenv("EC2_INSTANCE_ID", "")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Cooldown sau khi xử lý (tránh xử lý liên tục)
COOLDOWN = int(os.getenv("WATCHDOG_COOLDOWN", "300"))

# ──────────────────── LOGGING ────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("watchdog.log"),
    ],
)
log = logging.getLogger("watchdog")

# ──────────────────── AWS HELPERS ────────────────────
ec2 = boto3.client("ec2", region_name=AWS_REGION)


def terminate_self():
    """Terminate instance hiện tại (ASG sẽ tạo mới)."""
    log.info(f"TERMINATING instance {EC2_INSTANCE_ID} - ASG sẽ launch instance mới...")
    ec2.terminate_instances(InstanceIds=[EC2_INSTANCE_ID])


# ──────────────────── TELEGRAM HELPERS ────────────────────

def send_telegram(message):
    """Gửi tin nhắn qua Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Chưa cấu hình Telegram, bỏ qua thông báo")
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
        resp.raise_for_status()
        log.info("Đã gửi thông báo Telegram")
        return True
    except Exception as e:
        log.error(f"Lỗi gửi Telegram: {e}")
        return False


# ──────────────────── APP HELPERS ────────────────────

def check_health():
    """Gọi /health endpoint, trả về True nếu OK."""
    try:
        resp = requests.get(HEALTH_URL, timeout=20)
        if resp.status_code == 200:
            return True
        log.warning(f"Health check failed: status={resp.status_code} body={resp.text[:200]}")
        return False
    except Exception as e:
        log.warning(f"Health check error: {e}")
        return False


# ──────────────────── MAIN LOOP ────────────────────

def main():
    if not EC2_INSTANCE_ID:
        log.error("EC2_INSTANCE_ID chưa được set!")
        sys.exit(1)

    log.info(f"Watchdog started - checking {HEALTH_URL} every {CHECK_INTERVAL}s")
    log.info(f"Instance: {EC2_INSTANCE_ID} | Region: {AWS_REGION}")

    fail_count = 0
    last_action_time = 0

    while True:
        if check_health():
            fail_count = 0
        else:
            fail_count += 1
            log.warning(f"Health check FAIL ({fail_count}/{MAX_FAILURES})")

            if fail_count >= MAX_FAILURES:
                elapsed = time.time() - last_action_time
                if elapsed < COOLDOWN:
                    log.info(f"Cooldown còn {int(COOLDOWN - elapsed)}s, chờ...")
                else:
                    log.info("=== Server bị chặn - đang xử lý ===")
                    send_telegram(
                        f"🔴 Crawl API bị chặn!\n"
                        f"Instance: {EC2_INSTANCE_ID}\n"
                        f"Đang terminate và tạo instance mới..."
                    )
                    terminate_self()
                    time.sleep(120)
                    last_action_time = time.time()
                    fail_count = 0

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
