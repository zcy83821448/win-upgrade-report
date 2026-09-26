# -*- coding: utf-8 -*-
"""极简 Markdown -> HTML，用于把报告以排版好的形式显示出来。无第三方依赖。"""
import re
import html


def _esc(t):
    return html.escape(t, quote=False)


def _inline(t):
    t = _esc(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               r'<a href="\2" target="_blank">\1</a>', t)
    t = re.sub(r"(?<![\"'>=])(https?://[^\s<)]+)",
               r'<a href="\1" target="_blank">\1</a>', t)
    return t


def _table(rows):
    out = ['<table>']
    for i, row in enumerate(rows):
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if i == 1 and all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue
        tag = "th" if i == 0 else "td"
        out.append("<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def to_html(md):
    lines = md.replace("\r\n", "\n").split("\n")
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()

        if s.startswith("```"):
            lang = s[3:].strip()
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append(f'<pre><code class="lang-{_esc(lang)}">{_esc(chr(10).join(buf))}</code></pre>')
            continue

        if not s:
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            out.append("<hr>")
            i += 1
            continue

        if s.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue

        if re.match(r"^[-*+]\s+", s):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*+]\s+", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + "</ul>")
            continue

        if re.match(r"^\d+[.)]\s+", s):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+[.)]\s+", "", lines[i]))
                i += 1
            out.append("<ol>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + "</ol>")
            continue

        if s.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + _inline(" ".join(buf)) + "</blockquote>")
            continue

        buf = [s]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|-{3,})", lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>" + _inline(" ".join(buf)) + "</p>")
    return "\n".join(out)


PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root{{color-scheme:light dark}}
body{{margin:0;padding:40px 20px;background:#f6f7f9;color:#1b1d21;
 font:16px/1.75 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}}
main{{max-width:820px;margin:0 auto;background:#fff;border-radius:14px;
 padding:40px 44px;box-shadow:0 4px 24px rgba(0,0,0,.08)}}
h1{{font-size:27px;margin:0 0 6px}} h2{{font-size:20px;margin:30px 0 10px;
 padding-bottom:6px;border-bottom:1px solid #e6e8eb}}
h3{{font-size:17px;margin:22px 0 8px}}
p,li{{margin:8px 0}} ul,ol{{padding-left:24px}}
code{{background:#f0f1f3;border-radius:5px;padding:1px 5px;font-size:14px;
 font-family:Consolas,monospace}}
pre{{background:#f7f8fa;border:1px solid #e6e8eb;border-radius:9px;padding:14px;
 overflow:auto}} pre code{{background:none;padding:0}}
a{{color:#0a6cff;text-decoration:none}} a:hover{{text-decoration:underline}}
blockquote{{margin:12px 0;padding:8px 16px;border-left:3px solid #0a6cff;
 background:#f4f8ff;border-radius:0 8px 8px 0}}
table{{border-collapse:collapse;width:100%;margin:14px 0}}
th,td{{border:1px solid #e2e5e9;padding:8px 12px;text-align:left}}
th{{background:#f7f8fa}}
hr{{border:none;border-top:1px solid #e6e8eb;margin:26px 0}}
@media (prefers-color-scheme:dark){{
 body{{background:#17181b;color:#e6e7ea}} main{{background:#212327;
 box-shadow:none}} h2{{border-color:#33373d}} code,pre{{background:#2a2d32;
 border-color:#33373d}} th{{background:#2a2d32}} th,td{{border-color:#33373d}}
 hr{{border-color:#33373d}} blockquote{{background:#1d2735}}}}
</style></head><body><main>
{body}
</main></body></html>
"""


def render_page(md, title="Windows 更新报告"):
    return PAGE.format(title=_esc(title), body=to_html(md))


EXTRA_CSS = """
ul.tl{list-style:none;padding:0;margin:0}
ul.tl li{display:flex;align-items:center;gap:10px;padding:9px 4px;
 border-bottom:1px solid #eceef1;flex-wrap:wrap}
ul.tl .t{color:#7a8090;font-size:14px;min-width:118px;font-variant-numeric:tabular-nums}
ul.tl .c{font-weight:600;min-width:220px}
ul.tl .b{font-family:Consolas,monospace;font-size:14px;color:#4a5160;min-width:96px}
ul.tl a.m{color:#8a90a0;font-size:13px}
p.sub{color:#6b7280;margin:0 0 18px}
@media (prefers-color-scheme:dark){
 ul.tl li{border-color:#33373d} ul.tl .t{color:#9aa0ad} ul.tl .b{color:#a8aeba}
 p.sub{color:#9aa0ad}}
"""


def render_raw(body_html, title="Windows 更新报告"):
    """直接用已经写好的 HTML 作为正文（用于总览页这类自己拼 HTML 的场景）。"""
    extra = EXTRA_CSS.replace("{", "{{").replace("}", "}}")
    return PAGE.replace("</style>", extra + "</style>").format(
        title=_esc(title), body=body_html)
