# 組員 D 報告：新聞、部落格、旅遊與飲食媒體

負責來源：老師指定 10 個（page_003、page_004、page_009、page_014、page_017、page_021、page_022、page_023、page_025、page_029）＋網頁內延伸 4 個（page_022_ext_01～03、page_003_ext_01）＋自行新增 7 個（page_035～041），共 21 筆。

> 編號說明（依組員約定）：老師給的網址為 沿用 urls.csv 的原編號（例如 `page_003`）；網頁內延伸為 `page_xxx_ext_01`（type = article_ext）；自行找到的網站接在 urls.csv 原本編號之後，從 `page_035` 開始（032～034 為其他組員）。D 新增的網址登記於 `urls_member_D.csv`。

相關程式與檔案：

| 檔案 | 用途 |
| --- | --- |
| `crawler/crawler_member_D.py` | D 專用爬蟲（各站正文規則、圖片篩選、作者／日期、一層延伸） |
| `crawler/analyze_member_D.py` | 重複比對、主題分類、關鍵字、查核候選、整合知識資料 |
| `crawler/fact_check_D.json` | 人工查核紀錄（媒體敘述 vs 官方資料） |
| `output/` | 爬取成果：`index.jsonl`、`crawl_report.csv`、`articles/`、`images/`、`analysis/`、`knowledge_D.jsonl` |

---

## 1. 執行方式（與公版相同）

`crawler_member_D.py` 是依 README 複製公版 `crawler.py` 後修改的，輸入方式和公版一模一樣：

```bash
pip install -r requirements.txt          # 第一次
python crawler/crawler_member_D.py       # 互動模式
python crawler/analyze_member_D.py       # 產生關鍵字、主題、重複比對、查核報告
```

互動模式會依序詢問：組員編號（輸入 `D`）→ 網址 → 來源種類 seed/internal/extra → （internal 才問）父頁面 id → 備註；
編號依網址自動產生（`page_022`、`page_022_ext_01`、`page_035`，規則見下方「編號規則」），輸入 `quit` 結束，資料存到 `output/`。

單筆命令列模式（參數與公版相同），可用來指定和 `urls.csv` 一樣的編號：

```bash
python crawler/crawler_member_D.py --member D --id page_021 --url "https://supertaste.tvbs.com.tw/travel/348994"
python crawler/crawler_member_D.py --member D --url "老師指定的網址" --source-kind extra --notes "現場展示"
```

Windows 請把 `/` 換成 `\`。

---

## 2. 各網站結構與清理規則

在瀏覽器中檢查每個網站「伺服器回傳的原始 HTML」（也就是 requests 拿到的版本），確認正文容器與雜訊位置後寫成 `SITE_RULES`。

| id | 網站 | 類型 | 正文容器 | 主要移除的雜訊 | 作者／日期來源 |
| --- | --- | --- | --- | --- | --- |
| page_003 | 微笑台灣 | 旅遊媒體 | `main#first_article article` | 作者簡介 `.authorInfo`、標籤、推薦文章 | `li.author`／`li.update` |
| page_004 | 客庄小旅行（達人帶路） | 旅遊媒體 | `article.page-article` | 文章內目錄 `.anchor-nav`、作者介紹 `.blog-author-wrap`、Cookie 提示、登入彈窗 | `span.author`／meta `DC.Date` |
| page_009 | 方格子 vocus | 部落格 | `article.editor-content-block` | 廣告佔位、「你可能想看」推薦區 | JSON-LD author／`article:published_time` |
| page_014 | 我的旅圖中 | 部落格（WordPress） | `#penci-post-entry-inner` | 分享按鈕、文章標籤、相關文章、目錄 | `a.author-url`／`time.entry-date` |
| page_017 | 客庄小旅行 HA-FOOD | 飲食（店家頁） | `dl.description-list` + `article.page-article` | 「周邊美食／景點／旅宿」卡片 `section.page-section` | meta `DC.Date`（無個人作者，記錄發布單位） |
| page_021 | TVBS 食尚玩家 | 新聞／飲食媒體 | `article#article-content` | 文中廣告 `.ins-container`、頁首 | meta `author`／`article:published_time` |
| page_022 | 痞客邦 美食人生 | 部落格 | `.article-body` | 文末作者框、關鍵字、表情 gif | meta `author`／`og:article:published_time` |
| page_023 | Yahoo 奇摩新聞 | 新聞 | `article[id^=article-] div.atoms` | 廣告區塊、文末推廣連結「…》https://…」 | JSON-LD `datePublished`（無具名作者） |
| page_025 | 旅聯網 | 旅遊入口網（主題頁） | `#divcontent .profile_description` | 點閱數、分享鈕、Google 廣告、目錄路徑 | 無作者、無日期（記錄為未標示） |
| page_029 | 方格子 vocus | 部落格（歷史） | `article.editor-content-block` | 同 page_009 | JSON-LD author／`article:published_time` |
| page_038 | 中央社 CNA | 新聞（通訊社） | `div.centralContent div.paragraph` | Google News 圖示、文末「延伸閱讀》看更多」系列連結 | 內文署名「中央社記者○○○桃園14日電」（meta 只有「中央通訊社」） |
| page_035、039、040 | NOWnews、鏡週刊、輕旅行 | 新聞／雜誌／旅遊媒體 | 無專屬規則 → 公版通用方法（trafilatura） | 通用規則（延伸閱讀、推廣連結、分享數） | meta／JSON-LD |

