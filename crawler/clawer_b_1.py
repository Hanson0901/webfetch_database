#!/usr/bin/env python3
"""組員 B 專用的兩層觀音區網頁爬蟲。

這支程式以 urls.csv 中 page_005、page_011、page_018、page_019 為起點，
整理頁面內的連結，依連結文字與網址判斷是否值得納入觀音區知識資料，
並以 BFS 方式最多延伸兩層（seed=0、延伸頁=1/2）。延伸頁 ID 使用
`page_<seed>_ext_<nn>` 格式，例如 `page_005_ext_01`；同一網址重跑時沿用
`urls.csv` 中既有的 ID。

原始 crawler.py 保持不變；本檔只負責組員 B 的批次流程與連結判斷。
所有被判斷過的連結會寫入 link_assessment.csv，實際納入的延伸來源
會同步補進 urls.csv，方便之後由全組合併與驗收。
"""
from __future__ import annotations

import argparse
import csv
import html as html_lib
import importlib.util
import json
import logging
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

# 讓以 `python crawler/clawer_b_1.py` 執行時可以重用公版函式。
ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "crawler" / "crawler.py"
BASE_SPEC = importlib.util.spec_from_file_location("base_crawler", BASE_PATH)
if BASE_SPEC is None or BASE_SPEC.loader is None:  # pragma: no cover
    raise SystemExit(f"找不到公版爬蟲：{BASE_PATH}")
BASE = importlib.util.module_from_spec(BASE_SPEC)
BASE_SPEC.loader.exec_module(BASE)

DEFAULT_TIMEOUT = BASE.DEFAULT_TIMEOUT
KEYWORDS = BASE.KEYWORDS
LINK_LIMIT = BASE.LINK_LIMIT
USER_AGENT = BASE.USER_AGENT
canonical_url = BASE.canonical_url
compact = BASE.compact
extract_content = BASE.extract_content
clean_html = BASE.clean_html
image_candidates = BASE.image_candidates
load_index = BASE.load_index
merge_records_by_id = BASE.merge_records_by_id
now_iso = BASE.now_iso
robots_allowed = BASE.robots_allowed
save_image = BASE.save_image
website_name = BASE.website_name
write_index = BASE.write_index
write_report = BASE.write_report

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover - 由 requirements.txt 提供
    raise SystemExit("請先安裝 requirements.txt：" + str(exc))


SEED_IDS = {"page_005", "page_011", "page_018", "page_019"}
# 延伸頁面的 ID 以原始 seed 為前綴，例如 page_005_ext_01。
EXTENSION_ID_RE = re.compile(r"^(page_\d+)_ext_(\d+)$")
STRONG_TERMS = ("觀音區", "觀音", "白沙岬", "甘泉寺", "坑溪", "大堀溪", "大潭")
LOCAL_TERMS = ("燈塔", "藻礁", "觀新", "蓮花", "埤塘", "客家")
EXCLUDE_RE = re.compile(
    r"(?:/login|/logout|/register|/privacy|/terms|/sitemap|/feed|/rss|/search(?:/|\?)|"
    r"/wp-json|/xmlrpc|javascript:|mailto:|#|google(?:\.[^/]+)?/maps|maps\.google|"
    r"導航|google maps)",
    re.IGNORECASE,
)
IMAGE_NOISE_RE = re.compile(
    r"(?:logo|banner|favicon|avatar|icon|sprite|tracking|pixel|share|facebook|instagram|qrcode)",
    re.IGNORECASE,
)


def text_for_match(value: str) -> str:
    return unquote(value or "").replace("+", " ").lower()


