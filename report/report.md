# 桃園市觀音區地方知識爬蟲 — A 組（維基百科／歷史地理／文化知識）

> 組別：member-A（A 組，7 個種子網址）
> 主題：桃園市觀音區地方知識；可重複執行的多媒體爬蟲
> 程式：`crawler/crawler_member_A.py`（單檔，僅標準函式庫 + lxml + Pillow；headless Chrome 為選用增強）
> 資料時間：2026-11-05（Asia/Taipei）

## 1. 摘要

| 項目 | 結果 |
| --- | --- |
| 種子網址 | 7（`urls_member_A.csv`） |
| 一層延伸頁 | 13（原規劃 14，1 個與既有頁重複自動跳過） |
| 處理頁面總數 | **20** |
| 狀態 | success 20／partial 0／failed 0 |
| 擷取正文 | 43,497 字（清理後純文字，不含導覽／頁尾） |
| 保存圖片 | 51 張（JPEG，全部經 Pillow 驗證尺寸、sha256 去重） |
| 影片 | 0（20 頁皆未偵測到 video／audio／iframe 播放器，如實記錄，未以推測代替） |
| 跨頁重複 | 比較 190 對，最高相似度未達 0.55 → 無重複文章（`output/duplicates.json`） |
| 對照截圖 | 4 組站型（維基／國家文化記憶庫／政府機關／前端渲染 SPA），共 12 張 JPG |

## 2. 範圍與分工

A 組負責「維基百科／歷史地理／文化知識」7 個來源（`urls_member_A.csv` 的 page_001、010、015、016、020、028、031），
每個來源再往下抓 **一層** 延伸頁（同站或官方關聯站），檔名規則 `A_page_xxx_ext_01`。
為避免四人同一個 repo 撞名，本組**所有產出**（JSONL 的 `id`、文章／圖片／原始 HTML 檔名、截圖）一律加 `A_` 前綴；`urls_*.csv` 仍保留原始 page_xxx 作為種子定義。

| 種子 | 標題 | 站別 | 延伸頁 1 | 延伸頁 2 |
| --- | --- | --- | --- | --- |
| A_page_001 | 觀音區 | 維基百科 | 觀音區戶政事務所－歷史沿革 | 水務局－河川管理及維護 |
| A_page_010 | 甘泉寺（桃園市） | 維基百科 | 桃園觀光導覽網－甘泉寺 | 觀音區公所－本所沿革 |
| A_page_015 | 觀音坑溪 | 維基百科 | 維基百科－淡水河 | 維基百科－觀音山（新北市） |
| A_page_016 | 大堀溪 | 維基百科 | 水務局－大堀溪 | （水務局 10870 與 A_page_001_ext_02 同址，去重跳過） |
| A_page_020 | 大潭發電廠 | 維基百科 | 台電月刊－大潭電廠報導 | 經濟部能源署－大潭火力發電廠 |
| A_page_028 | 石門水庫移民聚落－觀音草漯移民新村 | 文化部國家文化記憶庫 | 國家文化記憶庫－移民新村牌樓 | 桃園市文化局－文史旅行手冊 |
| A_page_031 | 原住民族文獻 第59期 | 原民會《原住民族文獻》 | 桃園市新聞處－卡拉社專書 | 原住民族文獻 第58期 |

延伸頁的選擇規則（程式內 `EXT` 字典明列，非執行時亂猜）：同一主題的官方頁面優先（戶政、水務局、區公所、文化局、能源署、台電），
其次為同站上下期／相鄰條目。所有延伸網址皆人工先行確認可讀取後寫入程式，確保可重現。

## 3. 執行方式（可重現）

```bash
export PYTHONPATH=/Users/hanson0901/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/lib/python3.12/site-packages
/Users/hanson0901/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/bin/python3 \
  crawler/crawler_member_A.py --delay 1.2
```

常用選項：`--only A_page_010,A_page_020`（只跑指定種子與其延伸頁）、`--no-render`（關閉 headless Chrome）、
`--no-images`、`--no-extension`（不抓延伸頁）、`--output DIR`。

每次執行會重建 `output/index.jsonl`、`output/articles/*.md`、`output/crawl_report.csv`、`output/duplicates.json`，
並把每頁原始紀錄寫入 `output/records/<id>.json`（支援單頁增量重跑）。

截圖對照另以 `tools/make_screenshots.py` 產生（同樣只需標準函式庫 + Pillow + 本機 Chrome）：

```bash
python3 tools/make_screenshots.py
```

## 4. 任務 1：網址清單、延伸探索與狀態紀錄

