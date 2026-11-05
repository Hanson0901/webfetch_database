# 組員 D 報告：新聞、部落格、旅遊與飲食媒體

負責來源：D-001、D-002、D-003、D-004、D-005、D-006、D-007、D-008、D-009、D-010（共 10 個）

> 編號說明：D 的資料一律使用 `D-001`～`D-012`。對照 urls.csv：D-001=page_003、D-002=page_004、D-003=page_009、D-004=page_014、D-005=page_017、D-006=page_021、D-007=page_022、D-008=page_023、D-009=page_025、D-010=page_029；D-011 為自行找到的 NOWnews（extra），D-012 為由 D-007 延伸的痞客邦文章（internal）。完整對照見 `output/D/id_mapping.json`。

相關程式與檔案：

| 檔案 | 用途 |
| --- | --- |
| `crawler/crawler_member_D.py` | D 專用爬蟲（各站正文規則、圖片篩選、作者／日期、一層延伸） |
| `crawler/analyze_member_D.py` | 重複比對、主題分類、關鍵字、查核候選、整合知識資料 |
| `crawler/fact_check_D.json` | 人工查核紀錄（媒體敘述 vs 官方資料） |
| `output/D/` | 爬取成果：`index.jsonl`、`crawl_report.csv`、`articles/`、`images/`、`analysis/`、`knowledge_D.jsonl` |

---

## 1. 執行方式（與公版相同）

`crawler_member_D.py` 是依 README 複製公版 `crawler.py` 後修改的，輸入方式和公版一模一樣：

```bash
pip install -r requirements.txt          # 第一次
python crawler/crawler_member_D.py       # 互動模式
python crawler/analyze_member_D.py       # 產生關鍵字、主題、重複比對、查核報告
```

互動模式會依序詢問：組員編號（輸入 `D`）→ 網址 → 來源種類 seed/internal/extra → （internal 才問）父頁面 id → 備註；
編號自動產生 `D-001`、`D-002`…，輸入 `quit` 結束，資料存到 `output/D`。

單筆命令列模式（參數與公版相同），可用來指定和 `urls.csv` 一樣的編號：

```bash
python crawler/crawler_member_D.py --member D --id D-006 --url "https://supertaste.tvbs.com.tw/travel/348994"
python crawler/crawler_member_D.py --member D --url "老師指定的網址" --source-kind extra --notes "現場展示"
```

Windows 請把 `/` 換成 `\`。

---

## 2. 各網站結構與清理規則

在瀏覽器中檢查每個網站「伺服器回傳的原始 HTML」（也就是 requests 拿到的版本），確認正文容器與雜訊位置後寫成 `SITE_RULES`。

| id | 網站 | 類型 | 正文容器 | 主要移除的雜訊 | 作者／日期來源 |
| --- | --- | --- | --- | --- | --- |
| D-001 | 微笑台灣 | 旅遊媒體 | `main#first_article article` | 作者簡介 `.authorInfo`、標籤、推薦文章 | `li.author`／`li.update` |
| D-002 | 客庄小旅行（達人帶路） | 旅遊媒體 | `article.page-article` | 文章內目錄 `.anchor-nav`、作者介紹 `.blog-author-wrap`、Cookie 提示、登入彈窗 | `span.author`／meta `DC.Date` |
| D-003 | 方格子 vocus | 部落格 | `article.editor-content-block` | 廣告佔位、「你可能想看」推薦區 | JSON-LD author／`article:published_time` |
| D-004 | 我的旅圖中 | 部落格（WordPress） | `#penci-post-entry-inner` | 分享按鈕、文章標籤、相關文章、目錄 | `a.author-url`／`time.entry-date` |
| D-005 | 客庄小旅行 HA-FOOD | 飲食（店家頁） | `dl.description-list` + `article.page-article` | 「周邊美食／景點／旅宿」卡片 `section.page-section` | meta `DC.Date`（無個人作者，記錄發布單位） |
| D-006 | TVBS 食尚玩家 | 新聞／飲食媒體 | `article#article-content` | 文中廣告 `.ins-container`、頁首 | meta `author`／`article:published_time` |
| D-007 | 痞客邦 美食人生 | 部落格 | `.article-body` | 文末作者框、關鍵字、表情 gif | meta `author`／`og:article:published_time` |
| D-008 | Yahoo 奇摩新聞 | 新聞 | `article[id^=article-] div.atoms` | 廣告區塊、文末推廣連結「…》https://…」 | JSON-LD `datePublished`（無具名作者） |
| D-009 | 旅聯網 | 旅遊入口網（主題頁） | `#divcontent .profile_description` | 點閱數、分享鈕、Google 廣告、目錄路徑 | 無作者、無日期（記錄為未標示） |
| D-010 | 方格子 vocus | 部落格（歷史） | `article.editor-content-block` | 同 D-003 | JSON-LD author／`article:published_time` |

