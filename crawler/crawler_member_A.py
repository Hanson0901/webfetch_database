#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
member-A 爬蟲：維基百科／歷史地理／文化知識（桃園市觀音區）

只用標準函式庫 + lxml + Pillow，不需要 requests／bs4／trafilatura。
（本機 Python 環境未安裝上述套件，故以 urllib + curl 備援 + lxml 實作。）

用法：
    python3 crawler/crawler_member_A.py                 # 爬 urls_member_A.csv 全部 7 筆 + 一層延伸頁
    python3 crawler/crawler_member_A.py --only page_010 # 只爬指定 id
    python3 crawler/crawler_member_A.py --no-images     # 不下載圖片
    python3 crawler/crawler_member_A.py --delay 0.5     # 每次請求間隔

輸出：
    output/index.jsonl          每頁一筆結構化資料
    output/articles/*.md        清理後正文（含圖片對應、連結、來源）
    output/images/*.jpg         去重後圖片
    output/raw/*.html           原始 HTML 快照（供重現／截圖）
    output/crawl_report.csv     每頁 success/partial/failed 與原因
    output/duplicates.json      跨頁相似度（Jaccard）判定
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import ssl
import subprocess
import tempfile
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

from lxml import html as LH

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")
ARTICLES = os.path.join(OUT, "articles")
IMAGES = os.path.join(OUT, "images")
RAW = os.path.join(OUT, "raw")
VIDEOS = os.path.join(OUT, "videos")
REPORT = os.path.join(OUT, "crawl_report.csv")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.6",
}
TZ = timezone(timedelta(hours=8))

# headless Chrome：用於 SPA 頁面的實際渲染（本機已安裝 Google Chrome）
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_PROFILE = os.path.join(ROOT, ".chrome-profile")


def chrome_available():
    return os.path.exists(CHROME)


def chrome_dom(url, timeout=60):
    """以 headless Chrome 執行頁面 JS 後取回完整 DOM（不是用推測補內容）。"""
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
           "--disable-extensions", "--user-data-dir=" + CHROME_PROFILE,
           "--virtual-time-budget=15000", "--dump-dom", url]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        out = p.stdout.decode("utf-8", "ignore")
        return out if "</html>" in out.lower() else ""
    except Exception:
        return ""


# 每個來源的主題分類（依作業要求：自然景觀／歷史文化／地方產業／觀光景點）
CATEGORY = {
    "page_001": ("歷史文化", ["觀音區", "石觀音", "地名由來", "桃園市", "沿海"]),
    "page_010": ("歷史文化", ["甘泉寺", "石觀音", "觀音信仰", "甘泉井", "桃園觀音"]),
    "page_015": ("自然景觀", ["觀音坑溪", "五股區", "淡水河", "同名錯置", "新北市"]),
    "page_016": ("自然景觀", ["大堀溪", "市管河川", "觀音區", "蓮花", "流域"]),
    "page_020": ("地方產業", ["大潭發電廠", "台電", "天然氣", "觀音區", "電力"]),
    "page_028": ("歷史文化", ["石門水庫", "移民新村", "草漯", "文化資產", "國家文化記憶庫"]),
    "page_031": ("歷史文化", ["原住民族文獻", "泰雅族", "石門水庫", "卡拉社", "口述歷史"]),
}

SOURCE_NAME = {
    "zh.wikipedia.org": "維基百科（中文）",
    "tcmb.culture.tw": "文化部 國家文化記憶庫",
    "ihc.cip.gov.tw": "原住民族委員會《原住民族文獻》",
    "wrb.tycg.gov.tw": "桃園市政府水務局",
    "www.guanyin-hro.tycg.gov.tw": "桃園市觀音區戶政事務所",
    "www.guanyin.tycg.gov.tw": "桃園市觀音區公所",
    "travel.tycg.gov.tw": "桃園觀光導覽網",
    "culture.tycg.gov.tw": "桃園市政府文化局",
    "news.tycg.gov.tw": "桃園市政府新聞處",
    "service.taipower.com.tw": "台電月刊",
    "ea01.moeaea.gov.tw": "經濟部能源署",
}

WIKI_DROP = (
    "mw-editsection", "navbox", "vertical-navbox", "navbox-styles", "metadata",
    "ambox", "reflist", "references", "mw-references-wrap", "toc", "sistersitebox",
    "hatnote", "printfooter", "catlinks", "mw-jump-link", "noprint", "mw-empty-elt",
    "shortdescription", "mw-authority-control", "side-box", "mbox-small", "portal",
    "mw-indicators", "thumbcaption-empty",
)
BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "p", "li", "figcaption", "blockquote",
              "dt", "dd", "caption", "pre"}
SKIP_TAGS = {"script", "style", "noscript", "iframe", "svg", "button", "form",
             "select", "input", "video", "audio", "canvas", "template"}

IMG_ATTRS = ("src", "data-src", "data-original", "data-lazy-src", "data-actualsrc",
             "data-echo", "srcset", "data-srcset")
IMG_BAD_PAT = re.compile(
    r"(logo|icon|sprite|spacer|pixel|tracking|badge|button|avatar|emoji|placeholder|"
    r"loading|arrow|bullet|share|facebook|twitter|line_|plurk|youtube_|ad_|ads/|banner)",
    re.I)
JUNK_LINE = re.compile(
    r"^(跳至主要內容|跳到主要內容|::: ?首頁|首頁 ?[>／/]|選單|網站導覽|字級|分享|"
    r"回上一頁|上一頁|下一頁|列印|轉寄|您的瀏覽器|本網站需要JavaScript|"
    r"定位點|關閉|搜尋|English|桃園市政府$|手機版選單)")


def now_iso():
    return datetime.now(TZ).replace(microsecond=0).isoformat()


def norm_space(s):
    s = s.replace("\u3000", " ").replace("\xa0", " ")
    s = re.sub(r"\[[0-9]{1,3}\]", "", s)      # 維基註腳編號
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def domain_of(url):
    try:
        return urllib.parse.urlsplit(url).netloc.lower()
    except Exception:
        return ""


def source_name(url):
    d = domain_of(url)
    for k, v in SOURCE_NAME.items():
        if d == k or d.endswith("." + k):
            return v
    return d or "未知來源"


def sha1(s):
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()


def ensure_dirs():
    for d in (OUT, ARTICLES, IMAGES, RAW, VIDEOS):
        os.makedirs(d, exist_ok=True)


def _decode(raw, ctype):
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I)
    enc = m.group(1) if m else "utf-8"
    for e in (enc, "utf-8", "big5", "gb18030"):
        try:
            return raw.decode(e)
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


def _curl(url, timeout=60):
    """以 curl 取得內容；身體寫入暫存檔，狀態碼由 -w 單獨輸出，避免二進位內容干擾解析。"""
    fd, tmp = tempfile.mkstemp(prefix="fetch_", suffix=".bin")
    os.close(fd)
    cmd = ["curl", "-sS", "-L", "--compressed", "-m", str(timeout),
           "--retry", "3", "--retry-delay", "3", "--retry-all-errors",
           "-A", UA, "-H", "Accept-Language: zh-TW,zh;q=0.9",
           "-o", tmp, "-w", "%{http_code}", url]
    try:
        p = subprocess.run(cmd, capture_output=True)
        code = 0
        try:
            code = int((p.stdout or b"").strip() or 0)
        except Exception:
            code = 0
        body = b""
        try:
            with open(tmp, "rb") as f:
                body = f.read()
        except Exception:
            body = b""
        if p.returncode != 0 and not body:
            raise RuntimeError("curl exit %s: %s" % (p.returncode, p.stderr.decode("utf-8", "ignore")[:160]))
        if code >= 400 or (code == 0 and not body):
            raise RuntimeError("HTTP %s" % (code or "無回應"))
        return code, body
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def fetch(url, timeout=30, attempts=4):
    """先 urllib，失敗改用 curl（部分 .gov.tw 對 urllib 的 TLS 握手會直接斷線）。

    tycg.gov.tw 系列在短時間連續請求時會間歇性斷線／逾時，因此同一網址重試最多 attempts 次，
    每次間隔 3 秒，並在最後一次改走 curl。
    """
    last_info, last_text = None, ""
    for i in range(attempts):
        info, text = fetch_once(url, timeout=timeout, use_curl_last=(i % 2 == 1))
        if text:
            info["retries"] = i
            return info, text
        last_info, last_text = info, text
        if i < attempts - 1:
            time.sleep(2)
    last_info["retries"] = attempts - 1
    return last_info, last_text


def fetch_once(url, timeout=30, use_curl_last=False):
    info = {"url": url, "final_url": url, "status": 0, "engine": "urllib",
            "content_type": "", "error": "", "seconds": 0.0}
    t0 = time.time()
    raw, ctype = b"", ""
    try:
        if use_curl_last:
            raise RuntimeError("直接改用 curl")
        req = urllib.request.Request(url, headers=HEADERS)
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read()
            info["status"] = getattr(r, "status", 200) or 200
            info["final_url"] = r.geturl()
            ctype = r.headers.get("Content-Type", "")
    except Exception as e1:
        info["engine"] = "curl"
        try:
            code, raw = _curl(url, timeout=timeout * 2)
            info["status"] = code
            ctype = ""
            info["final_url"] = url
        except Exception as e2:
            info["error"] = "%s / curl: %s" % (e1, e2)
            info["seconds"] = round(time.time() - t0, 2)
            return info, ""
    info["content_type"] = ctype
    info["seconds"] = round(time.time() - t0, 2)
    return info, _decode(raw, ctype)


def _strip(el, classes):
    for c in classes:
        for n in el.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' %s ')]" % c):
            if n.getparent() is not None:
                n.getparent().remove(n)
    for n in el.xpath(".//sup[contains(@class,'reference')]"):
        if n.getparent() is not None:
            n.getparent().remove(n)


def pick_content(doc, url):
    """回傳 (element, strategy, partial_reason)。依站別挑選正文容器。"""
    host = domain_of(url)

    if "wikipedia.org" in host:
        main = doc.xpath("//div[@id='mw-content-text']//div[contains(@class,'mw-parser-output')]")
        if not main:
            main = doc.xpath("//div[@id='mw-content-text']")
        if main:
            el = main[0]
            _strip(el, WIKI_DROP)
            return el, "wikipedia:mw-parser-output", ""

    if "tcmb.culture.tw" in host:
        for xp in ("//*[@id='index_main']", "//div[contains(@class,'material_detail')]",
                   "//div[contains(@class,'container-fluid')]"):
            n = doc.xpath(xp)
            if n and len(norm_space(n[0].text_content())) > 80:
                return n[0], "tcmb:index_main", ""

    if "ihc.cip.gov.tw" in host:
        n = doc.xpath("//div[contains(@class,'mainArea')]") or doc.xpath("//main")
        if n:
            _strip(n[0], ["breadcrumb", "nav"])
            return n[0], "ihc:mainArea", ""

    if "tycg.gov.tw" in host and "travel.tycg.gov.tw" not in host:
        # CCMS 版型（文化局、新聞處）：正文在 #CCMS_Content；區公所／水務局用 .area-editor
        n = doc.xpath("//*[@id='CCMS_Content']") or doc.xpath("//div[contains(@class,'area-editor')]")
        if n:
            holder = LH.Element("div")
            for x in n:
                holder.append(x)
            return holder, "tycg:CCMS_Content/area-editor", ""

    best, best_score = None, 0
    for el in doc.xpath("//article|//main|//div|//section"):
        cls = (el.get("class") or "") + " " + (el.get("id") or "")
        if re.search(r"(nav|menu|footer|header|sidebar|comment|share|related|breadcrumb)", cls, re.I):
            continue
        t = norm_space(el.text_content())
        if len(t) < 200:
            continue
        link_len = sum(len(norm_space(a.text_content())) for a in el.xpath(".//a"))
        own = len(t) - link_len
        score = own * (1.6 if re.search(r"(content|article|post|entry|main|detail|editor)", cls, re.I) else 1.0)
        if score > best_score:
            best, best_score = el, score
    if best is not None:
        return best, "generic:max-text-density", ""
    return None, "none", "找不到可辨識的正文容器"


def to_markdown(el):
    """把 HTML 區塊轉成保留段落／標題／清單／表格的文字。"""
    lines = []

    def walk(node):
        tag = node.tag if isinstance(node.tag, str) else ""
        if tag in SKIP_TAGS:
            return
        if tag == "table":
            for tr in node.xpath(".//tr"):
                cells = [norm_space(c.text_content()) for c in tr.xpath("./th|./td")]
                cells = [c for c in cells if c]
                if cells:
                    lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
            return
        if tag in BLOCK_TAGS:
            txt = norm_space(node.text_content())
            if txt:
                if tag in ("h1", "h2", "h3", "h4", "h5"):
                    lvl = {"h1": "##", "h2": "##", "h3": "###", "h4": "####", "h5": "#####"}[tag]
                    lines.append("")
                    lines.append("%s %s" % (lvl, txt))
                elif tag == "li":
                    lines.append("- " + txt)
                elif tag == "figcaption":
                    lines.append("*圖說：%s*" % txt)
                elif tag == "blockquote":
                    lines.append("> " + txt)
                else:
                    lines.append(txt)
            return
        for ch in node:
            walk(ch)

    for ch in el:
        walk(ch)

    out, prev = [], None
    for ln in lines:
        t = ln.rstrip()
        if not t.strip():
            if out and out[-1] != "":
                out.append("")
            continue
        if JUNK_LINE.match(t) and len(t) < 40:
            continue
        if t == prev:
            continue
        out.append(t)
        prev = t
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def page_meta(doc):
    meta = {"description": "", "og_image": [], "jsonld": [], "published": ""}
    for m in doc.xpath("//meta"):
        key = (m.get("name") or m.get("property") or m.get("itemprop") or "").lower()
        val = m.get("content") or ""
        if not val:
            continue
        if key in ("description", "og:description"):
            if len(val) > len(meta["description"]):
                meta["description"] = val
        elif key in ("og:image", "twitter:image"):
            meta["og_image"].append(urllib.parse.urljoin("https:", val) if val.startswith("//") else val)
        elif key in ("article:published_time", "date", "pubdate", "og:published_time"):
            meta["published"] = meta["published"] or val
    for s in doc.xpath("//script[@type='application/ld+json']"):
        try:
            meta["jsonld"].append(json.loads(s.text or "{}"))
        except Exception:
            continue
    return meta


def meta_text(meta):
    """SPA 頁面用：description + JSON-LD 的 name/description/address/geo。"""
    parts = []
    if meta["description"]:
        parts.append(meta["description"])
    for d in meta["jsonld"]:
        items = d if isinstance(d, list) else [d]
        for it in items:
            if not isinstance(it, dict):
                continue
            bits = []
            for k in ("name", "description", "address", "geo"):
                v = it.get(k)
                if isinstance(v, dict):
                    v = " ".join(x for x in v.values() if isinstance(x, str))
                if isinstance(v, str) and v:
                    bits.append(v)
            if bits:
                parts.append("；".join(dict.fromkeys(bits)))
    return "\n\n".join(dict.fromkeys(p for p in parts if p))


def candidate_images(doc, page_url):
    cands, seen = [], set()
    for img in doc.xpath("//img"):
        src = ""
        for a in IMG_ATTRS:
            v = img.get(a) or ""
            if not v:
                continue
            if a in ("srcset", "data-srcset"):
                first = [p.strip().split(" ")[0] for p in v.split(",") if p.strip()]
                v = first[-1] if first else ""
            if v:
                src = v
                break
        if not src or src.startswith("data:"):
            continue
        src = urllib.parse.urljoin(page_url, src.strip())
        if src.startswith("//"):
            src = "https:" + src
        low = src.lower()
        if low.endswith((".svg", ".gif", ".ico")):
            continue
        if IMG_BAD_PAT.search(src) and "upload.wikimedia" not in low:
            continue
        if src in seen:
            continue
        try:
            w = int(re.sub(r"\D", "", img.get("width") or "0") or 0)
            h = int(re.sub(r"\D", "", img.get("height") or "0") or 0)
        except Exception:
            w = h = 0
        if w and h and w < 150 and h < 150:
            continue
        alt = norm_space(img.get("alt") or "")
        cap = ""
        par = img.getparent()
        for _ in range(4):
            if par is None:
                break
            fcs = par.xpath(".//figcaption")
            if fcs:
                cap = norm_space(fcs[0].text_content())
                break
            par = par.getparent()
        seen.add(src)
        cands.append({"url": src, "alt": alt, "caption": cap or alt})
    return cands


def wiki_full_url(u, width=900):
    """維基縮圖改成固定寬度並移除追蹤參數，避免下載到 250px 小圖。"""
    if "wikimedia.org" in u and "/thumb/" in u:
        u = u.split("?")[0]
        u = re.sub(r"/\d+px-", "/%dpx-" % width, u)
    return u


def _curl_bytes(url, referer="", timeout=45):
    cmd = ["curl", "-sS", "-L", "--compressed", "-m", str(timeout), "-A", UA,
           "-w", "\n__HTTP_CODE__%{http_code}", url]
    if referer:
        cmd[1:1] = ["-e", referer]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("curl exit %s" % p.returncode)
    body, idx = p.stdout, p.stdout.rfind(b"\n__HTTP_CODE__")
    code = 0
    if idx >= 0:
        try:
            code = int(body[idx + 15:].strip() or 0)
        except Exception:
            code = 0
        body = body[:idx]
    if code >= 400 or code == 0:
        raise RuntimeError("HTTP %s" % (code or "無回應"))
    return body


def download_image(url, out_path, referer=""):
    try:
        headers = dict(HEADERS)
        headers["Accept"] = "image/avif,image/webp,image/png,image/*,*/*;q=0.8"
        if referer:
            headers["Referer"] = referer
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=40, context=ssl.create_default_context()) as r:
                data = r.read()
        except Exception:
            data = _curl_bytes(url, referer=referer)
        if len(data) < 3000:
            return False, "檔案過小（%d bytes）" % len(data)
        if Image is None:
            return False, "無 Pillow，僅能記錄 URL"
        im = Image.open(io.BytesIO(data))
        im.load()
        if im.width < 200 or im.height < 150:
            return False, "尺寸過小（%dx%d）" % (im.width, im.height)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        im.save(out_path, "JPEG", quality=85, optimize=True)
        return True, "%dx%d" % (im.width, im.height)
    except Exception as e:
        return False, str(e)[:160]