### 4.1 全部 20 頁結果

| id | 類型 | 標題 | 字數 | 圖 | 狀態 | 擷取策略 |
| --- | --- | --- | ---: | ---: | --- | --- |
| A_page_001 | seed | 觀音區 | 5,360 | 4 | success | wikipedia:mw-parser-output |
| A_page_001_ext_01 | ext | 觀音區戶政事務所－歷史沿革 | 915 | 0 | success | tycg:CCMS_Content/area-editor |
| A_page_001_ext_02 | ext | 水務局－河川管理及維護 | 267 | 3 | success | tycg:CCMS_Content/area-editor |
| A_page_010 | seed | 甘泉寺（桃園市） | 1,513 | 5 | success | wikipedia:mw-parser-output |
| A_page_010_ext_01 | ext | 桃園觀光導覽網－甘泉寺 | 324 | 2 | success | chrome-headless+generic |
| A_page_010_ext_02 | ext | 觀音區公所－本所沿革 | 369 | 0 | success | tycg:CCMS_Content/area-editor |
| A_page_015 | seed | 觀音坑溪 | 486 | 3 | success | wikipedia:mw-parser-output |
| A_page_015_ext_01 | ext | 淡水河 | 15,699 | 4 | success | wikipedia:mw-parser-output |
| A_page_015_ext_02 | ext | 觀音山（新北市） | 3,637 | 4 | success | wikipedia:mw-parser-output |
| A_page_016 | seed | 大堀溪 | 488 | 1 | success | wikipedia:mw-parser-output |
| A_page_016_ext_01 | ext | 水務局－大堀溪 | 457 | 3 | success | tycg:CCMS_Content/area-editor |
| A_page_020 | seed | 大潭發電廠 | 3,436 | 2 | success | wikipedia:mw-parser-output |
| A_page_020_ext_01 | ext | 台電月刊－大潭電廠 | 541 | 0 | success | chrome-headless+generic |
| A_page_020_ext_02 | ext | 能源署－大潭火力發電廠 | 683 | 1 | success | generic:max-text-density |
| A_page_028 | seed | 石門水庫移民聚落－觀音草漯移民新村 | 877 | 1 | success | tcmb:index_main |
| A_page_028_ext_01 | ext | 移民新村牌樓 | 868 | 1 | success | tcmb:index_main |
| A_page_028_ext_02 | ext | 文化局－文史旅行手冊 | 150 | 1 | success | tycg:CCMS_Content/area-editor |
| A_page_031 | seed | 原住民族文獻 第59期 | 3,432 | 8 | success | ihc:mainArea |
| A_page_031_ext_01 | ext | 新聞處－卡拉社專書 | 1,327 | 4 | success | tycg:CCMS_Content/area-editor |
| A_page_031_ext_02 | ext | 原住民族文獻 第58期 | 2,668 | 4 | success | ihc:mainArea |

去重紀錄：A_page_016 的第 2 個延伸候選（水務局 `cp.aspx?n=10870`）與 A_page_001_ext_02 完全相同，
程式以 `crawled_urls` 比對後跳過並在主控台輸出「跳過重複 URL」，因此延伸頁為 13 而非 14。

### 4.2 失敗與異常紀錄

本次全 20 頁皆 success，但仍有三類必須揭露的處理：

1. **前端渲染（SPA）頁**：`travel.tycg.gov.tw`、`service.taipower.com.tw` 伺服器端只回傳框架，原始 HTML 幾乎沒有正文。
   程式偵測正文 < 200 字時，改用本機 headless Chrome 實際執行 JS 後取得 DOM（存 `output/raw/<id>.rendered.html`），
   重新擷取後採用，並在 `notes` 註明「非推測內容」。A_page_010_ext_01（324 字、2 圖）、A_page_020_ext_01（541 字）即此類。
2. **間歇性連線停滯**：`*.tycg.gov.tw` 系列偶發 stalled（HTTP 200 但只吐一半位元組）。程式以 urllib／curl 交錯重試 4 次，
   並記下每次失敗原因；本輪重跑後未再出現 partial。
3. **簽章過期圖片**：國家文化記憶庫部分圖片位於 `tcmbfile.culture.tw`，網址帶 Google 簽章（`X-Goog-Algorithm`），
   已過期回 HTTP 400。程式只記錄該 URL 與失敗原因，**不下載替代圖、不以其他圖冒充**；可下載的是 `dcm.s3.hicloud.net.tw` 的副本。

