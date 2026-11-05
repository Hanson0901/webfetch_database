#!/usr/bin/env python3
"""組員 D 的爬蟲：新聞、部落格、旅遊與飲食媒體（依 README：複製公版 crawler.py 後修改）。

使用方式與公版完全相同：
    python crawler/crawler_member_D.py            → 互動模式：輸入組員編號 D，逐筆貼上網址，quit 結束
    python crawler/crawler_member_D.py --url ...  → 單筆命令列模式（參數與公版相同）

適用網站（D 負責）：
  page_003 微笑台灣、page_004 / page_017 客庄小旅行（客委會）、page_009 / page_029 方格子 vocus、
  page_014 我的旅圖中、page_021 TVBS 食尚玩家、page_022 痞客邦、page_023 Yahoo 奇摩新聞、page_025 旅聯網

修改原因（只改 README 建議修改的部分，輸入方式、編號、輸出資料夾、合併流程都與公版相同）：
  1. extract_content()：公版用 trafilatura 或 <article>，在這些網站會混入作者介紹、周邊推薦、
     廣告與延伸閱讀；改為「各站正文容器 + 站內雜訊選擇器」（SITE_RULES），找不到才退回公版做法。
  2. image_candidates() / save_image()：公版先讀 src，遇到 lazy loading（客庄小旅行 _loading.gif、
     旅聯網 grey.gif）會抓到佔位圖；改為優先讀 data-original-src / data-original / data-src / srcset，
     只收正文內圖片，排除 Logo、icon、表情 gif、追蹤像素，並保留圖說、圖片來源標示與所屬段落。
  3. crawl_web()：媒體文章保留作者、發表日期；標記 data_nature="media"（媒體內容，未經官方查核）。
  4. extension_candidates()：只取正文內、與觀音區相關的連結，排除「觀音山」（新北市）與社群分享連結。
輸出欄位與公版相同（另外多出 author、published_at 等欄位，放在後面），可直接與 A/B/C 合併。
"""
# ---------------------------------------------------------------------------
# D 負責的網址（執行互動模式時，依序複製貼上；編號對照 urls.csv）
# ---------------------------------------------------------------------------
# page_003  https://smiletaiwan.cw.com.tw/article/6889
# page_004  https://romantichakka.com/hakkatours/TourExpert?a=1202&fromlist=1&id=1624
# page_009  https://vocus.cc/article/695b08a8fd897800017a25c9
# page_014  https://duringmyjourney.com/treegarden/
# page_017  https://romantichakka.com/explore/HaFood?a=1955&id=3209
# page_021  https://supertaste.tvbs.com.tw/travel/348994
# page_022  https://wonderfood.pixnet.net/blog/posts/8229181678
# page_023  https://tw.news.yahoo.com/%E5%B7%A8%E5%A4%A7%E9%A3%9B%E6%A9%9F%E7%95%B6%E8%83%8C%E6%99%AF-%E5%BB%A2%E5%A2%9F%E8%AE%8A%E8%BA%AB%E7%86%B1%E9%96%80%E6%89%93%E5%8D%A1%E9%BB%9E-083000098.html
# page_025  https://www.waytogo.cc/topic/4157
# page_029  https://vocus.cc/article/6692021dfd89780001850bb9
#
# ---------------------------------------------------------------------------
# 目前有的網站規則（SITE_RULES，共 8 套）：程式用網址的網域判斷要套哪一套
#   - 網域相同或是它的子網域就套用，例如 abc.pixnet.net → pixnet.net 規則
#   - 會先轉址的網址，用「轉址後」的網域判斷
#   - 對不到任何一套 → 用公版的通用方法（trafilatura → <article>/<main>）
#
#   規則（網域）                  網站                    類型                 適用網址
#   smiletaiwan.cw.com.tw         微笑台灣                旅遊媒體             page_003
#   romantichakka.hakka.gov.tw    客庄小旅行（客委會）    旅遊／飲食媒體       page_004、page_017
#                                 （romantichakka.com 會轉址到這裡）
#   vocus.cc                      方格子                  部落格               page_009、page_029
#   duringmyjourney.com           我的旅圖中              部落格（WordPress）  page_014
#   supertaste.tvbs.com.tw        TVBS 食尚玩家           新聞／飲食媒體       page_021
#   pixnet.net                    痞客邦（所有部落格）    部落格               page_022
#   tw.news.yahoo.com             Yahoo 奇摩新聞          新聞                 page_023
#   waytogo.cc                    旅聯網                  旅遊入口網           page_025
#
# 另外有「通用規則」，每個網站都會套用：
#   移除廣告／分享／訂閱／Cookie／彈窗、遇到「延伸閱讀」截斷、刪除分享數（如 2.1K）、
#   排除 Logo／icon／追蹤像素圖片、沒有作者欄位時從正文「文／」「記者／」找作者
#
# 編號規則：D 的資料一律用 D-001、D-002…（程式自動接續）；對應的 urls.csv 編號記在備註，
# 目前對照：D-001=page_003、D-002=page_004、D-003=page_009、D-004=page_014、D-005=page_017、
#           D-006=page_021、D-007=page_022、D-008=page_023、D-009=page_025、D-010=page_029

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import mimetypes
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse
from urllib.robotparser import RobotFileParser

try:
    import requests
    from bs4 import BeautifulSoup, Comment, NavigableString, Tag
except ImportError as exc:
    raise SystemExit("請先安裝 requirements.txt：" + str(exc))

try:
    import trafilatura
except ImportError:
    trafilatura = None

try:
    from PIL import Image
    from io import BytesIO
except ImportError:
    Image = None
    BytesIO = None

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# D 修改：微笑台灣等網站的防火牆會擋掉「不像瀏覽器」的 User-Agent（回傳 403，robots.txt 其實允許）。
# 改用常見的「Mozilla/5.0 (compatible; 爬蟲名稱)」格式，仍清楚標示是本課程的爬蟲，並照樣遵守 robots.txt 與限速。
USER_AGENT = "Mozilla/5.0 (compatible; GuanyinKnowledgeCrawler/1.0; +educational course project; respectful-rate-limit)"
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
}
DEFAULT_TIMEOUT = 25
IMAGE_LIMIT = 40  # D：旅遊文章照片較多（page_014 有 37 張），每篇上限調高
LINK_LIMIT = 80
EXTENSION_LIMIT = 12
KEYWORDS = ("觀音", "白沙岬", "甘泉寺", "坑溪", "大堀溪", "大潭", "桃園", "燈塔", "藻礁", "埤塘", "客家")
NOISE_SELECTORS = [
    "nav", "header", "footer", "aside", "script", "style", "noscript", "form",
    ".ad", ".ads", ".advertisement", ".banner", ".cookie", ".popup", ".modal",
    ".share", ".social", ".recommend", ".related", ".breadcrumb", ".menu",
]