TVBS 另外移除「本週優惠券」區、本文目錄、文中廣告、「看更多」、文章上方「搶優惠」跑馬燈；微笑台灣另外移除文中推薦文章 `.contentList`、標籤區 `.keywordsList`。
規則依網域套用，子網域也適用（例如所有 `xxx.pixnet.net` 部落格都套用痞客邦規則），共 9 套；網址會先轉址的（romantichakka.com → romantichakka.hakka.gov.tw）以轉址後的網域判斷。

**存取問題與處理**：第一次爬 page_003（微笑台灣）時，公版預設的 User-Agent 被網站防火牆拒絕（HTTP 403，robots.txt 其實允許 `/article/`），保留 `unavailable` 紀錄後，改用標準格式 `Mozilla/5.0 (compatible; GuanyinKnowledgeCrawler/1.0; ...)`（仍清楚標示為課程爬蟲、照樣遵守 robots.txt 與限速），之後成功取得。未使用任何繞過登入、驗證碼或付費牆的方法。

### 清理策略（三層）

1. **選容器**：只取上表的正文容器，導覽列、頁首頁尾、側欄、推薦文章本來就在容器外，直接被排除。找不到容器時才退回 `trafilatura`，再不行才用公版的通用方法，並在 `extraction_method` 欄位記錄用了哪一種。
2. **容器內去雜訊**：通用規則（廣告、分享、訂閱、Cookie、彈窗、相關文章）＋各站專用規則；每個選擇器刪了幾個節點記錄在 `noise_removed`。
3. **段落過濾**：遇到「延伸閱讀／推薦閱讀／相關文章」標題就截斷後面內容；刪除「分享、上一張、下一張」等短字串與重複段落；刪除文末推廣連結。刪除的區塊數記在 `blocks_dropped`。

保留的內容：標題、小標（轉成 Markdown `##`）、段落、條列、表格、定義清單（店家電話／地址／營業時間）、圖片與圖說，以及作者、日期、原始網址。

### 清理前後對照（任務 2，3 種網站類型）

| 類型 | 網址 | 原始頁面截圖 | 清理結果 | 原始頁面上被移除的雜訊 |
| --- | --- | --- | --- | --- |
| 新聞／飲食媒體 | page_021 TVBS 食尚玩家 | `screenshots/page_021_before.png` | `output/articles/page_021.md` | 頂部選單、TVBS 財經橫幅廣告、側欄 Adobe／背包廣告、浮動「AI 顧問」廣告與右下角影片廣告、「搶優惠」跑馬燈、「本週優惠券，領起來」區塊、「下載食尚APP」連結 |
| 部落格 | page_022 痞客邦 | `screenshots/page_022_before.png` | `output/articles/page_022.md` | 頂部痞客邦登入列、側欄「社群金點賞」徽章與臉書粉絲團、文中遊戲廣告、右下角浮動購物廣告、標題前的表情 gif；文末另有延伸閱讀、作者框、留言與人氣（截圖未截到，清理結果中同樣被移除） |
| 飲食店家頁 | page_017 客庄小旅行 | `screenshots/page_017_before.png` | `output/articles/page_017.md` | 頂部網站選單與語言／翻譯按鈕、「#餐食」標籤、「本頁店家資料由業者提供」免責聲明、「最後更新日期」、「周邊資訊」分頁與周邊美食／景點／旅宿卡片（截圖外另有 Cookie 提示與登入彈窗，同樣被移除）；保留店家電話、地址、營業時間與店家介紹 |

