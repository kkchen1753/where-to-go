# 週末不加價 — 住宿價格追蹤工具

每天記錄住宿「平日」與「週六」入住一晚的價格，存進資料庫，累積 4–8 週後拿來計算週末溢價。
產品規劃見 [CLAUDE.md](CLAUDE.md)。

只用 Python 標準函式庫（3.8 以上），不用 `pip install`。

## 開始使用

```bash
cp hotels.example.csv hotels.csv        # 住宿清單，改成你要追蹤的住宿
cp config.example.json config.json      # 選用，不建立就用預設值
python track.py plan                    # 看今天要記錄哪些入住日
```

### 住宿清單 `hotels.csv`

一列是一間住宿的一種房型。同一間要追蹤多種房型就寫多列。

| 欄位 | 說明 |
| --- | --- |
| `hotel_id` | 自訂代號（英數），之後不要改 |
| `name` / `region` | 名稱、地區 |
| `room_type` | 房型。溢價一定要比同一種房型 |
| `source` | 價格來源：`manual` 人工輸入；`demo` 假資料（只用於測試） |
| `source_ref` | 自動抓價時，該來源認得的住宿代號 |
| `url` | 訂房頁網址，會帶進人工填價表方便點開 |
| `rating` / `review_count` | 評分、評論數，之後判斷「優質」門檻用 |

## 每天的流程（人工輸入）

```bash
python track.py template --nights wed,sat   # 產生 input/今天日期.csv
# 用 Excel / Google 試算表打開，填「價格」（含稅總價），沒房就在「無房」填任意字
python track.py import input/2026-10-27.csv
python track.py status                      # 各住宿累積幾天了
```

- 價格可以寫 `2,800`、`NT$2800`，會自動整理。
- 價格和無房都空白的列會略過，所以沒查完也可以先匯入。
- **任何一列有錯，整份都不會匯入**，修好再匯一次就好；同一天重複匯入會覆蓋。
- 人工記錄量很大（10 間 × 8 週 × 6 晚 ≈ 480 筆），建議用 `--nights wed,sat` 只抽週三與週六。

## 設定 `config.json`

| 欄位 | 預設 | 說明 |
| --- | --- | --- |
| `weeks_ahead` | `8` | 追蹤未來幾週的入住日 |
| `nights` | 週日～週四、週六 | 要記錄哪幾晚：`sun mon tue wed thu fri sat` |
| `request_delay_seconds` | `3` | 自動抓價時每次請求間隔 |
| `db_path` / `hotels_csv` / `input_dir` | | 檔案位置 |

## 其他指令

```bash
python track.py fetch                # 自動抓價（source 不是 manual 的住宿）
python track.py export prices.csv    # 匯出全部價格，可貼到試算表或當備份
python -m unittest                   # 跑測試
```

資料庫在 `data/prices.db`，沒有放進 git，請定期 `export` 備份。

## 新增自動抓價來源

在 `tracker/sources.py` 寫一個 `PriceSource` 子類別，實作 `fetch(hotel, checkin)` 回傳 `Quote`，
再登記到 `SOURCES`。單筆失敗會記錄並跳過，不影響其他住宿。
