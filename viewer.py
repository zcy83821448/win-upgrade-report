# -*- coding: utf-8 -*-
"""报告查看器：报告在独立的原生窗口（WebView2 + 自绘窗口边框）里看。

由通知点击（winupdrept: 协议）或手动调用：
    pythonw viewer.py winupdrept:index              总览页（浏览器）
    pythonw viewer.py winupdrept:folder             报告文件夹
    pythonw viewer.py winupdrept:log                运行日志
    pythonw viewer.py winupdrept:r/<频道>/<构建号>    某一份具体报告（原生窗口）
    pythonw viewer.py "路径\\xxx.md"                 指定报告（原生窗口）
    pythonw viewer.py                              最新一份报告（原生窗口）

以前报告无论从通知点还是手动打开，最后都是 webbrowser.open 丢给浏览器；
现在改成开一个独立原生窗口：窗口边框、标题栏、最小化/最大化/关闭和八向缩放
全部用 HTML/CSS/JS 自绘，和设置窗口是同一套做法；正文沿用设置界面阅读器的
内嵌排版。WebView2 起不来时仍然退回浏览器，保证报告一定看得到。
"""
import glob
import html as html_mod
import os
import re
import sys
import threading
import traceback
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, REPORT_DIR, LOG_DIR, resource_path   # noqa: E402
from mdlite import render_page                                      # noqa: E402
import reporter                                                     # noqa: E402

WINDOW_W, WINDOW_H = 900, 720
WINDOW_MIN_W, WINDOW_MIN_H = 720, 480


