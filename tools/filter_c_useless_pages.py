#!/usr/bin/env python3
"""Filter unusable branch-C crawl records without touching other members.

Strict filtering keeps only C records whose crawl status is successful and
whose extracted text is non-empty.  This removes failed/unavailable records
and successful records that contain no usable text, including image-only pages.
The index and crawl report are filtered together; article files and images
that are referenced only by removed records are pruned safely.

Run without arguments for a dry-run summary. Use ``--apply`` to modify the
working tree.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


KEEP_STATUSES = {"success", "completed"}
IMAGE_PREFIXES = ("images/", "output/images/")


def load_index(path: Path) -> tuple[list[dict[str, Any]], list[str], str, str]:
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
            raise ValueError(f"expected JSON object in {path}")
        records.append(value)
    return records, lines, newline, bom


def is_c_record(record: dict[str, Any]) -> bool:
    return record.get("assigned_member") == "C"


def is_useful(record: dict[str, Any]) -> bool:
    status = str(record.get("crawl_status") or "").strip().lower()
    content = str(record.get("content") or "").strip()
    return status in KEEP_STATUSES and bool(content)


def image_paths(value: Any) -> set[str]:
    paths: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            filename = item.get("file")
            if isinstance(filename, str) and filename.startswith(IMAGE_PREFIXES):
                paths.add(filename)
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return paths


def image_disk_path(root: Path, reference: str) -> Path | None:
    if reference.startswith("images/"):
        return root / "output" / reference
    if reference.startswith("output/images/"):
        return root / reference
    return None


def atomic_write(path: Path, data: bytes) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def filtered_index_bytes(
    path: Path,
    original_lines: list[str],
    newline: str,
    bom: str,
    removed_ids: set[str],
) -> bytes:
    kept_lines: list[str] = []
    for line in original_lines:
        if not line.strip():
            kept_lines.append(line)
            continue
        record = json.loads(line)
        record_id = str(record.get("id") or "")
        if record.get("assigned_member") == "C" and record_id in removed_ids:
            continue
        kept_lines.append(line)
    text = newline.join(kept_lines)
    if original_lines:
        text += newline
    return (bom + text).encode("utf-8")


def filtered_report_bytes(path: Path, removed_ids: set[str]) -> tuple[bytes, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ValueError(f"empty crawl report: {path}")
    header = rows[0]
    if "id" not in header or "parent_id" not in header:
        raise ValueError("crawl_report.csv has unexpected columns")
    id_index = header.index("id")
    retained = [header]
    removed_count = 0
    for row in rows[1:]:
        if len(row) <= id_index:
            raise ValueError("crawl report row has fewer columns than its header")
        if row[id_index] in removed_ids:
            removed_count += 1
            continue
        retained.append(row)
    output: list[str] = []
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerows(retained)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8"), removed_count


def validate_parent_closure(records: Iterable[dict[str, Any]], removed_ids: set[str]) -> None:
    retained_ids = {str(record.get("id") or "") for record in records if str(record.get("id") or "") not in removed_ids}
    orphaned: list[tuple[str, str]] = []
    for record in records:
        record_id = str(record.get("id") or "")
        if record_id in removed_ids:
            continue
        parent_id = record.get("parent_id")
        if parent_id and parent_id not in retained_ids:
            orphaned.append((record_id, str(parent_id)))
    if orphaned:
        raise ValueError(f"filter would orphan records: {orphaned[:10]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="apply the filter instead of showing a dry-run")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    index_path = root / "output" / "index.jsonl"
    report_path = root / "output" / "crawl_report.csv"
    article_dir = root / "output" / "articles"

    records, original_lines, newline, bom = load_index(index_path)
    c_records = [record for record in records if is_c_record(record)]
    removed_records = [record for record in c_records if not is_useful(record)]
    removed_ids = {str(record.get("id") or "") for record in removed_records}
    if len(removed_ids) != len(removed_records):
        raise ValueError("C records contain duplicate or empty IDs")
    validate_parent_closure(records, removed_ids)

    report_bytes, report_removed_count = filtered_report_bytes(report_path, removed_ids)
    if report_removed_count != len(removed_ids):
        raise ValueError(
            f"crawl report contains {report_removed_count} removable IDs; expected {len(removed_ids)}"
        )

    retained_records = [record for record in records if str(record.get("id") or "") not in removed_ids]
    removed_image_refs = set().union(*(image_paths(record.get("images")) for record in removed_records)) if removed_records else set()
    retained_image_refs = set().union(*(image_paths(record.get("images")) for record in retained_records)) if retained_records else set()
    image_refs_to_prune = removed_image_refs - retained_image_refs
    image_files_to_prune = [
        image_disk_path(root, reference)
        for reference in sorted(image_refs_to_prune)
        if image_disk_path(root, reference) is not None and image_disk_path(root, reference).is_file()
    ]
    article_files_to_prune = [
        article_dir / f"{record_id}.md"
        for record_id in sorted(removed_ids)
        if (article_dir / f"{record_id}.md").is_file()
    ]

    print(f"C records: {len(c_records)}")
    print(f"C records retained: {len(c_records) - len(removed_ids)}")
    print(f"C records removed: {len(removed_ids)}")
    print(f"Removed statuses: {dict(Counter(str(record.get('crawl_status') or '') for record in removed_records))}")
    print(f"Article files to prune: {len(article_files_to_prune)}")
    print(f"Image files to prune: {len(image_files_to_prune)}")
    if not args.apply:
        print("dry-run only; pass --apply to modify the working tree")
        return 0

    atomic_write(index_path, filtered_index_bytes(index_path, original_lines, newline, bom, removed_ids))
    atomic_write(report_path, report_bytes)
    for path in article_files_to_prune:
        path.unlink()
    for path in image_files_to_prune:
        path.unlink()

    final_records, _, _, _ = load_index(index_path)
    if any(str(record.get("id") or "") in removed_ids for record in final_records):
        raise ValueError("removed record remains in index after filtering")
    validate_parent_closure(final_records, set())
    print(f"filtered {len(removed_ids)} C records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