--- | --- | --- | --- |
| 新聞 | page_023 Yahoo | `screenshots/page_023_before.png` | `output/articles/page_023.md` |
| 部落格 | page_022 痞客邦 | `screenshots/page_022_before.png` | `output/articles/page_022.md` |
| 飲食店家頁 | page_017 客庄小旅行 | `screenshots/page_017_before.png` | `output/articles/page_017.md` |

---

## 3. 圖片擷取與篩選（任務 3）

- **Lazy loading**：依序讀 `data-original-src`（vocus 原圖）、`data-original`（旅聯網）、`data-src`（客庄小旅行、微笑台灣）、`srcset` 最大張，最後才用 `src`；`_loading.gif`、`grey.gif` 等佔位圖直接略過。公版先讀 `src`，在客庄小旅行只會抓到 loading 圖，這是修改的主要原因之一。
- **只收正文內圖片**：選單、Logo、頭像、推薦文章縮圖都在容器外，不會被抓。
- **排除規則**：網址或 class 含 logo／icon／avatar／banner／share／ad／tracking；`.svg`；痞客邦 `.gif`（表情、分隔線）；HTML 標示寬高 < 60；下載後小於 1KB（追蹤像素）；寬高都小於 150px。被排除的圖片與原因記在 `images_rejected`。
- **去重**：同一網址只下載一次；內容相同（SHA-256 相同）的圖片只存一份，並沿用已存在的檔名。
- **命名**：`page_021_image_01.jpg`、`page_021_image_02.webp`……
- **圖文對應**：每張圖記錄 `caption`（figcaption、vocus 圖說、▲開頭的說明、alt）、`credit`（「圖片來源：IG@…」「圖片提供／…」）、`context.heading`（所屬小標）與 `context.near_text`（前一段文字），文章 Markdown 中圖片也放在原本的位置。
- **圖片來源標示**：TVBS、Yahoo 的圖片多為「圖片來源：IG@xxx」或「圖片提供／xxx」，程式另外存到 `credit`；vocus page_009 作者自己標示「圖片截圖於網路」，記錄為「原始出處不明」，報告中不可當成作者自己拍攝。沒有標示的寫「未標示」，不自行猜測。

---

## 4. 一層延伸探索（任務 1）

- 挑選條件：只取「正文內」的連結，且連結文字或網址含觀音區相關詞（觀音、白沙岬、甘泉寺、草漯、藻礁…），排除社群分享、地圖、圖片連結；深度只有 1 層，最多 12 個。
- 「觀音」判斷會排除「觀音山」：page_025 旅聯網的主題頁是「中華民國領海基點」，頁面上的「觀音」是新北市的「北海岸及觀音山」，和桃園觀音區無關，程式會加上 `relevance_warning`。
- 實際延伸 4 頁（`type = article_ext`、`depth = 1`，`parent_id` 為父頁面）：

| id | 父頁面 | 延伸理由 |
| --- | --- | --- |
| page_022_ext_01 | page_022 | 文末連結「【桃園白沙岬燈塔】觀音夕照」 |
| page_022_ext_02 | page_022 | 文末連結「【白沙岬燈塔 & 觀音濱海遊憩區】」 |
| page_022_ext_03 | page_022 | 文末連結「【桃園半日遊】…白沙岬燈塔」 |
| page_003_ext_01 | page_003 | 文末「本文轉載自《我的旅圖中》」，為原始出處（用來驗證重複文章偵測） |