def link_details(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    """擷取頁內連結與可供人工檢查的連結文字。"""
    base = canonical_url(base_url)
    base_host = urlparse(base).netloc
    details: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tag in soup.find_all("a", href=True):
        raw = str(tag.get("href", "")).strip()
        href = canonical_url(urljoin(base, raw))
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if href == base or href in seen:
            continue
        label = compact(
            tag.get_text(" ", strip=True)
            or tag.get("aria-label")
            or tag.get("title")
            or "",
            240,
        )
        haystack = text_for_match(f"{label} {href}")
        if EXCLUDE_RE.search(haystack):
            continue
        same_host = parsed.netloc == base_host
        # 保留同站連結，以及網址或連結文字明確提到地方主題的跨站連結。
        if not same_host and not any(term.lower() in haystack for term in STRONG_TERMS + LOCAL_TERMS):
            continue
        seen.add(href)
        details.append(
            {
                "url": href,
                "label": label,
                "same_host": same_host,
                "source_host": base_host,
            }
        )
        if len(details) >= LINK_LIMIT:
            break
    return details


def assess_link(detail: dict[str, Any]) -> dict[str, Any]:
    """以網址與連結文字做可追溯的相關性判斷。"""
    haystack = text_for_match(f"{detail.get('label', '')} {detail.get('url', '')}")
    score = 0
    reasons: list[str] = []
    matched_strong = [term for term in STRONG_TERMS if term.lower() in haystack]
    matched_local = [term for term in LOCAL_TERMS if term.lower() in haystack]
    if matched_strong:
        score += 4
        reasons.append("命中觀音區或在地地名：" + ", ".join(matched_strong))
    if matched_local:
        score += 2
        reasons.append("命中地方主題詞：" + ", ".join(matched_local))
    if detail.get("same_host"):
        score += 1
        reasons.append("與父頁面同站")
    relevant = score >= 4
    if not reasons:
        reasons.append("未命中觀音區相關詞")
    return {
        **detail,
        "score": score,
        "relevant": relevant,
        "reason": "; ".join(reasons),
    }


def html_fragment_text(fragment: str) -> str:
    """把 API 或文章片段中的 HTML 轉成保留段落的純文字。"""
    parsed = BeautifulSoup(fragment or "", "html.parser")
    parsed = clean_html(parsed)
    text = parsed.get_text("\n", strip=True)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def wordpress_content(soup: BeautifulSoup) -> tuple[str, BeautifulSoup | None]:
    """WordPress 文章正文在 post-content；通用抽取器有時會誤選店家摘要。"""
    node = soup.select_one("article.post .post-content") or soup.select_one("article.post")
    if not node:
        return "", None
    fragment = BeautifulSoup(str(node), "html.parser")
    # 文章容器裡還會嵌入相關文章、留言表單與評分元件，這些不屬於正文。
    for selector in (
        "section.related-posts",
        ".single-related-posts",
        ".respond",
        ".comment-respond",
        ".comment-form",
        ".kk-star-ratings",
        ".blogimove_localbusiness_mystar",
        ".fb-share-button",
    ):
        for extra in fragment.select(selector):
            extra.decompose()
    # 側欄作者介紹不是文章正文；作者、日期等 metadata 仍保留在索引欄位。
    for heading in fragment.select(".infotitle"):
        for ancestor in heading.parents:
            classes = set(ancestor.get("class") or [])
            if ancestor.name == "div" and any(
                value.startswith("fusion-builder-column") for value in classes
            ):
                ancestor.decompose()
                break
    return html_fragment_text(str(fragment)), fragment


def jsonld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text()
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        values = data if isinstance(data, list) else [data]
        objects.extend(item for item in values if isinstance(item, dict))
    return objects


def meta_images(soup: BeautifulSoup, base_url: str, caption: str) -> list[dict[str, str]]:
    """官方 React 頁面把圖片放在 og:image / JSON-LD，body 內沒有 img。"""
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(raw: Any, label: str = "") -> None:
        if not isinstance(raw, str) or not raw.strip():
            return
        url = canonical_url(urljoin(base_url, raw.strip()))
        if url in seen or url.startswith("data:"):
            return
        seen.add(url)
        found.append({"url": url, "caption": label or caption})

    for tag in soup.find_all("meta", attrs={"property": "og:image"}):
        add(tag.get("content"), caption)
    for obj in jsonld_objects(soup):
        images = obj.get("image")
        if isinstance(images, str):
            add(images, caption)
        elif isinstance(images, list):
            for image in images:
                add(image, caption)
    return found


def official_attraction_data(
    session: requests.Session,
    response_url: str,
) -> dict[str, Any] | None:
    """讀取桃園觀光 React 頁面使用的公開 opendata API。"""
    match = re.search(r"/([^/]+)/travel/attraction/(\d+)", response_url)
    if not match:
        return None
    lang, attraction_id = match.group(1), match.group(2)
    endpoint = f"{urlparse(response_url).scheme}://{urlparse(response_url).netloc}/{lang}/opendata/attractions"
    try:
        api_response = session.post(
            endpoint,
            timeout=DEFAULT_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": response_url,
                "Accept": "application/json, text/plain, */*",
            },
        )
        api_response.raise_for_status()
        data = api_response.json()
        for item in data.get("data", []):
            if str(item.get("id")) == attraction_id:
                return item
    except (requests.RequestException, ValueError, TypeError):
        return None
    return None


