#!/usr/bin/env python3
"""組員 B 的 YouTube 資料擷取流程。

流程：
1. 取得公開 metadata。
2. 嘗試取得公開人工字幕與自動字幕，不下載影片。
3. 保存公開縮圖並明確標記為 thumbnail；沒有合法影片檔時不冒充代表畫面。
4. 若沒有字幕，記錄無法取得原因與語音轉文字狀態。

本程式不繞過登入、付費牆、驗證碼或平台限制，也不預設下載音訊。
若日後確認有合法音訊使用權，可另外安裝語音辨識工具後再擴充 ASR。
"""
from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import json
import logging
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "crawler" / "crawler.py"
BASE_SPEC = importlib.util.spec_from_file_location("base_crawler", BASE_PATH)
if BASE_SPEC is None or BASE_SPEC.loader is None:  # pragma: no cover
    raise SystemExit(f"找不到公版爬蟲：{BASE_PATH}")
BASE = importlib.util.module_from_spec(BASE_SPEC)
BASE_SPEC.loader.exec_module(BASE)

canonical_url = BASE.canonical_url
compact = BASE.compact
keywords_for = BASE.keywords_for
load_index = BASE.load_index
merge_records_by_id = BASE.merge_records_by_id
now_iso = BASE.now_iso
write_index = BASE.write_index
write_report = BASE.write_report

try:
    import requests
    import yt_dlp
except ImportError as exc:  # pragma: no cover - requirements.txt 提供
    raise SystemExit("請先安裝 requirements.txt：" + str(exc))


VIDEO_IDS = {"page_026", "page_027", "page_030"}
SUBTITLE_LANGS = ["zh-Hant", "zh-TW", "zh", "en", "ja", "zh-Hans"]
TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?)\s+-->\s+"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?)"
)
TAG_RE = re.compile(r"<[^>]+>")


def read_video_rows(urls_path: Path) -> list[dict[str, str]]:
    with urls_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    videos = [row for row in rows if row.get("id") in VIDEO_IDS and row.get("type") == "youtube"]
    missing = sorted(VIDEO_IDS - {row.get("id") for row in videos})
    if missing:
        raise SystemExit("urls.csv 缺少指定 YouTube 來源：" + ", ".join(missing))
    return sorted(videos, key=lambda row: row["id"])


def fmt_time(value: str) -> str:
    """把 VTT 時間轉成適合 Markdown 顯示的 HH:MM:SS。"""
    value = value.split(".", 1)[0]
    parts = value.split(":")
    if len(parts) == 2:
        parts.insert(0, "00")
    return ":".join(part.zfill(2) for part in parts)