> 對照作業要求「無法存取者不得虛構」：以上三類都在 `output/records/*.json` 的 `notes`／`error` 與 `crawl_report.csv` 留下逐筆原因。

## 5. 任務 2：正文與雜訊分離

### 5.1 策略（依站型）

| 站型 | 代表頁 | 擷取策略 | 移除的雜訊 |
| --- | --- | --- | --- |
| 維基百科（百科全書） | A_page_001、A_page_010、A_page_015/016/020 | 取 `#mw-content-text .mw-parser-output`，再剝除資訊框表格以外的編輯元件 | 編輯鉛筆、目錄、導覽方塊（navbox）、參考資料清單、分類列、語言選單 |
| 國家文化記憶庫（策展資料庫） | A_page_028、A_page_028_ext_01 | 取 `#index_main`（備援 `.material_detail`） | 全站頁首頁尾、麵包屑、搜尋框、推薦卡片、分享列 |
| 政府機關 CMS（tycg 系列） | A_page_001_ext_01、A_page_016_ext_01、A_page_031_ext_01 | 優先 `#CCMS_Content`，其次 `.area-editor` | 主選單、語言列、側欄快捷、跑馬燈、頁尾、無障礙工具列 |
| 前端渲染 SPA | A_page_010_ext_01、A_page_020_ext_01 | headless Chrome 渲染後，以「文字密度 + class 加權」找最大正文容器 | 地圖、營業時間表、社群分享按鈕、頁籤 |

> 政府 CMS 頁面整頁 `textContent` 會被行內 JS 字串污染（例如出現 `$(function`），因此**不使用整頁文字**，只取正文容器。

### 5.2 原始網頁 vs 清理後對照（截圖）

| 站型 | 對照圖 |
| --- | --- |
| 維基百科 | `report/screenshots/A_page_001_compare.jpg` |
| 國家文化記憶庫 | `report/screenshots/A_page_028_compare.jpg` |
| 政府機關（觀音區公所） | `report/screenshots/A_page_010_ext_02_compare.jpg` |
| 前端渲染 SPA（觀光導覽網） | `report/screenshots/A_page_010_ext_01_compare.jpg` |

每組含 `_original.jpg`（原始網址畫面）、`_cleaned.jpg`（清理後結構化結果）、`_compare.jpg`（左右併圖，左標「原始網頁」、右標「清理後結果」）。
清單見 `report/screenshots/screenshots_manifest.json`。

## 6. 任務 3：圖片擷取

- 來源：`<img>` 的 `src`／`data-src`／`data-original`／`srcset`（處理 lazy-load），以及 `og:image`；
  `srcset` 取最大寬度候選。維基縮圖自動改抓 900px 版本（`/250px-` → `/900px-`），避免小圖被尺寸門檻淘汰。
- 排除：檔名／class 含 logo、icon、pixel、tracking、share、banner、button、sprite、avatar、emoji 者；
  SVG／GIF 一律不收；下載後以 Pillow 驗證，小於 200×150 或檔案 < 6KB 視為裝飾圖丟棄。
- 去重：內容 sha256 前 16 碼，同頁重複即刪檔不記錄。
- 命名：`output/images/page_xxx_image_01.jpg`、延伸頁 `page_xxx_ext_01_image_01.jpg`；統一轉 JPEG（q85）。
- 對應紀錄：每張圖在 `records/<id>.json` 的 `images[]` 內含 `file`／`original_url`／`alt`／`caption`／`size`／`sha256`，
  `articles/<id>.md` 內以「`*圖說：…*`」文字對應，達到圖文互查。
- 上限：種子頁 8 張、延伸頁 4 張（避免單頁吃光容量）。
- 共 51 張；17 頁有圖、3 頁無合適內文圖片（A_page_001_ext_01、A_page_010_ext_02、A_page_020_ext_01），
  這些頁面在 `notes` 明確寫「無合適內文圖片（已排除 logo／icon／追蹤像素／社群按鈕）」，**不以頁面橫幅或 logo 充數**。

## 7. 任務 4：影片與字幕

20 頁全部掃描 `<video>`、`<audio>`、`<iframe>`（含 YouTube／Vimeo 嵌入），結果為 **0 個可處理影片**。
因此沒有可下載的影片、沒有可取得的字幕，也沒有做 ASR。

- 依作業規定「不得繞過平台限制」：未嘗試下載 YouTube 串流、未破解任何播放器。
- 每頁 `notes` 均留下「此頁未偵測到 video／audio 標籤或嵌入播放器，無合法可處理影片。」，
  `output/videos/` 目錄保留為空並在 `crawl_report.csv` 反映（`images_saved` 有值、影片欄位無資料）。
