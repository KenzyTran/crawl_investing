"""
Watchdog - Tự động phát hiện server bị chặn và xử lý.

Có 2 chế độ (WATCHDOG_MODE):
- "elastic" (mặc định): Xoay Elastic IP trên cùng instance
- "spot": Terminate instance → ASG tự tạo instance mới với IP mới

Flow:
1. Gọi /health mỗi CHECK_INTERVAL giây
2. Nếu fail liên tiếp MAX_FAILURES lần → coi như bị chặn
3. Tuỳ mode: xoay Elastic IP hoặc terminate instance
4. Cập nhật IP mới lên n8n qua API
"""

import os
import sys
import time
import logging
import requests
import boto3
from botocore.exceptions import ClientError

# ──────────────────── CẤU HÌNH ────────────────────
# Lấy từ biến môi trường, fallback sang giá trị mặc định

CHECK_INTERVAL = int(os.getenv("WATCHDOG_INTERVAL", "60"))        # Kiểm tra mỗi 60s
MAX_FAILURES = int(os.getenv("WATCHDOG_MAX_FAILURES", "3"))       # Fail 3 lần liên tiếp → xoay IP
APP_PORT = int(os.getenv("APP_PORT", "5000"))
HEALTH_URL = f"http://127.0.0.1:{APP_PORT}/health"

# AWS
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-1")
EC2_INSTANCE_ID = os.getenv("EC2_INSTANCE_ID", "")  # Bắt buộc phải set

# n8n (để cập nhật IP mới)
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "")            # VD: https://your-n8n.com
N8N_API_KEY = os.getenv("N8N_API_KEY", "")               # API key của n8n
N8N_VARIABLE_KEY = os.getenv("N8N_VARIABLE_KEY", "CRAWL_SERVER_IP")  # Tên biến trong n8n

# Cooldown sau khi xoay IP (tránh xoay liên tục)
COOLDOWN = int(os.getenv("WATCHDOG_COOLDOWN", "300"))     # 5 phút

# Mode: "elastic" (xoay Elastic IP) hoặc "spot" (terminate instance, ASG tạo mới)
WATCHDOG_MODE = os.getenv("WATCHDOG_MODE", "elastic")

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


def get_current_elastic_ip():
    """Lấy Elastic IP hiện tại đang gắn với instance."""
    resp = ec2.describe_addresses(
        Filters=[{"Name": "instance-id", "Values": [EC2_INSTANCE_ID]}]
    )
    addresses = resp.get("Addresses", [])
    if addresses:
        return addresses[0]["AllocationId"], addresses[0]["PublicIp"]
    return None, None


def get_instance_public_ip():
    """Lấy public IP hiện tại (kể cả không phải Elastic IP)."""
    resp = ec2.describe_instances(InstanceIds=[EC2_INSTANCE_ID])
    instance = resp["Reservations"][0]["Instances"][0]
    return instance.get("PublicIpAddress")


def rotate_elastic_ip():
    """Xoay Elastic IP: allocate mới → associate → release cũ."""
    old_alloc_id, old_ip = get_current_elastic_ip()
    log.info(f"IP hiện tại: {old_ip} (allocation: {old_alloc_id})")

    # Allocate IP mới
    new_alloc = ec2.allocate_address(Domain="vpc")
    new_alloc_id = new_alloc["AllocationId"]
    new_ip = new_alloc["PublicIp"]
    log.info(f"Đã allocate IP mới: {new_ip} ({new_alloc_id})")

    # Associate IP mới với instance
    ec2.associate_address(
        InstanceId=EC2_INSTANCE_ID,
        AllocationId=new_alloc_id,
        AllowReassociation=True,
    )
    log.info(f"Đã associate {new_ip} với instance {EC2_INSTANCE_ID}")

    # Release IP cũ
    if old_alloc_id:
        try:
            ec2.release_address(AllocationId=old_alloc_id)
            log.info(f"Đã release IP cũ: {old_ip} ({old_alloc_id})")
        except ClientError as e:
            log.warning(f"Không release được IP cũ: {e}")

    return new_ip


