# -*- coding: utf-8 -*-
"""把报告的 Markdown 解析成结构化块，供 WPF 原生渲染（不依赖 HTML/WebView）。

解析规则和 mdlite.py 保持同一套方言（报告都是它生成/展示的），只是输出
JSON 块而不是 HTML，行内样式（粗体/代码/链接/删除线/斜体）拆成 span 列表，
由前端按段落样式统一排版。
"""
import re

# 行内 token：代码、粗体、斜体、删除线、链接、裸链接
_INLINE_RE = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\*\*(?P<bold>[^*]+)\*\*"
    r"|~~(?P<del>[^~]+)~~"
    r"|(?<!\*)\*(?P<em>[^*\n]+)\*(?!\*)"
    r"|\[(?P<ltext>[^\]]+)\]\((?P<lhref>https?://[^)\s]+)\)"
    r"|(?P<url>https?://[^\s<)]+)"
)


def _spans(text):
    """把一行文本拆成 [{"t":"text"|"code"|"b"|"i"|"s"|"a", "v":..., "href":...}]。"""
    out = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            out.append({"t": "text", "v": text[pos:m.start()]})
        if m.group("code") is not None:
            out.append({"t": "code", "v": m.group("code")})
        elif m.group("bold") is not None:
            out.append({"t": "b", "v": m.group("bold")})
        elif m.group("del") is not None:
            out.append({"t": "s", "v": m.group("del")})
        elif m.group("em") is not None:
            out.append({"t": "i", "v": m.group("em")})
        elif m.group("lhref") is not None:
            out.append({"t": "a", "v": m.group("ltext"), "href": m.group("lhref")})
        elif m.group("url") is not None:
            out.append({"t": "a", "v": m.group("url"), "href": m.group("url")})
        pos = m.end()
    if pos < len(text):
        out.append({"t": "text", "v": text[pos:]})
    return [s for s in out if s["v"]]


def _table_rows(rows):
    head = []
    body = []
    for idx, row in enumerate(rows):
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if idx == 1 and all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue
        if idx == 0:
            head = [_spans(c) for c in cells]
        else:
            body.append([_spans(c) for c in cells])
    return {"t": "table", "head": head, "rows": body}


def to_blocks(md):
    """Markdown -> 块列表。空行/纯空白不会产生空块。"""
    lines = str(md or "").replace("\r\n", "\n").split("\n")
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        s = ln.strip()

        if s.startswith("```"):
            lang = s[3:].strip()
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append({"t": "code", "lang": lang, "text": "\n".join(buf)})
            continue

        if not s:
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            blocks.append({"t": "h", "level": len(m.group(1)),
                           "spans": _spans(m.group(2))})
            i += 1
            continue

        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            blocks.append({"t": "hr"})
            i += 1
            continue

        if s.startswith("|") and i + 1 < n and lines[i + 1].strip().startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            blocks.append(_table_rows(rows))
            continue

        if re.match(r"^[-*+]\s+", s):
            items = []
            while i < n and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(_spans(re.sub(r"^\s*[-*+]\s+", "", lines[i])))
                i += 1
            blocks.append({"t": "ul", "items": items})
            continue

        if re.match(r"^\d+[.)]\s+", s):
            items = []
            while i < n and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                items.append(_spans(re.sub(r"^\s*\d+[.)]\s+", "", lines[i])))
                i += 1
            blocks.append({"t": "ol", "items": items})
            continue

        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append({"t": "quote", "spans": _spans(" ".join(buf))})
            continue

        buf = [s]
        i += 1
        while i < n and lines[i].strip() and not re.match(
                r"^(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|-{3,})", lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        blocks.append({"t": "p", "spans": _spans(" ".join(buf))})

    return blocks


def title_of(blocks, fallback="Windows 更新报告"):
    for b in blocks:
        if b.get("t") == "h" and b.get("level") == 1:
            text = "".join(s.get("v", "") for s in b.get("spans") or [])
            if text.strip():
                return text.strip()
    return fallback