- 若教師抽查到含影片的頁面，程式會把 `<video>` 的 `src`／`<iframe>` 的 `src` 寫入 `media` 與 `videos` 欄位，
  但**不會**自動下載，需人工確認授權後再處理。

## 8. 任務 5：結構化欄位

`output/index.jsonl` 每行一筆 JSON，欄位統一如下（範例為 A_page_010 節錄）：

```json
{
  "id": "A_page_010",
  "type": "seed",
  "parent_id": null,
  "title": "甘泉寺 (桃園市)",
  "source_url": "https://zh.wikipedia.org/wiki/%E7%94%98%E6%B3%89%E5%AF%BA_(%E6%A1%83%E5%9C%92%E5%B8%82)",
  "source_name": "維基百科（中文）",
  "content": "…清理後正文（Markdown）…",
  "images": [{"file": "output/images/A_page_010_image_01.jpg", "original_url": "…", "caption": "石觀音"}],
  "links": [{"url": "…", "text": "…"}],
  "timestamps": {"published": "", "crawled_at": "2026-11-05T18:33:00+08:00"},
  "crawl_status": "success",
  "crawled_at": "2026-11-05T18:33:00+08:00",
  "category": "歷史文化",
  "keywords": ["甘泉寺", "石觀音", "觀音區", "觀音信仰", "甘泉井"],
  "strategy": "wikipedia:mw-parser-output",
  "notes": ["…"],
  "media": {"video_tags": 0, "audio_tags": 0, "iframes": []},
  "videos": [],
  "http_status": 200,
  "engine": "urllib",
  "attachments": [],
  "content_hash": "…",
  "chars": 1513,
  "member": "A"
}
```

另有 `output/articles/<id>.md`（人可讀：metadata 區塊 + 內文 + 圖片清單 + 影片說明 + 原始連結），
三種檢視（JSONL／Markdown／CSV）以 `id` 對齊，可互相對照。

## 9. 任務 6：去重、分類、關鍵字與查證

### 9.1 跨站重複

以清理後正文的 5-gram 字元 shingle 計算 Jaccard 相似度，門檻 0.55，共比較 190 對，**無任何一對達門檻**。
（已知相近者為同站上下期文獻 A_page_031 與 A_page_031_ext_02，相似度仍低於門檻，屬同刊物不同文章。）
結果寫入 `output/duplicates.json`（含比較對數、門檻與說明）。

### 9.2 分類與關鍵字

| 分類 | 頁數 | 頁面 |
| --- | ---: | --- |
| 歷史文化 | 12 | A_page_001、001_ext_01、001_ext_02、010、010_ext_01、010_ext_02、028、028_ext_01、028_ext_02、031、031_ext_01、031_ext_02 |
| 自然景觀 | 5 | A_page_015、015_ext_01、015_ext_02、016、016_ext_01 |
| 地方產業 | 3 | A_page_020、020_ext_01、020_ext_02 |

每頁 5–6 個關鍵字已寫入 `keywords`（例：A_page_016「大堀溪、觀音區、市管河川、蓮花、水質」）。

### 9.3 地方知識交叉查證（≥3 筆）