def official_content(
    api_data: dict[str, Any],
) -> str:
    fields = [
        f"官方摘要：{api_data.get('summary', '')}" if api_data.get("summary") else "",
        f"地址：{api_data.get('address', '')}" if api_data.get("address") else "",
        f"開放資訊：{api_data.get('opentime', '')}" if api_data.get("opentime") else "",
        f"座標：{api_data.get('lat', '')}, {api_data.get('lng', '')}"
        if api_data.get("lat") and api_data.get("lng")
        else "",
        "詳細介紹：" if api_data.get("description") else "",
        html_fragment_text(api_data.get("description", "")),
    ]
    return "\n\n".join(item for item in fields if item).strip()


def crawl_web_b(
    row: dict[str, str],
    out: Path,
    session: requests.Session,
    seen_hashes: dict[str, str],
) -> dict[str, Any]:
    """公版 crawl_web 的 B 版：額外保存 link_details。"""
    url = canonical_url(row["source_url"])
    result: dict[str, Any] = {
        "id": row["id"],
        "assigned_member": row.get("assigned_member") or "B",
        "source_kind": row.get("source_kind") or "seed",
        "parent_id": row.get("parent_id") or "",
        "depth": str(row.get("depth") or "0"),
        "notes": row.get("notes") or "",
        "type": "web",
        "source_url": url,
        "source_name": urlparse(url).netloc,
        "title": url,
        "content": "",
        "images": [],
        "links": [],
        "link_details": [],
        "timestamps": [],
        "keywords": [],
        "crawled_at": now_iso(),
    }
    allowed, robot_reason = robots_allowed(url, session)
    if not allowed:
        result.update(crawl_status="unavailable", failure_reason=robot_reason)
        return result
    try:
        response = session.get(
            url,
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            result.update(
                crawl_status="unavailable",
                failure_reason=f"content is not HTML: {content_type}",
            )
            return result
        content, soup, title = extract_content(response.text, response.url)
        # page_005 是 WordPress；正文在 article.post .post-content，
        # 通用 trafilatura 有時只留下景點摘要與商家欄位。
        wordpress_text, wordpress_soup = wordpress_content(soup)
        if wordpress_text:
            content = wordpress_text
            image_soup = wordpress_soup or soup
        else:
            image_soup = soup

        # page_011、page_018、page_019 是 React 應用程式：原始 body 只有
        # app-root，完整內容要從頁面使用的公開 opendata API 取得。
        api_data = official_attraction_data(session, response.url)
        if api_data:
            content = official_content(api_data)
            title = api_data.get("name") or title

        details = link_details(soup, response.url)
        if api_data and api_data.get("description"):
            api_soup = BeautifulSoup(api_data["description"], "html.parser")
            api_details = link_details(api_soup, response.url)
            existing = {item["url"] for item in details}
            details.extend(item for item in api_details if item["url"] not in existing)
        result.update(
            source_url=url,
            title=title,
            source_name=website_name(response.url, soup),
            content=content,
            links=[item["url"] for item in details],
            link_details=details,
            keywords=[k for k in KEYWORDS if k in f"{title} {content}"][:5],
            http_status=response.status_code,
            final_url=response.url,
            content_length=len(content),
        )
        candidates = image_candidates(image_soup, response.url)
        if api_data:
            candidates.extend(meta_images(soup, response.url, title))
            # 官方 API 描述內嵌圖片（例如白沙岬燈塔日文頁）也要保存。
            api_soup = BeautifulSoup(api_data.get("description", ""), "html.parser")
            candidates.extend(image_candidates(api_soup, response.url))
        unique_candidates: list[dict[str, str]] = []
        seen_candidate_urls: set[str] = set()
        for candidate in candidates:
            if candidate["url"] in seen_candidate_urls:
                continue
            seen_candidate_urls.add(candidate["url"])
            unique_candidates.append(candidate)
        for candidate in unique_candidates[:60]:
            if IMAGE_NOISE_RE.search(f"{candidate.get('url', '')} {candidate.get('caption', '')}"):
                continue
            image = save_image(session, candidate, out / "images", row["id"], seen_hashes)
            if image:
                result["images"].append(image)
        article_file = out / "articles" / f"{row['id']}.md"
        links_md = "\n".join(
            f"- {item['url']}（{item.get('label') or '無文字標籤'}）"
            for item in details
        )
        article_file.write_text(
            f"# {title}\n\n"
            f"- 原始網址：{url}\n"
            f"- 網站：{result['source_name']}\n"
            f"- 關鍵字：{', '.join(result['keywords']) or '待人工補充'}\n\n"
            + (
                f"- 官方資料 ID：{api_data.get('id')}\n"
                f"- 官方資料更新時間：{api_data.get('date_modified', '')}\n\n"
                if api_data
                else ""
            )
            + f"{content}\n\n## 頁內連結\n{links_md}\n",
            encoding="utf-8",
        )
        if api_data:
            result["official_api"] = {
                "endpoint_type": "桃園觀光 opendata attractions",
                "id": api_data.get("id"),
                "address": api_data.get("address", ""),
                "opentime": api_data.get("opentime", ""),
                "lat": api_data.get("lat"),
                "lng": api_data.get("lng"),
                "summary": api_data.get("summary", ""),
                "date_modified": api_data.get("date_modified", ""),
            }
        result.update(crawl_status="success", failure_reason="")
    except requests.RequestException as exc:
        result.update(
            crawl_status="unavailable" if isinstance(exc, requests.exceptions.SSLError) else "failed",
            failure_reason=f"{type(exc).__name__}: {compact(str(exc), 300)}",
        )
    except Exception as exc:  # pragma: no cover - 以輸出紀錄保留意外錯誤
        logging.exception("unexpected failure for %s", url)
        result.update(
            crawl_status="failed",
            failure_reason=f"{type(exc).__name__}: {compact(str(exc), 300)}",
        )
    return result


def read_seeds(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    seeds = [
        {
            **row,
            "assigned_member": "B",
            "source_kind": "seed",
            "parent_id": "",
            "depth": "0",
        }
        for row in rows
        if row.get("id") in SEED_IDS and row.get("type") == "web"
    ]
    missing = sorted(SEED_IDS - {row["id"] for row in seeds})
    if missing:
        raise SystemExit("urls.csv 缺少指定起點：" + ", ".join(missing))
    return sorted(seeds, key=lambda row: row["id"])


def append_urls_csv(csv_path: Path, records: list[dict[str, Any]]) -> int:
    """只把實際爬取且判定相關的延伸頁補入 urls.csv。"""
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        existing_rows = list(csv.DictReader(handle))
    existing_urls = {canonical_url(row.get("source_url", "")) for row in existing_rows}
    existing_ids = {row.get("id", "") for row in existing_rows}
    new_records = []
    for record in records:
        if record.get("source_kind") != "internal" or record.get("crawl_status") != "success":
            continue
        if canonical_url(record.get("source_url", "")) in existing_urls:
            continue
        if record.get("id") in existing_ids:
            continue
        new_records.append(
            {
                "id": record["id"],
                "type": "web",
                "source_url": record["source_url"],
                "source_kind": "internal",
                "parent_id": record.get("parent_id", ""),
                "depth": str(record.get("depth", "")),
                "assigned_member": "B",
                "notes": record.get("notes", ""),
            }
        )
        existing_urls.add(canonical_url(record["source_url"]))
        existing_ids.add(record["id"])
    if not new_records:
        return 0
    fieldnames = ["id", "type", "source_url", "source_kind", "parent_id", "depth", "assigned_member", "notes"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows)
        writer.writerows(new_records)
    return len(new_records)


def existing_extension_ids(csv_path: Path) -> tuple[dict[str, str], dict[str, set[int]]]:
    """讀取既有延伸來源，讓重跑時沿用同一個 ID。

    URL 已存在於 urls.csv 時，新的爬取結果必須使用原本的 ID，否則
    index.jsonl 會同時留下同一網址的舊資料與新資料。回傳值包含 URL→ID
    對照，以及每個 seed 已使用的延伸序號。
    """
    url_to_id: dict[str, str] = {}
    used: dict[str, set[int]] = defaultdict(set)
    if not csv_path.exists():
        return url_to_id, used
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            record_id = str(row.get("id") or "")
            match = EXTENSION_ID_RE.fullmatch(record_id)
            if not match:
                continue
            root_id, sequence = match.groups()
            used[root_id].add(int(sequence))
            source_url = canonical_url(row.get("source_url") or "")
            if source_url:
                url_to_id[source_url] = record_id
    return url_to_id, used


def allocate_extension_id(
    root_id: str,
    source_url: str,
    existing_url_to_id: dict[str, str],
    used_extension_numbers: dict[str, set[int]],
) -> str:
    """為延伸網址取得穩定的 page_<seed>_ext_<nn> ID。"""
    canonical = canonical_url(source_url)
    existing_id = existing_url_to_id.get(canonical, "")
    if existing_id:
        match = EXTENSION_ID_RE.fullmatch(existing_id)
        if match and match.group(1) == root_id:
            return existing_id

    sequence = 1
    while sequence in used_extension_numbers[root_id]:
        sequence += 1
    used_extension_numbers[root_id].add(sequence)
    target_id = f"{root_id}_ext_{sequence:02d}"
    existing_url_to_id[canonical] = target_id
    return target_id


def main() -> int:
    parser = argparse.ArgumentParser(description="組員 B：四個起點、最多兩層延伸的觀音區爬蟲")
    parser.add_argument("--urls", type=Path, default=ROOT / "urls.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "B")
    parser.add_argument("--max-depth", type=int, default=2, help="seed=0；預設最多延伸到第 2 層")
    parser.add_argument("--max-pages", type=int, default=40, help="避免同站連結爆量的安全上限")
    parser.add_argument("--per-page", type=int, default=12, help="每頁最多評估並排入的相關連結數")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    if args.max_depth < 0:
        raise SystemExit("--max-depth 不可小於 0")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out = args.output
    for folder in (out, out / "articles", out / "images", out / "videos"):
        folder.mkdir(parents=True, exist_ok=True)

    seeds = read_seeds(args.urls)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    seen_hashes: dict[str, str] = {}
    existing_url_to_id, used_extension_numbers = existing_extension_ids(args.urls)
    seen_urls: set[str] = set()
    root_by_id: dict[str, str] = {}
    queue: list[dict[str, str]] = []
    for seed in seeds:
        seed["source_url"] = canonical_url(seed["source_url"])
        queue.append(seed)
        seen_urls.add(seed["source_url"])
        root_by_id[seed["id"]] = seed["id"]

    records: list[dict[str, Any]] = []
    assessments: list[dict[str, Any]] = []
    queued_count = 0
    while queue and len(records) < args.max_pages:
        row = queue.pop(0)
        # 某些網站會把不同入口網址導向同一篇文章；已在本輪抓過的最終網址不再重抓。
        requested_url = canonical_url(row["source_url"])
        known_final_urls = {
            canonical_url(str(item.get("final_url") or item.get("source_url") or ""))
            for item in records
            if item.get("crawl_status") == "success"
        }
        if requested_url in known_final_urls:
            duplicate_id = next(
                (
                    str(item.get("id"))
                    for item in records
                    if item.get("crawl_status") == "success"
                    and canonical_url(str(item.get("final_url") or item.get("source_url") or ""))
                    == requested_url
                ),
                row.get("id", ""),
            )
            for prior_assessment in assessments:
                if prior_assessment.get("target_id") == row.get("id", ""):
                    prior_assessment["target_id"] = duplicate_id
            assessments.append(
                {
                    "parent_id": row.get("parent_id", ""),
                    "parent_depth": int(row.get("depth", "0")) - 1,
                    "url": requested_url,
                    "label": row.get("notes", ""),
                    "same_host": "",
                    "score": "",
                    "relevant": True,
                    "reason": "入口網址已在本輪其他網址取得，略過重複爬取",
                    "action": "skip_duplicate",
                    "target_id": duplicate_id,
                }
            )
            continue
        depth = int(row.get("depth", "0"))
        logging.info("crawling depth=%s id=%s %s", depth, row["id"], row["source_url"])
        record = crawl_web_b(row, out, session, seen_hashes)
        final_url = canonical_url(str(record.get("final_url") or record.get("source_url") or ""))
        prior_final_urls = {
            canonical_url(str(item.get("final_url") or item.get("source_url") or ""))
            for item in records
            if item.get("crawl_status") == "success"
        }
        if record.get("crawl_status") == "success" and final_url in prior_final_urls:
            # 不同入口導向同一篇文章時，只保留第一次成功的內容，避免
            # index.jsonl 與 urls.csv 出現重複知識來源。
            article_path = out / "articles" / f"{row['id']}.md"
            if article_path.exists():
                article_path.unlink()
            for image in record.get("images", []):
                image_path = out / image.get("file", "")
                if image_path.exists() and image_path.name.startswith(f"{row['id']}_"):
                    image_path.unlink()
            duplicate_id = next(
                (
                    str(item.get("id"))
                    for item in records
                    if item.get("crawl_status") == "success"
                    and canonical_url(str(item.get("final_url") or item.get("source_url") or ""))
                    == final_url
                ),
                row.get("id", ""),
            )
            for prior_assessment in assessments:
                if prior_assessment.get("target_id") == row.get("id", ""):
                    prior_assessment["target_id"] = duplicate_id
            assessments.append(
                {
                    "parent_id": row.get("parent_id", ""),
                    "parent_depth": depth - 1,
                    "url": row.get("source_url", ""),
                    "label": row.get("notes", ""),
                    "same_host": "",
                    "score": "",
                    "relevant": True,
                    "reason": f"導向已保存來源 {final_url}，略過重複內容",
                    "action": "skip_duplicate_final",
                    "target_id": duplicate_id,
                }
            )
            continue
        records.append(record)
        time.sleep(max(0.0, args.delay))
        if record.get("crawl_status") != "success" or depth >= args.max_depth:
            continue

        candidates = [assess_link(item) for item in record.get("link_details", [])]
        candidates.sort(key=lambda item: (-int(item["score"]), item["url"]))
        selected = 0
        for item in candidates:
            assessment = {
                "parent_id": record["id"],
                "parent_depth": depth,
                "url": item["url"],
                "label": item.get("label", ""),
                "same_host": item.get("same_host", False),
                "score": item["score"],
                "relevant": item["relevant"],
                "reason": item["reason"],
                "action": "crawl" if item["relevant"] else "skip",
                "target_id": "",
            }
            if item["relevant"] and selected < args.per_page and item["url"] not in seen_urls:
                next_depth = depth + 1
                root_id = root_by_id.get(record["id"], record["id"])
                target_id = allocate_extension_id(
                    root_id,
                    item["url"],
                    existing_url_to_id,
                    used_extension_numbers,
                )
                child = {
                    "id": target_id,
                    "type": "web",
                    "source_url": item["url"],
                    "source_kind": "internal",
                    "parent_id": record["id"],
                    "depth": str(next_depth),
                    "assigned_member": "B",
                    "notes": f"連結文字：{item.get('label') or '無'}；{item['reason']}",
                }
                queue.append(child)
                root_by_id[target_id] = root_id
                seen_urls.add(item["url"])
                queued_count += 1
                selected += 1
                assessment["target_id"] = target_id
            assessments.append(assessment)

    # 如果超過安全上限，仍將剩餘候選以 skip 記錄，不讓它們消失。
    for row in queue:
        assessments.append(
            {
                "parent_id": row.get("parent_id", ""),
                "parent_depth": int(row.get("depth", "0")) - 1,
                "url": row.get("source_url", ""),
                "label": "",
                "same_host": "",
                "score": "",
                "relevant": True,
                "reason": "達到 --max-pages 安全上限，未執行",
                "action": "skip_limit",
                "target_id": row.get("id", ""),
            }
        )

    index_path = out / "index.jsonl"
    existing = load_index(index_path)
    merged = merge_records_by_id(existing, records)
    write_index(merged, index_path)
    write_report(merged, out / "crawl_report.csv")

    with (out / "link_assessment.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["parent_id", "parent_depth", "url", "label", "same_host", "score", "relevant", "reason", "action", "target_id"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(assessments)

    # 只把實際成功的延伸結果寫回來源登記表。
    added_to_urls = append_urls_csv(args.urls, records)
    summary = {
        "generated_at": now_iso(),
        "id_naming": {
            "seed": "page_<number>",
            "extension": "page_<seed>_ext_<two_digit_sequence>",
        },
        "seed_count": len(seeds),
        "max_depth": args.max_depth,
        "crawled_count_this_run": len(records),
        "success_count_this_run": sum(r.get("crawl_status") == "success" for r in records),
        "failed_count_this_run": sum(r.get("crawl_status") == "failed" for r in records),
        "unavailable_count_this_run": sum(r.get("crawl_status") == "unavailable" for r in records),
        "link_assessment_count": len(assessments),
        "relevant_links_queued": queued_count,
        "urls_csv_rows_added": added_to_urls,
        "total_records_after_merge": len(merged),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
