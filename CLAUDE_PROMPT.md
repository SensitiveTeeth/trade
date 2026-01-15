# Danelfin + Futu OpenAPI 自動化交易系統 - Claude Prompt

## 專案背景

你正在協助開發一個自動化股票交易系統，該系統整合：
- **Danelfin API**: 提供 AI 評分（1-10分）作為買賣訊號來源
- **富途 OpenAPI**: 執行美股交易（支援模擬/真實交易）
- **Telegram Bot**: 發送即時交易通知
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
                    └─────────────────────────┘
```

## 交易策略規則

### 買入條件
- AI Score = 10（強力買入訊號）
- 該股票尚未持有
- 持倉數量未達上限（預設 MAX_POSITIONS = 8）

### 賣出條件
- AI Score < 7（評分下降）
- 達到目標價（止盈，通常設定 10-20% 漲幅）
- 跌破止損價（止損）

### 監控股票清單
預設追蹤銀行股：`["BAC", "FHN", "OZK", "NBTB", "SSB"]`

## 關鍵 API 規格

### Danelfin API
- 端點：`https://apirest.danelfin.com/ranking`
- 參數：`ticker`, `date`
- 驗證：Header `x-api-key`
- 回傳：`aiscore`, `fundamental`, `technical`, `sentiment`, `target_price`

### 富途 OpenAPI
- 安裝：`pip install futu-api`
- 需先啟動 FutuOpenD 網關
- 模擬交易：`trd_env=TrdEnv.SIMULATE`
- 真實交易：`trd_env=TrdEnv.REAL`

### Telegram Bot API
- 端點：`https://api.telegram.org/bot{TOKEN}/sendMessage`
- 參數：`chat_id`, `text`, `parse_mode`

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
    ai_score INTEGER,
    reason VARCHAR(100)
);

-- 持倉記錄表
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    quantity INTEGER NOT NULL,
    avg_cost DECIMAL(10,2) NOT NULL,
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
    UNIQUE(date, ticker)
);
```

## 執行環境

### 推薦部署方案
- **平台**：雲端 VPS（香港機房，低延遲連接富途伺服器）
- **系統**：Ubuntu 22.04
- **配置**：2 核 CPU / 2 GB RAM / 40 GB SSD
- **供應商**：阿里雲、騰訊雲、AWS Lightsail、Vultr

### 排程頻率
| 檢查項目 | 頻率 | 說明 |
|----------|------|------|
| Danelfin AI Score | 每日 1 次 | 開盤前檢查 |
| 股價（止盈止損） | 每 5-15 分鐘 | 盤中監控 |

## 美股交易時段（香港時間）

| 時段 | 美國時間 | 香港時間（夏令） |
|------|----------|------------------|
| 盤前 | 04:00-09:30 | 16:00-21:30 |
| 正常盤 | 09:30-16:00 | 21:30-04:00 |
| 盤後 | 16:00-20:00 | 04:00-08:00 |

**注意**：模擬交易僅支援正常交易時段，不支援盤前盤後。

## 開發注意事項

1. **API 金鑰安全**：所有 API 金鑰應存放於環境變數或 `.env` 檔案，勿硬編碼
2. **錯誤處理**：所有 API 呼叫需有 try-except 包裝與重試機制
3. **日誌記錄**：所有交易動作需記錄到資料庫與 Telegram
4. **模擬優先**：新功能先在模擬環境測試 1-2 個月
5. **風險控制**：
   - 單一持倉不超過總資金 20%
   - 設定每日最大虧損限制
   - 實現止損止盈自動化

## 預估交易頻率

- 每月交易次數：5-10 次
- 平均持倉週期：1-3 個月
- 交易風格：波段交易（Swing Trading）

## 程式碼風格要求

- 語言：Python 3.10+
- 套件管理：requirements.txt 或 pyproject.toml
- 程式碼格式：遵循 PEP 8
- 類型提示：使用 type hints
- 文檔字串：使用 Google style docstrings

## 待實現功能清單

- [ ] Danelfin API 整合
- [ ] 富途 OpenAPI 交易模組
- [ ] Telegram 通知機制
- [ ] SQLite 資料庫操作
- [ ] 排程任務管理（schedule 或 APScheduler）
- [ ] 止盈止損監控
- [ ] 績效報表生成
- [ ] 錯誤重試與告警機制
