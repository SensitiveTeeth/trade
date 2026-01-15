#!/bin/bash
# EC2 User Data Script - Full Setup
# Install Docker + Clone repo + Prepare config files

set -e
exec > /var/log/user-data.log 2>&1

REPO_URL="https://github.com/SensitiveTeeth/trade.git"
TRADING_DIR=/home/ubuntu/trading

echo "=== Installing Docker ==="

# Install Docker
apt-get update
apt-get install -y ca-certificates curl gnupg git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Allow ubuntu user to run docker
usermod -aG docker ubuntu

echo "=== Cloning Repository ==="

# Clone repo with error handling
mkdir -p $TRADING_DIR
if ! git clone $REPO_URL $TRADING_DIR; then
    echo "ERROR: Failed to clone repository"
    exit 1
fi

# Prepare config files
cd $TRADING_DIR
cp .env.example .env
cp futuopend/FutuOpenD.xml.example futuopend/FutuOpenD.xml

# Set ownership
chown -R ubuntu:ubuntu $TRADING_DIR

echo "=== Setup Complete ==="
echo ""
echo "Next steps (SSH in and run):"
echo "1. Edit .env:"
echo "   nano ~/trading/.env"
echo "   - DANELFIN_API_KEY"
echo "   - TELEGRAM_BOT_TOKEN"
echo "   - TELEGRAM_CHAT_ID"
echo ""
echo "2. Edit FutuOpenD.xml:"
echo "   nano ~/trading/futuopend/FutuOpenD.xml"
echo "   - login_account"
echo "   - login_pwd"
echo ""
echo "3. Start services:"
echo "   cd ~/trading && docker compose up -d"
