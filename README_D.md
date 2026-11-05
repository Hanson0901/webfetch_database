# 組員 D 使用說明（新聞、部落格、旅遊與飲食媒體）

這份說明介紹 D 負責的所有檔案在做什麼、怎麼執行、跑完會產生什麼。

---

## 一、D 的檔案總覽

```
webfetch_database-main/
├── README_D.md                    ← 本說明
├── crawler/
│   ├── crawler.py                 公版爬蟲（組員的，D 沒有修改）
│   ├── crawler_member_D.py        D 的爬蟲：抓網頁、清理正文、存圖片
│   ├── analyze_member_D.py        D 的分析：關鍵字、主題、重複比對、查核報告
│   └── fact_check_D.json          D 的人工查核紀錄（媒體說法 vs 官方資料）
├── output/
│   └── D/                         D 的爬取與分析成果（程式自動產生）
└── report/
    ├── report.md                  全組共用報告（待整合）
    ├── report_D.md                D 的實作報告
    └── screenshots/               清理前後對照截圖（任務 2）
```

---

## 二、程式檔案

### 1. `crawler/crawler_member_D.py`（爬蟲）

依 README 規定「複製公版 crawler.py，只修改自己負責的網站規則」製作。輸入方式、編號、輸出格式都和公版相同，可以和 A、B、C 的資料合併。

**做的事情：**

1. 讀取你輸入的網址，檢查 robots.txt 是否允許。
2. 依網址的網域找出對應的網站規則（共 8 套，清單寫在檔案最上面的註解）。
3. 只取正文區塊，移除廣告、選單、推薦文章、優惠券、分享按鈕等雜訊。
4. 抓出標題、作者、發表日期。
5. 下載正文內的圖片（包含延遲載入的圖），排除 Logo、小圖示、表情符號，並記錄圖說與「圖片來源」標示。
6. 把結果存成 Markdown 文章、圖片檔與 `index.jsonl`。

**和公版不同的地方：** 只改了 README 允許修改的函式（`extract_content`、`image_candidates`、`save_image`、`crawl_web`、`extension_candidates`、`write_report`），修改原因寫在檔案開頭。

### 2. `crawler/analyze_member_D.py`（分析）

讀取 `output/D/index.jsonl`，完成作業任務 6「資料整理及來源查證」：

- 每篇文章產生 3–5 個關鍵字
- 主題分類：自然景觀、歷史文化、地方產業、觀光景點、美食飲食
- 偵測不同媒體間的重複段落，列出同一景點在不同媒體的說法
- 自動挑出值得查證的句子（含年份、數字、「唯一」「第一」等）
- 整合人工查核結果，產生知識資料

只使用 Python 內建套件，不需另外安裝。

### 3. `crawler/fact_check_D.json`（人工查核紀錄）

5 筆查核資料，每筆包含：媒體原文敘述、官方資料來源與網址、判定結果（符合／部分符合／不符）與說明。
要新增查核時，照同樣格式加一筆，再執行一次 `analyze_member_D.py` 即可。

---

## 三、怎麼執行

結果固定存到專案根目錄的 `output\D`，不論在哪個資料夾執行、或在 VS Code 按 ▶ 都一樣。

### 第一次：安裝套件

```
python -m pip install -r requirements.txt
```

### 爬蟲：互動模式（和公版一樣）

```
python crawler\crawler_member_D.py
```

依序輸入：組員編號 `D` → 網址 → 來源種類（直接按 Enter 為 `seed`）→ 備註 → 是否繼續。輸入 `quit` 結束。編號自動產生 `D-001`、`D-002`…

### 爬蟲：單筆模式

```
python crawler\crawler_member_D.py --member D --url "https://supertaste.tvbs.com.tw/travel/348994"
```

### 編號規則

D 的資料一律用 `D-001`、`D-002`…（程式自動接續編號）。原始網址對應的 `urls.csv` 編號（page_xxx）記在 `notes` 欄，
完整對照表在 `output/D/id_mapping.json`：

| D 編號 | urls.csv | 網站 |
| --- | --- | --- |
| D-001 | page_003 | 微笑台灣 |
| D-002 | page_004 | 客庄小旅行（達人帶路） |
| D-003 | page_009 | 方格子 |
| D-004 | page_014 | 我的旅圖中 |
| D-005 | page_017 | 客庄小旅行（店家） |
| D-006 | page_021 | TVBS 食尚玩家 |
| D-007 | page_022 | 痞客邦 |
| D-008 | page_023 | Yahoo 奇摩新聞 |
| D-009 | page_025 | 旅聯網 |
| D-010 | page_029 | 方格子 |
| D-011 | （extra） | NOWnews 今日新聞 |
| D-012 | （internal，父頁面 D-007） | 痞客邦 白沙岬燈塔文章 |

