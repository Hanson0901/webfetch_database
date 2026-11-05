#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""產生「原始網頁 vs 清理後正文」對照截圖（headless Chrome + Pillow 併圖）。

用法：
  python3 tools/make_screenshots.py            # 產生預設 4 組對照
僅使用標準函式庫與 Pillow，不需要 playwright。
"""
import json
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.abspath(os.path.join(__file__, "..")))
OUT = os.path.join(ROOT, "report", "screenshots")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE = os.path.join(ROOT, ".chrome-profile")

# 三種不同類型網站 + 一個前端渲染（SPA）案例
TARGETS = [
    ("A_page_001", "維基百科（百科全書型）"),
    ("A_page_028", "國家文化記憶庫（策展資料庫型）"),
    ("A_page_010_ext_02", "桃園市觀音區公所（政府機關型）"),
    ("A_page_010_ext_01", "桃園觀光導覽網（前端渲染 SPA 型）"),
]

FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


def font(size):
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                continue
    return ImageFont.load_default()


def esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def md_to_html(md, title):
    """把爬蟲輸出的 Markdown 轉成簡單 HTML，用於「清理後」對照截圖。"""
    lines = md.splitlines()
    out, in_list = [], False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for ln in lines:
        s = ln.rstrip()
        if not s.strip():
            close_list()
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            close_list()
            lv = min(len(m.group(1)) + 1, 4)
            out.append("<h%d>%s</h%d>" % (lv, esc(m.group(2)), lv))
            continue
        if re.match(r"^[-*]\s+", s):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>%s</li>" % esc(re.sub(r"^[-*]\s+", "", s)))
            continue
        if s.startswith("!["):
            close_list()
            continue
        close_list()
        out.append("<p>%s</p>" % esc(s))
    close_list()
    body = "\n".join(out)
    return """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>%s</title><style>
body{font-family:"PingFang TC","Helvetica Neue",Arial,sans-serif;margin:0;background:#fff;color:#1b1b1b}
.wrap{max-width:1000px;margin:0 auto;padding:28px 36px 60px}
h1{font-size:28px;line-height:1.35;margin:0 0 6px}
.badge{display:inline-block;background:#e8f0fe;color:#1a3d7c;border-radius:4px;padding:2px 8px;font-size:13px;margin-bottom:18px}
h2{font-size:21px;margin:24px 0 8px;border-left:4px solid #1a73e8;padding-left:10px}
h3,h4{font-size:17px;margin:18px 0 6px}
p,li{font-size:15.5px;line-height:1.85;margin:8px 0}
ul{padding-left:26px}
</style></head><body><div class="wrap">
<div class="badge">清理後結果：結構化欄位 ＋ 正文（crawler_member_A.py 輸出）</div>
<h1>%s</h1>
%s
</div></body></html>""" % (esc(title), esc(title), body)


def shoot(url, path, height=2200, wait=8000):
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
           "--disable-extensions", "--user-data-dir=" + PROFILE,
           "--window-size=1280,%d" % height,
           "--virtual-time-budget=%d" % wait,
           "--screenshot=" + path, url]
    tmp = path + ".tmp.png"
    cmd[-1] = url
    cmd = [c if not c.startswith("--screenshot=") else "--screenshot=" + tmp for c in cmd]
    for attempt in range(2):
        try:
            subprocess.run(cmd, capture_output=True, timeout=55)
        except subprocess.TimeoutExpired:
            pass
        if os.path.exists(tmp) and os.path.getsize(tmp) > 20000:
            Image.open(tmp).convert("RGB").save(path, quality=90, optimize=True)
            os.remove(tmp)
            return True
        # 清掉半成品，重試一次（部分 tycg 頁面連線會間歇性停滯）
        if os.path.exists(tmp):
            os.remove(tmp)
    return False


def label(img, text, sub=None):
    W = img.width
    bar = Image.new("RGB", (W, 64), (26, 115, 232))
    d = ImageDraw.Draw(bar)
    d.text((18, 12), text, font=font(24), fill=(255, 255, 255))
    if sub:
        d.text((18, 40), sub, font=font(15), fill=(230, 240, 255))
    out = Image.new("RGB", (W, img.height + 64), (255, 255, 255))
    out.paste(bar, (0, 0))
    out.paste(img, (0, 64))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    lines = []
    for pid, kind in TARGETS:
        rec = json.load(open(os.path.join(ROOT, "output", "records", pid + ".json"), encoding="utf-8"))
        md = open(os.path.join(ROOT, "output", "articles", pid + ".md"), encoding="utf-8").read()
        # 只取正文（去掉 md 內的 front-matter 區塊）
        body = md
        if md.startswith("#"):
            body = md
        raw_jpg = os.path.join(OUT, pid + "_original.jpg")
        clean_jpg = os.path.join(OUT, pid + "_cleaned.jpg")
        ok1 = shoot(rec["final_url"] if rec.get("final_url") else rec["source_url"], raw_jpg)
        html_path = os.path.join(tempfile.gettempdir(), pid + "_cleaned.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(md_to_html(body, rec["title"]))
        ok2 = shoot("file://" + html_path, clean_jpg, height=2200)
        status = "ok" if (ok1 and ok2) else "fail"
        lines.append((pid, kind, status, ok1, ok2))
        print("%-16s %-28s original=%s cleaned=%s" % (pid, kind, ok1, ok2))
        if ok1 and ok2:
            a = Image.open(raw_jpg).convert("RGB")
            b = Image.open(clean_jpg).convert("RGB")
            h = min(a.height, b.height)
            a = a.crop((0, 0, a.width, h))
            b = b.crop((0, 0, b.width, h))
            a = label(a, "原始網頁（原始網址）", kind)
            b = label(b, "清理後結果（結構化欄位 ＋ 正文）", "移除導覽列／選單／頁尾／廣告／社群分享／Cookie 提示")
            comp = Image.new("RGB", (a.width + b.width + 16, max(a.height, b.height)), (210, 214, 220))
            comp.paste(a, (0, 0))
            comp.paste(b, (a.width + 16, 0))
            comp.save(os.path.join(OUT, pid + "_compare.jpg"), quality=88, optimize=True)
            print("  -> %s_compare.jpg (%dx%d)" % (pid, comp.width, comp.height))
    with open(os.path.join(OUT, "screenshots_manifest.json"), "w", encoding="utf-8") as f:
        json.dump([{"id": p, "site_type": k, "status": s, "original": o, "cleaned": c}
                   for p, k, s, o, c in lines], f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