# ===========================================================================
# 組員 D 新增：各網站規則與工具函式（公版沒有的部分）
# ===========================================================================
MIN_IMAGE_SIDE = 150  # 下載後寬高都小於此值 → 視為 icon／裝飾圖

COMMON_NOISE = [
    "script", "style", "noscript", "template", "iframe", "form", "button", "svg", "nav",
    "ins", ".adsbygoogle", "[id^=div-gpt]", "[class*=advert]", ".ad", ".ads",
    "[class*=share]", "[class*=social]", "[class*=subscribe]", "[class*=newsletter]",
    "[class*=cookie]", "[id*=cookie]", "[class*=popup]", "[class*=modal]",
    "[class*=breadcrumb]", "[class*=recommend]", "[class*=related]",
]


SITE_RULES: dict[str, dict[str, Any]] = {
    "smiletaiwan.cw.com.tw": {
        "media_type": "旅遊媒體",
        "content": ["main#first_article article", "main#first_article"],
        "noise": [".authorInfo", ".contentList", ".keywordsList", ".tags", ".tag", ".keyword", "[class*=fb-]"],  # .contentList = 文中推薦文章
        "author": ["li.author"],
        "date": ["li.update"],
        "title_strip": r"\s-\s.*$",
    },
    "romantichakka.hakka.gov.tw": {
        "media_type": "旅遊／飲食媒體（客委會「客庄小旅行」）",
        "content": ["dl.description-list", "article.page-article"],
        "images": ["figure.carousel-image"],
        "noise": [".anchor-nav", ".blog-author-wrap", "section.page-section", "#lbs_modal", ".cookie-description"],
        "author": ["span.author"],
        "date_meta": ["DC.Date"],
        "title_strip": r"-客庄小旅行$",
    },
    "vocus.cc": {
        "media_type": "部落格（方格子 vocus）",
        "content": ["article.editor-content-block"],
        "image_attrs": ["data-original-src"],
        "caption": [".captionTheme__paragraph"],
        "caption_scope": ".lexical__image",
        "title_strip": r"｜[^｜]*$",
    },
    "duringmyjourney.com": {
        "media_type": "部落格（我的旅圖中）",
        "content": ["#penci-post-entry-inner", ".entry-content", "article.post"],
        "noise": [".penci-post-share-box", ".post-tags", ".jp-relatedposts", ".sharedaddy",
                  ".penci-single-link-pages", "#ez-toc-container", ".ez-toc-container", ".post-pagination"],
        "author": ["a.author-url", ".author-post a"],
        "date": ["time.entry-date.published"],
        "title_strip": r"\s–\s.*$",
    },
    "supertaste.tvbs.com.tw": {
        "media_type": "新聞／飲食媒體（TVBS 食尚玩家）",
        "content": ["article#article-content"],
        "noise": [".ins-container", "header", "#coupon_block", "section.max-w-195", "div.my-5", "p.endtext", 'a[href*="tvbs.to"]'],  # 優惠券、本文目錄、文中廣告、「看更多」、下載APP
        "title_strip": r"\s\|\s.*$",
    },
    "pixnet.net": {  # 所有痞客邦部落格（xxx.pixnet.net）共用同一套版型
        "media_type": "部落格（痞客邦 PIXNET）",
        "content": [".article-body", "#article-content-inner"],
        "noise": [".article-footer", ".author-profile", ".article-keyword", ".pixnet-ad"],
        "skip_gif": True,  # 痞客邦文章中的 gif 多為表情、分隔線
        "title_strip": r"\s\|\s.*$",
    },
    "tw.news.yahoo.com": {
        "media_type": "新聞（Yahoo 奇摩新聞）",
        "content": ['article[id^="article-"] div.atoms', "div.caas-body"],
        "noise": ["[class*=ad-]"],
    },
    "waytogo.cc": {
        "media_type": "旅遊入口網（旅聯網主題頁）",
        "content": ["#divcontent .profile_description", "#divcontent"],
        "noise": ["#DocStats", ".contextmenu-has-AD", ".profile_links", ".topicattributes"],
        "image_attrs": ["data-original"],
        "title_strip": r"\s-\s旅聯網$",
    },
}


GUANYIN_PATTERN = re.compile(
    r"觀音(?!山)|白沙岬|甘泉寺|石觀音|草漯|藻礁|觀新|大堀溪|樹林村|保生里|新坡|崙坪|白千層|蓮花|向陽農場|觀音工業區|大潭")


STOP_BLOCK = re.compile(r"^(延伸閱讀|推薦閱讀|相關文章|你可能也會喜歡|更多相關|看更多|熱門文章|本文經授權)")


JUNK_BLOCK = re.compile(r"^(分享|分享至|分享到|複製連結|加入好友|追蹤我們|訂閱|廣告|Advertisement|上一張|下一張|:::|請左右移動看更多|更多資訊|\d+(\.\d+)?\s*[KkMm萬]?|追蹤.{0,20}Follow us!?)$")


CREDIT_PATTERN = re.compile(r"[（(]?\s*(?:圖片來源|圖片提供|圖片|圖文|圖|攝影|照片來源)\s*[：:／/]\s*([^）)\n]{1,40})")


PLACEHOLDER = re.compile(r"(_?loading|grey|gray|blank|spacer|placeholder|transparent|pixel|lazy)\.(gif|png|svg|jpg)$", re.I)


BAD_IMAGE = re.compile(
    r"logo|icon|avatar|emoji|emoticon|sprite|banner|badge|qrcode|share|facebook|line\.me|"
    r"doubleclick|scorecardresearch|googlesyndication|/_next/static/media|/ads?/|pixel|instagram|[/_-]ig[-_.]", re.I)


SOCIAL_HOST = re.compile(r"facebook\.com|line\.me|twitter\.com|x\.com|instagram\.com|pinterest|plurk|threads\.net|"
                         r"youtube\.com/@|google\.com/maps|goo\.gl|maps\.app", re.I)


TRACKING_PARAMS = re.compile(r"^(utm_|guccounter|guce_|fbclid|gclid|si$)")


def rule_for(url: str) -> tuple[str, dict[str, Any]]:
    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    for key, rule in SITE_RULES.items():
        if host == key or host.endswith("." + key):
            return key, rule
    return "", {}


def clean_url(url: str) -> str:
    """去掉 #fragment 與追蹤參數（例如 Yahoo 的 guccounter / guce_referrer）。"""
    parsed = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
    return parsed._replace(query=urlencode(query), fragment="").geturl()


