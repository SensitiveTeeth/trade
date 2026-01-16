# Danelfin + Futu OpenAPI 自動化交易系統 - Claude Prompt

## 專案背景

這是一個自動化美股交易系統，整合：
- **Danelfin API**: 提供 AI 評分（1-10分）作為買賣訊號來源
- **富途 OpenAPI**: 執行美股交易（支援模擬/真實交易）
- **Telegram Bot**: 發送即時交易通知（含 429 rate limit 處理）
- **SQLite**: 儲存交易記錄與持倉資料

## 技術架構

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Danelfin API   │────▶│   交易程式      │────▶│  富途 OpenAPI   │
│  (訊號來源)     │     │   (決策引擎)    │     │   (執行交易)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
    每日 AI 評分           判斷買賣條件             下單/平倉
                                │
                                ▼
                    ┌─────────────────────┐
                    │  Telegram + SQLite  │
                    │  (通知 + 記錄)      │
                    └─────────────────────┘
```

## 部署架構 (Docker)

```
┌──────────────────────────────────────────────────────┐
│  EC2 Instance                                        │
│  ┌─────────────────────────────────────────────────┐ │
│  │  Docker (共享網路命名空間)                       │ │
│  │  ┌─────────────────┐  ┌─────────────────┐       │ │
│  │  │   futuopend     │◀─│    trading      │       │ │
│  │  │   (網關)        │  │    (交易程式)   │       │ │
│  │  │   Port 11111    │  │  127.0.0.1連接  │       │ │
│  │  └─────────────────┘  └─────────────────┘       │ │
│  └─────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

**重要**：trading 容器使用 `network_mode: "service:futuopend"` 共享網路命名空間，避免跨網通信加密要求。

## 交易策略規則

### 買入條件
- AI Score = 10（從 Danelfin API 批量查詢 AI Score 10 的所有股票）
- 該股票尚未持有
- 持倉數量未達上限（預設 MAX_POSITIONS = 8）

### 賣出條件
- AI Score < 7（評分下降）
- 達到目標價（止盈 +15%）
- 跌破止損價（止損 -8%）

### 股票來源
系統每日自動從 Danelfin API 批量查詢所有 AI Score = 10 的美股（通常 30-40 支）。

## 關鍵 API 規格

### Danelfin API
- 端點：`https://apirest.danelfin.com/ranking`
- 單一股票查詢：`?ticker=BAC`
- 批量查詢（AI Score 10）：`?date=2026-01-16&aiscore=10`
- 驗證：Header `x-api-key`
- 回傳：`aiscore`, `fundamental`, `technical`, `sentiment`, `target_price`

### 富途 OpenAPI
- 安裝：`pip install futu-api`
- 需先啟動 FutuOpenD 網關
- 模擬交易：`trd_env=TrdEnv.SIMULATE`（需在 Moomoo App 開通美股模擬交易）
- 真實交易：`trd_env=TrdEnv.REAL`
- 市場篩選：`filter_trdmarket=TrdMarket.US`

### Telegram Bot API
- 端點：`https://api.telegram.org/bot{TOKEN}/sendMessage`
- 參數：`chat_id`, `text`, `parse_mode`
- Rate Limit：最小間隔 0.5 秒，429 錯誤自動重試

## 資料庫結構

```sql
-- 交易記錄表
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    ticker VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL,  -- BUY / SELL
    quantity INTEGER NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    total_amount DECIMAL(12,2) NOT NULL,
    ai_score INTEGER,
    reason VARCHAR(100),
    order_id VARCHAR(50),
    status VARCHAR(20) DEFAULT 'FILLED'
);

-- 持倉記錄表
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    quantity INTEGER NOT NULL,
    avg_cost DECIMAL(10,2) NOT NULL,
    entry_date DATETIME,
    entry_ai_score INTEGER,
    target_price DECIMAL(10,2),
    stop_loss DECIMAL(10,2)
);

-- AI Score 歷史記錄表
CREATE TABLE ai_score_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    ai_score INTEGER,
    fundamental_score INTEGER,
    technical_score INTEGER,
    sentiment_score INTEGER,
    target_price DECIMAL(10,2),
    UNIQUE(date, ticker)
);
```

