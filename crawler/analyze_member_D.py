#!/usr/bin/env python3
"""組員 D：資料整理與來源查證（任務 6）。

讀取 output/D/index.jsonl（crawler_member_D.py 的結果），產生：
  output/D/analysis/keywords_topics.csv   每篇 3–5 個關鍵字 + 主題分類
  output/D/analysis/duplicates.json       不同媒體之間重複／高度相似的段落與文章
  output/D/analysis/duplicates_D.md       可閱讀的重複敘述比對表（含同一景點在不同媒體的說法）
  output/D/analysis/claims_candidates.csv 程式自動找出的「可查核敘述」候選（狀態：待查核）
  output/D/analysis/fact_check_D.md       人工查核結果（媒體敘述 vs 官方資料，分開標示）
  output/D/knowledge_D.jsonl              整合後的知識資料：media_content 與 verification 分欄

只使用標準函式庫，不需額外安裝套件。可加 --compare-all 一起比對 output/A、B、C。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from urllib.parse import unquote, urlparse

try:  # 選用：pip install jieba
    import jieba.analyse as jieba_analyse
except ImportError:
    jieba_analyse = None

HERE = Path(__file__).resolve().parent

# 觀音區相關詞庫（關鍵字優先從這裡挑，避免斷詞錯誤）
LEXICON = [
    "白沙岬燈塔", "甘泉寺", "石觀音", "甘泉井", "草漯沙丘", "觀新藻礁", "藻礁", "大堀溪", "觀音溪", "新屋溪", "埤塘", "陂塘",
    "蓮花", "蓮花季", "向陽農場", "蓮荷園", "青林農場", "水之丘", "白千層", "綠色隧道", "鐵砲百合", "百合花",
    "崙坪文化地景園區", "崙坪", "客家", "客庄", "海客", "石滬", "牽罟", "防風林", "沙丘", "燈塔", "海岸",
    "觀音工業區", "大潭發電廠", "大潭", "樹林", "草漯", "保生", "新坡", "富源", "移民新村", "石門水庫", "泰雅族",
    "牛肉麵", "客家菜包", "草仔粿", "麵包", "景觀餐廳", "無菜單料理", "日式", "飛機", "廢墟", "打卡",
    "龜殼劇場", "好客食堂", "客家工藝館", "古剎", "三教合一", "觀音菩薩", "領海基點", "地質公園",
]
TOPIC_RULES = {
    "自然景觀": ["沙丘", "藻礁", "海岸", "溪", "防風林", "白千層", "綠色隧道", "花海", "百合", "濕地", "夕陽", "地質", "生態", "海景"],
    "歷史文化": ["清朝", "清代", "清乾隆", "清咸豐", "乾隆", "咸豐", "日治", "明治", "古蹟", "歷史", "寺", "廟", "觀音菩薩", "移民", "石滬", "牽罟", "客家", "文化", "紀念", "古剎"],
    "地方產業": ["工業區", "發電廠", "農場", "蓮花", "產業", "漁", "農", "工廠", "麵包工廠", "養殖"],
    "觀光景點": ["景點", "打卡", "一日遊", "步道", "燈塔", "園區", "門票", "停車", "營業時間", "拍照", "旅行"],
    "美食飲食": ["餐廳", "料理", "牛肉麵", "麵包", "菜包", "草仔粿", "咖啡", "小吃", "美食", "套餐", "甜點", "店家", "湯頭", "滷味", "食堂"],
}
# 「同一景點在不同媒體的說法」比對用
ENTITIES = ["白沙岬燈塔", "甘泉寺", "白千層", "草漯沙丘", "觀新藻礁", "崙坪", "向陽農場", "蓮荷園", "石滬", "飛機", "移民新村", "樹園子"]
STOP = set("的了是在有和與及也就都而但這那一個我們你他她它很更最還要會可以可能因為所以如果以及或是及其之為於從到被讓把對".replace("", " ").split())
NOISE_TERMS = ("時間", "日至", "優惠", "營業", "星期", "電話", "地址", "小時", "人次", "錢錢", "中央社", "記者", "編輯")
GENERIC_META = {"旅行", "生活", "旅人", "專欄", "風土", "台灣味", "微笑台灣", "319鄉鎮", "368鄉鎮", "誠食", "桃園市", "桃園", "居民", "工程", "建設", "紀念", "海邊", "3C"}
FACT_HINT = re.compile(r"\d{3,4}\s*年|民國\s*\d+|清(朝|代)?|乾隆|嘉慶|道光|咸豐|同治|光緒|明治|大正|昭和|日治|\d+(\.\d+)?\s*(公尺|公頃|公里|平方公里|戶|人|萬|億)|唯一|第一|最早|最大|最高|僅次")


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def paragraphs(text: str, min_len: int = 30) -> list[str]:
    return [p.strip() for p in re.split(r"\n+", text or "") if len(p.strip()) >= min_len]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[。！？!?])|\n", text or "") if len(s.strip()) >= 12]


def shingles(text: str, n: int = 4) -> set[str]:
    t = re.sub(r"[\s\W_]+", "", text)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def containment(a: set[str], b: set[str]) -> float:
    """短段落被長段落包含的比例（改寫、節錄時比 Jaccard 更敏感）。"""
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    return len(small & big) / len(small) if small else 0.0


# ---------------------------------------------------------------------------
def cjk_ngrams(text: str) -> Counter:
    c: Counter = Counter()
    for run in re.findall(r"[一-鿿]{2,}", text):
        for n in (2, 3, 4, 5, 6):
            for i in range(len(run) - n + 1):
                g = run[i:i + n]
                if not any(ch in STOP for ch in (g[0], g[-1])):
                    c[g] += 1
    return c


def keywords(records: list[dict]) -> dict[str, list[str]]:
    """詞庫命中優先；不足 5 個時用 TF-IDF（字元 n-gram）補足，並排除被已選詞包含的片段。"""
    meta = {r["id"]: r.get("meta_keywords") or [] for r in records}
    docs = {r["id"]: r.get("title", "") + "\n" + r.get("content", "") for r in records}
    grams = {i: cjk_ngrams(t) for i, t in docs.items()}
    df: Counter = Counter()
    for g in grams.values():
        df.update(set(g))
    n_docs = max(1, len(docs))
    result: dict[str, list[str]] = {}
    for rid, text in docs.items():
        picked: list[str] = []
        lex_hits = sorted(((text.count(w), w) for w in LEXICON if w in text), reverse=True)
        for cnt, w in lex_hits:
            if any(w in p for p in picked):
                continue  # 「燈塔」已被「白沙岬燈塔」涵蓋
            picked.append(w)
            if len(picked) >= 4:
                break
        meta_kw = [k for k in meta.get(rid, []) if 2 <= len(k) <= 8 and k in text and k not in GENERIC_META]
        for k in meta_kw:
            if len(picked) >= 4:
                break
            if not any(k in p or p in k for p in picked):
                picked.append(k)
        g_counts = grams[rid]

        def maximal(g: str, cnt: int) -> bool:
            # 「門水庫大」這種片段：存在更長且次數相近的詞（石門水庫大移民）就不選
            return not any(len(h) == len(g) + 1 and g in h and c >= 0.8 * cnt for h, c in g_counts.items())

        if jieba_analyse is not None:  # 有安裝 jieba 時用它的 TF-IDF 斷詞，結果較自然
            scored = [(0, w) for w in jieba_analyse.extract_tags(text, topK=15) if len(w) >= 2 and not w.isdigit()]
        else:
            scored = sorted(((cnt * math.log((1 + n_docs) / (1 + df[g])) * len(g), g) for g, cnt in g_counts.items()
                             if 2 <= len(g) <= 4 and cnt >= 3 and maximal(g, cnt)), reverse=True)
        for _, g in scored:
            if len(picked) >= 5:
                break
            if any(g in p or p in g for p in picked):
                continue
            if any(w in g for w in NOISE_TERMS):  # 營業時間、電話這類資訊不是主題關鍵字
                continue
            picked.append(g)
        picked = [w for w in picked if not any(w != o and w in o for o in picked)]  # 「燈塔」併入「白沙岬燈塔」
        result[rid] = picked[:5]
    return result


def topics(text: str) -> tuple[str, list[str], dict[str, int]]:
    scores = {t: sum(text.count(w) for w in words) for t, words in TOPIC_RULES.items()}
    top = max(scores.values()) if scores else 0
    labels = [t for t, s in sorted(scores.items(), key=lambda x: -x[1]) if top and s >= max(2, top * 0.5)]
    return (labels[0] if labels else "未分類"), labels, scores


# ---------------------------------------------------------------------------
def find_duplicates(records: list[dict], para_threshold: float = 0.5, doc_threshold: float = 0.3) -> dict:
    paras = [(r["id"], r.get("source_name", ""), p, shingles(p)) for r in records for p in paragraphs(r.get("content", ""))]
    para_pairs = []
    for (ia, sa, pa, ha), (ib, sb, pb, hb) in combinations(paras, 2):
        if ia == ib:
            continue
        score = containment(ha, hb)
        if score >= para_threshold:
            para_pairs.append({"a": ia, "b": ib, "score": round(score, 3), "a_text": pa[:160], "b_text": pb[:160]})
    para_pairs.sort(key=lambda x: -x["score"])

    doc_sh = {r["id"]: shingles(r.get("content", "")) for r in records}
    doc_pairs = []
    for a, b in combinations(doc_sh, 2):
        j = jaccard(doc_sh[a], doc_sh[b])
        if j >= doc_threshold:
            doc_pairs.append({"a": a, "b": b, "jaccard": round(j, 3)})

    entity_mentions: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        for ent in ENTITIES:
            hits = [s for s in sentences(r.get("content", "")) if ent in s]
            if hits:
                entity_mentions[ent].append({"id": r["id"], "source": r.get("source_name", ""), "sentences": hits[:3]})
    shared = {e: v for e, v in entity_mentions.items() if len(v) >= 2}
    return {"paragraph_pairs": para_pairs, "document_pairs": doc_pairs, "shared_entities": shared}


def claim_candidates(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        for s in sentences(r.get("content", "")):
            if FACT_HINT.search(s) and any(e in s for e in ENTITIES + ["觀音", "燈塔", "寺", "沙丘", "移民"]):
                out.append({"id": r["id"], "source_name": r.get("source_name", ""), "sentence": s[:200],
                            "hint": FACT_HINT.search(s).group(0), "status": "待查核"})
    return out


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "output" / "D")  # 固定為專案根目錄的 output/D
    ap.add_argument("--fact-check", type=Path, default=HERE / "fact_check_D.json")
    ap.add_argument("--compare-all", action="store_true", help="一起比對 output/A、B、C 的資料（偵測跨組重複）")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):  # Windows 終端機（cp950）印中文不出錯
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    all_records = load(args.output / "index.jsonl")
    records = [r for r in all_records if r.get("crawl_status") == "success" and r.get("content")]
    others = []
    if args.compare_all:
        for m in "ABC":
            others += [r for r in load(args.output.parent / m / "index.jsonl") if r.get("crawl_status") == "success" and r.get("content")]
    if not records:
        print("找不到成功的 D 資料，請先執行 crawler_member_D.py")
        return 1
    ana = args.output / "analysis"
    ana.mkdir(parents=True, exist_ok=True)

    kw = keywords(records + others)
    rows = []
    for r in records:
        primary, labels, scores = topics(r.get("title", "") + r.get("content", ""))
        r["_kw"], r["_topic"], r["_topics"] = kw[r["id"]], primary, labels
        rows.append({"id": r["id"], "title": r.get("title", ""), "source_name": r.get("source_name", ""),
                     "media_type": r.get("media_type", ""), "author": r.get("author", ""), "published_at": r.get("published_at", ""),
                     "keywords": "、".join(kw[r["id"]]), "primary_topic": primary, "topics": "、".join(labels),
                     "topic_scores": json.dumps(scores, ensure_ascii=False)})
    with (ana / "keywords_topics.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    dup = find_duplicates(records + others)
    (ana / "duplicates.json").write_text(json.dumps(dup, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# D：不同媒體的重複／相似敘述比對", "",
          "方法：段落以 4 字元 shingle 計算「包含率」（短段落有多少比例出現在另一段），≥ 0.5 視為重複或改寫；"
          "整篇文章以 Jaccard 相似度 ≥ 0.3 視為高度相似。另列出同一景點在不同媒體中的敘述，方便人工比對差異。", "",
          "## 段落層級重複", "", "| A | B | 包含率 | A 段落 | B 段落 |", "| --- | --- | --- | --- | --- |"]
    md += [f"| {p['a']} | {p['b']} | {p['score']} | {p['a_text'][:60]} | {p['b_text'][:60]} |" for p in dup["paragraph_pairs"][:40]] or ["| — | — | — | 沒有找到重複段落 | |"]
    md += ["", "## 文章層級相似", ""] + ([f"- {p['a']} ↔ {p['b']}：Jaccard {p['jaccard']}" for p in dup["document_pairs"]] or ["- 沒有高度相似的整篇文章（各媒體多為原創撰寫）"])
    md += ["", "## 同一景點在不同媒體的敘述", ""]
    for ent, items in dup["shared_entities"].items():
        md.append(f"### {ent}（{len(items)} 個來源）")
        for it in items:
            md.append(f"- **{it['id']}**（{it['source']}）：" + " / ".join(s[:90] for s in it["sentences"]))
        md.append("")
    (ana / "duplicates_D.md").write_text("\n".join(md), encoding="utf-8")

    claims = claim_candidates(records)
    with (ana / "claims_candidates.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "source_name", "sentence", "hint", "status"])
        w.writeheader()
        w.writerows(claims)

    checks = json.loads(args.fact_check.read_text(encoding="utf-8"))["checks"] if args.fact_check.exists() else []
    fc = ["# D：媒體敘述與官方資料查核", "",
          "> 媒體／部落格內容只當作參考起點。下表左欄是媒體原文敘述（未經證實），右欄是官方或政府資料。"
          "判定只依官方資料，查不到佐證的部分標記「未證實」，不以 AI 推測補上。", ""]
    for c in checks:
        fc += [f"## {c['claim_id']}　{c['topic']}　→ **{c['verdict']}**", "",
               f"**媒體敘述**（urls.csv：{c['media_source_id']}，{c['media_source_url']}）", "", f"> {c['media_claim']}", "",
               "**官方／政府資料**", ""]
        fc += [f"- [{e['name']}]({e['url']})：{e['summary']}" for e in c["official_evidence"]]
        fc += [f"- （其他）[{e['name']}]({e['url']})：{e['summary']}" for e in c.get("also_seen_in", [])]
        fc += ["", f"**說明**：{c['note']}", ""]
    fc += ["## 其他程式找到、尚未人工查核的敘述", "", f"共 {len(claims)} 句，見 claims_candidates.csv（狀態皆為「待查核」）。", ""]
    (ana / "fact_check_D.md").write_text("\n".join(fc), encoding="utf-8")

    # 查核紀錄用「網址」對應到資料（互動模式的編號是 D-001…，不一定等於 urls.csv 的 page_xxx）
    def url_key(u: str) -> str:
        p = urlparse(unquote(u or "").strip())
        host = (p.hostname or "").lower().removeprefix("www.").replace("romantichakka.hakka.gov.tw", "romantichakka.com")
        q = "&".join(sorted(x for x in p.query.split("&") if x and not re.match(r"(utm_|guccounter|guce_|fbclid|si=)", x)))
        return f"{host}{p.path.rstrip('/')}?{q}"

    check_by_url = defaultdict(list)
    for c in checks:
        check_by_url[url_key(c["media_source_url"])].append(
            {k: c[k] for k in ("claim_id", "topic", "media_claim", "verdict", "official_evidence", "note")})
    by_id = {r["id"]: check_by_url.get(url_key(r.get("source_url", ""))) or check_by_url.get(url_key(r.get("final_url", ""))) or []
             for r in records}
    dup_map = defaultdict(set)
    for p in dup["paragraph_pairs"]:
        dup_map[p["a"]].add(p["b"])
        dup_map[p["b"]].add(p["a"])
    with (args.output / "knowledge_D.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            item = {
                "id": r["id"], "type": r.get("type", "web"), "title": r.get("title", ""), "source_url": r.get("source_url", ""),
                "source_name": r.get("source_name", ""), "media_type": r.get("media_type", ""), "author": r.get("author", ""),
                "published_at": r.get("published_at", ""), "crawled_at": r.get("crawled_at", ""),
                "keywords": r["_kw"], "primary_topic": r["_topic"], "topics": r["_topics"],
                "media_content": {"data_nature": "media（媒體／部落格內容，未經查核）", "content": r.get("content", ""),
                                  "images": r.get("images", []), "links": r.get("content_links", [])},
                "verification": {"status": "partially_checked" if by_id.get(r["id"]) else "unverified",
                                 "checks": by_id.get(r["id"], [])},
                "similar_to": sorted(dup_map.get(r["id"], [])),
                "guanyin_relevance": r.get("guanyin_relevance", {}),
            }
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    tbl = ["# D：爬取結果與失敗紀錄（由 analyze_member_D.py 自動產生）", "",
           "| id | 狀態 | 網站 | 作者 | 日期 | 正文字數 | 圖片保存／排除 | 觀音區相關度 | 失敗原因／提醒 |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in all_records:
        rel = r.get("guanyin_relevance") or {}
        tbl.append(f"| {r.get('id')} | {r.get('crawl_status')} | {r.get('source_name', '')} | {r.get('author') or '未標示'} | "
                   f"{r.get('published_at') or '未標示'} | {r.get('content_length', len(r.get('content', '')))} | "
                   f"{len(r.get('images', []))}／{len(r.get('images_rejected', []))} | {rel.get('level', '')}（{rel.get('mentions', '')}） | "
                   f"{(r.get('failure_reason') or '') + (r.get('relevance_warning') or '')} |")
    (ana / "crawl_summary_D.md").write_text("\n".join(tbl) + "\n", encoding="utf-8")

    print(f"keywords/topics: {len(rows)} 篇；重複段落 {len(dup['paragraph_pairs'])} 組；共同景點 {len(dup['shared_entities'])} 個；"
          f"查核候選 {len(claims)} 句；人工查核 {len(checks)} 筆 → {ana}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