| # | 地方知識 | 主張 | 來源 A | 來源 B | 來源 C | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 觀音區名與甘泉寺起源 | 清咸豐 10 年（1860）黃等（成）於溪中拾得石觀音，建草菴奉祀，地名「石觀音」由此而來 | 維基 A_page_010（咸豐十年／1860） | 觀音區戶政 A_page_001_ext_01（西元 1860 年、咸豐 10 年） | 觀音區公所 A_page_010_ext_02（清朝咸豐 10 年 1860 農曆 4 月 22 日） | 三方一致（**1860**）；惟桃園觀光導覽網 meta 描述寫「清乾隆年間（1780 年）」，屬不同說法，並列不採信 |
| 2 | 大堀溪長度與流域 | 市管河川，流經觀音、新屋、中壢、楊梅，於觀音工業區南端出海 | 維基 A_page_016：主流 18.59 km、流域 47.38 km²、上游頭洲溪源於楊梅高榮里 | 水務局 A_page_016_ext_01：主流 14.5 km、平均坡降 1:143、上游自楊梅幼獅工業區 | 水務局 A_page_001_ext_02：桃園市市管河川共 9 條，含大堀溪 | 口徑不同（18.59 vs 14.5 km）；官方與百科並列，報告不擇一當定論 |
| 3 | 大潭發電廠規模 | 桃園觀音大潭里之燃氣複循環電廠，台灣最大天然氣電廠 | 維基 A_page_020：總裝置容量 7,540.2 MW；8 號機 2024-07-31 商轉、9 號機 2025-07-23 商轉 | 經濟部能源署 A_page_020_ext_02：6 部機組、計畫民國 110 年擴建至 300 萬瓩 | 台電月刊 A_page_020_ext_01（渲染後）：佔地約 116 公頃、供北台灣 1/3 電力 | 官方頁面內容較舊（擴建仍寫「計畫」），維基數字較新；以「官方口徑 + 更新時間」並列，未把維基當最新事實 |
| 4 | 石門水庫移民聚落（草漯） | 1957–1963 年間遷入，首批 29 戶、後續 7 戶，合計 36 戶 | 國家文化記憶庫 A_page_028 | 桃園市文化局 A_page_028_ext_02（手冊走讀點含「觀音草漯/樹林」） | 維基 A_page_001（草漯次分區位置、開發最早） | 一致（移民聚落與草漯次分區位置相符） |
| 5 | 卡拉社（泰雅）遷徙 | 石門水庫淹沒區族人三度搬遷：石秀坪→大溪中庄新村→觀音大潭新村 | 桃園市新聞處 A_page_031_ext_01 | 原住民族文獻 A_page_031（同批移民研究，作者李慧慧） | 原住民族文獻 A_page_031_ext_02（第58期） | 一致 |

> 原則：官方網站（戶政、區公所、水務局、文化局、能源署、台電）與可信出版品（國家文化記憶庫、原民會文獻）並列；
> 遇到數字不一致時**兩個都留**，並註明資料時點，不把 AI 推測寫成事實。

## 10. 重要範圍警示（必看）

**A_page_015「觀音坑溪」不是桃園市觀音區的溪。** 維基該條目描述的是**新北市五股區**的觀音坑溪
（源於觀音山南側凌雲禪寺附近，海拔 372 公尺，長 6.2 公里、流域 9.2 平方公里，流入淡水河），
與桃園觀音區無地緣關係（僅名稱相同）。因此：

- 本頁內容**不得**當作「桃園市觀音區地方知識」引用；
- 其污染敘述（《看見台灣》拍到染整廢水）屬於新北五股案例；
- 報告中保留原樣並加註，延伸頁改抓淡水河與觀音山（新北市），以呈現其真實水系脈絡。

桃園觀音區實際的溪流為：大堀溪、觀音溪、新屋溪、富林溪（水務局 A_page_001_ext_02 列出 9 條市管河川），
其中大堀溪已由 A_page_016 與 A_page_016_ext_01 正確涵蓋。

## 11. 已知限制

1. **無 requests／bs4／trafilatura**：本機 Python 環境僅有標準函式庫與 lxml，因此自寫 HTML→Markdown 轉換（表格轉 Markdown、圖片轉圖說、清單保留）。
   若教師環境有安裝 `requirements.txt` 的套件，公版 `crawler.py` 仍可獨立運作，本組程式不依賴它。
2. **headless Chrome 為選用**：若機器無 Chrome，程式自動跳過渲染（`--no-render` 等效），SPA 頁會退回 meta 描述並標 partial。
3. **截圖需 Chrome**：`tools/make_screenshots.py` 同理；無 Chrome 時不產生截圖，不會用假圖代替。
4. **台電月刊內文**：渲染後僅得 541 字（列表頁文案），全文在需授權的 API 後端，未取得，如實記錄。

## 12. 檔案結構（本組產出）

```
crawler/crawler_member_A.py      # 主程式（20 頁、圖片、JSONL/Markdown/CSV 輸出）
tools/make_screenshots.py        # 原始 vs 清理後對照截圖
urls_member_A.csv                # A 組 7 個種子網址
output/
  index.jsonl                    # 20 筆結構化資料（任務 5）
  crawl_report.csv               # 每頁狀態／字數／圖片數／錯誤原因
  duplicates.json                # 跨頁相似度比對結果
  records/<id>.json              # 每頁完整紀錄（增量重跑用）
  articles/<id>.md               # 人可讀文章（metadata + 正文 + 圖說）
  images/*.jpg                   # 51 張圖片（page_xxx[_ext_nn]_image_NN.jpg）
  raw/<id>.html                  # 原始 HTML（含 <id>.rendered.html 為 Chrome 渲染後）
  videos/                        # 空（無合法可處理影片）
report/
  report.md                      # 本文件
  screenshots/*.jpg              # 4 組站型 ×（原始／清理後／併圖）
```