def parse_vtt(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    chunks: list[dict[str, str]] = []
    i = 0
    previous = ""
    while i < len(lines):
        match = TIMESTAMP_RE.search(lines[i])
        if not match:
            i += 1
            continue
        text_lines: list[str] = []
        i += 1
        while i < len(lines) and not TIMESTAMP_RE.search(lines[i]):
            line = TAG_RE.sub("", html.unescape(lines[i])).strip()
            if line and line.upper() not in {"WEBVTT", "KARAOKE"}:
                text_lines.append(line)
            i += 1
        text = compact(" ".join(text_lines), 2000)
        if text and text != previous:
            chunks.append(
                {
                    "start": fmt_time(match.group("start")),
                    "end": fmt_time(match.group("end")),
                    "text": text,
                }
            )
            previous = text
    return chunks


def caption_markdown(captions: list[dict[str, str]]) -> str:
    return "\n".join(
        f"- [{item['start']}] {item['text']}" for item in captions
    )


def subtitle_priority(path: Path) -> tuple[int, str]:
    """繁中優先，其次簡中、英文、日文；確保 page_026 不誤選日文字幕。"""
    name = path.name.lower()
    if ".zh-tw." in name:
        rank = 0
    elif ".zh-hant." in name:
        rank = 1
    elif ".zh." in name or ".zh-hans." in name:
        rank = 2
    elif ".en." in name:
        rank = 3
    elif ".ja." in name:
        rank = 4
    else:
        rank = 5
    return rank, name


def safe_download_thumbnail(url: str, destination: Path) -> dict[str, Any] | None:
    if not url:
        return None
    try:
        response = requests.get(url, timeout=25, headers={"User-Agent": BASE.USER_AGENT})
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if not content_type.startswith("image/") or len(response.content) < 512:
            return None
        destination.write_bytes(response.content)
        return {
            "file": f"videos/{destination.name}",
            "source_url": url,
            "caption": "YouTube 公開縮圖；不是影片代表畫面",
            "image_type": "thumbnail",
        }
    except requests.RequestException:
        return None


def probe_video(row: dict[str, str], out: Path, allow_audio_download: bool = False) -> dict[str, Any]:
    url = canonical_url(row["source_url"])
    video_id = ""
    result: dict[str, Any] = {
        "id": row["id"],
        "assigned_member": "B",
        "source_kind": row.get("source_kind") or "seed",
        "parent_id": row.get("parent_id") or "",
        "depth": row.get("depth") or "0",
        "notes": row.get("notes") or "",
        "type": "youtube",
        "source_url": url,
        "source_name": "YouTube",
        "title": url,
        "video_id": video_id,
        "content": "",
        "images": [],
        "links": [],
        "timestamps": [],
        "keywords": [],
        "crawled_at": now_iso(),
        "caption_status": "not_checked",
        "transcript_source": "none",
        "frames": [],
        "audio_status": "not_downloaded",
    }
    metadata: dict[str, Any] | None = None
    try:
        opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 25,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            metadata = ydl.extract_info(url, download=False)
        video_id = metadata.get("id") or ""
        title = metadata.get("title") or url
        description = metadata.get("description") or ""
        result.update(
            title=title,
            video_id=video_id,
            source_name=metadata.get("channel") or metadata.get("uploader") or "YouTube",
            duration=metadata.get("duration"),
            description=description,
            keywords=keywords_for(f"{title} {description}"),
            thumbnail_url=metadata.get("thumbnail") or "",
            webpage_url=metadata.get("webpage_url") or url,
        )
    except Exception as exc:
        result.update(
            crawl_status="unavailable",
            failure_reason=f"metadata access failed: {type(exc).__name__}: {compact(str(exc), 300)}",
            caption_status="not_checked",
        )
        return result

    # 保存縮圖作為來源輔助資料，明確標記其不是影片畫面。
    thumbnail = safe_download_thumbnail(
        result.get("thumbnail_url", ""),
        out / f"{row['id']}_thumbnail.jpg",
    )
    if thumbnail:
        result["images"].append(thumbnail)

    caption_files_before = {p.resolve() for p in out.glob(f"{row['id']}.*")}
    subtitle_error = ""
    try:
        opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": SUBTITLE_LANGS,
            "subtitlesformat": "vtt",
            "outtmpl": str(out / f"{row['id']}.%(ext)s"),
            "socket_timeout": 25,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as exc:
        subtitle_error = f"字幕下載程序失敗：{type(exc).__name__}: {compact(str(exc), 240)}"

    subtitle_files = sorted(
        p for p in out.glob(f"{row['id']}*.vtt") if p.resolve() not in caption_files_before
    )
    if not subtitle_files:
        # 也接受之前存在、但本輪沒有新建的字幕檔，避免重跑時遺失結果。
        subtitle_files = sorted(out.glob(f"{row['id']}*.vtt"))
    if subtitle_files:
        subtitle_files.sort(key=subtitle_priority)
        subtitle_path = subtitle_files[0]
        captions = parse_vtt(subtitle_path)
        result["timestamps"] = captions
        result["content"] = caption_markdown(captions)
        result["caption_status"] = "available"
        result["transcript_source"] = "youtube_public_caption_or_auto_caption"
        if len(subtitle_files) > 1:
            result["notes"] = (result.get("notes", "") + "；另有字幕檔：" + ", ".join(p.name for p in subtitle_files[1:])).strip("；")
    else:
        result["caption_status"] = "not_available"
        result["transcript_source"] = "none"
        if subtitle_error:
            result["caption_failure_reason"] = subtitle_error
        else:
            result["caption_failure_reason"] = "未找到公開人工字幕或自動字幕"

    # 沒有字幕時不自動抓音訊；現有環境也沒有 Whisper/faster-whisper 引擎。
    if allow_audio_download:
        result["audio_status"] = "not_run_explicit_asr_engine_required"
        result["asr_failure_reason"] = "已要求音訊流程，但尚未安裝或設定語音辨識引擎"
    else:
        result["audio_status"] = "not_downloaded_requires_explicit_authorization"
        result["asr_failure_reason"] = "未下載音訊；需確認合法使用權並以 --allow-audio-download 啟用後續流程"

    result["frames_status"] = "not_available_video_not_downloaded"
    result["frames_failure_reason"] = "目前只取得公開縮圖，沒有合法影片檔可擷取代表畫面"
    result["crawl_status"] = "success" if metadata else "unavailable"
    result["failure_reason"] = "" if metadata else result.get("failure_reason", "")

    video_md = out / f"{row['id']}.md"
    metadata_lines = [
        f"# {result['title']}",
        "",
        f"- 原始網址：{url}",
        f"- 頻道：{result.get('source_name', 'YouTube')}",
        f"- 影片 ID：{result.get('video_id', '')}",
        f"- 影片長度（秒）：{result.get('duration', '')}",
        f"- 字幕狀態：{result.get('caption_status', '')}",
        f"- 文字來源：{result.get('transcript_source', '')}",
        f"- 音訊狀態：{result.get('audio_status', '')}",
        f"- 代表畫面狀態：{result.get('frames_status', '')}",
        "",
        "## 描述",
        result.get("description", "") or "（無公開描述）",
        "",
        "## 字幕或逐字稿",
        result.get("content", "") or "（未取得公開字幕；未以推測內容替代）",
        "",
        "## 未取得項目",
        f"- 字幕：{result.get('caption_failure_reason', '無')}",
        f"- 語音轉文字：{result.get('asr_failure_reason', '無')}",
        f"- 代表畫面：{result.get('frames_failure_reason', '無')}",
    ]
    video_md.write_text("\n".join(metadata_lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="組員 B：YouTube metadata、字幕與可取得資料擷取")
    parser.add_argument("--urls", type=Path, default=ROOT / "urls.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "B" / "videos")
    parser.add_argument(
        "--allow-audio-download",
        action="store_true",
        help="僅在已確認有合法音訊使用權時啟用；目前仍需額外 ASR 引擎",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args.output.mkdir(parents=True, exist_ok=True)
    rows = read_video_rows(args.urls)
    records = []
    for row in rows:
        logging.info("probing %s %s", row["id"], row["source_url"])
        records.append(probe_video(row, args.output, args.allow_audio_download))

    index_path = args.output.parent / "index.jsonl"
    existing = load_index(index_path)
    merged = merge_records_by_id(existing, records)
    write_index(merged, index_path)
    write_report(merged, args.output.parent / "crawl_report.csv")

    summary_path = args.output.parent / "summary.json"
    old_summary: dict[str, Any] = {}
    if summary_path.exists():
        try:
            old_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old_summary = {}
    old_summary["youtube_run"] = {
        "generated_at": now_iso(),
        "processed_count": len(records),
        "metadata_success": sum(r.get("crawl_status") == "success" for r in records),
        "caption_available": sum(r.get("caption_status") == "available" for r in records),
        "caption_missing": sum(r.get("caption_status") == "not_available" for r in records),
        "audio_downloaded": sum(r.get("audio_status") == "downloaded" for r in records),
        "frames_available": sum(r.get("frames_status") == "available" for r in records),
        "records_added_or_replaced": len(records),
    }
    old_summary["total_records_after_merge"] = len(merged)
    summary_path.write_text(json.dumps(old_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(old_summary["youtube_run"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