def _log_error(where):
    """查看器没有控制台（pythonw / exe），失败原因写日志里方便排查。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "viewer.log"), "a", encoding="utf-8") as f:
            f.write(f"=== {where} ===\n{traceback.format_exc()}\n")
    except Exception:
        pass


def _embed_css(html):
    """沿用设置界面阅读器的内嵌样式（字号、行宽、配色）。"""
    try:
        from gui import _inject_report_css
        return _inject_report_css(html)
    except Exception:
        _log_error("注入报告样式")
        return html


def _report_title(html_path, cfg=None):
    """更新线 · 构建号；找不到就从文件名里抽构建号。"""
    stem = os.path.splitext(os.path.basename(html_path))[0]
    m = re.search(r"_([0-9]+(?:-[0-9]+)+)_", stem)
    build = m.group(1).replace("-", ".") if m else ""
    folder = os.path.basename(os.path.dirname(html_path))
    name = ""
    for c in (cfg or {}).get("channels") or []:
        try:
            if reporter.chan_slug(c.get("id") or "") == folder:
                name = c.get("name") or ""
                break
        except Exception:
            pass
    if name and build:
        return f"{name} · {build}"
    if build:
        return f"更新报告 · {build}"
    return stem


# 自绘窗口边框 + 标题栏 + 八向缩放 + 报告 iframe 的整页外壳。
# 样式刻意复制设置窗口的 titlebar / wbtn / resizers，作为同一个产品的外观。
_SHELL = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@</title>
<style>
:root{
  --bg:#F6F5F2; --surface:#FFFFFF; --line:#E7E3DC;
  --ink:#1C1B19; --ink-2:#5F5B54; --ink-3:#6F6A61;
  --accent:#1F5AE0; --font:"Segoe UI Variable Text","Segoe UI","Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif;
}
*,*::before,*::after{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);
  font-size:13.5px;overflow:hidden;user-select:none;cursor:default;
}
.app{display:flex;flex-direction:column;height:100%}
.titlebar{
  position:relative;flex:0 0 40px;height:40px;
  display:flex;align-items:stretch;justify-content:space-between;
  background:var(--bg);border-bottom:1px solid var(--line);user-select:none;
}
.titlebar-drag{
  flex:1;min-width:0;display:flex;align-items:center;gap:9px;
  padding:0 10px 0 15px;cursor:default;
}
.tb-mark{
  width:16px;height:16px;flex:none;display:block;
  fill:none;stroke:currentColor;stroke-width:1.35;
  stroke-linecap:round;stroke-linejoin:round;color:var(--ink);
}
.tb-name{font-size:12px;color:var(--ink-2);white-space:nowrap;flex:none}
.tb-div{width:1px;height:12px;background:var(--line);flex:none;margin:0 2px}
.tb-title{
  font-size:12.5px;font-weight:600;color:var(--ink);
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.wctl{display:flex;height:100%;flex:none}
.wbtn{
  width:46px;height:100%;padding:0;border:0;border-radius:0;
  background:transparent;color:var(--ink-2);
  display:flex;align-items:center;justify-content:center;cursor:default;
}
.wbtn:hover{background:#ECE9E3;color:var(--ink)}
.wbtn:active{background:#E2DED7}
.wbtn-close:hover{background:#C42B1C;color:#fff}
.wbtn-close:active{background:#AC2417;color:#fff}
.wbtn:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.wbtn .ico{
  width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:1.2;
  stroke-linecap:round;stroke-linejoin:round;
}
.content{position:relative;flex:1;min-height:0;background:var(--bg);padding:14px 16px 16px}
.doc-card{
  height:100%;background:#fff;border:1px solid var(--line);border-radius:12px;
  box-shadow:0 1px 2px rgba(28,27,25,.04);overflow:hidden;
}
.doc{display:block;width:100%;height:100%;border:0;background:#fff}
.resizers{position:fixed;inset:0;z-index:40;pointer-events:none}
.rz{position:fixed;pointer-events:auto;background:transparent}
.rz-n{top:0;left:10px;right:10px;height:5px;cursor:ns-resize}
.rz-s{bottom:0;left:10px;right:10px;height:5px;cursor:ns-resize}
.rz-w{left:0;top:10px;bottom:10px;width:5px;cursor:ew-resize}
.rz-e{right:0;top:10px;bottom:10px;width:5px;cursor:ew-resize}
.rz-nw{top:0;left:0;width:10px;height:10px;cursor:nwse-resize}
.rz-ne{top:0;right:0;width:10px;height:10px;cursor:nesw-resize}
.rz-sw{bottom:0;left:0;width:10px;height:10px;cursor:nesw-resize}
.rz-se{bottom:0;right:0;width:10px;height:10px;cursor:nwse-resize}
body.is-maximized .resizers{display:none}
.titlebar.is-blurred .tb-name,
.titlebar.is-blurred .tb-title,
.titlebar.is-blurred .wbtn{color:var(--ink-3)}
.titlebar.is-blurred .wbtn:hover{color:var(--ink)}
</style>
</head>
<body>
<svg style="position:absolute;width:0;height:0;overflow:hidden" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">
  <symbol id="i-win-min" viewBox="0 0 24 24"><path d="M5 12h14"/></symbol>
  <symbol id="i-win-max" viewBox="0 0 24 24"><rect x="5.5" y="5.5" width="13" height="13" rx="1"/></symbol>
  <symbol id="i-win-restore" viewBox="0 0 24 24"><rect x="4.5" y="9" width="10.5" height="10.5" rx="1"/><path d="M8.6 9V6.4a1.4 1.4 0 0 1 1.4-1.4h7.6a1.4 1.4 0 0 1 1.4 1.4V14a1.4 1.4 0 0 1-1.4 1.4h-2.1"/></symbol>
  <symbol id="i-close" viewBox="0 0 24 24"><path d="M6.2 6.2l11.6 11.6M17.8 6.2L6.2 17.8"/></symbol>
</svg>

<div class="app">
  <header class="titlebar" id="titlebar">
    <div class="titlebar-drag pywebview-drag-region" id="titlebarDrag">
      <svg class="tb-mark" viewBox="0 0 16 16" aria-hidden="true">
        <rect x="1.7" y="2.5" width="12.6" height="8.3" rx="1.5"/>
        <path d="M5.4 13.4h5.2M8 10.8v2.6"/>
      </svg>
      <span class="tb-name">win升级报告</span>
      <span class="tb-div" aria-hidden="true"></span>
      <span class="tb-title">@@TITLE@@</span>
    </div>
    <div class="wctl" role="group" aria-label="窗口控制">
      <button type="button" class="wbtn" id="winMin" title="最小化" aria-label="最小化">
        <svg class="ico" aria-hidden="true"><use href="#i-win-min"></use></svg>
      </button>
      <button type="button" class="wbtn" id="winMax" title="最大化" aria-label="最大化">
        <svg class="ico" aria-hidden="true"><use href="#i-win-max"></use></svg>
      </button>
      <button type="button" class="wbtn wbtn-close" id="winClose" title="关闭" aria-label="关闭">
        <svg class="ico" aria-hidden="true"><use href="#i-close"></use></svg>
      </button>
    </div>
  </header>
  <div class="content">
    <div class="doc-card">
      <iframe class="doc" title="报告内容" sandbox="allow-same-origin allow-popups"
        srcdoc="@@DOC@@"></iframe>
    </div>
  </div>
</div>

<div class="resizers" aria-hidden="true">
  <div class="rz rz-n" data-edge="n"></div>
  <div class="rz rz-s" data-edge="s"></div>
  <div class="rz rz-w" data-edge="w"></div>
  <div class="rz rz-e" data-edge="e"></div>
  <div class="rz rz-nw" data-edge="nw"></div>
  <div class="rz rz-ne" data-edge="ne"></div>
  <div class="rz rz-sw" data-edge="sw"></div>
  <div class="rz rz-se" data-edge="se"></div>
</div>

<script>
(function(){
  function api(){ return (window.pywebview && window.pywebview.api) || null; }
  function call(name, arg){
    var a = api();
    if (!a || typeof a[name] !== 'function') return null;
    try {
      /* 无参方法必须真的不传参：pywebview 把 undefined 当成一个参数，
         Python 侧 window_toggle_max() 会因此 TypeError，按钮就"失灵"了。 */
      return arg === undefined ? a[name]() : a[name](arg);
    } catch (e) { return null; }
  }
  function setMax(max){
    document.body.classList.toggle('is-maximized', !!max);
    var use = document.querySelector('#winMax use');
    if (use) use.setAttribute('href', max ? '#i-win-restore' : '#i-win-max');
    var btn = document.getElementById('winMax');
    if (btn) {
      btn.title = max ? '还原' : '最大化';
      btn.setAttribute('aria-label', btn.title);
    }
  }
  function toggleMax(){
    var r = call('window_toggle_max');
    if (r && r.then) r.then(function(x){ if (x && typeof x.maximized === 'boolean') setMax(x.maximized); });
  }
  document.getElementById('winMin').addEventListener('click', function(){ call('window_minimize'); });
  document.getElementById('winMax').addEventListener('click', toggleMax);
  document.getElementById('winClose').addEventListener('click', function(){ call('window_close'); });
  document.getElementById('titlebarDrag').addEventListener('dblclick', function(e){
    e.preventDefault(); toggleMax();
  });
  Array.prototype.forEach.call(document.querySelectorAll('.wbtn'), function(btn){
    btn.addEventListener('mousedown', function(e){ e.stopPropagation(); });
  });
  Array.prototype.forEach.call(document.querySelectorAll('.rz'), function(rz){
    rz.addEventListener('mousedown', function(e){
      e.preventDefault(); e.stopPropagation();
      if (document.body.classList.contains('is-maximized')) return;
      call('begin_resize', rz.dataset.edge);
    });
  });
  var bar = document.getElementById('titlebar');
  function syncFocus(){ if (bar) bar.classList.toggle('is-blurred', !document.hasFocus()); }
  window.addEventListener('focus', syncFocus);
  window.addEventListener('blur', syncFocus);
  syncFocus();
})();
</script>
</body>
</html>
"""


