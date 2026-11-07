#!/usr/bin/env python3
"""Normalize the historical C crawl to the assignment's canonical IDs.

The C branch was crawled more than once from the page_013 EZGO seed while
using member-prefixed IDs. This migration keeps every record and asset, but
maps those IDs into one canonical seed family:

    C-001                 -> page_013
    C-002                 -> page_013_ext_01
    C-003                 -> page_013_ext_02
    C-003 descendants    -> page_013_ext_03 ... (index order)

The duplicate/failed seed records are retained rather than silently deleted.
All parent IDs, article filenames, image filenames, JSON image references,
and crawl-report IDs are migrated together. The existing page_034 record is
already in the canonical page_<number> grammar and is intentionally kept.
"""
from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


LEGACY_PREFIX = "C-"
CANONICAL_PAGE_013 = "page_013"
LEGACY_IMAGE_RE = re.compile(r"^(?P<owner>.+)_image_(?P<number>\d+)(?P<ext>\.[^.]+)$")


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str], str, str]:
    raw = path.read_bytes()
    bom = "\ufeff" if raw.startswith(b"\xef\xbb\xbf") else ""
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"expected JSON object in {path}: {line[:80]}")
        records.append(value)
    return records, lines, newline, bom


def build_id_map(records: list[dict[str, Any]]) -> dict[str, str]:
    legacy_ids = [str(record["id"]) for record in records if str(record.get("id", "")).startswith(LEGACY_PREFIX)]
    if set(("C-001", "C-002", "C-003")) - set(legacy_ids):
        raise ValueError("expected C-001, C-002, and C-003 in output/index.jsonl")
    descendants = [old_id for old_id in legacy_ids if old_id.startswith("C-003_")]
    mapping = {
        "C-001": CANONICAL_PAGE_013,
        "C-002": f"{CANONICAL_PAGE_013}_ext_01",
        "C-003": f"{CANONICAL_PAGE_013}_ext_02",
    }
    for sequence, old_id in enumerate(descendants, start=3):
        mapping[old_id] = f"{CANONICAL_PAGE_013}_ext_{sequence:02d}"
    if set(mapping) != set(legacy_ids):
        missing = sorted(set(legacy_ids) - set(mapping))
        extra = sorted(set(mapping) - set(legacy_ids))
        raise ValueError(f"legacy mapping mismatch; missing={missing[:5]}, extra={extra[:5]}")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("canonical ID mapping is not unique")
    return mapping


def owner_for_image(filename: str, id_map: dict[str, str]) -> str:
    candidates = [old_id for old_id in id_map if filename.startswith(f"{old_id}_image_")]
    if not candidates:
        raise ValueError(f"cannot determine legacy owner for image {filename}")
    return max(candidates, key=len)


def build_image_map(image_dir: Path, id_map: dict[str, str]) -> dict[str, str]:
    image_map: dict[str, str] = {}
    for source in sorted(image_dir.iterdir()):
        if not source.is_file() or not source.name.startswith(LEGACY_PREFIX):
            continue
        owner = owner_for_image(source.name, id_map)
        match = LEGACY_IMAGE_RE.fullmatch(source.name)
        if not match or match.group("owner") != owner:
            raise ValueError(f"unexpected legacy image filename: {source.name}")
        destination = f"{id_map[owner]}_image_{match.group('number')}{match.group('ext')}"
        if destination in image_map.values():
            raise ValueError(f"two legacy images map to {destination}")
        image_map[source.name] = destination
    return image_map


def replace_image_paths(value: Any, image_map: dict[str, str]) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if not isinstance(item, dict):
            continue
        filename = item.get("file")
        if not isinstance(filename, str):
            continue
        if filename.startswith("images/"):
            prefix = "images/"
        elif filename.startswith("output/images/"):
            prefix = "output/images/"
        else:
            continue
        basename = filename.removeprefix(prefix)
        if basename.startswith(LEGACY_PREFIX):
            if basename not in image_map:
                raise ValueError(f"referenced legacy image is not on disk: {filename}")
            item["file"] = f"{prefix}{image_map[basename]}"


def update_records(records: list[dict[str, Any]], id_map: dict[str, str], image_map: dict[str, str]) -> None:
    for record in records:
        old_id = str(record.get("id", ""))
        if old_id in id_map:
            record["id"] = id_map[old_id]
            parent_id = record.get("parent_id")
            if isinstance(parent_id, str) and parent_id in id_map:
                record["parent_id"] = id_map[parent_id]
            replace_image_paths(record.get("images"), image_map)


def rename_files(directory: Path, mapping: dict[str, str]) -> None:
    if not mapping:
        return
    sources = {directory / source for source in mapping}
    destinations = {directory / destination for destination in mapping.values()}
    collisions = [path for path in destinations if path.exists() and path not in sources]
    if collisions:
        raise ValueError(f"destination files already exist: {collisions[:5]}")
    if len(destinations) != len(mapping):
        raise ValueError("file rename destinations are not unique")

    token = next(tempfile._get_candidate_names())
    staged: list[tuple[Path, Path]] = []
    for index, (source_name, destination_name) in enumerate(sorted(mapping.items())):
        source = directory / source_name
        if not source.is_file():
            raise FileNotFoundError(source)
        temporary = directory / f".c-naming-{token}-{index:04d}.tmp"
        os.replace(source, temporary)
        staged.append((temporary, directory / destination_name))
    for temporary, destination in staged:
        os.replace(temporary, destination)