### 清理策略（三層）

1. **選容器**：只取上表的正文容器，導覽列、頁首頁尾、側欄、推薦文章本來就在容器外，直接被排除。找不到容器時才退回 `trafilatura`，再不行才用公版的通用方法，並在 `extraction_method` 欄位記錄用了哪一種。
2. **容器內去雜訊**：通用規則（廣告、分享、訂閱、Cookie、彈窗、相關文章）＋各站專用規則；每個選擇器刪了幾個節點記錄在 `noise_removed`。
3. **段落過濾**：遇到「延伸閱讀／推薦閱讀／相關文章」標題就截斷後面內容；刪除「分享、上一張、下一張」等短字串與重複段落；刪除文末推廣連結。刪除的區塊數記在 `blocks_dropped`。

保留的內容：標題、小標（轉成 Markdown `##`）、段落、條列、表格、定義清單（店家電話／地址／營業時間）、圖片與圖說，以及作者、日期、原始網址。

### 清理前後對照（任務 2，至少 3 種網站類型）

建議截圖這三個（放 `report/screenshots/`）：

| 類型 | 網址 | 原始頁面截圖 | 清理結果 |
| --- | --- | --- | --- |
| 新聞 | D-008 Yahoo | `screenshots/D_D-008_before.png` | `output/D/articles/D-008.md` |
| 部落格 | D-007 痞客邦 | `screenshots/D_D-007_before.png` | `output/D/articles/D-007.md` |
| 飲食店家頁 | D-005 客庄小旅行 | `screenshots/D_D-005_before.png` | `output/D/articles/D-005.md` |

---

## 3. 圖片擷取與篩選（任務 3）

- **Lazy loading**：依序讀 `data-original-src`（vocus 原圖）、`data-original`（旅聯網）、`data-src`（客庄小旅行、微笑台灣）、`srcset` 最大張，最後才用 `src`；`_loading.gif`、`grey.gif` 等佔位圖直接略過。公版先讀 `src`，在客庄小旅行只會抓到 loading 圖，這是修改的主要原因之一。
- **只收正文內圖片**：選單、Logo、頭像、推薦文章縮圖都在容器外，不會被抓。
- **排除規則**：網址或 class 含 logo／icon／avatar／banner／share／ad／tracking；`.svg`；痞客邦 `.gif`（表情、分隔線）；HTML 標示寬高 < 60；下載後小於 1KB（追蹤像素）；寬高都小於 150px。被排除的圖片與原因記在 `images_rejected`。
- **去重**：同一網址只下載一次；內容相同（SHA-256 相同）的圖片只存一份，並沿用已存在的檔名。
- **命名**：D-006_image_01.jpg`、D-006_image_02.webp`……
- **圖文對應**：每張圖記錄 `caption`（figcaption、vocus 圖說、▲開頭的說明、alt）、`credit`（「圖片來源：IG@…」「圖片提供／…」）、`context.heading`（所屬小標）與 `context.near_text`（前一段文字），文章 Markdown 中圖片也放在原本的位置。
- **圖片來源標示**：TVBS、Yahoo 的圖片多為「圖片來源：IG@xxx」或「圖片提供／xxx」，程式另外存到 `credit`；vocus D-003 作者自己標示「圖片截圖於網路」，記錄為「原始出處不明」，報告中不可當成作者自己拍攝。沒有標示的寫「未標示」，不自行猜測。

---

## 4. 一層延伸探索（任務 1）

與公版相同：爬完後建立延伸清單（`ext_001`…，狀態 `queued`），由人工確認後再用 `--source-kind internal --parent-id <父頁面id>` 爬取，並補進 `urls.csv`。D 修改的是挑選條件：只取「正文內」、連結文字或網址含觀音區相關詞的連結，排除社群分享、地圖、圖片連結，最多 12 個，深度 1。

「觀音」判斷會排除「觀音山」：D-009 旅聯網的主題頁是「中華民國領海基點」，頁面上的「觀音」是新北市的「北海岸及觀音山」，和桃園觀音區無關。程式會在這種頁面加上 `relevance_warning`，報告中也要說明這一點。

---

## 5. 重複比對、主題分類與關鍵字（任務 6）