def _shell_html(title, doc):
    return (_SHELL.replace("@@TITLE@@", html_mod.escape(title))
                  .replace("@@DOC@@", html_mod.escape(doc, quote=True)))


def _open_native(html_path, title):
    """开一个无边框自绘窗口显示报告；关掉窗口后 webview.start 返回。"""
    import gui
    import webview

    with open(html_path, "r", encoding="utf-8", errors="replace") as f:
        doc = _embed_css(f.read())

    class ViewerApi(gui.GuiApi):
        """只复用窗口控制那套方法，不加载设置界面要用的配置/任务状态。"""

        def __init__(self):
            self._lock = threading.RLock()
            self._window = None
            self._hwnd_cache = 0
            self._maximized = False
            self._normal_rect = None
            self._max_lock = threading.Lock()
            self._resize_alive = False

    gui.RESIZE_MIN_W = WINDOW_MIN_W
    gui.RESIZE_MIN_H = WINDOW_MIN_H
    api = ViewerApi()
    window = webview.create_window(
        title,
        html=_shell_html(title, doc),
        js_api=api,
        width=WINDOW_W,
        height=WINDOW_H,
        min_size=(WINDOW_MIN_W, WINDOW_MIN_H),
        resizable=True,
        maximized=False,                # 打开就是普通窗口，不铺满屏幕
        frameless=True,                 # 原生标题栏/边框不要，全部由页面自绘
        easy_drag=False,                # 只让标题栏拖
        shadow=True,
        background_color="#F6F5F2",
        text_select=True,
    )
    api._window = window

    def on_shown():
        try:
            api._apply_corner(gui.DWMWCP_ROUND)
        except Exception:
            pass
        try:
            api._fix_initial_size(WINDOW_W, WINDOW_H)
        except Exception:
            pass

    try:
        window.events.shown += on_shown
    except Exception:
        pass

    icon = resource_path("icon.ico")
    webview.start(gui="edgechromium", private_mode=True,
                  icon=icon if os.path.exists(icon) else None)