### 分析

```
python crawler\analyze_member_D.py
```

### 來源種類怎麼選

| 種類 | 什麼時候用 |
| --- | --- |
| `seed` | 老師提供的網址（D 的 10 個網址都是） |
| `internal` | 從某篇文章裡找到的相關連結，要另外輸入父頁面 id |
| `extra` | 自己搜尋找到的網站，備註寫搜尋關鍵字 |

---

## 四、執行結果（`output/D/`）

### 爬蟲產生的檔案

| 檔案／資料夾 | 內容 |
| --- | --- |
| `index.jsonl` | 每個網址一筆完整資料：標題、作者、日期、正文、圖片、連結、爬取狀態。四組合併時用的就是這個 |
| `crawl_report.csv` | 逐網址的爬取紀錄表，可用 Excel 開啟：狀態、失敗原因、字數、圖片數 |
| `summary.json` | 本次執行的統計：成功、失敗、無法存取各幾筆 |
| `articles/` | 每篇清理後的文章（Markdown），圖片放在原本的位置，文末附圖片清單與正文內連結 |
| `images/` | 下載的圖片，檔名如 `page_021_image_01.jpg` |
| `videos/` | 影片用資料夾（D 沒有影片，保持空的） |

`summary.json` 的欄位：

| 欄位 | 意思 |
| --- | --- |
| `current_run_success` | 這次成功幾筆 |
| `current_run_failed` | 程式或網路問題失敗幾筆（可重試） |
| `current_run_unavailable` | 網站拒絕存取幾筆（403、404、robots.txt 禁止等，依規定不繞過） |
| `replaced_records` | 編號重複、用新資料取代幾筆 |
| `new_records` | 新增幾筆 |
| `total_records_after_merge` | 合併後總共幾筆 |
| `extension_records` | 產生幾個延伸連結（`ext_001`…） |

### 分析產生的檔案（`output/D/analysis/` 與 `knowledge_D.jsonl`）

| 檔案 | 內容 |
| --- | --- |
| `analysis/crawl_summary_D.md` | 10 個網址的結果總表，可直接貼進報告 |
| `analysis/keywords_topics.csv` | 每篇的關鍵字與主題分類 |
| `analysis/duplicates_D.md` | 重複段落比對、同一景點在不同媒體的說法 |
| `analysis/duplicates.json` | 同上，程式用格式 |
| `analysis/claims_candidates.csv` | 程式挑出的待查核句子 |
| `analysis/fact_check_D.md` | 人工查核結果：媒體原文 vs 官方資料 |
| `knowledge_D.jsonl` | 整合後的知識資料，媒體內容（`media_content`）與查核結果（`verification`）分開存放 |

---

## 五、報告相關（`report/`）

| 檔案 | 內容 |
| --- | --- |
| `report_D.md` | D 的實作報告：各網站清理規則、圖片處理、延伸探索、查核結果 |
| `screenshots/` | 放原始網頁截圖，與 `articles/` 的清理結果對照（任務 2 要求至少 3 種網站） |
| `report.md` | 全組共用的總報告，最後要把 D 的重點整合進去 |

---

## 六、常見問題

| 狀況 | 原因與解法 |
| --- | --- |
| `No module named 'requests'` | 目前的 Python 沒裝套件。執行 `python -m pip install -r requirements.txt`，或改用已安裝好的 `py -3.10` |
| `No module named 'crawler'` | 資料夾裡少了公版 `crawler.py`（舊版才會），請用完整專案資料夾 |
| 結果跑到 `crawler\output` | 舊版才會這樣；現在的版本固定存到專案根目錄的 `output\D` |
| 狀態 `unavailable`、原因 403 | 網站拒絕程式存取。依作業規定保留紀錄、不繞過，報告中說明原因 |
| 正文出現廣告或推薦文章 | 該網站的規則需要調整，修改 `crawler_member_D.py` 裡 `SITE_RULES` 的 `noise` 清單 |
| 老師給沒見過的網址 | 程式仍可執行，會用通用方法；`crawl_report.csv` 的 `extraction_method` 會顯示 `trafilatura (no site rule matched)` |