def extract_links(doc, page_url):
    links, seen = [], set()
    host = domain_of(page_url)
    for a in doc.xpath("//a[@href]"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        u = urllib.parse.urljoin(page_url, href)
        if not u.startswith("http"):
            continue
        u = u.split("#")[0]
        if u in seen:
            continue
        seen.add(u)
        links.append({"url": u, "text": norm_space(a.text_content())[:80],
                      "internal": domain_of(u) == host})
    return links


def shingles(text, k=5):
    t = re.sub(r"\s+", "", text)
    if len(t) <= k:
        return {hash(t)} if t else set()
    return {hash(t[i:i + k]) for i in range(0, len(t) - k, 2)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def parse_date(meta, content):
    if meta.get("published"):
        return str(meta["published"])[:10]
    m = re.search(r"日期[：:]\s*(\d{2,3})-(\d{2})-(\d{2})", content)
    if m:
        y = int(m.group(1))
        y = y + 1911 if y < 1911 else y
        return "%04d-%s-%s" % (y, m.group(2), m.group(3))
    m = re.search(r"(20\d{2})[/\-年](\d{1,2})[/\-月](\d{1,2})", content)
    if m:
        return "%04d-%02d-%02d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"第\s*\d+\s*期\s*(20\d{2})[/\-](\d{1,2})", content)
    if m:
        return "%s-%02d" % (m.group(1), int(m.group(2)))
    return ""


def license_note(u):
    if "upload.wikimedia.org" in u:
        return "Wikimedia Commons 檔案（授權見原檔頁；轉存僅供作業引用）"
    if "culture.tw" in u:
        return "文化部國家文化記憶庫（頁面標示 CC BY 3.0 TW）"
    if "tycg.gov.tw" in u:
        return "桃園市政府網站（政府網站資料開放宣告）"
    if "ihc.cip.gov.tw" in u:
        return "原住民族委員會《原住民族文獻》（政府出版品）"
    if "taipower" in u:
        return "台電（台灣電力公司）網站"
    return "來源網站內容，授權狀態未標示"


def _dedupe_str(items):
    seen, out = set(), []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


def process(page_id, url, kind, seed_id=None, args=None):
    args = args or {}
    cat, kws = CATEGORY.get(seed_id or page_id, ("歷史文化", []))
    rec = {
        "id": page_id,
        "type": "article" if kind == "seed" else "article_ext",
        "parent_id": seed_id or "",
        "title": "",
        "source_url": url,
        "final_url": url,
        "source_name": source_name(url),
        "content": "",
        "images": [],
        "links": [],
        "timestamps": {"published": "", "crawled_at": now_iso()},
        "crawl_status": "failed",
        "crawled_at": now_iso(),
        "category": cat,
        "keywords": list(kws),
        "strategy": "",
        "notes": [],
        "media": {"video_tags": 0, "audio_tags": 0, "iframes": []},
        "http_status": 0,
        "engine": "",
        "error": "",
        "content_hash": "",
        "chars": 0,
    }

    info, text = fetch(url, timeout=args.get("timeout", 30))
    rec["http_status"] = info["status"]
    rec["final_url"] = info["final_url"]
    rec["engine"] = info["engine"]
    if not text:
        rec["error"] = info.get("error") or "無回應內容"
        return rec, None

    try:
        with open(os.path.join(RAW, "%s.html" % page_id), "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass

    try:
        doc = LH.fromstring(text)
    except Exception as e:
        rec["error"] = "HTML 解析失敗：%s" % e
        return rec, None

    for bad in doc.xpath("//script|//style|//noscript"):
        bad.getparent().remove(bad)

    h1 = norm_space(doc.xpath("string(//h1)") or "")
    ttl = norm_space(doc.xpath("string(//title)") or "")
    ttl = re.sub(r"\s*[-–—|]\s*(维基百科|維基百科).*$", "", ttl) or ttl
    if h1 and ttl and h1 in ttl:
        rec["title"] = ttl[:160]
    else:
        rec["title"] = (ttl or h1)[:160]

    meta = page_meta(doc)
    el, strategy, why = pick_content(doc, url)
    body = to_markdown(el) if el is not None else ""
    rec["strategy"] = strategy

    if len(body) < 200 and chrome_available() and not args.get("no_render"):
        html2 = chrome_dom(url)
        if html2:
            try:
                with open(os.path.join(RAW, "%s.rendered.html" % page_id), "w", encoding="utf-8") as f:
                    f.write(html2)
                doc = LH.fromstring(html2)
                for bad in doc.xpath("//script|//style|//noscript"):
                    if bad.getparent() is not None:
                        bad.getparent().remove(bad)
                meta = page_meta(doc)
                el2, strategy2, why2 = pick_content(doc, url)
                body2 = to_markdown(el2) if el2 is not None else ""
                if len(body2) > len(body) + 100:
                    body = body2
                    rec["strategy"] = "chrome-headless+" + strategy2
                    rec["rendered"] = True
                    rec["notes"].append("伺服器端只回傳框架：改以 headless Chrome 實際執行 JS 後擷取正文（非推測內容）。")
            except Exception as e:
                rec["notes"].append("Chrome 渲染失敗：%s" % str(e)[:80])

    if len(body) < 200:
        mt = meta_text(meta)
        if len(mt) > len(body):
            body = mt
            rec["strategy"] = rec["strategy"] + "+meta/JSON-LD"
        if len(body) < 120:
            rec["crawl_status"] = "partial" if body else "failed"
            rec["error"] = why or "正文擷取不足（可能為前端渲染 SPA）"
            rec["notes"].append("伺服器端僅回傳框架，且 headless 渲染未取得正文；內容僅取自 meta description／JSON-LD。")
        else:
            rec["crawl_status"] = "success"
            rec["notes"].append("頁面屬公告／摘要型，正文本身較短（已完整擷取）；完整內容另見頁面附件連結。")
    else:
        rec["crawl_status"] = "success"

    rec["content"] = body.strip()
    rec["chars"] = len(rec["content"])
    rec["content_hash"] = sha1(re.sub(r"\s+", "", rec["content"]))[:16]
    rec["timestamps"]["published"] = parse_date(meta, rec["content"])

    rec["media"]["video_tags"] = len(doc.xpath("//video"))
    rec["media"]["audio_tags"] = len(doc.xpath("//audio"))
    rec["media"]["iframes"] = [i.get("src") for i in doc.xpath("//iframe[@src]")][:10]
    rec["videos"] = []
    if not (rec["media"]["video_tags"] or rec["media"]["audio_tags"] or rec["media"]["iframes"]):
        rec["notes"].append("此頁未偵測到 video／audio 標籤或嵌入播放器，無合法可處理影片。")

    rec["links"] = extract_links(doc, url)
    if strategy.startswith(("generic", "wikipedia")):
        rec["links"] = [l for l in rec["links"] if "Special:" not in l["url"]][:300]
    rec["attachments"] = _dedupe_str([l["url"] for l in rec["links"]
                                 if re.search(r"\.pdf($|\?)|Download\.ashx", l["url"], re.I)])[:10]

    if not args.get("no_images"):
        cands = candidate_images(doc, url)
        if not cands:
            cands = [{"url": u, "alt": "", "caption": ""} for u in meta["og_image"][:9]]
        limit = 8 if kind == "seed" else 4
        saved = 0
        used = set()
        for c in cands:
            if saved >= limit:
                break
            u = wiki_full_url(c["url"]) if "upload.wikimedia" in c["url"] else c["url"]
            fname = "%s_image_%02d.jpg" % (page_id, saved + 1)
            path = os.path.join(IMAGES, fname)
            ok, detail = download_image(u, path, referer=url)
            if not ok:
                rec["notes"].append("圖片略過：%s（%s）" % (u, detail))
                continue
            with open(path, "rb") as f:
                h = hashlib.sha256(f.read()).hexdigest()[:16]
            if h in used:
                os.remove(path)
                continue
            used.add(h)
            saved += 1
            rec["images"].append({
                "file": "output/images/" + fname,
                "original_url": u,
                "page_url": url,
                "article_id": page_id,
                "caption": c.get("caption") or c.get("alt") or "",
                "width_height": detail,
                "sha256_16": h,
                "license_note": license_note(u),
            })
        if not rec["images"]:
            rec["notes"].append("無合適內文圖片（已排除 logo／icon／追蹤像素／社群按鈕）。")
    return rec, doc


def write_article(rec):
    p = os.path.join(ARTICLES, "%s.md" % rec["id"])
    L = []
    L.append("# %s" % (rec["title"] or rec["id"]))
    L.append("")
    L.append("- id：%s" % rec["id"])
    L.append("- 類型：%s" % rec["type"])
    L.append("- 原始網址：%s" % rec["source_url"])
    L.append("- 網站名稱：%s" % rec["source_name"])
    L.append("- 擷取策略：%s" % rec["strategy"])
    L.append("- 爬取狀態：**%s**（HTTP %s）" % (rec["crawl_status"], rec["http_status"]))
    L.append("- 發佈／更新日期：%s" % (rec["timestamps"]["published"] or "未標示"))
    L.append("- 爬取時間：%s" % rec["crawled_at"])
    L.append("- 分類：%s" % rec["category"])
    L.append("- 關鍵字：%s" % "、".join(rec["keywords"]))
    if rec["notes"]:
        L.append("- 備註：")
        for n in rec["notes"]:
            L.append("  - %s" % n)
    L.append("")
    L.append("## 內文（清理後）")
    L.append("")
    L.append(rec["content"] or "（無內容）")
    L.append("")
    L.append("## 影片／音訊")
    L.append("")
    if rec["media"]["video_tags"] or rec["media"]["audio_tags"] or rec["media"]["iframes"]:
        L.append("- video 標籤：%d；audio 標籤：%d" % (rec["media"]["video_tags"], rec["media"]["audio_tags"]))
        for s in rec["media"]["iframes"]:
            L.append("- 嵌入播放器：%s" % s)
        L.append("- 影片檔未下載（僅記錄來源與型別，未繞過平台／版權限制）。")
    else:
        L.append("此頁無影片或音訊元素，亦無嵌入播放器，故無合法可處理之影片。")
    L.append("")
    if rec["images"]:
        L.append("## 內文圖片對應")
        L.append("")
        for i, im in enumerate(rec["images"], 1):
            L.append("![%s](../images/%s)" % (im["caption"] or ("圖 %d" % i), os.path.basename(im["file"])))
            L.append("")
            L.append("- 檔案：%s" % im["file"])
            L.append("- 原始網址：%s" % im["original_url"])
            L.append("- 說明：%s" % (im["caption"] or "（原頁無圖說）"))
            L.append("- 授權：%s" % im["license_note"])
            L.append("")
    if rec["links"]:
        L.append("## 頁面超連結（前 40 筆）")
        L.append("")
        for l in rec["links"][:40]:
            L.append("- [%s](%s)%s" % (l["text"] or l["url"], l["url"], "" if l["internal"] else "（外部）"))
        L.append("")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return p


def load_seeds(list_file):
    rows = []
    with open(list_file, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            g = {((k or "").strip().lower()): (v or "").strip() for k, v in r.items()}
            pid = g.get("id") or g.get("page_id") or ""
            url = g.get("url") or g.get("source_url") or ""
            if pid and url:
                rows.append({"id": pid, "url": url,
                             "note": g.get("note") or g.get("notes") or "",
                             "member": g.get("member") or ""})
    return rows


EXT = {
    "page_001": [
        ("https://www.guanyin-hro.tycg.gov.tw/cp.aspx?n=13772", "觀音區戶政事務所｜歷史沿革（石觀音庄與地名由來）"),
        ("https://wrb.tycg.gov.tw/cp.aspx?n=10870", "桃園市政府水務局｜河川管理（市管河川總覽）"),
    ],
    "page_010": [
        ("https://travel.tycg.gov.tw/zh-tw/Travel/Attraction/292", "桃園觀光導覽網｜甘泉寺（景點介紹）"),
        ("https://www.guanyin.tycg.gov.tw/cp.aspx?n=6884", "觀音區公所｜本所沿革"),
    ],
    "page_015": [
        ("https://zh.wikipedia.org/wiki/%E6%B7%A1%E6%B0%B4%E6%B2%B3", "維基百科｜淡水河（觀音坑溪匯入水系）"),
        ("https://zh.wikipedia.org/wiki/%E8%A7%80%E9%9F%B3%E5%B1%B1_(%E6%96%B0%E5%8C%97%E5%B8%82)", "維基百科｜觀音山（新北市）"),
    ],
    "page_016": [
        ("https://wrb.tycg.gov.tw/cp.aspx?n=10865", "桃園市政府水務局｜大堀溪（官方小檔案）"),
        ("https://wrb.tycg.gov.tw/cp.aspx?n=10870", "桃園市政府水務局｜河川管理（市管河川總覽）"),
    ],
    "page_020": [
        ("https://service.taipower.com.tw/tpcjournal/article/7728", "台電月刊｜大潭發電廠相關報導（前端渲染 SPA，API 需授權，未渲染故無正文）"),
        ("https://ea01.moeaea.gov.tw/e0408/energy-smartcity/page/stronghold/show.aspx?kind=2&num=83&page=1", "經濟部能源署｜大潭火力發電廠"),
    ],
    "page_028": [
        ("https://tcmb.culture.tw/zh-tw/detail?id=574199&indexCode=Culture_Place", "國家文化記憶庫｜石門水庫移民新村牌樓"),
        ("https://culture.tycg.gov.tw/News_Content.aspx?n=11238&sms=14627&s=1066849", "桃園市政府文化局｜文化新聞"),
    ],
    "page_031": [
        ("https://news.tycg.gov.tw/News_Content.aspx?n=5016&s=316772", "桃園市政府新聞處｜卡拉社專書報導"),
        ("https://ihc.cip.gov.tw/EJournal/EJournalCat/735", "原住民族文獻｜電子期刊第 59 期另一篇"),
    ],
}


def main():
    ap = argparse.ArgumentParser(description="member-A 觀音區知識爬蟲（維基／歷史地理／文化）")
    ap.add_argument("--list-file", default=os.path.join(ROOT, "urls_member_A.csv"))
    ap.add_argument("--only", default="", help="只跑指定 id，逗號分隔")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--no-extension", action="store_true")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--no-render", action="store_true", help="不使用 headless Chrome 渲染 SPA")
    ns = ap.parse_args()
    args = vars(ns)

    if not os.path.exists(args["list_file"]):
        sys.exit("找不到網址清單：%s" % args["list_file"])

    ensure_dirs()
    seeds = load_seeds(args["list_file"])
    only = {s.strip() for s in args["only"].split(",") if s.strip()}
    if only:
        seeds = [s for s in seeds if s["id"] in only]

    recdir = os.path.join(OUT, "records")
    os.makedirs(recdir, exist_ok=True)

    def save(rec):
        with open(os.path.join(recdir, "%s.json" % rec["id"]), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)

    crawled = {}

    for s in seeds:
        print("[seed] %s %s" % (s["id"], s["url"]))
        rec, doc = process(s["id"], s["url"], "seed", args=args)
        rec["member"] = s.get("member") or "A"
        save(rec)
        crawled[rec["source_url"]] = rec["id"]
        time.sleep(args["delay"])

        if args["no_extension"] or doc is None:
            continue
        for i, (eurl, enote) in enumerate(EXT.get(s["id"], []), 1):
            eid = "%s_ext_%02d" % (s["id"], i)
            if eurl in crawled:
                rec["notes"].append("延伸頁 %s 與 %s 為同一網址，未重複下載（%s）" % (eid, crawled[eurl], eurl))
                print("  [ext] 跳過重複 URL：%s" % eurl)
                continue
            print("  [ext] %s %s" % (eid, eurl))
            erec, _ = process(eid, eurl, "ext", seed_id=s["id"], args=args)
            erec["notes"].append("延伸來源說明：%s" % enote)
            erec["keywords"] = list(dict.fromkeys(rec["keywords"] + [enote.split("｜")[-1][:12]]))
            save(erec)
            crawled[eurl] = eid
            time.sleep(args["delay"])

    # 由 output/records/*.json 重建（支援 --only 增量重跑，不會覆蓋其他頁成果）
    records = []
    for fn in sorted(os.listdir(recdir)):
        if fn.endswith(".json"):
            with open(os.path.join(recdir, fn), encoding="utf-8") as f:
                records.append(json.load(f))
    for r in records:
        r["notes"] = [n for n in r.get("notes", []) if not n.startswith("與 page_")]
        r.pop("duplicate_of", None)

    sh = {r["id"]: shingles(r["content"]) for r in records if r["content"]}
    dups, compared = [], 0
    ids = list(sh)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            compared += 1
            jac = jaccard(sh[ids[i]], sh[ids[j]])
            if jac >= 0.55:
                dups.append({"a": ids[i], "b": ids[j], "jaccard": round(jac, 3)})
    for d in dups:
        for r in records:
            if r["id"] == d["b"]:
                r["duplicate_of"] = d["a"]
                r["notes"].append("與 %s 高度相似（Jaccard=%.2f）" % (d["a"], d["jaccard"]))

    with open(os.path.join(OUT, "index.jsonl"), "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for r in records:
        write_article(r)
    with open(os.path.join(OUT, "duplicates.json"), "w", encoding="utf-8") as f:
        json.dump({"pairs": dups, "compared_pairs": compared, "threshold": 0.55,
                   "note": "以清理後正文的 5-gram 字元 shingle Jaccard 相似度比對"},
                  f, ensure_ascii=False, indent=2)
    with open(REPORT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "type", "parent_id", "url", "final_url", "status", "http_status",
                    "engine", "title", "content_chars", "images_saved", "links_found",
                    "published", "category", "error"])
        for r in records:
            w.writerow([r["id"], r["type"], r.get("parent_id", ""), r["source_url"], r["final_url"],
                        r["crawl_status"], r["http_status"], r["engine"], r["title"],
                        r["chars"], len(r["images"]), len(r["links"]),
                        r["timestamps"]["published"], r["category"], r["error"]])

    ok = sum(1 for r in records if r["crawl_status"] == "success")
    pa = sum(1 for r in records if r["crawl_status"] == "partial")
    fa = sum(1 for r in records if r["crawl_status"] == "failed")
    imgs = sum(len(r["images"]) for r in records)
    print("\n=== 完成：%d 頁（success %d / partial %d / failed %d），圖片 %d 張 ===" % (
        len(records), ok, pa, fa, imgs))
    for r in records:
        if r["crawl_status"] != "success":
            print("  ! %-10s %-40s %s" % (r["crawl_status"], r["id"], r["error"][:90]))


if __name__ == "__main__":
    main()
