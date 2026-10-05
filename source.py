# -*- coding: utf-8 -*-
"""数据来源：Flight Hub（Insider 频道）+ uupdump（正式版线）+ 官方发布说明原文。

所有网络请求都走 http_get：支持代理、超时、重试。
"""
import re
import html
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import channels as ch_mod

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
}
SSL_CTX = ssl.create_default_context()

# 运行期参数，由 checker 从 config 注入
SETTINGS = {"proxy": "", "timeout": 30, "retries": 2}


def configure(cfg):
    SETTINGS["proxy"] = (cfg.get("proxy") or "").strip()
    SETTINGS["timeout"] = int(cfg.get("request_timeout") or 30)
    SETTINGS["retries"] = max(0, int(cfg.get("retries") if cfg.get("retries") is not None else 2))


def settings_snapshot():
    """给并发探测用的设置快照：多条线同时抓时，每条都拿自己的一份，
    免得跑到一半 configure() 改了全局设置（历史上 configure 确实被调过两次）。"""
    return dict(SETTINGS)


class FetchError(Exception):
    pass


# opener 按代理设置缓存：同一份设置下反复请求时不必重建 handler 链。
# 上游每个频道都要抓一次页面，重试还会再来一遍，这里省的是关键路径上的纯浪费。
_OPENERS = {}


def _opener(proxy=None):
    key = SETTINGS["proxy"] if proxy is None else proxy
    op = _OPENERS.get(key)
    if op is None:
        handlers = []
        if key:
            handlers.append(urllib.request.ProxyHandler({"http": key, "https": key}))
        handlers.append(urllib.request.HTTPSHandler(context=SSL_CTX))
        op = urllib.request.build_opener(*handlers)
        _OPENERS[key] = op
    return op


def _decode(raw):
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def http_get(url, timeout=None, headers=None, retries=None, settings=None):
    st = settings or SETTINGS
    timeout = timeout or st["timeout"]
    retries = st["retries"] if retries is None else retries
    opener = _opener(st.get("proxy") or "")
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=headers or HEADERS)
        try:
            with opener.open(req, timeout=timeout) as r:
                raw = r.read()
            return _decode(raw)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
    raise FetchError(f"{type(last).__name__}: {last}") from last


# ------------------------------------------------- 「变了没有」的条件请求