def open_report(html_path, cfg=None):
    """优先原生自绘窗口；起不来就退回浏览器。"""
    try:
        _open_native(html_path, _report_title(html_path, cfg))
        return True
    except Exception:
        _log_error("原生报告窗口")
        try:
            webbrowser.open("file:///" + os.path.abspath(html_path).replace("\\", "/"))
        except Exception:
            _log_error("浏览器打开报告")
        return False


def render_report(md_path):
    """Markdown 报告 -> 排版好的 HTML（写到 md 旁边），返回 HTML 路径。"""
    with open(md_path, "r", encoding="utf-8") as f:
        md = f.read()
    title = os.path.splitext(os.path.basename(md_path))[0]
    html_path = os.path.splitext(md_path)[0] + ".html"
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(render_page(md, title))
    except Exception:
        _log_error("渲染 Markdown 报告")
        return md_path
    return html_path


def newest_report(report_dir):
    files = glob.glob(os.path.join(report_dir, "**", "*.md"), recursive=True)
    files = [f for f in files if "_view" not in os.path.basename(f)]
    return max(files, key=os.path.getmtime) if files else None


def find_by_arg(cfg, arg):
    """r/<频道目录>/<构建号> -> 报告文件路径"""
    parts = arg.split("/")
    if len(parts) < 3:
        return None
    base = cfg.get("report_dir") or REPORT_DIR
    chan, build = parts[1], parts[2].replace(".", "-")
    pats = [os.path.join(base, chan, f"*{build}*.html"),
            os.path.join(base, chan, f"*{build}*.md")]
    for p in pats:
        hits = sorted(glob.glob(p), key=os.path.getmtime, reverse=True)
        if hits:
            return hits[0]
    return None


def _open_target(target, cfg):
    if not target.lower().endswith((".md", ".markdown", ".txt")):
        return open_report(target, cfg)
    html_path = render_report(target)
    if html_path.lower().endswith((".md", ".markdown", ".txt")):
        return False
    return open_report(html_path, cfg)


def main():
    arg = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    cfg = load_config()
    report_dir = cfg.get("report_dir") or REPORT_DIR
    low = arg.lower()

    if low.startswith("winupdrept:"):
        arg = arg.split(":", 1)[1]
        low = arg.lower()

    if low.startswith("http"):
        webbrowser.open(arg)
        return 0
    if low in ("folder", "--folder"):
        os.startfile(report_dir)                    # noqa: S606
        return 0
    if low in ("log", "--log"):
        log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "checker.log")
        os.startfile(log if os.path.exists(log) else os.path.dirname(log))  # noqa: S606
        return 0
    if low in ("index", "--index"):
        idx = os.path.join(report_dir, reporter.INDEX_NAME)
        if not os.path.exists(idx):
            from config import load_state
            st = load_state()
            names = {c["id"]: c.get("name", c["id"]) for c in cfg.get("channels", [])}
            reporter.write_index(cfg, st, names)
        webbrowser.open("file:///" + idx.replace("\\", "/"))
        return 0

    if low.startswith("r/"):
        target = find_by_arg(cfg, arg)
        if target:
            return 0 if _open_target(target, cfg) else 1

    if arg and os.path.isfile(arg):
        return 0 if _open_target(arg, cfg) else 1

    target = newest_report(report_dir)
    if not target:
        os.startfile(report_dir)                    # noqa: S606
        return 1
    return 0 if _open_target(target, cfg) else 1


if __name__ == "__main__":
    sys.exit(main())
