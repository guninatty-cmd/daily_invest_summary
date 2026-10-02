# -*- coding: utf-8 -*-
import json
import os
import re
from jinja2 import Environment, FileSystemLoader

# ---------- Watchlist ticker highlighting ----------
# 관심 종목의 단일 출처는 저장소의 watchlist.txt(티커 한 줄에 하나, # 은 주석)다.
# 렌더 전에 같은 폴더에 watchlist.txt를 내려받아 두면 해당 티커 배지가 별표+호박색으로 강조된다.
# 카드 데이터의 tickers는 "애플(AAPL)" 또는 "S&P500" 같은 문자열이며, 괄호 안 심볼을 비교한다.
def _extract_ticker_symbol(ticker_str):
    m = re.search(r"\(([^)]+)\)", ticker_str)
    return (m.group(1) if m else ticker_str).strip().upper()

def load_watchlist_tickers(path="watchlist.txt"):
    tickers = set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if line:
                tickers.add(line.upper())
    return tickers
SECTION_META = {
    "macro": {"label": "거시·정책", "color": "#2563eb"},
    "market": {"label": "시장 흐름", "color": "#7c3aed"},
    "industry": {"label": "산업·테마", "color": "#0d9488"},
    "stock": {"label": "개별 기업", "color": "#c2410c"},
    "youtube": {"label": "유튜브 분석", "color": "#be123c"},
}
SENTIMENT_CLASS = {
    "호재": "tag-positive",
    "악재": "tag-negative",
    "중립": "tag-neutral",
}
_TOC_PAGE_CONTENT_MM = 222.0        # mobile page height (240mm, tuned to fit one phone screen without in-page scroll) minus @page top/bottom margins (9mm+9mm)
_TOC_HEADER_BLOCK_MM = 31.0
_TOC_SECTION_HEAD_MM = 11.0
_TOC_SECTION_GAP_MM = 5.0
_TOC_MORE_LINE_MM = 4.5
_TOC_LI_PADDING_MM = 3.2
_TOC_LINE_HEIGHT_MM = 7.7
_TOC_CHARS_PER_LINE = 27
_TOC_SAFETY_MARGIN_MM = 7.0
def _toc_lines_for_title(title):
    import math
    return max(1, math.ceil(len(title) / _TOC_CHARS_PER_LINE))
def _toc_item_height_mm(title):
    return _TOC_LI_PADDING_MM + _TOC_LINE_HEIGHT_MM * _toc_lines_for_title(title)
def compute_cover_toc(data, sections=("macro", "market", "industry", "stock", "youtube")):
    present = [s for s in sections if data.get(s)]
    overhead = len(present) * (_TOC_SECTION_HEAD_MM + _TOC_SECTION_GAP_MM)
    budget = _TOC_PAGE_CONTENT_MM - _TOC_HEADER_BLOCK_MM - overhead - _TOC_SAFETY_MARGIN_MM
    shown_count = {s: len(data[s]) for s in present}
    heights = {s: [_toc_item_height_mm(it["title"]) for it in data[s]] for s in present}
    hidden = {s: 0 for s in present}
    def total_height():
        t = 0.0
        for s in present:
            t += sum(heights[s][: shown_count[s]])
            if hidden[s] > 0:
                t += _TOC_MORE_LINE_MM
        return t
    guard = sum(shown_count.values()) + 1
    while total_height() > budget and guard > 0:
        guard -= 1
        candidates = [s for s in present if shown_count[s] > 0]
        if not candidates:
            break
        s = max(candidates, key=lambda s: shown_count[s])
        shown_count[s] -= 1
        hidden[s] += 1
    return {
        s: {"shown": data[s][: shown_count[s]], "hidden": hidden[s]}
        for s in present
    }
_FS_HEADER_BLOCK_MM = 14.0
_FS_ITEM_PADDING_MM = 2.6
_FS_LINE_HEIGHT_MM = 6.5
_FS_CHARS_PER_LINE = 18
_FS_MORE_LINE_MM = 4.5
_FS_SAFETY_MARGIN_MM = 18.0
def _fs_lines_for_title(title):
    import math
    return max(1, math.ceil(len(title) / _FS_CHARS_PER_LINE))
def _fs_item_height_mm(title):
    return _FS_ITEM_PADDING_MM + _FS_LINE_HEIGHT_MM * _fs_lines_for_title(title)
def compute_factsheet_cover(data):
    reports = data.get("factsheet_reports") or []
    if not reports:
        return {"shown": [], "hidden": 0}
    budget = _TOC_PAGE_CONTENT_MM - _FS_HEADER_BLOCK_MM - _FS_SAFETY_MARGIN_MM
    n = len(reports)
    while n > 0:
        hidden = len(reports) - n
        h = sum(_fs_item_height_mm(r["title"]) for r in reports[:n])
        if hidden > 0:
            h += _FS_MORE_LINE_MM
        if h <= budget:
            break
        n -= 1
    return {"shown": reports[:n], "hidden": len(reports) - n}
def build_report_pdf(data, out_path, charts=None, snapshots=None, template_dir=None, watchlist_tickers=None):
    template_dir = template_dir or os.path.dirname(os.path.abspath(__file__))
    env = Environment(loader=FileSystemLoader(template_dir))
    if watchlist_tickers is None:
        watchlist_tickers = load_watchlist_tickers(os.path.join(template_dir, "watchlist.txt"))
    env.globals["in_watchlist"] = lambda t: _extract_ticker_symbol(t) in watchlist_tickers
    tmpl = env.get_template("template.html")
    cover_toc = compute_cover_toc(data)
    factsheet_cover = compute_factsheet_cover(data)
    html = tmpl.render(data=data, section_meta=SECTION_META, sentiment_class=SENTIMENT_CLASS,
                        cover_toc=cover_toc, factsheet_cover=factsheet_cover)
    with open(os.path.join(template_dir, "_rendered.html"), "w", encoding="utf-8") as f:
        f.write(html)
    from weasyprint import HTML
    HTML(string=html, base_url=template_dir).write_pdf(out_path)
    return out_path
if __name__ == "__main__":
    d = json.load(open("report_data.json", encoding="utf-8"))
    build_report_pdf(d, "output.pdf")
    print("done")