## 執行環境

### 部署方案
- **平台**：AWS EC2 (Amazon Linux 2023)
- **配置**：t3.micro / t3.small
- **容器化**：Docker Compose
- **時區**：Asia/Hong_Kong

### 排程頻率
| 檢查項目 | 頻率 | 時間 (HKT) |
|----------|------|------------|
| Danelfin AI Score 10 批量查詢 | 每日 + 啟動時 | 21:00 |
| 股價監控（止盈止損） | 每 1 分鐘 | 盤中 |
| 每日總結 | 每日 | 05:00 |

### 啟動時同步
- 程式啟動時自動從 Futu API 獲取當前持倉
- 與 SQLite 資料庫比對，自動同步差異：
  - 新增遺漏的持倉
  - 刪除過時的持倉
  - 更新數量/成本差異

## 美股交易時段（香港時間）

| 時段 | 美國時間 | 香港時間（夏令） | 香港時間（冬令） |
|------|----------|------------------|------------------|
| 盤前 | 04:00-09:30 | 16:00-21:30 | 17:00-22:30 |
| 正常盤 | 09:30-16:00 | 21:30-04:00 | 22:30-05:00 |
| 盤後 | 16:00-20:00 | 04:00-08:00 | 05:00-09:00 |

**注意**：模擬交易僅支援正常交易時段，不支援盤前盤後。

## 專案結構

```
trade/
├── Dockerfile                    # Trading 程式映像
├── docker-compose.yml            # 容器編排
├── .env                          # 環境變數（API keys）
├── requirements.txt              # Python 依賴
├── futuopend/
│   ├── Dockerfile                # FutuOpenD 映像
│   └── FutuOpenD.xml             # FutuOpenD 配置
└── src/
    ├── main.py                   # 主程式入口
    ├── config.py                 # 配置管理
    ├── database.py               # SQLite 操作
    ├── danelfin.py               # Danelfin API 客戶端
    ├── futu_trader.py            # 富途交易模組
    ├── telegram_bot.py           # Telegram 通知
    └── strategy.py               # 交易策略邏輯
```

## 開發注意事項

1. **API 金鑰安全**：所有 API 金鑰存放於 `.env` 檔案，勿提交至 Git
2. **錯誤處理**：所有 API 呼叫需有 try-except 包裝與重試機制
3. **日誌記錄**：所有交易動作記錄到資料庫與 Telegram
4. **模擬優先**：設定 `IS_SIMULATION=true` 進行測試
5. **風險控制**：
   - 持倉數量上限（MAX_POSITIONS = 8）
   - 止盈 +15% / 止損 -8%
   - 訂單狀態輪詢確認成交

## 常用命令

```bash
# 啟動服務
docker compose up -d

# 查看日誌
docker compose logs -f

# 查看 FutuOpenD 日誌
docker compose logs -f futuopend

# 重啟服務
docker compose restart

# 停止服務
docker compose down

# 更新 trading 容器（保持 FutuOpenD 運行）
git pull && docker compose build trading && docker compose up -d --no-deps trading

# FutuOpenD 需要重新驗證時
docker attach futuopend
# 輸入：input_phone_verify_code -code=XXXXXX
# 分離：Ctrl+P Ctrl+Q
```

## 程式碼風格要求

- 語言：Python 3.10+
- 套件管理：requirements.txt
- 程式碼格式：遵循 PEP 8
- 類型提示：使用 type hints
- 文檔字串：使用 Google style docstrings

## 已實現功能

- [x] Danelfin API 整合（單一查詢 + 批量查詢）
- [x] 富途 OpenAPI 交易模組（模擬/真實交易）
- [x] Telegram 通知機制（含 429 rate limit 處理）
- [x] SQLite 資料庫操作
- [x] 排程任務管理（APScheduler）
- [x] 止盈止損監控
- [x] 啟動時持倉同步
- [x] Docker 容器化部署

## 待實現功能

- [ ] GitHub Actions CI/CD 自動部署
- [ ] 舊 Docker 映像自動清理
- [ ] 績效報表生成
