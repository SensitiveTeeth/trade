# Danelfin + Futu Automated Trading System

Automated stock trading system based on Danelfin AI scores and Futu OpenAPI.

## Architecture

```
Danelfin API --> Trading Program --> Futu OpenAPI
(AI Score)        (Python)          (Execute Trades)
                      |
                      v
              Telegram + SQLite
              (Notify + Record)
```

## Quick Start

### 1. Create AWS EC2

- **Instance Type**: t3.small
- **Region**: ap-east-1 (Hong Kong)
- **AMI**: Ubuntu 22.04
- **User Data**: Copy contents of `ec2-user-data-docker.sh`

### 2. Configure Security Group

Open the following ports:
| Port | Purpose |
|------|---------|
| 22   | SSH     |

### 3. SSH into EC2

```bash
ssh ubuntu@<EC2-PUBLIC-IP>
```

### 4. Wait for Setup to Complete

First boot requires 2-3 minutes. Check progress:
```bash
tail -f /var/log/user-data.log
```

Verify Docker is installed:
```bash
docker --version
```

### 5. Configure Environment Variables

The repo is already cloned. Edit the config:
```bash
vim ~/trading/.env
```

Fill in the following:
- `DANELFIN_API_KEY` - Danelfin API key
- `TELEGRAM_BOT_TOKEN` - Telegram Bot Token
- `TELEGRAM_CHAT_ID` - Telegram Chat ID

### 6. Configure FutuOpenD

```bash
vim ~/trading/futuopend/FutuOpenD.xml
```

Fill in the following:
- `login_account` - Futu account
- `login_pwd` - Plain text password (or use `login_pwd_md5`)

#### How to Get Password MD5 (Optional)

If you prefer MD5 password over plain text:

```bash
# macOS
echo -n "your_password" | md5

# Linux
echo -n "your_password" | md5sum | awk '{print $1}'

# Python
python3 -c "import hashlib; print(hashlib.md5('your_password'.encode()).hexdigest())"
```

Enter the 32-character output into `login_pwd_md5`.

### 7. Start FutuOpenD and Enter Verification Code

FutuOpenD requires SMS verification code on first login (per IP/device). This is a security requirement by Futu and cannot be bypassed.

```bash
# Start FutuOpenD first
cd ~/trading && docker compose up -d futuopend

# Attach to container to enter verification code
docker attach futuopend
```

Wait for SMS verification code, then enter:
```
input_phone_verify_code -code=XXXXXX
```

After successful login (you'll see `登录成功`), detach from container:
```
Press Ctrl+P then Ctrl+Q
```

Verify FutuOpenD is healthy:
```bash
docker compose ps
# Should show: futuopend ... (healthy)
```

### 8. Start Trading Service

```bash
docker compose up -d
```

## Common Commands

```bash
# Check service status
docker compose ps

# View logs
docker compose logs -f

# View specific service logs
docker compose logs -f trading
docker compose logs -f futuopend

# Restart services
docker compose restart

# Stop services
docker compose down

# Update trading service only (keeps FutuOpenD running)
git pull
docker compose build trading
docker compose up -d --no-deps trading

# Update all services (will restart FutuOpenD, may need re-verification)
git pull
docker compose up -d --build
```

## Project Structure

```
trade/
├── Dockerfile                    # Trading program image
├── docker-compose.yml            # Service orchestration
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment variables template
├── ec2-user-data-docker.sh       # EC2 User Data script (full setup)
├── futuopend/
│   ├── Dockerfile                # FutuOpenD image
│   └── FutuOpenD.xml.example     # FutuOpenD config template
├── src/                          # Trading program source code
│   ├── main.py                   # Entry point with scheduler
│   ├── config.py                 # Configuration
│   ├── database.py               # SQLite operations
│   ├── danelfin.py               # Danelfin API client
│   ├── futu_trader.py            # Futu OpenAPI trading
│   ├── telegram_bot.py           # Telegram notifications
│   └── strategy.py               # Trading strategy logic
├── data/                         # Database files
└── logs/                         # Log files
```

## Trading Strategy

### Buy/Sell Rules

| Condition | Action |
|-----------|--------|
| AI Score = 10 (from Danelfin Top Stocks) | Buy |
| Holding position with AI Score < 7 | Sell |
| +15% from entry | Take profit |
| -8% from entry | Stop loss |

### How It Works

1. **Daily Check (21:00 HKT / on startup)**:
   - Fetches all US stocks with AI Score = 10 from Danelfin API (typically 30-40 stocks)
   - Buys any new AI Score 10 stocks (up to max positions)
   - Checks current holdings - sells if AI Score dropped below 7

2. **Price Check (every 1 minute)**:
   - Monitors stop loss (-8%) and take profit (+15%) for all positions

### Schedule

| Task | Frequency | Time (HKT) |
|------|-----------|------------|
| Danelfin AI Score 10 check | Daily + on startup | 21:00 |
| Price check (stop loss/take profit) | Every 1 minute | During market hours |

## Maintenance

### Clean Up Docker Images

After rebuilding, old images accumulate and consume disk space. Run periodically:

```bash
# Clean unused images, containers, and build cache
docker system prune -a -f

# Check disk usage
docker system df
df -h
```

## Notes

1. **Test with simulation first** - Set `IS_SIMULATION=true` in `.env`
2. **Keep API keys secure** - Do not commit `.env` to Git
3. **Monitor service status** - Regularly check Telegram notifications and logs
4. **Max positions** - Default limit is 8 concurrent positions
5. **FutuOpenD verification code** - Required on first login per IP/device. If EC2 IP changes (e.g., after stop/start), you may need to re-enter verification code. Consider using Elastic IP for stable address.
6. **Re-enter verification code** - If FutuOpenD requires re-verification:
   ```bash
   docker attach futuopend
   # Enter: input_phone_verify_code -code=XXXXXX
   # Detach: Ctrl+P Ctrl+Q
   ```

## TODO

- [ ] GitHub Actions CI/CD for automated deployment
- [ ] Auto cleanup old Docker images after deployment
- [ ] Daily summary notification (scheduled at 05:00 HKT)