- 自行新增 7 個網站（`source_kind = extra`，查詢關鍵字記在 `urls_member_D.csv`）：NOWnews（蓮花園農場人數）、TVBS 兩篇（蓮花季、農場排名）、中央社（大潭藻礁）、鏡週刊（觀音一日遊）、輕旅行（觀音秘境）、微笑台灣（白沙岬燈塔）。

---

## 5. 重複比對、主題分類與關鍵字（任務 6）

- **重複／相似**：段落用 4 字元 shingle 算「包含率」，≥ 0.5 就列為重複或改寫；整篇文章用 Jaccard ≥ 0.3。另外列出「同一景點在不同媒體的敘述」，例如白沙岬燈塔、白千層、甘泉寺，方便比較各媒體說法差在哪裡（`analysis/duplicates_D.md`）。加上 `--compare-all` 可以一起比對 A、B、C 的資料。
- **主題分類**：自然景觀、歷史文化、地方產業、觀光景點、美食飲食，依主題詞出現次數決定主要類別，可以有多個標籤。
- **關鍵字**：每篇 3–5 個。先從觀音區詞庫挑（白沙岬燈塔、甘泉寺、草漯沙丘……），再用網站自己的 meta keywords，不夠再用 TF-IDF 補；有安裝 `jieba` 時改用 jieba 斷詞。

---

**重複比對結果**：page_003（微笑台灣）與 page_003_ext_01（我的旅圖中）整篇 Jaccard 相似度 0.67、11 段重複，證實微笑台灣文章是轉載自「我的旅圖中」；痞客邦同一作者的 3 篇延伸文章之間也有重複的參觀資訊段落。「白沙岬燈塔塔高約37公尺、僅次於鵝鑾鼻、台灣唯一紅磚石造」這段話同時出現在 page_004、page_023、page_022_ext_02，顯示媒體之間沿用同一段介紹。

## 6. 來源查證（媒體內容與官方資料分開）

媒體內容在 `index.jsonl` 裡一律標記 `data_nature=media`、`verification_status=unverified`；查核結果放在 `fact_check_D.json`，整合輸出 `knowledge_D.jsonl` 也分成 `media_content` 和 `verification` 兩欄。

| 編號 | 媒體敘述 | 官方資料 | 判定 |
| --- | --- | --- | --- |
| D-FC-01 | Yahoo（page_023）：白沙岬燈塔「塔高約37公尺」 | 航港局：塔高 27.7 m，**燈高** 36.6 m | 不符（把燈高寫成塔高） |
| D-FC-02 | Yahoo（page_023）：「台灣唯一」用紅磚與石頭建造的燈塔 | 文化部國家文化記憶庫：「首次」使用磚與石材；航港局：圓形磚塔 | 部分符合（「唯一」無佐證） |
| D-FC-03 | vocus（page_009）：甘泉寺是「清乾隆古剎」 | 客家雲：乾隆45年（1780）出現石觀音，咸豐8年（1858）建廟；區公所寫咸豐年間 | 部分符合（官方說法不一） |
| D-FC-04 | vocus（page_029）：泰雅族移民先到中庄，1963 年颱風後遷到觀音大潭 | 水利署：51 年遷中庄，52 年 9 月颱風沖毀後遷觀音鄉大潭村 | 符合 |
| D-FC-05 | 客庄小旅行（page_004）：草漯沙丘位於老街溪口南岸至大堀溪出海口 | 林業及自然保育署：老街溪口南岸至大堀溪口北岸，約 456 公頃 | 符合 |

查核來源：

- 交通部航港局 燈塔專區－白沙岬燈塔：https://lighthouse.motcmpb.gov.tw/lighthouse_3_29.html
- 文化部 國家文化記憶庫－觀音白沙岬燈塔：https://tcmb.culture.tw/zh-tw/detail?indexCode=Culture_Place&id=113634
- 客家委員會 客家雲－觀音甘泉寺：https://cloud.hakka.gov.tw/Details?p=64716&pid=279528
- 桃園觀光導覽網－甘泉寺：https://travel.tycg.gov.tw/zh-tw/travel/attraction/292
- 桃園市觀音區公所－觀音意象：https://www.guanyin.tycg.gov.tw/cp.aspx?n=6874
- 經濟部水利署電子報－石門水庫淹沒區住民遷移安置歷程特展：https://www.wra.gov.tw/epaper/Article_Detail.aspx?s=8967&n=30173
- 農業部林業及自然保育署－草漯沙丘：https://www.forest.gov.tw/0008127