def rename_articles(article_dir: Path, id_map: dict[str, str]) -> None:
    mapping: dict[str, str] = {}
    for source in sorted(article_dir.glob(f"{LEGACY_PREFIX}*.md")):
        old_id = source.stem
        if old_id not in id_map:
            raise ValueError(f"article has no ID mapping: {source.name}")
        mapping[source.name] = f"{id_map[old_id]}.md"
    rename_files(article_dir, mapping)


def write_jsonl_preserving_non_c_lines(path: Path, records: list[dict[str, Any]], original_lines: list[str], newline: str, bom: str, id_map: dict[str, str]) -> None:
    migrated_by_id = {str(record["id"]): record for record in records if str(record.get("id", "")) in id_map.values()}
    output_lines: list[str] = []
    for line in original_lines:
        if not line.strip():
            output_lines.append(line)
            continue
        original = json.loads(line)
        old_id = str(original.get("id", ""))
        if old_id in id_map:
            migrated = migrated_by_id[id_map[old_id]]
            output_lines.append(json.dumps(migrated, ensure_ascii=False))
        else:
            output_lines.append(line)
    text = newline.join(output_lines)
    if original_lines:
        text += newline
    path.write_text(bom + text, encoding="utf-8", newline="")


def migrate_report(path: Path, id_map: dict[str, str]) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if not fieldnames or "id" not in fieldnames or "parent_id" not in fieldnames:
            raise ValueError("crawl_report.csv has unexpected columns")
        rows = list(reader)
    changed = 0
    for row in rows:
        old_id = row.get("id", "")
        if old_id in id_map:
            row["id"] = id_map[old_id]
            if row.get("parent_id", "") in id_map:
                row["parent_id"] = id_map[row["parent_id"]]
            changed += 1
        elif row.get("parent_id", "") in id_map:
            row["parent_id"] = id_map[row["parent_id"]]
    if any(row.get("id", "").startswith(LEGACY_PREFIX) for row in rows):
        raise ValueError("legacy IDs remain in crawl report")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    if changed != len(id_map):
        raise ValueError(f"crawl report changed {changed} IDs, expected {len(id_map)}")


def validate(root: Path) -> None:
    index_path = root / "output" / "index.jsonl"
    records = [json.loads(line) for line in index_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    ids = [str(record.get("id", "")) for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("index IDs are not unique after migration")
    if any(record.get("id", "").startswith(LEGACY_PREFIX) for record in records):
        raise ValueError("legacy C ID remains in index")
    by_id = set(ids)
    for record in records:
        parent_id = record.get("parent_id")
        if parent_id and parent_id not in by_id:
            raise ValueError(f"missing parent {parent_id!r} for {record.get('id')}")
        for image in record.get("images", []) or []:
            if not isinstance(image, dict) or not isinstance(image.get("file"), str):
                continue
            if image["file"].startswith("images/"):
                path = root / "output" / image["file"]
            elif image["file"].startswith("output/images/"):
                path = root / image["file"]
            else:
                # Video thumbnails/subtitles are outside this migration's
                # scope and may be intentionally absent in the worktree.
                continue
            if not path.is_file():
                raise ValueError(f"missing image {image['file']} for {record.get('id')}")
    for directory in (root / "output" / "articles", root / "output" / "images"):
        if any(path.name.startswith(LEGACY_PREFIX) for path in directory.iterdir() if path.is_file()):
            raise ValueError(f"legacy file remains in {directory}")
    page_013 = next(record for record in records if record.get("id") == CANONICAL_PAGE_013)
    if page_013.get("source_url") != "https://ezgo.ardswc.gov.tw/zh-tw/leisure-area/1529/":
        raise ValueError("page_013 no longer points to the canonical EZGO seed")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    index_path = root / "output" / "index.jsonl"
    records, original_lines, newline, bom = load_jsonl(index_path)
    id_map = build_id_map(records)
    outside_ids = {str(record.get("id", "")) for record in records if not str(record.get("id", "")).startswith(LEGACY_PREFIX)}
    collisions = outside_ids.intersection(id_map.values())
    if collisions:
        raise ValueError(f"canonical targets already exist: {sorted(collisions)}")

    image_dir = root / "output" / "images"
    image_map = build_image_map(image_dir, id_map)
    update_records(records, id_map, image_map)

    rename_articles(root / "output" / "articles", id_map)
    rename_files(image_dir, image_map)
    write_jsonl_preserving_non_c_lines(index_path, records, original_lines, newline, bom, id_map)
    migrate_report(root / "output" / "crawl_report.csv", id_map)
    validate(root)
    print(f"migrated {len(id_map)} records and {len(image_map)} images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