class Conditional:
    """记住每个网址上次的 ETag / Last-Modified，下次带上它去问「变了没有」。

    为什么需要它：哨兵每 5 分钟看一次官方看板，如果每次都把整页拉下来
    （约 113 KB），一天就是 30 多 MB，纯浪费。带上上次的标记去问，没变化时
    微软服务器直接回 304，**传输 0 字节**，连 HTML 都不用解析。
    这是实测确认过的（Flight Hub 支持 ETag 和 Last-Modified）。

    用法：
        cond = Conditional()
        status, text = cond.get(url)
        if status == 304:      # 没变化，什么都不用做
            ...
        else:                  # 有新内容，text 就是整页
            ...
    """

    def __init__(self):
        self._marks = {}          # url -> {"etag":..., "lastmod":...}
        self.hits = 0             # 回 304（没变化）的次数
        self.misses = 0           # 真的拉了全文的次数

    def forget(self):
        """丢掉所有标记：下次一定拿全文（例如怀疑自己漏掉了变化）。"""
        self._marks.clear()

    def get(self, url, timeout=None, settings=None):
        st = settings or SETTINGS
        timeout = timeout or st["timeout"]
        retries = st["retries"]
        opener = _opener(st.get("proxy") or "")
        mark = self._marks.get(url) or {}
        headers = dict(HEADERS)
        if mark.get("etag"):
            headers["If-None-Match"] = mark["etag"]
        if mark.get("lastmod"):
            headers["If-Modified-Since"] = mark["lastmod"]

        last = None
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, headers=headers)
            try:
                with opener.open(req, timeout=timeout) as r:
                    raw = r.read()
                    # 响应头要在 with 里面读，出了这个块对象就关了
                    self._marks[url] = {"etag": r.headers.get("ETag") or "",
                                        "lastmod": r.headers.get("Last-Modified") or ""}
                self.misses += 1
                return 200, _decode(raw)
            except urllib.error.HTTPError as e:
                if e.code == 304:
                    self.hits += 1
                    return 304, None          # 没变化：正文压根没下载
                last = e
                if e.code in (403, 429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
            except Exception as e:
                last = e
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
        raise FetchError(f"{type(last).__name__}: {last}") from last


# ------------------------------------------------------------- Flight Hub

def flighthub(timeout=None, settings=None):
    """抓 Flight Hub 并解析出所有 Insider 频道的最新构建。"""
    page = http_get(ch_mod.FLIGHTHUB_URL, timeout=timeout, settings=settings)
    data = ch_mod.parse_flighthub(page)
    if not data:
        raise FetchError("Flight Hub 页面没解析出任何频道，页面结构可能变了")
    return data


def flighthub_conditional(cond, timeout=None, settings=None):
    """哨兵用的版本：先问「变了没有」，真的变了才解析。

    返回 (状态码, 数据)：
        (304, None)  —— 一点都没变，什么都没下载，直接跳过
        (200, {...}) —— 有新内容，data 是解析好的各条线最新构建
    """
    status, page = cond.get(ch_mod.FLIGHTHUB_URL, timeout=timeout, settings=settings)
    if status == 304:
        return 304, None
    data = ch_mod.parse_flighthub(page)
    if not data:
        # 页面结构变了的话，标记要丢掉，否则会一直卡在「看起来变了但解析不出来」
        cond.forget()
        raise FetchError("Flight Hub 页面没解析出任何频道，页面结构可能变了")
    return 200, data


# --------------------------------------------------------------- uupdump

_ROW_RE = re.compile(
    r"<tr>\s*<td>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>",
    re.S | re.I)
_BUILD_RE = re.compile(r"\((\d{4,6}\.\d+)\)")


def parse_uupdump(page_html):
    rows = []
    for m in _ROW_RE.finditer(page_html):
        cell, arch, date = m.group(1), m.group(2), m.group(3)
        text = re.sub(r"<[^>]+>", " ", cell)
        bm = _BUILD_RE.search(text)
        if not bm:
            continue
        clean = lambda s: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
        rows.append({"build": bm.group(1), "name": clean(cell),
                     "arch": clean(arch), "date": clean(date)})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def uupdump_latest(url_or_category, arch="amd64", timeout=None, settings=None):
    url = url_or_category
    if not url.startswith("http"):
        url = "https://uupdump.net/known.php?q=category:" + url_or_category
    rows = parse_uupdump(http_get(url, timeout=timeout, settings=settings))
    if not rows:
        raise FetchError("uupdump 页面里没解析到任何版本，页面结构可能变了")
    # 先按构建号归并，取构建号最新的那一组；组内再按偏好挑架构
    newest_build = rows[0]["build"]                      # 行已按日期倒序
    same = [r for r in rows if r["build"] == newest_build]
    want = (arch or "amd64").lower()
    pick = next((r for r in same if want[:3] in r["arch"].lower()), same[0])
    return pick, rows


# ---------------------------------------------------------- 官方发布说明

_LEARN_SEARCH = "https://learn.microsoft.com/api/search?locale=en-us&$top=10&search="
# 若 Flight Hub / Learn 都没有，退到这几个搜索页找线索
_DDG = "https://html.duckduckgo.com/html/?q="

_JUNK = ("Table of contents", "Exit editor mode", "Ask Learn", "Reading mode",
         "Read in English", "Add to Plans", "Copy Markdown", "Print", "Feedback",
         "Summarize this article for me", "Access to this page requires authorization",
         "Add", "Edit", "Note")


def page_text(page_html):
    m = re.search(r"<main[^>]*>(.*?)</main>", page_html, re.S | re.I)
    body = m.group(1) if m else page_html
    body = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", body,
                  flags=re.S | re.I)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    body = re.sub(r"<br\s*/?>|</p>|</li>|</h[1-6]>|</tr>", "\n", body, flags=re.I)
    txt = html.unescape(re.sub(r"<[^>]+>", " ", body))
    txt = re.sub(r"[ \t ]+", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n", txt)
    lines = [ln.strip() for ln in txt.split("\n")]
    lines = [ln for ln in lines if ln and ln not in _JUNK]
    return "\n".join(lines).strip()


def _try_learn_search(build, major):
    """用 Learn 站内搜索按构建号找官方说明；major 用于排除搜错的页面。"""
    try:
        data = json.loads(http_get(_LEARN_SEARCH + urllib.parse.quote(build)))
    except Exception:
        return None, ""
    want_slug = str(build).replace(".", "-")
    for item in data.get("results", []):
        u = item.get("url", "")
        if "release-notes" not in u and "release-health" not in u:
            continue
        if "release-notes" in u and major and want_slug not in u and major not in u:
            continue          # 别把别的版本的说明当成本版本的
        try:
            txt = page_text(http_get(u))
        except Exception:
            continue
        if len(txt) > 200:
            return u, txt
    return None, ""


def _try_ddg(build, major):
    try:
        h = http_get(_DDG + urllib.parse.quote(f"Windows 11 build {build} release notes"))
    except Exception:
        return None, ""
    urls = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"', h):
        raw = m.group(1)
        um = re.search(r"uddg=([^&\"]+)", raw)
        u = urllib.parse.unquote(um.group(1)) if um else raw
        if "/l/?uddg=" in u:
            continue
        urls.append(u)
    urls = [u for u in urls if "duckduckgo" not in u]
    # 官方站点优先
    urls.sort(key=lambda u: (0 if "microsoft.com" in u else 1))
    for u in urls:
        if major and major not in u:
            continue
        try:
            txt = page_text(http_get(u))
        except Exception:
            continue
        if len(txt) > 200:
            return u, txt
    return None, ""


def official_notes(build, hints=None, major=None):
    """按可靠性依次尝试，返回 (url, 原文, 来源种类)。

    hints: 已知的候选链接列表（Flight Hub 上的官方说明链接优先用它）
    """
    major = major or (re.findall(r"\d{4,6}", str(build)) or [""])[0]
    for url in (hints or []):
        try:
            txt = page_text(http_get(url))
            if len(txt) > 200:
                return url, txt, "官方（链接已知）"
        except Exception:
            continue
    u, t = _try_learn_search(build, major)
    if t:
        return u, t, "微软 Learn 搜索"
    u, t = _try_ddg(build, major)
    if t:
        return u, t, "搜索到的官方页面"
    return None, "", ""
