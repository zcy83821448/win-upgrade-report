# -*- coding: utf-8 -*-
"""写报告、维护每频道的报告列表和总览页 index.html。"""
import os
import re
import glob
import html
import datetime as dt

from mdlite import render_page, render_raw
from config import REPORT_DIR, atomic_write_text, resource_path

INDEX_NAME = "总览.html"

_READER_CSS_CACHE = None


def reader_css():
    """报告排版 CSS 的唯一来源：webui/reader.css。

    设置窗口内嵌预览、独立报告窗口、浏览器直接打开的报告页都读这一份，
    保证四个地方看起来一模一样（以前被复制成三份，已经出现字号漂移）。
    """
    global _READER_CSS_CACHE
    if _READER_CSS_CACHE is None:
        try:
            p = resource_path(os.path.join("webui", "reader.css"))
            with open(p, "r", encoding="utf-8") as f:
                _READER_CSS_CACHE = f.read()
        except Exception:
            _READER_CSS_CACHE = ""
    return _READER_CSS_CACHE


def reader_style_tag():
    css = reader_css()
    if not css:
        return ""
    return '<style id="winupd-reader">\n' + css + '\n</style>'



def chan_slug(cid):
    """频道 id -> 目录名 / 通知参数里用的短标识（纯 ASCII）。"""
    s = re.sub(r"[^A-Za-z0-9\-]+", "_", str(cid)).strip("_")
    return s or "chan"


def chan_dir(cfg, cid):
    base = cfg.get("report_dir") or REPORT_DIR
    d = os.path.join(base, chan_slug(cid))
    os.makedirs(d, exist_ok=True)
    return d


def report_paths(cfg, cid, build, date_str):
    d = chan_dir(cfg, cid)
    stem = f"更新报告_{build.replace('.', '-')}_{date_str}"
    return os.path.join(d, stem + ".md"), os.path.join(d, stem + ".html")


def write(cfg, cid, build, markdown, title=None):
    """写报告：md 和 html 都原子落盘，浏览器不会读到写了一半的半页。"""
    date_str = dt.date.today().isoformat()
    md_path, html_path = report_paths(cfg, cid, build, date_str)
    atomic_write_text(md_path, markdown.rstrip() + "\n")
    try:
        page = render_page(markdown, title or os.path.basename(md_path)[:-3],
                           extra_css=reader_style_tag())
        atomic_write_text(html_path, page)
    except Exception:
        html_path = ""
    return md_path, html_path


def prune(cfg, cid, keep=None):
    """每个频道只留最近 N 份报告，防止越堆越多。"""
    keep = int(keep or cfg.get("keep_reports") or 200)
    d = chan_dir(cfg, cid)
    files = sorted(glob.glob(os.path.join(d, "*.md")), key=os.path.getmtime, reverse=True)
    for old in files[keep:]:
        for p in (old, os.path.splitext(old)[0] + ".html"):
            try:
                os.remove(p)
            except Exception:
                pass


def one_line_summary(md):
    blocks = md.split("## ")
    for b in blocks:
        if b.startswith("一句话总结"):
            for ln in b.split("\n")[1:]:
                ln = ln.strip().strip("*# ").strip()
                if ln and not ln.startswith("（"):
                    return ln[:120]
    # 退而求其次：第一段正文
    for ln in md.split("\n"):
        ln = ln.strip()
        if ln and not ln.startswith(("#", "-", "*", "|", ">")):
            return ln[:120]
    return ""


def _rel(path, base):
    try:
        return os.path.relpath(path, base).replace("\\", "/")
    except Exception:
        return path.replace("\\", "/")


def write_index(cfg, state, chan_names):
    """生成总览页：所有频道的报告时间线 + 当前基线版本。"""
    base = cfg.get("report_dir") or REPORT_DIR
    rows = []
    for cid, cs in (state.get("channels") or {}).items():
        d = chan_dir(cfg, cid)
        for md in glob.glob(os.path.join(d, "*.md")):
            htmlf = os.path.splitext(md)[0] + ".html"
            build = ""
            m = re.search(r"更新报告_([0-9\-]+)_(\d{4}-\d{2}-\d{2})", os.path.basename(md))
            if m:
                build = m.group(1).replace("-", ".", 1)
            rows.append({
                "time": dt.datetime.fromtimestamp(os.path.getmtime(md)),
                "channel": chan_names.get(cid, cid),
                "build": build,
                "md": md,
                "html": htmlf if os.path.exists(htmlf) else md,
            })
    rows.sort(key=lambda r: r["time"], reverse=True)

    cards = []
    for cid, cs in sorted((state.get("channels") or {}).items()):
        cards.append(
            "<tr><td>{}</td><td><code>{}</code></td><td>{}</td><td>{}</td></tr>".format(
                html.escape(chan_names.get(cid, cid)),
                html.escape(str(cs.get("last_version") or "—")),
                html.escape(str(cs.get("last_check_date") or "—")),
                (f'<a href="{html.escape(_rel(cs.get("last_report"), base))}">最近报告</a>'
                 if cs.get("last_report") else "—")))

    items = []
    for r in rows[:300]:
        items.append(
            f'<li><span class="t">{r["time"]:%Y-%m-%d %H:%M}</span>'
            f'<span class="c">{html.escape(r["channel"])}</span>'
            f'<span class="b">{html.escape(r["build"] or "")}</span>'
            f'<a href="{html.escape(_rel(r["html"], base))}">打开</a>'
            f' <a class="m" href="{html.escape(_rel(r["md"], base))}">md</a></li>')

    body = f"""
<h1>Windows 更新报告 · 总览</h1>
<p class="sub">共 {len(rows)} 份报告，覆盖 {len(cards)} 条更新线。点击右侧「打开」看排版好的报告。</p>
<h2>各条线当前基线</h2>
<table><tr><th>更新线</th><th>当前记录版本</th><th>上次检测</th><th>报告</th></tr>
{''.join(cards) or '<tr><td colspan="4">还没有记录</td></tr>'}</table>
<h2>报告时间线</h2>
<ul class="tl">{''.join(items) or '<li>还没有报告</li>'}</ul>
"""
    path = os.path.join(base, INDEX_NAME)
    atomic_write_text(path, render_raw(body, "Windows 更新报告总览"))
    return path