- **重複／相似**：段落用 4 字元 shingle 算「包含率」，≥ 0.5 就列為重複或改寫；整篇文章用 Jaccard ≥ 0.3。另外列出「同一景點在不同媒體的敘述」，例如白沙岬燈塔、白千層、甘泉寺，方便比較各媒體說法差在哪裡（`analysis/duplicates_D.md`）。加上 `--compare-all` 可以一起比對 A、B、C 的資料。
- **主題分類**：自然景觀、歷史文化、地方產業、觀光景點、美食飲食，依主題詞出現次數決定主要類別，可以有多個標籤。
- **關鍵字**：每篇 3–5 個。先從觀音區詞庫挑（白沙岬燈塔、甘泉寺、草漯沙丘……），再用網站自己的 meta keywords，不夠再用 TF-IDF 補；有安裝 `jieba` 時改用 jieba 斷詞。

---

## 6. 來源查證（媒體內容與官方資料分開）

媒體內容在 `index.jsonl` 裡一律標記 `data_nature=media`、`verification_status=unverified`；查核結果放在 `fact_check_D.json`，整合輸出 `knowledge_D.jsonl` 也分成 `media_content` 和 `verification` 兩欄。

| 編號 | 媒體敘述 | 官方資料 | 判定 |
| --- | --- | --- | --- |
| D-FC-01 | Yahoo（D-008）：白沙岬燈塔「塔高約37公尺」 | 航港局：塔高 27.7 m，**燈高** 36.6 m | 不符（把燈高寫成塔高） |
| D-FC-02 | Yahoo（D-008）：「台灣唯一」用紅磚與石頭建造的燈塔 | 文化部國家文化記憶庫：「首次」使用磚與石材；航港局：圓形磚塔 | 部分符合（「唯一」無佐證） |
| D-FC-03 | vocus（D-003）：甘泉寺是「清乾隆古剎」 | 客家雲：乾隆45年（1780）出現石觀音，咸豐8年（1858）建廟；區公所寫咸豐年間 | 部分符合（官方說法不一） |
| D-FC-04 | vocus（D-010）：泰雅族移民先到中庄，1963 年颱風後遷到觀音大潭 | 水利署：51 年遷中庄，52 年 9 月颱風沖毀後遷觀音鄉大潭村 | 符合 |
| D-FC-05 | 客庄小旅行（D-002）：草漯沙丘位於老街溪口南岸至大堀溪出海口 | 林業及自然保育署：老街溪口南岸至大堀溪口北岸，約 456 公頃 | 符合 |

查核來源：

- 交通部航港局 燈塔專區－白沙岬燈塔：https://lighthouse.motcmpb.gov.tw/lighthouse_3_29.html
- 文化部 國家文化記憶庫－觀音白沙岬燈塔：https://tcmb.culture.tw/zh-tw/detail?indexCode=Culture_Place&id=113634
- 客家委員會 客家雲－觀音甘泉寺：https://cloud.hakka.gov.tw/Details?p=64716&pid=279528
- 桃園觀光導覽網－甘泉寺：https://travel.tycg.gov.tw/zh-tw/travel/attraction/292
- 桃園市觀音區公所－觀音意象：https://www.guanyin.tycg.gov.tw/cp.aspx?n=6874
- 經濟部水利署電子報－石門水庫淹沒區住民遷移安置歷程特展：https://www.wra.gov.tw/epaper/Article_Detail.aspx?s=8967&n=30173
- 農業部林業及自然保育署－草漯沙丘：https://www.forest.gov.tw/0008127

注意：觀音區公所的景點介紹也寫「塔高37公尺」，和 Yahoo 文字幾乎一樣，表示觀光文宣之間會互相引用，**政府網站上的觀光文案也不一定是權威資料**，技術數據應以主管機關（航港局）為準。

---

## 7. 爬取結果與失敗紀錄

執行兩支程式後，完整結果會自動寫在 `output/D/analysis/crawl_summary_D.md`（逐網址狀態、字數、圖片數、失敗原因），可直接貼到這裡。預期需要特別說明的項目：

| id | 狀態 | 正文字數 | 圖片（保存／排除） | 失敗原因／備註 |
| --- | --- | --- | --- | --- |
| D-001 | | | | |
| D-002 | | | | 會轉址到 romantichakka.hakka.gov.tw（記錄在 final_url） |
| D-003 | | | | 圖片為「截圖於網路」，來源不明 |
| D-004 | | | | |
| D-005 | | | | 店家頁，無個人作者 |
| D-006 | | | | |
| D-007 | | | | |
| D-008 | | | | 原網址的 guccounter 等追蹤參數已移除 |
| D-009 | | | | 與桃園觀音區關聯低（觀音山 ≠ 觀音區） |
| D-010 | | | | |

已知限制：

- 若網站改版、或之後改成 JavaScript 動態載入，正文少於 80 字會標記 `failed` 並寫明原因，需要更新 `SITE_RULES`。
- 網站回應 403／429 時記錄為 `unavailable`，不繞過限制。
- 圖片版權屬原作者或網站，只供課程作業使用。
