#!/usr/bin/env python3
"""從觀音區參考起點建立可重複執行的多媒體資料集。

設計原則：尊重 robots.txt、只擷取公開 HTML/圖片與可合法取得的字幕資訊，
所有失敗與未取得項目都寫入 crawl_report.csv / index.jsonl。
"""
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
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

try:
    import requests
    from bs4 import BeautifulSoup
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

USER_AGENT = "GuanyinKnowledgeCrawler/1.0 (+educational; respectful-rate-limit)"
DEFAULT_TIMEOUT = 25
IMAGE_LIMIT = 12
LINK_LIMIT = 80
EXTENSION_LIMIT = 12
KEYWORDS = ("觀音", "白沙岬", "甘泉寺", "坑溪", "大堀溪", "大潭", "桃園", "燈塔", "藻礁", "埤塘", "客家")
NOISE_SELECTORS = [
    "nav", "header", "footer", "aside", "script", "style", "noscript", "form",
    ".ad", ".ads", ".advertisement", ".banner", ".cookie", ".popup", ".modal",
    ".share", ".social", ".recommend", ".related", ".breadcrumb", ".menu",
]


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


def extract_content(html: str, url: str) -> tuple[str, BeautifulSoup, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = page_title(url, soup)
    if trafilatura:
        extracted = trafilatura.extract(html, url=url, include_links=False, include_images=False, favor_precision=True)
        if extracted and len(extracted.strip()) >= 80:
            return extracted.strip(), soup, title
    clean = clean_html(soup)
    main = clean.find("article") or clean.find("main") or clean.body or clean
    text = "\n\n".join(x.strip() for x in main.stripped_strings if x.strip())
    return text, soup, title


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


def image_candidates(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for tag in soup.find_all(["img", "source"]):
        raw = tag.get("src") or tag.get("data-src") or tag.get("data-original") or tag.get("data-lazy-src")
        if not raw and tag.get("srcset"):
            raw = tag["srcset"].split(",")[0].strip().split(" ")[0]
        if not raw:
            continue
        url = canonical_url(urljoin(base_url, raw))
        if url in seen or url.startswith("data:"):
            continue
        seen.add(url)
        alt = compact(tag.get("alt") or tag.get("title") or "", 300)
        parent = tag.find_parent(["figure", "picture"])
        caption = compact(parent.get_text(" ", strip=True), 300) if parent else alt
        found.append({"url": url, "caption": caption or alt})
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


def save_image(session: requests.Session, item: dict[str, str], image_dir: Path, page_id: str, seen_hashes: dict[str, str]) -> dict[str, Any] | None:
    try:
        response = session.get(item["url"], timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        data = response.content
        if len(data) < 512 or len(data) > 20_000_000:
            return None
        digest = sha256(data)
        if digest in seen_hashes:
            filename = seen_hashes[digest]
        else:
            ext = mimetypes.guess_extension(response.headers.get("content-type", "").split(";")[0]) or Path(urlparse(item["url"]).path).suffix or ".jpg"
            if ext.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                ext = ".jpg"
            filename = f"{page_id}_image_{len(seen_hashes)+1:02d}{ext.lower()}"
            (image_dir / filename).write_bytes(data)
            seen_hashes[digest] = filename
        dimensions = None
        if Image and BytesIO:
            try:
                with Image.open(BytesIO(data)) as im:
                    dimensions = {"width": im.width, "height": im.height}
                    if im.width <= 2 and im.height <= 2:
                        return None
            except Exception:
                pass
        return {"file": f"images/{filename}", "source_url": item["url"], "caption": item.get("caption", ""), "sha256": digest, "dimensions": dimensions}
    except requests.RequestException:
        return None


def crawl_web(row: dict[str, str], out: Path, session: requests.Session, seen_hashes: dict[str, str]) -> dict[str, Any]:
    url = canonical_url(row["source_url"])
    result: dict[str, Any] = {"id": row["id"], "assigned_member": row.get("assigned_member") or "", "source_kind": row.get("source_kind") or "seed", "parent_id": row.get("parent_id") or "", "depth": row.get("depth") or "0", "notes": row.get("notes") or "", "type": "web", "source_url": url, "source_name": urlparse(url).netloc, "title": url, "content": "", "images": [], "links": [], "timestamps": [], "keywords": [], "crawled_at": now_iso()}
    allowed, robot_reason = robots_allowed(url, session)
    if not allowed:
        result.update(crawl_status="unavailable", failure_reason=robot_reason)
        return result
    try:
        response = session.get(url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type:
            result.update(crawl_status="unavailable", failure_reason=f"content is not HTML: {content_type}")
            return result
        content, soup, title = extract_content(response.text, response.url)
        result.update(source_url=url, title=title, source_name=website_name(response.url, soup), content=content, links=related_links(soup, response.url), keywords=keywords_for(title + " " + content), http_status=response.status_code, final_url=response.url, content_length=len(content))
        for candidate in image_candidates(soup, response.url)[:IMAGE_LIMIT]:
            image = save_image(session, candidate, out / "images", row["id"], seen_hashes)
            if image:
                result["images"].append(image)
        article_file = out / "articles" / f"{row['id']}.md"
        article_file.write_text(f"# {title}\n\n- 原始網址：{url}\n- 網站：{result['source_name']}\n- 關鍵字：{', '.join(result['keywords']) or '待人工補充'}\n\n{content}\n\n## 相關連結\n" + "\n".join(f"- {x}" for x in result["links"]), encoding="utf-8")
        result.update(crawl_status="success", failure_reason="")
    except requests.RequestException as exc:
        reason = f"{type(exc).__name__}: {compact(str(exc), 300)}"
        status = "unavailable" if isinstance(exc, requests.exceptions.SSLError) else "failed"
        result.update(crawl_status=status, failure_reason=reason)
    except Exception as exc:
        logging.exception("unexpected failure for %s", url)
        result.update(crawl_status="failed", failure_reason=f"{type(exc).__name__}: {compact(str(exc), 300)}")
    return result


def extension_candidates(records: list[dict[str, Any]]) -> list[str]:
    candidates: list[str] = []
    for record in records:
        for link in record.get("links", []):
            if link not in candidates and any(k in link for k in KEYWORDS):
                candidates.append(link)
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


def next_id(out: Path, member: str) -> str:
    prefix = f"{member}-" if member != "UNASSIGNED" else "page_"
    largest = 0
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
    fields = ["id", "type", "source_url", "source_kind", "parent_id", "depth", "assigned_member", "notes", "title", "source_name", "crawl_status", "failure_reason", "crawled_at", "image_count", "link_count"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for r in records:
            row = {field: r.get(field, "") for field in fields}
            row.update(image_count=len(r.get("images", [])), link_count=len(r.get("links", [])))
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output"))
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
    if out == Path("output"):
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