def terminate_self():
    """Terminate instance hiện tại (dùng cho spot mode - ASG sẽ tạo mới)."""
    log.info(f"TERMINATING instance {EC2_INSTANCE_ID} - ASG sẽ launch instance mới...")
    ec2.terminate_instances(InstanceIds=[EC2_INSTANCE_ID])


# ──────────────────── N8N HELPERS ────────────────────

def update_n8n_variable(new_ip):
    """Cập nhật biến trong n8n qua API với IP mới."""
    if not N8N_BASE_URL or not N8N_API_KEY:
        log.warning("Chưa cấu hình N8N_BASE_URL hoặc N8N_API_KEY, bỏ qua cập nhật n8n")
        return False

    headers = {"X-N8N-API-KEY": N8N_API_KEY, "Content-Type": "application/json"}
    base = N8N_BASE_URL.rstrip("/")
    value = f"http://{new_ip}:{APP_PORT}"

    # Thử lấy variable hiện tại
    try:
        resp = requests.get(f"{base}/api/v1/variables", headers=headers, timeout=10)
        resp.raise_for_status()
        variables = resp.json().get("data", resp.json()) if isinstance(resp.json(), dict) else resp.json()

        existing = None
        for v in variables:
            if v.get("key") == N8N_VARIABLE_KEY:
                existing = v
                break

        if existing:
            # Update variable
            var_id = existing["id"]
            resp = requests.patch(
                f"{base}/api/v1/variables/{var_id}",
                headers=headers,
                json={"key": N8N_VARIABLE_KEY, "value": value},
                timeout=10,
            )
            resp.raise_for_status()
            log.info(f"Đã cập nhật biến n8n '{N8N_VARIABLE_KEY}' = {value}")
        else:
            # Tạo variable mới
            resp = requests.post(
                f"{base}/api/v1/variables",
                headers=headers,
                json={"key": N8N_VARIABLE_KEY, "value": value},
                timeout=10,
            )
            resp.raise_for_status()
            log.info(f"Đã tạo biến n8n mới '{N8N_VARIABLE_KEY}' = {value}")

        return True
    except Exception as e:
        log.error(f"Lỗi cập nhật n8n: {e}")
        return False


# ──────────────────── APP HELPERS ────────────────────

def restart_app():
    """Restart crawl-api service."""
    log.info("Đang restart crawl-api...")
    os.system("systemctl restart crawl-api")
    time.sleep(5)  # Chờ app khởi động


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
        log.error("EC2_INSTANCE_ID chưa được set! Export biến môi trường trước khi chạy.")
        sys.exit(1)

    log.info(f"Watchdog started - checking {HEALTH_URL} every {CHECK_INTERVAL}s")
    log.info(f"Instance: {EC2_INSTANCE_ID} | Region: {AWS_REGION}")

    fail_count = 0
    last_rotate_time = 0

    while True:
        if check_health():
            fail_count = 0
        else:
            fail_count += 1
            log.warning(f"Health check FAIL ({fail_count}/{MAX_FAILURES})")

            if fail_count >= MAX_FAILURES:
                elapsed = time.time() - last_rotate_time
                if elapsed < COOLDOWN:
                    log.info(f"Cooldown còn {int(COOLDOWN - elapsed)}s, chờ...")
                else:
                    log.info(f"=== BẮT ĐẦU XỬ LÝ (mode={WATCHDOG_MODE}) ===")
                    try:
                        if WATCHDOG_MODE == "spot":
                            # Spot mode: terminate → ASG launch mới → user-data cập nhật n8n
                            terminate_self()
                            # Script sẽ dừng khi instance bị terminate
                            time.sleep(120)
                        else:
                            # Elastic mode: xoay IP trên cùng instance
                            new_ip = rotate_elastic_ip()
                            restart_app()
                            update_n8n_variable(new_ip)
                            log.info(f"=== HOÀN TẤT - IP mới: {new_ip} ===")
                        last_rotate_time = time.time()
                        fail_count = 0
                    except Exception as e:
                        log.error(f"Lỗi xử lý: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