> 以上查核由組員 D 依官方連結人工確認（請在繳交前逐一點開確認）。同樣的「37 公尺」說法也出現在 page_004、page_022_ext_02。另：白沙岬燈塔的古蹟等級，國家文化記憶庫寫「市定古蹟」，文化部文化資產局公告寫「國定古蹟」，以文化資產局為準。

注意：觀音區公所的景點介紹也寫「塔高37公尺」，和 Yahoo 文字幾乎一樣，表示觀光文宣之間會互相引用，**政府網站上的觀光文案也不一定是權威資料**，技術數據應以主管機關（航港局）為準。

---

## 7. 爬取結果與失敗紀錄

21 筆全部 `success`，沒有失敗或無法存取的網址（最新結果以 `output/crawl_report.csv`、`output/analysis/crawl_summary_D.md` 為準）。

| id | type | 狀態 | 網站 | 正文字數 | 圖片（保存／排除） | 備註 |
| --- | --- | --- | --- | --- | --- | --- |
| page_003 | article | success | 微笑台灣 | 1499 | 11／0 | 第一次爬取 HTTP 403，調整 User-Agent 後成功（見第 2 節） |
| page_004 | article | success | romantichakka.hakka.gov.tw | 3621 | 24／0 | 轉址到 romantichakka.hakka.gov.tw（記錄在 final_url） |
| page_009 | article | success | vocus | 1336 | 14／0 | 圖片作者自述「截圖於網路」，原始出處不明 |
| page_014 | article | success | 我的旅圖中 during my journey | 2831 | 37／2 |  |
| page_017 | article | success | romantichakka.hakka.gov.tw | 365 | 1／0 | 店家頁，無個人作者（記錄發布單位客家委員會） |
| page_021 | article | success | 食尚玩家 | 1118 | 11／0 |  |
| page_022 | article | success | 美食人生 | 976 | 14／3 |  |
| page_023 | article | success | Yahoo News | 711 | 8／0 | 網址追蹤參數已移除；作者取自內文署名 |
| page_025 | article | success | www.waytogo.cc | 103 | 0／0 | 與桃園觀音區關聯低（觀音山 ≠ 觀音區），保留紀錄並標示 |
| page_029 | article | success | vocus | 1688 | 2／0 |  |
| page_035 | article | success | NOWnews今日新聞 | 1146 | 4／0 |  |
| page_022_ext_01 | article_ext | success | 美食人生 | 1219 | 31／3 |  |
| page_022_ext_02 | article_ext | success | 美食人生 | 1702 | 23／2 |  |
| page_003_ext_01 | article_ext | success | 我的旅圖中 during my journey | 1538 | 29／1 |  |
| page_022_ext_03 | article_ext | success | 美食人生 | 1442 | 16／6 |  |
| page_036 | article | success | 食尚玩家 | 1145 | 10／0 |  |
| page_037 | article | success | 食尚玩家 | 794 | 2／0 |  |
| page_038 | article | success | 中央社 CNA | 1198 | 0／2 | 原文無新聞照片；作者取自內文「中央社記者」署名 |
| page_039 | article | success | 鏡週刊 Mirror Media | 2237 | 11／9 |  |
| page_040 | article | success | 輕旅行 | 2040 | 5／0 |  |
| page_041 | article | success | 微笑台灣 | 907 | 8／0 |  |

**影片（任務 4）**：D 負責的來源皆為文字文章，沒有需要處理的影片；影片字幕與代表畫面由組員 B 負責。

已知限制：

- 若網站改版、或之後改成 JavaScript 動態載入，正文少於 80 字會標記 `failed` 並寫明原因，需要更新 `SITE_RULES`。
- 網站回應 403／429 時記錄為 `unavailable`，不繞過限制。
- 圖片版權屬原作者或網站，只供課程作業使用；沒有圖說的圖片標示「（原網頁未提供圖說）」，對應段落記在 `context`。
