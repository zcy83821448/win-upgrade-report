# -*- coding: utf-8 -*-
"""更新线（频道）的定义与发现。

两类来源：
  * flighthub —— 微软 Flight Hub 官方看板，覆盖所有 Insider 频道（Experimental / Beta /
    Release Preview 的各条线）。既能拿到构建号，也直接拿到官方发布说明的精确链接，最可靠。
  * uupdump  —— 抓 uupdump 的某个分类，覆盖零售 / 正式版线（Flight Hub 不管这些）。
"""
import re
import datetime as dt

LEARN = "https://learn.microsoft.com"
FLIGHTHUB_URL = LEARN + "/en-us/windows-insider/flight-hub/"

# Flight Hub 的栏目目录名 -> 显示名
FH_NAMES = {
    "experimental": "Windows 11 26H2 Experimental（试验）",
    "experimental-future-platforms": "Windows 11 Experimental（未来平台）",
    "experimental-26-h1": "Windows 11 26H1 Experimental",
    "beta": "Windows 11 Beta",
    "beta-26h1": "Windows 11 26H1 Beta",
    "release-preview": "Windows 11 Release Preview",
    "release-preview-26h1": "Windows 11 26H1 Release Preview",
    "release-preview-24h2-25h2": "Windows 11 24H2/25H2 Release Preview",
    "dev": "Windows 11 Dev",
    "canary": "Windows 11 Canary",
}
FH_ORDER = list(FH_NAMES.keys())

# uupdump 分类 -> 显示名（零售 / 正式版线，以及备用入口）
UUP_NAMES = {
    "w11-26h2-experimental": "uupdump：26H2 Experimental",
    "w11-26h2": "uupdump：26H2（正式/零售）",
    "w11-26h1": "uupdump：26H1",
    "w11-25h2-beta": "uupdump：25H2 Beta",
    "w11-25h2": "uupdump：25H2（正式）",
    "w11-24h2-beta": "uupdump：24H2 Beta",
    "w11-24h2": "uupdump：24H2（正式）",
    "w11-23h2": "uupdump：23H2（正式）",
    "w11-22h2": "uupdump：22H2（正式）",
    "w11-21h2": "uupdump：21H2（正式）",
    "w10-22h2": "uupdump：Win10 22H2",
    "w10-21h2": "uupdump：Win10 21H2",
    "w10-1809": "uupdump：Win10 1809",
    "server-24h2": "uupdump：Server 24H2",
    "server-23h2": "uupdump：Server 23H2",
    "server-22h2": "uupdump：Server 22H2",
    "server-21h2": "uupdump：Server 21H2",
}
UUP_ORDER = list(UUP_NAMES.keys())

# 默认监控的线：就是最开始的 26H2 Experimental
DEFAULT_CHANNELS = [
    {"id": "fh:experimental", "source": "flighthub", "folder": "experimental",
     "name": FH_NAMES["experimental"], "enabled": True, "arch": "amd64"},
]


def fh_channel(folder):
    return {"id": "fh:" + folder, "source": "flighthub", "folder": folder,
            "name": FH_NAMES.get(folder, "Insider：" + folder),
            "enabled": False, "arch": "amd64"}


def uup_channel(category):
    return {"id": "uup:" + category, "source": "uupdump", "category": category,
            "name": UUP_NAMES.get(category, "uupdump：" + category),
            "enabled": False, "arch": "amd64"}


def all_presets():
    """界面里可勾选的全部预设（Flight Hub 优先）。"""
    return [fh_channel(f) for f in FH_ORDER] + [uup_channel(c) for c in UUP_ORDER]