def norm_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("　", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def normalize_date(value: str) -> str:
    """回傳 YYYY-MM-DD；無法辨識時回傳空字串（原始值另外保存）。"""
    m = re.search(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})", value or "")
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def guanyin_relevance(text: str) -> dict[str, Any]:
    hits = GUANYIN_PATTERN.findall(text)
    terms: dict[str, int] = {}
    for h in hits:
        terms[h] = terms.get(h, 0) + 1
    n = len(hits)
    level = "high" if n >= 5 else "medium" if n >= 2 else "low"
    return {"mentions": n, "level": level, "terms": dict(sorted(terms.items(), key=lambda x: -x[1])[:8])}


ARTICLE_TYPES = {"Article", "NewsArticle", "BlogPosting", "Report", "WebPage"}


def json_ld_items(soup: BeautifulSoup) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        for obj in stack:
            if not isinstance(obj, dict):
                continue
            items.extend(x for x in obj.get("@graph", [obj]) if isinstance(x, dict))
    return items


def ld_author(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(filter(None, (ld_author(v) for v in value)))
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")


def meta_content(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def select_text(soup: BeautifulSoup, selectors: list[str]) -> tuple[str, str]:
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            return node.get("datetime", "") or "", compact(node.get_text(" ", strip=True), 120)
    return "", ""


def extract_metadata(soup: BeautifulSoup, rule: dict[str, Any], url: str) -> dict[str, Any]:
    ld = [x for x in json_ld_items(soup) if str(x.get("@type")) in ARTICLE_TYPES or
          (isinstance(x.get("@type"), list) and ARTICLE_TYPES & set(x["@type"]))]
    ld_main = next((x for x in ld if x.get("datePublished") and x.get("author")), None) or \
        next((x for x in ld if x.get("datePublished")), None) or {}

    _, author = select_text(soup, rule.get("author", []))
    author = re.sub(r"^(作者|文|撰文|by)\s*[:：/／]?\s*", "", author, flags=re.I).strip()
    author_source = "site_field" if author else ""
    if not author and ld_main.get("author"):
        author, author_source = ld_author(ld_main["author"]), "json-ld"
    if not author:
        m = meta_content(soup, "author", "article:author", "dable:author")
        if m and not m.startswith("http"):
            author, author_source = m, "meta"

    raw_date_attr, raw_date_text = select_text(soup, rule.get("date", []))
    published_raw = raw_date_attr or raw_date_text
    if not published_raw:
        published_raw = meta_content(soup, *rule.get("date_meta", []), "article:published_time",
                                     "og:article:published_time", "pubdate", "DC.Date")
    if not published_raw:
        published_raw = str(ld_main.get("datePublished") or "")
    if not published_raw:
        t = soup.find("time", attrs={"datetime": True})
        published_raw = t["datetime"] if t else ""
    modified_raw = meta_content(soup, "article:modified_time", "og:article:modified_time", "og:updated_time") or \
        str(ld_main.get("dateModified") or "")

    raw_title = page_title(url, soup)
    title = raw_title
    if rule.get("title_strip"):
        stripped = re.sub(rule["title_strip"], "", raw_title).strip()
        title = stripped if len(stripped) >= 2 else raw_title
    meta_kw = [k.strip() for k in re.split(r"[,，、]", meta_content(soup, "keywords", "news_keywords")) if k.strip()]
    return {
        "title": title, "raw_title": raw_title,
        "author": author or "", "author_source": author_source or ("not_found" if not author else ""),
        "published_at": normalize_date(published_raw), "published_raw": published_raw,
        "modified_at": normalize_date(modified_raw),
        "publisher": next((v for v in (meta_content(soup, "DC.Publisher", "publisher", "article:publisher"),)
                           if v and not v.startswith("http")), "") or website_name(url, soup),
        "description": compact(meta_content(soup, "og:description", "description"), 300),
        "meta_keywords": meta_kw[:15],
    }


HEADINGS = {"h1": 2, "h2": 2, "h3": 3, "h4": 4, "h5": 4, "h6": 4}


BLOCKS = {"p", "div", "section", "article", "blockquote", "dl", "pre", "header", "aside", "main", "address", "center"}


class BlockWriter:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.buf: list[str] = []

    def flush(self, kind: str = "p") -> None:
        text = norm_text("".join(self.buf))
        self.buf = []
        if text:
            self.items.append({"kind": kind, "text": text})

    def add(self, item: dict[str, Any]) -> None:
        self.flush()
        self.items.append(item)


def table_markdown(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [norm_text(c.get_text(" ", strip=True)).replace("|", "／").replace("\n", " ") for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def walk(node: Tag, out: BlockWriter) -> None:
    for child in node.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            out.buf.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name
        if name == "br":
            out.buf.append("\n")
        elif name == "img":
            out.add({"kind": "img", "tag": child})
        elif name in BLOCKS and any(c in HEADINGS for c in child.get("class", [])) and len(child.get_text(strip=True)) <= 60:
            # 客庄小旅行的小標是 <div class="h4">，當成標題處理，圖片才能對應到正確段落
            out.flush()
            level = HEADINGS[next(c for c in child.get("class", []) if c in HEADINGS)]
            text = norm_text(child.get_text(" ", strip=True))
            if text:
                out.items.append({"kind": "h", "level": level, "text": text})
        elif name in HEADINGS:
            out.flush()
            text = norm_text(child.get_text(" ", strip=True))
            for img in child.find_all("img"):
                out.add({"kind": "img", "tag": img})
            if text:
                out.items.append({"kind": "h", "level": HEADINGS[name], "text": text})
        elif name == "table":
            md = table_markdown(child)
            if md:
                out.add({"kind": "table", "text": md})
        elif name in ("ul", "ol"):
            out.flush()
            for li in child.find_all("li", recursive=False):
                walk(li, out)
                out.flush("li")
        elif name == "li":
            out.flush()
            walk(child, out)
            out.flush("li")
        elif name == "figure":
            out.flush()
            cap = child.find("figcaption")
            cap_text = norm_text(cap.get_text(" ", strip=True)) if cap else ""
            if cap:
                cap.extract()
            start = len(out.items)
            walk(child, out)
            out.flush()
            for item in out.items[start:]:
                if item["kind"] == "img" and cap_text:
                    item["caption"] = cap_text
            if cap_text:
                out.items.append({"kind": "caption", "text": cap_text})
        elif name == "dt":  # 定義清單：「店家電話：+886…」合成一行
            out.flush()
            out.buf.append(norm_text(child.get_text(" ", strip=True)).rstrip(" :：") + "：")
        elif name == "dd":
            walk(child, out)
            out.buf[:] = [norm_text("".join(out.buf)).replace("：\n", "：").replace("\n", "；")]
            out.flush("li")
        elif name in BLOCKS:
            out.flush()
            walk(child, out)
            out.flush("quote" if name == "blockquote" else "p")
        else:  # inline：a, span, strong, em, picture …
            walk(child, out)


def pick_containers(soup: BeautifulSoup, rule: dict[str, Any]) -> tuple[list[Tag], str]:
    found: list[Tag] = []
    used: list[str] = []
    """依序套用選擇器；與已選容器重疊（相同、子孫、祖先）的節點略過，
    因此「備援選擇器」不會重複收錄，而「不同區塊」（例如店家資訊表 + 店家介紹）會合併。"""
    for sel in rule.get("content", []):
        for node in soup.select(sel):
            if any(node is f or f in node.parents or node in f.parents for f in found):
                continue
            if len(node.get_text(strip=True)) < 20:
                continue
            found.append(node)
            if sel not in used:
                used.append(sel)
    return found, ", ".join(used)


def remove_noise(nodes: list[Tag], rule: dict[str, Any]) -> dict[str, int]:
    removed: dict[str, int] = {}
    for sel in COMMON_NOISE + rule.get("noise", []):
        for node in nodes:
            try:
                hits = node.select(sel)
            except Exception:  # 少數瀏覽器式選擇器 bs4 不支援
                continue
            for hit in hits:
                if hit is node:
                    continue
                hit.decompose()
                removed[sel] = removed.get(sel, 0) + 1
    return removed


def filter_blocks(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    dropped = 0
    last_text = ""
    for idx, item in enumerate(items):
        if item.get("text"):  # 段落中間的「（延伸閱讀：…）」也移除
            item["text"] = re.sub(r"[（(]\s*延伸閱讀\s*[：:][^）)]*[）)]", "", item["text"]).strip()
        text = item.get("text", "")
        if item["kind"] != "img":
            if (len(text) <= 20 and STOP_BLOCK.match(text)) or re.match(r"^[【\[]?延伸閱讀", text):
                dropped += len(items) - idx  # 之後全部是延伸閱讀／推薦區
                break
            if JUNK_BLOCK.match(text) or text == last_text:
                dropped += 1
                continue
            if re.fullmatch(r"[\W_]*", text):
                dropped += 1
                continue
            # 結尾的推廣連結，例如「…好拍又好逛》https://…」
            if re.search(r"》\s*https?://\S+$", text) and len(text) < 120:
                dropped += 1
                continue
            last_text = text
        kept.append(item)
    return kept, max(dropped, 0)


def best_from_srcset(srcset: str) -> str:
    best, best_w = "", -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = int(re.sub(r"\D", "", bits[1]) or 0) if len(bits) > 1 else 0
        if w > best_w:
            best, best_w = bits[0], w
    return best


def image_url(tag: Tag, rule: dict[str, Any], page_url: str) -> str:
    attrs = rule.get("image_attrs", []) + ["data-original-src", "data-original", "data-src", "data-lazy-src",
                                            "data-lazyload", "data-echo", "data-url"]
    for a in attrs:
        v = (tag.get(a) or "").strip()
        if v and not v.startswith("data:") and not PLACEHOLDER.search(v.split("?")[0]):
            return urljoin(page_url, v)
    for a in ("data-srcset", "srcset"):
        if tag.get(a):
            v = best_from_srcset(tag[a])
            if v and not v.startswith("data:"):
                return urljoin(page_url, v)
    v = (tag.get("src") or "").strip()
    if v and not v.startswith("data:") and not PLACEHOLDER.search(v.split("?")[0]):
        return urljoin(page_url, v)
    return ""


def reject_reason(url: str, tag: Tag, rule: dict[str, Any]) -> str:
    path = urlparse(url).path.lower()
    if not url:
        return "no usable src (placeholder only)"
    if path.endswith(".svg"):
        return "svg icon"
    if rule.get("skip_gif") and path.endswith(".gif"):
        return "decorative gif / emoticon"
    if BAD_IMAGE.search(url) or BAD_IMAGE.search(" ".join(tag.get("class", []))):
        return "logo / icon / ad / tracking pattern"
    for dim in ("width", "height"):
        v = re.sub(r"\D", "", str(tag.get(dim) or ""))
        if v and int(v) < 60:
            return f"too small ({dim}={v})"
    return ""


def caption_for(tag: Tag, item: dict[str, Any], rule: dict[str, Any]) -> str:
    if item.get("caption"):
        return item["caption"]
    scope_sel = rule.get("caption_scope")
    if scope_sel:
        scope = tag.find_parent(class_=scope_sel.lstrip(".")) if scope_sel.startswith(".") else None
        if scope:
            for sel in rule.get("caption", []):
                c = scope.select_one(sel)
                if c and c.get_text(strip=True):
                    return norm_text(c.get_text(" ", strip=True))
    fig = tag.find_parent("figure")
    if fig and fig.find("figcaption"):
        return norm_text(fig.find("figcaption").get_text(" ", strip=True))
    return norm_text(tag.get("alt") or tag.get("title") or "")


def author_from_text(content: str) -> str:
    """D：網站沒有作者欄位時，從正文開頭的署名找作者，例如 Yahoo 的「文／MOOK景點家編輯部整理報導」。"""
    m = re.search(r"(?:^|\n)\s*(?:文|撰文|記者|作者)\s*[／/｜|:：]\s*([^\n／/｜|]{2,25})", content[:300])
    return m.group(1).strip() if m else ""


def credit_of(caption: str) -> str:
    m = CREDIT_PATTERN.search(caption or "")
    if m:
        return m.group(1).strip(" ）)")
    if "截圖於網路" in (caption or ""):
        return "作者標示「截圖於網路」，原始出處不明"
    return ""


def content_links(nodes: list[Tag], page_url: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in nodes:
        for a in node.find_all("a", href=True):
            href = clean_url(urljoin(page_url, a["href"]))
            p = urlparse(href)
            if p.scheme not in ("http", "https") or href in seen or href == clean_url(page_url) or SOCIAL_HOST.search(href) \
                    or re.search(r"share|sharer|intent/tweet", href, re.I):
                continue
            if re.search(r"\.(jpe?g|png|gif|webp)$", p.path, re.I):
                continue
            seen.add(href)
            text = compact(a.get_text(" ", strip=True), 120)
            related = bool(GUANYIN_PATTERN.search(text + " " + href)) and not SOCIAL_HOST.search(href)
            links.append({"url": href, "text": text, "guanyin_related": related})
    return links


def write_article(out: Path, r: dict[str, Any], md_lines: list[str]) -> None:
    head = [
        f"# {r['title']}", "",
        f"- 編號：{r['id']}",
        f"- 原始網址：{r['source_url']}",
        *( [f"- 最終網址（轉址後）：{r['final_url']}"] if r.get("final_url") and r["final_url"] != r["source_url"] else [] ),
        f"- 網站：{r['source_name']}（{r['media_type']}）",
        f"- 作者：{r['author'] or '未標示'}（發布單位：{r.get('publisher') or r['source_name']}）",
        f"- 發表日期：{r['published_at'] or r['published_raw'] or '未標示'}" + (f"（最後更新 {r['modified_at']}）" if r.get("modified_at") and r["modified_at"] != r.get("published_at") else ""),
        f"- 取得時間：{r['crawled_at']}",
        f"- 擷取方式：{r['extraction_method']}",
        "- 資料性質：**媒體／部落格內容，尚未經官方資料查核**（查核結果見 analysis/fact_check_D.md）",
    ]
    if r.get("relevance_warning"):
        head.append(f"- ⚠ 相關性提醒：{r['relevance_warning']}")
    body = "\n\n".join(md_lines)
    img_table = ["", "## 圖片清單", "", "| 檔案 | 圖說 | 圖片來源標示 | 對應段落 | 原始網址 |", "| --- | --- | --- | --- | --- |"]
    for img in r["images"]:
        cell = lambda s: str(s or "").replace("|", "／").replace("\n", " ")  # noqa: E731
        img_table.append(f"| {cell(img['file'])} | {cell(img['caption'])} | {cell(img['credit'])} | "
                         f"{cell(img['context']['heading'])}：{cell(img['context']['near_text'])[:40]} | {img['source_url']} |")
    if not r["images"]:
        img_table.append("| （無） | 正文內沒有可合法取得且適合保留的圖片 | | | |")
    link_lines = [f"- [{l['text'] or l['url']}]({l['url']})" + ("　← 觀音區相關" if l["guanyin_related"] else "")
                  for l in r.get("content_links", [])]
    links = ["", "## 正文內連結", ""] + (link_lines or ["- （無）"])
    text = "\n".join(head) + "\n\n---\n\n" + body + "\n" + "\n".join(img_table) + "\n" + "\n".join(links) + "\n"
    (out / "articles" / f"{r['id']}.md").write_text(text, encoding="utf-8")



def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def compact(text: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    return parsed._replace(fragment="").geturl()


def website_name(url: str, soup: BeautifulSoup | None = None) -> str:
    if soup:
        meta = soup.find("meta", attrs={"property": "og:site_name"}) or soup.find("meta", attrs={"name": "application-name"})
        if meta and meta.get("content"):
            return compact(meta["content"], 120)
    return urlparse(url).netloc


def page_title(url: str, soup: BeautifulSoup | None = None) -> str:
    if soup:
        for attrs in ({"property": "og:title"}, {"name": "twitter:title"}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                return compact(tag["content"], 300)
        if soup.title and soup.title.get_text(strip=True):
            return compact(soup.title.get_text(" ", strip=True), 300)
    return url


def robots_allowed(url: str, session: requests.Session) -> tuple[bool, str]:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = session.get(robots_url, timeout=10, headers={"User-Agent": USER_AGENT})
        if response.status_code >= 400:
            return True, "robots.txt unavailable; proceeded with conservative rate limit"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return parser.can_fetch(USER_AGENT, url), "robots.txt disallows URL" if not parser.can_fetch(USER_AGENT, url) else ""
    except requests.RequestException as exc:
        return True, f"robots.txt check failed: {type(exc).__name__}"


def clean_html(soup: BeautifulSoup) -> BeautifulSoup:
    for selector in NOISE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()
    return soup


def extract_article(raw: bytes, url: str) -> dict[str, Any]:
    """D：依網站規則選正文容器 → 去雜訊 → 轉成區塊（段落／標題／條列／表格／圖片）。"""
    soup = BeautifulSoup(raw, "html.parser")
    site_key, rule = rule_for(url)
    meta = extract_metadata(soup, rule, url)
    all_links = related_links(soup, url)  # 整頁超連結清單（在去雜訊之前取得）
    containers, used_sel = pick_containers(soup, rule) if rule else ([], "")
    extra_img_nodes = [n for sel in rule.get("images", []) for n in soup.select(sel)]
    if containers:
        noise_removed = remove_noise(containers + extra_img_nodes, rule)
        writer = BlockWriter()
        for node in extra_img_nodes:
            for img in node.find_all("img"):
                writer.add({"kind": "img", "tag": img, "caption": norm_text(img.get("alt") or "")})
        for node in containers:
            walk(node, writer)
            writer.flush()
        blocks, dropped = filter_blocks(writer.items)
        method = f"site_rule[{site_key}]: {used_sel}"
    else:  # 沒有網站規則：沿用公版做法（trafilatura → 通用）
        noise_removed, dropped, text = {}, 0, ""
        html = raw.decode("utf-8", errors="ignore")
        if trafilatura:
            text = trafilatura.extract(html, url=url, include_links=False, include_images=False, favor_precision=True) or ""
        method = "trafilatura (no site rule matched)" if len(text.strip()) >= 80 else "generic body text"
        if len(text.strip()) < 80:
            main = clean_html(BeautifulSoup(raw, "html.parser"))
            node = main.find("article") or main.find("main") or main.body or main
            text = "\n".join(x.strip() for x in node.stripped_strings if x.strip())
        blocks = [{"kind": "p", "text": t} for t in norm_text(text).split("\n") if t.strip()]
        for tag in (soup.find("article") or soup.find("main") or soup).find_all("img"):
            blocks.append({"kind": "img", "tag": tag})
    return {"soup": soup, "site_key": site_key, "rule": rule, "meta": meta, "links": all_links,
            "containers": containers, "blocks": blocks, "method": method,
            "noise_removed": noise_removed, "blocks_dropped": dropped}


def extract_content(html: str, url: str) -> tuple[str, BeautifulSoup, str]:
    """與公版相同的介面：回傳（正文, soup, 標題）。"""
    art = extract_article(html.encode("utf-8") if isinstance(html, str) else html, url)
    text = "\n\n".join(b["text"] for b in art["blocks"] if b["kind"] != "img")
    return text, art["soup"], art["meta"]["title"]



def related_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    links: list[str] = []
    base_host = urlparse(base_url).netloc
    for tag in soup.find_all("a", href=True):
        href = canonical_url(urljoin(base_url, tag["href"]))
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        if href == canonical_url(base_url) or href in links:
            continue
        label = compact(tag.get_text(" ", strip=True), 120)
        candidate = f"{label} {href}".lower()
        if parsed.netloc == base_host or any(k.lower() in candidate for k in KEYWORDS):
            links.append(href)
        if len(links) >= LINK_LIMIT:
            break
    return links


def image_candidates(blocks: list[dict[str, Any]], rule: dict[str, Any], base_url: str, title: str) -> list[dict[str, Any]]:
    """D：依正文順序找圖片（含 lazy loading），附上圖說、圖片來源標示與所屬段落；不合格的寫明原因。"""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    heading, prev_text = title, ""
    for i, item in enumerate(blocks):
        if item["kind"] == "h":
            heading = item["text"]
        if item["kind"] in ("p", "li", "quote") and len(item["text"]) >= 15:
            prev_text = item["text"]
        if item["kind"] != "img":
            continue
        tag: Tag = item["tag"]
        url = image_url(tag, rule, base_url)
        if url in seen:
            item["skip"] = True
            continue
        seen.add(url)
        caption = caption_for(tag, item, rule)
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if nxt and nxt["kind"] in ("p", "caption") and len(nxt["text"]) <= 120 and \
                (nxt["kind"] == "caption" or nxt["text"] == caption or re.search(r"^▲|圖片|圖／|攝影|照片", nxt["text"])):
            caption = nxt["text"] if len(nxt["text"]) > len(caption) or not caption else caption
            nxt["is_caption"] = True
        found.append({"url": url, "caption": caption, "credit": credit_of(caption) or "未標示（文章未註明圖片來源）",
                      "context": {"heading": heading, "near_text": compact(prev_text, 80)},
                      "position": i, "reject_reason": reject_reason(url, tag, rule)})
    return found



def keywords_for(text: str) -> list[str]:
    return [k for k in KEYWORDS if k in text][:5]


def youtube_id(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc in ("youtu.be", "www.youtu.be"):
        return parsed.path.strip("/").split("/")[0] or None
    if "youtube.com" in parsed.netloc:
        if parsed.path == "/watch":
            from urllib.parse import parse_qs
            return parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/")[2]
    return None


def crawl_youtube(row: dict[str, str], out: Path, session: requests.Session) -> dict[str, Any]:
    url = row["source_url"]
    vid = youtube_id(url)
    result: dict[str, Any] = {"id": row.get("id", ""), "assigned_member": row.get("assigned_member") or "", "source_kind": row.get("source_kind") or "seed", "parent_id": row.get("parent_id") or "", "depth": row.get("depth") or "0", "notes": row.get("notes") or "", "type": "youtube", "source_url": url, "video_id": vid, "images": [], "links": [], "timestamps": [], "content": ""}
    if not vid:
        result.update(crawl_status="failed", failure_reason="cannot identify YouTube video id")
        return result
    if not yt_dlp:
        result.update(crawl_status="unavailable", failure_reason="optional yt-dlp is not installed; no video content fetched")
        return result
    try:
        opts = {"quiet": True, "skip_download": True, "writesubtitles": False, "writeautomaticsub": False, "noplaylist": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        title = info.get("title") or url
        result.update(title=title, source_name=info.get("channel") or info.get("uploader") or "YouTube", duration=info.get("duration"), description=info.get("description") or "", keywords=keywords_for(title + " " + (info.get("description") or "")))
        result["caption_status"] = "not downloaded automatically; rerun with a legally accessible caption source if available"
        result.update(crawl_status="success", failure_reason="")
    except Exception as exc:  # library errors vary by site and are recorded as data
        result.update(title=url, source_name="YouTube", crawl_status="unavailable", failure_reason=f"metadata/caption access failed: {type(exc).__name__}: {compact(str(exc), 240)}")
    return result


def save_image(session: requests.Session, item: dict[str, Any], image_dir: Path, page_id: str, seen_hashes: dict[str, str]) -> dict[str, Any] | None:
    """與公版相同的介面；D 改為每篇文章各自編號（page_id_image_01…），並排除過小的圖。
    沒存成功時把原因寫進 item["reject_reason"]。"""
    try:
        response = session.get(item["url"], timeout=DEFAULT_TIMEOUT,
                               headers={"User-Agent": USER_AGENT, "Referer": item.get("referer", "")})
        response.raise_for_status()
    except requests.RequestException as exc:
        item["reject_reason"] = f"download failed: {type(exc).__name__}"
        return None
    data = response.content
    ctype = response.headers.get("content-type", "").split(";")[0].strip()
    if not ctype.startswith("image/"):
        item["reject_reason"] = f"not an image ({ctype or 'unknown'})"
        return None
    if len(data) < 1024 or len(data) > 20_000_000:
        item["reject_reason"] = "file size out of range (< 1KB tracking pixel / > 20MB)"
        return None
    dimensions = None
    if Image and BytesIO:
        try:
            with Image.open(BytesIO(data)) as im:
                dimensions = {"width": im.width, "height": im.height}
        except Exception:
            pass
        if dimensions and dimensions["width"] < MIN_IMAGE_SIDE and dimensions["height"] < MIN_IMAGE_SIDE:
            item["reject_reason"] = f"too small ({dimensions['width']}x{dimensions['height']})"
            return None
    digest = sha256(data)
    if digest in seen_hashes:
        filename = seen_hashes[digest]
    else:
        ext = mimetypes.guess_extension(ctype) or Path(urlparse(item["url"]).path).suffix or ".jpg"
        ext = {".jpe": ".jpg", ".jpeg": ".jpg"}.get(ext.lower(), ext.lower())
        if ext not in {".jpg", ".png", ".webp", ".gif"}:
            ext = ".jpg"
        filename = f"{page_id}_image_{item.get('index', len(seen_hashes) + 1):02d}{ext}"
        (image_dir / filename).write_bytes(data)
        seen_hashes[digest] = filename
    return {"file": f"images/{filename}", "source_url": item["url"], "caption": item.get("caption", ""),
            "credit": item.get("credit", ""), "context": item.get("context", {}), "article_id": page_id,
            "sha256": digest, "dimensions": dimensions}



def crawl_web(row: dict[str, str], out: Path, session: requests.Session, seen_hashes: dict[str, str]) -> dict[str, Any]:
    url = clean_url(row["source_url"])  # D：去掉 Yahoo guccounter 等追蹤參數
    result: dict[str, Any] = {"id": row["id"], "assigned_member": row.get("assigned_member") or "", "source_kind": row.get("source_kind") or "seed", "parent_id": row.get("parent_id") or "", "depth": row.get("depth") or "0", "notes": row.get("notes") or "", "type": "web", "source_url": url, "source_name": urlparse(url).netloc, "title": url, "content": "", "images": [], "links": [], "timestamps": [], "keywords": [], "crawled_at": now_iso(),
                              "data_nature": "media", "verification_status": "unverified"}
    allowed, robot_reason = robots_allowed(url, session)
    if not allowed:
        result.update(crawl_status="unavailable", failure_reason=robot_reason)
        return result
    try:
        response = session.get(url, timeout=DEFAULT_TIMEOUT, headers=BROWSER_HEADERS, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type:
            result.update(crawl_status="unavailable", failure_reason=f"content is not HTML: {content_type}")
            return result
        art = extract_article(response.content, response.url)
        meta, blocks, rule = art["meta"], art["blocks"], art["rule"]

        # 圖片：依正文順序下載，建立圖文對應
        rejected: list[dict[str, str]] = []
        for cand in image_candidates(blocks, rule, response.url, meta["title"]):
            block = blocks[cand["position"]]
            if not cand["reject_reason"] and len(result["images"]) >= IMAGE_LIMIT:
                cand["reject_reason"] = f"over per-article limit ({IMAGE_LIMIT})"
            if not cand["reject_reason"]:
                cand.update(index=len(result["images"]) + 1, referer=response.url)
                image = save_image(session, cand, out / "images", row["id"], seen_hashes)
                if image:
                    result["images"].append(image)
                    block["image"] = image
                    time.sleep(0.3)
                    continue
            rejected.append({"source_url": cand["url"], "reason": cand["reject_reason"]})
            block["skip"] = True

        # 組合 Markdown（圖片放在原本的位置）
        md_lines: list[str] = []
        plain: list[str] = []
        for item in blocks:
            k = item["kind"]
            if k == "img":
                img = item.get("image")
                if img and not item.get("skip"):
                    md_lines.append(f"![{img['caption'] or '圖片'}](../{img['file']})")
                    md_lines.append(f"*圖說：{img['caption'] or '（無）'}｜圖片來源：{img['credit']}*")
                continue
            if item.get("is_caption") or k == "caption":
                continue
            t = item["text"]
            plain.append(t)
            if k == "h":
                md_lines.append("#" * item["level"] + " " + t)
            elif k == "li":
                md_lines.append("- " + t.replace("\n", " "))
            elif k == "quote":
                md_lines.append("> " + t.replace("\n", "\n> "))
            else:
                md_lines.append(t)
        content = "\n\n".join(plain)

        result.update(
            title=meta["title"], raw_title=meta["raw_title"], source_name=website_name(response.url, art["soup"]),
            site_rule=art["site_key"] or "none", media_type=rule.get("media_type", "其他媒體"),
            author=meta["author"] or author_from_text(content), author_source=meta["author_source"] if meta["author"] else ("content_byline" if author_from_text(content) else "not_found"), publisher=meta["publisher"],
            published_at=meta["published_at"], published_raw=meta["published_raw"], modified_at=meta["modified_at"],
            description=meta["description"], meta_keywords=meta["meta_keywords"],
            content=content, content_length=len(content), extraction_method=art["method"],
            noise_removed=art["noise_removed"], blocks_dropped=art["blocks_dropped"], images_rejected=rejected,
            links=art["links"], content_links=content_links(art["containers"], response.url) if art["containers"] else [],
            keywords=keywords_for(meta["title"] + " " + content),
            guanyin_relevance=guanyin_relevance(meta["title"] + content),
            http_status=response.status_code, final_url=response.url,
        )
        if result["guanyin_relevance"]["level"] == "low":
            result["relevance_warning"] = "正文很少提到桃園觀音區的地名" + (
                "；頁面中的「觀音山」在新北市，與桃園觀音區無關" if "觀音山" in content else "")
        if len(content) < 80:
            result.update(crawl_status="failed", failure_reason="正文少於 80 字：可能是 JavaScript 動態載入或網站改版")
        else:
            result.update(crawl_status="success", failure_reason="")
        write_article(out, result, md_lines)
    except requests.RequestException as exc:
        reason = f"{type(exc).__name__}: {compact(str(exc), 300)}"
        status = "unavailable" if isinstance(exc, requests.exceptions.SSLError) else "failed"
        if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in (401, 403, 404, 410, 429, 451):
            status = "unavailable"
        result.update(crawl_status=status, failure_reason=reason)
    except Exception as exc:
        logging.exception("unexpected failure for %s", url)
        result.update(crawl_status="failed", failure_reason=f"{type(exc).__name__}: {compact(str(exc), 300)}")
    return result



def extension_candidates(records: list[dict[str, Any]]) -> list[str]:
    """D：只從「正文內」且與觀音區相關的連結建立延伸清單（排除「觀音山」、社群分享連結）。"""
    candidates: list[str] = []
    for record in records:
        for link in record.get("content_links", []):
            if link["guanyin_related"] and link["url"] not in candidates:
                candidates.append(link["url"])
            if len(candidates) >= EXTENSION_LIMIT:
                return candidates
    return candidates



def prompt_value(label: str, default: str = "", required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default:
            return default
        if not required:
            return ""
        print("此欄位必填。")


def prompt_member(args: argparse.Namespace) -> str:
    if args.assigned_member:
        return args.assigned_member.upper()
    while True:
        member = input("請輸入組員編號（A/B/C/D）: ").strip().upper()
        if member in {"A", "B", "C", "D"}:
            args.assigned_member = member
            return member
        print("請輸入 A、B、C 或 D。")


_SESSION_IDS: set[str] = set()  # D 修正：同一次互動輸入的多筆網址，編號要接續（公版會重複給 D-001）


def next_id(out: Path, member: str) -> str:
    prefix = f"{member}-" if member != "UNASSIGNED" else "page_"
    largest = max((int(v[len(prefix):]) for v in _SESSION_IDS if v.startswith(prefix) and v[len(prefix):].isdigit()), default=0)
    index_file = out / "index.jsonl"
    if index_file.exists():
        for line in index_file.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line).get("id", "")
            except json.JSONDecodeError:
                continue
            if value.startswith(prefix) and value[len(prefix):].isdigit():
                largest = max(largest, int(value[len(prefix):]))
    return f"{prefix}{largest + 1:03d}"


def prompt_record(index: int, args: argparse.Namespace, out: Path) -> dict[str, str] | None:
    print(f"\n--- 新增第 {index} 筆來源 ---")
    record_id = args.id if index == 1 and args.id else next_id(out, args.assigned_member)
    print(f"編號：{record_id}（可用 quit 結束）")
    _SESSION_IDS.add(record_id)
    source_url = prompt_value("網址", required=True)
    if source_url.lower() == "quit":
        return None
    inferred_type = "youtube" if youtube_id(source_url) else "web"
    source_type = inferred_type
    source_kind = prompt_value("來源種類 seed/internal/extra", "seed").lower()
    parent_id = prompt_value("父頁面 id（只有 internal 才需要）") if source_kind == "internal" else ""
    depth = "1" if source_kind == "internal" else "0"
    notes = prompt_value("備註（可留白）")
    return {"id": record_id, "type": source_type, "source_url": canonical_url(source_url), "source_kind": source_kind, "parent_id": parent_id, "depth": depth, "assigned_member": args.assigned_member, "notes": notes}


def input_rows(args: argparse.Namespace, out: Path) -> list[dict[str, str]]:
    if args.url:
        source_url = canonical_url(args.url)
        return [{
            "id": args.id or next_id(out, args.assigned_member),
            "type": args.type or ("youtube" if youtube_id(source_url) else "web"),
            "source_url": source_url,
            "source_kind": args.source_kind,
            "parent_id": args.parent_id,
            "depth": str(args.depth if args.depth is not None else (1 if args.source_kind == "internal" else 0)),
            "assigned_member": args.assigned_member,
            "notes": args.notes,
        }]
    print("互動模式：本程式不讀取 urls.csv，只處理這次輸入的網址。輸入 quit 可結束。")
    rows: list[dict[str, str]] = []
    index = 1
    while True:
        row = prompt_record(index, args, out)
        if row is None:
            break
        rows.append(row)
        index += 1
        more = input("繼續新增網址？[Y/n]: ").strip().lower()
        if more in {"n", "no", "q", "quit"}:
            break
    return rows


def write_report(records: list[dict[str, Any]], path: Path) -> None:
    # 公版欄位 + D 加上的作者、日期、圖片排除數等欄位（放在最後，不影響合併）
    fields = ["id", "type", "source_url", "source_kind", "parent_id", "depth", "assigned_member", "notes", "title", "source_name", "crawl_status", "failure_reason", "crawled_at", "image_count", "link_count",
              "author", "published_at", "media_type", "extraction_method", "content_length", "images_rejected", "guanyin_mentions", "final_url"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for r in records:
            row = {field: r.get(field, "") for field in fields}
            row.update(image_count=len(r.get("images", [])), link_count=len(r.get("links", [])),
                       images_rejected=len(r.get("images_rejected", [])),
                       guanyin_mentions=(r.get("guanyin_relevance") or {}).get("mentions", ""))
            writer.writerow(row)



def load_index(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            logging.warning("略過無法解析的 JSONL 行：%s", line[:120])
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def merge_records_by_id(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """相同 id 取 incoming；新 id 依輸入順序追加到最後。"""
    replacements = {str(record.get("id")): record for record in incoming if record.get("id")}
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in existing:
        record_id = str(record.get("id", ""))
        if not record_id or record_id in seen:
            continue
        merged.append(replacements.pop(record_id, record))
        seen.add(record_id)
    merged.extend(replacements.values())
    return merged


def write_index(records: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


# 專案根目錄的 output 資料夾（crawler 的上一層），從哪裡執行結果都存在同一個地方
PROJECT_OUTPUT = Path(__file__).resolve().parent.parent / "output"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT_OUTPUT)  # D：固定存到專案根目錄的 output，不受執行位置影響
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--no-extension", action="store_true", help="不執行一層延伸探索")
    parser.add_argument("--id", help="非互動模式的來源編號")
    parser.add_argument("--url", help="非互動模式的單一網址；不提供則進入互動輸入")
    parser.add_argument("--type", choices=("web", "youtube"))
    parser.add_argument("--source-kind", choices=("seed", "internal", "extra"), default="seed")
    parser.add_argument("--parent-id", default="")
    parser.add_argument("--depth", type=int, default=None)
    parser.add_argument("--member", "--assigned-member", dest="assigned_member", help="自動化執行時可指定組員；一般執行會改由程式詢問")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    member = prompt_member(args)
    out = args.output
    if out == PROJECT_OUTPUT:
        out = out / member
    for folder in (out, out / "articles", out / "images", out / "videos"):
        folder.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    rows = input_rows(args, out)
    if not rows:
        print("沒有輸入來源，程式結束。")
        return 0
    seen_urls: set[str] = set()
    unique_rows: list[dict[str, str]] = []
    for row in rows:
        url = canonical_url(row["source_url"])
        if url not in seen_urls:
            item = dict(row)
            item["source_url"] = url
            unique_rows.append(item)
            seen_urls.add(url)
    rows = unique_rows
    records: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}
    for row in rows:
        logging.info("crawling %s %s", row["id"], row["source_url"])
        if row["type"] == "youtube":
            record = crawl_youtube(row, out, session)
            record.update(id=row["id"], crawled_at=now_iso())
        else:
            record = crawl_web(row, out, session, seen_hashes)
        records.append(record)
        time.sleep(max(0.0, args.delay))
    if not args.no_extension:
        for index, url in enumerate(extension_candidates(records), 1):
            records.append({"id": f"ext_{index:03d}", "type": "web_extension", "source_url": url, "source_kind": "internal", "parent_id": "AUTO_DISCOVERED", "depth": "1", "assigned_member": "UNASSIGNED", "notes": "請人工確認後加入 urls.csv", "source_name": urlparse(url).netloc, "title": "延伸探索尚未擷取", "content": "", "images": [], "links": [], "timestamps": [], "keywords": [], "crawl_status": "queued", "failure_reason": "延伸連結已建立清單；以 --no-extension 關閉或另行排程擷取", "crawled_at": now_iso()})
    index_path = out / "index.jsonl"
    existing_records = load_index(index_path)
    existing_ids = {str(record.get("id")) for record in existing_records if record.get("id")}
    incoming_ids = {str(record.get("id")) for record in records if record.get("id")}
    merged_records = merge_records_by_id(existing_records, records)
    write_index(merged_records, index_path)
    write_report(merged_records, out / "crawl_report.csv")
    summary = {
        "generated_at": now_iso(),
        "current_run_records": len(records),
        "current_run_success": sum(r.get("crawl_status") == "success" for r in records),
        "current_run_failed": sum(r.get("crawl_status") == "failed" for r in records),
        "current_run_unavailable": sum(r.get("crawl_status") == "unavailable" for r in records),
        "replaced_records": len(existing_ids & incoming_ids),
        "new_records": len(incoming_ids - existing_ids),
        "total_records_after_merge": len(merged_records),
        "extension_records": len(records) - len(rows),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
