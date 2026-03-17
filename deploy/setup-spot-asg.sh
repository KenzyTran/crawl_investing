#!/bin/bash
# Tạo Launch Template + Auto Scaling Group cho spot instance
# Chạy script này từ máy local (cần AWS CLI đã cấu hình)
set -e

# ──────── CẤU HÌNH - SỬA TRƯỚC KHI CHẠY ────────
REGION="ap-southeast-1"
AMI_ID="ami-0c02fb55956c7d316"           # Amazon Linux 2023 (kiểm tra AMI mới nhất cho region)
INSTANCE_TYPE="t3.micro"
KEY_NAME="your-key-pair"                  # Tên key pair SSH
SECURITY_GROUP_ID="sg-xxxxxxxxx"          # Security group (mở port 5000)
SUBNET_IDS="subnet-xxx,subnet-yyy"       # Subnet IDs (ít nhất 2 AZ)
IAM_INSTANCE_PROFILE="CrawlApiRole"      # IAM role name (xem bên dưới)

LT_NAME="crawl-api-lt"
ASG_NAME="crawl-api-asg"

# ──────── Tạo Launch Template ────────
echo "=== Tạo Launch Template ==="
USER_DATA=$(base64 -w 0 deploy/user-data.sh)

aws ec2 create-launch-template \
    --region "$REGION" \
    --launch-template-name "$LT_NAME" \
    --launch-template-data "{
        \"ImageId\": \"$AMI_ID\",
        \"InstanceType\": \"$INSTANCE_TYPE\",
        \"KeyName\": \"$KEY_NAME\",
        \"SecurityGroupIds\": [\"$SECURITY_GROUP_ID\"],
        \"IamInstanceProfile\": {\"Name\": \"$IAM_INSTANCE_PROFILE\"},
        \"UserData\": \"$USER_DATA\",
        \"InstanceMarketOptions\": {
            \"MarketType\": \"spot\",
            \"SpotOptions\": {
                \"SpotInstanceType\": \"one-time\",
                \"InstanceInterruptionBehavior\": \"terminate\"
            }
        },
        \"TagSpecifications\": [{
            \"ResourceType\": \"instance\",
            \"Tags\": [{\"Key\": \"Name\", \"Value\": \"crawl-api-spot\"}]
        }]
    }"

echo "✓ Launch Template created: $LT_NAME"

# ──────── Tạo Auto Scaling Group ────────
echo "=== Tạo Auto Scaling Group ==="

aws autoscaling create-auto-scaling-group \
    --region "$REGION" \
    --auto-scaling-group-name "$ASG_NAME" \
    --launch-template "LaunchTemplateName=$LT_NAME,Version=\$Latest" \
    --min-size 1 \
    --max-size 1 \
    --desired-capacity 1 \
    --vpc-zone-identifier "$SUBNET_IDS" \
    --health-check-type EC2 \
    --health-check-grace-period 300 \
    --tags "Key=Project,Value=crawl-api,PropagateAtLaunch=true"

echo "✓ Auto Scaling Group created: $ASG_NAME"

echo ""
echo "=== DONE ==="
echo "ASG sẽ tự launch 1 spot instance."
echo "Khi bị chặn: watchdog terminate instance → ASG launch mới → IP mới → n8n tự cập nhật"
echo ""
echo "Kiểm tra: aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names $ASG_NAME --region $REGION"