def norm_channel(ch):
    """补齐字段、统一格式，保证各种来源的频道都能被主程序处理。"""
    ch = dict(ch)
    src = ch.get("source") or ("flighthub" if str(ch.get("id", "")).startswith("fh:")
                               else "uupdump")
    ch["source"] = src
    if src == "flighthub":
        folder = ch.get("folder") or str(ch.get("id", "")).split(":", 1)[-1]
        ch["folder"] = folder
        ch["id"] = "fh:" + folder
        ch.setdefault("name", FH_NAMES.get(folder, "Insider：" + folder))
    else:
        cat = ch.get("category")
        if not cat:
            url = ch.get("url") or ""
            m = re.search(r"category:([a-z0-9\-]+)", url)
            cat = m.group(1) if m else str(ch.get("id", "")).split(":", 1)[-1]
        ch["category"] = cat
        ch["url"] = ch.get("url") or (
            "https://uupdump.net/known.php?q=category:" + cat)
        ch["id"] = "uup:" + cat
        ch.setdefault("name", UUP_NAMES.get(cat, "uupdump：" + cat))
    ch.setdefault("arch", "amd64")
    ch["enabled"] = bool(ch.get("enabled", False))
    return ch


def pretty_build(build, source="uupdump"):
    """把内部版本标识整理成好看的样子（多构建的 KB 页面会带斜杠）。"""
    b = str(build or "").strip()
    b = re.sub(r"^(preview-)?build-", "", b)
    parts = [p for p in b.split("-") if p]
    # 28000-2605 -> 28000.2605 ；28000-2605-29000-3000 这种保留成 a/b
    out = []
    for i in range(0, len(parts) - 1, 2):
        if parts[i].isdigit() and parts[i + 1].isdigit():
            out.append(f"{parts[i]}.{parts[i + 1]}")
    return "/".join(out) if out else b


def build_sort_key(build):
    """用于判断“是不是更新了”的排序键：取主版本号的两个数字。"""
    nums = re.findall(r"\d+", str(build))
    try:
        return tuple(int(n) for n in nums[:2])
    except Exception:
        return (0, 0)


def rel_notes_url(href):
    """Flight Hub 里的相对链接 -> Learn 绝对链接。"""
    href = (href or "").strip()
    if href.startswith("http"):
        return href
    if href.startswith("../"):
        return LEARN + "/en-us/windows-insider/" + href[3:]
    if href.startswith("/"):
        return LEARN + href
    return LEARN + "/en-us/windows-insider/" + href.lstrip("./")


_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_LINK_RE = re.compile(r'<a[^>]+href="([^"]*release-notes[^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def parse_flighthub(page_html):
    """解析 Flight Hub：返回 {folder: {'latest': {...}, 'history': [...]}}"""
    out = {}
    for row in _ROW_RE.findall(page_html):
        cells = _CELL_RE.findall(row)
        if len(cells) < 2:
            continue
        build = re.sub(r"<[^>]+>", "", cells[0]).strip().strip("*").strip()
        m = _LINK_RE.search(cells[1]) or _LINK_RE.search(row)
        if not build or not m:
            continue
        href, inner = m.group(1), m.group(2)
        fm = re.search(r"release-notes/([^/]+)/", href)
        if not fm:
            continue
        folder = fm.group(1)
        dm = _DATE_RE.search(re.sub(r"<[^>]+>", "", inner)) or _DATE_RE.search(href)
        if dm:
            mm, dd, yy = (int(x) for x in dm.groups())
            try:
                when = dt.date(yy, mm, dd)
            except ValueError:
                when = None
        else:
            when = None
        item = {"build": build, "raw": href.rsplit("/", 1)[-1],
                "url": rel_notes_url(href), "date": when.isoformat() if when else "",
                "is_latest_mark": "*" in cells[0]}
        out.setdefault(folder, {"history": []})["history"].append(item)

    for folder, d in out.items():
        hist = d["history"]
        marked = [x for x in hist if x["is_latest_mark"]]
        if marked:
            d["latest"] = marked[0]
        else:
            dated = [x for x in hist if x["date"]]
            d["latest"] = max(dated, key=lambda x: x["date"]) if dated else hist[0]
    return out


def merge_discovered(configured, discovered):
    """把 Flight Hub 上发现的新频道补进配置（默认不启用），已配置的保留用户设置。"""
    known = {c["id"] for c in configured}
    added = []
    for folder in discovered:
        cid = "fh:" + folder
        if cid in known:
            continue
        added.append(fh_channel(folder))
    return configured + added, added
