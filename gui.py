# -*- coding: utf-8 -*-
"""设置界面后端：pywebview 原生窗口（WebView2）+ JS API。

界面文件在 webui/（index.html / app.css / app.js）。前端通过
window.pywebview.api.<方法> 调用本文件里的 GuiApi，接口约定见 CONTRACT.md。

本文件后半部分是 GuiApi（唯一给前端用的接口）和 main()（起原生窗口）。
前半部分全是模块级 helper：打包 / 计划任务 / 开机自启 / 子进程相关的老代码，
被 selfcheck.py、app.py 直接 import，名字和签名不能动。
"""
import base64
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import functools
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (load_config, save_config, load_state, save_state, channel_state,   # noqa: E402
                    resolve_api_key, mask_key, BASE_DIR, REPORT_DIR, LOG_DIR,
                    DEFAULTS, resource_path, is_frozen, app_exe, child_env,
                    load_watch, request_check_now, request_exit, patch_config)
import channels as ch_mod                                                   # noqa: E402
import notify                                                               # noqa: E402
import reporter                                                             # noqa: E402
import mdlite                                                               # noqa: E402
import deepseek_api                                                         # noqa: E402
import tray as tray_mod                                                     # noqa: E402
import selfcheck                                                            # noqa: E402
import hotwin                                                               # noqa: E402

WATCH_TASK_NAME = "WinUpdReport_Watch"
DAILY_TASK_NAME = "WinUpdReport_Daily"     # 旧版每日任务；装哨兵时顺手卸掉
TASK_NAME = WATCH_TASK_NAME                # 界面上显示和操作的主任务
PS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                  "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
TASK_PS1 = resource_path("task.ps1")
CHECKER = os.path.join(BASE_DIR, "checker.py")
WATCH = os.path.join(BASE_DIR, "watch.py")
LOG_PATH = os.path.join(LOG_DIR, "checker.log")
NO_WINDOW = 0x08000000
NEW_CONSOLE = 0x00000010
APP_TITLE = "win升级报告"
FROZEN = is_frozen()

# 窗口默认尺寸（逻辑像素）。frameless 切换会让 WinForms 把窗口缩掉一圈，
# 所以窗口显示出来后再按这两个数校正一次（见 _fix_initial_size）。
WINDOW_W, WINDOW_H = 1120, 780

# 「报告详细程度」的可选值（前端下拉用）
DETAIL_OPTIONS = list(deepseek_api.DETAIL_SPEC.keys())


def pythonw():
    exe = sys.executable
    cand = exe[:-len("python.exe")] + "pythonw.exe" if exe.lower().endswith("python.exe") else exe
    return cand if os.path.exists(cand) else exe


def check_cmd(args, console=False):
    """检测模式的命令行：打包后是自己这个 exe 加 --check，源码时是 python checker.py。"""
    if FROZEN:
        return [sys.executable, "--check"] + list(args)
    return [sys.executable if console else pythonw(), CHECKER] + list(args)


def view_cmd(arg):
    """查看器模式的命令行。"""
    if FROZEN:
        return [sys.executable, "--view", arg]
    return [pythonw(), os.path.join(BASE_DIR, "viewer.py"), arg]


def watch_cmd(args=None):
    """哨兵模式的命令行：打包后是自己这个 exe 加 --watch，源码时是 pythonw watch.py。"""
    if FROZEN:
        return [sys.executable, "--watch"] + list(args or [])
    return [pythonw(), WATCH] + list(args or [])


def run_background(args):
    """后台静默跑一次检测，不看输出。

    注意 env：必须先把 _MEIPASS2 摘掉（见 config.child_env 的说明），
    否则这个子进程会住进界面自己的临时目录，界面一退出就删不掉那个目录。
    """
    return subprocess.Popen(check_cmd(args), cwd=BASE_DIR,
                            creationflags=NO_WINDOW, env=child_env())


def spawn_view(arg):
    """打开查看器 / 总览页，不等待。"""
    return subprocess.Popen(view_cmd(arg), cwd=BASE_DIR,
                            creationflags=NO_WINDOW, env=child_env())


def ps_run(args, timeout=90):
    try:
        return subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                               "Bypass", "-WindowStyle", "Hidden"] + args,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", creationflags=NO_WINDOW, timeout=timeout)
    except Exception as e:
        class R:
            returncode, stdout, stderr = 1, "", str(e)
        return R()


# ------------------------------------------------------- 计划任务（需提权）
def task_target():
    """每日任务要运行什么（旧版，现在基本不用了）。"""
    if FROZEN:
        return sys.executable, "--check"
    return pythonw(), f'"{CHECKER}"'


def watch_target():
    """哨兵要运行什么：打包后是 exe --watch，源码时是 pythonw watch.py。"""
    if FROZEN:
        return sys.executable, "--watch"
    return pythonw(), f'"{WATCH}"'


def local_task_ps1():
    """把打包进去的 task.ps1 复制一份到 logs\\ 下再用。

    提权后的进程要能读到这个脚本，用 _MEIPASS 里的临时路径不保险（主进程一退出就没了）。
    """
    dst = os.path.join(LOG_DIR, "task_run.ps1")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(TASK_PS1, "rb") as f:
            data = f.read()
        with open(dst, "wb") as f:
            f.write(data if data.startswith(b"\xef\xbb\xbf") else b"\xef\xbb\xbf" + data)
        return dst
    except Exception:
        notify.ensure_bom(TASK_PS1)
        return TASK_PS1


def ps_task(action, mode="watch", time="12:00", days=1, at_logon=False,
            also_remove=""):
    ps1 = local_task_ps1()
    if mode == "daily":
        exe, args, name = *task_target(), DAILY_TASK_NAME
    else:
        exe, args, name = *watch_target(), WATCH_TASK_NAME
    extra = ["-AtLogon:$true"] if at_logon else []
    if also_remove:
        extra += ["-AlsoRemove", also_remove]
    return ps_run(["-File", ps1, "-Action", action, "-Mode", mode,
                   "-TaskName", name, "-Time", time, "-DaysInterval", str(days),
                   "-Exe", exe, "-Arguments", args, "-WorkDir", BASE_DIR] + extra)


def is_elevated():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ps_task_elevated(action, mode="watch", time="12:00", days=1, timeout=300,
                     at_logon=False, also_remove=""):
    import tempfile
    ps1 = local_task_ps1()
    if mode == "daily":
        exe, targs, name = *task_target(), DAILY_TASK_NAME
    else:
        exe, targs, name = *watch_target(), WATCH_TASK_NAME
    extra = " -AtLogon:$true" if at_logon else ""
    if also_remove:
        extra += f" -AlsoRemove '{also_remove}'"
    out_log = os.path.join(tempfile.gettempdir(), "winupd_task_out.txt")
    inner = os.path.join(tempfile.gettempdir(), "winupd_task_inner.ps1")
    body = [
        "$ErrorActionPreference = 'Continue'",
        f"$log = '{out_log}'",
        "Remove-Item -LiteralPath $log -ErrorAction SilentlyContinue",
        "try {",
        f"  & '{ps1}' -Action '{action}' -Mode '{mode}' -TaskName '{name}' "
        f"-Time '{time}' -DaysInterval {int(days)} "
        f"-Exe '{exe}' -Arguments '{targs}' -WorkDir '{BASE_DIR}'{extra} *>&1 | "
        "ForEach-Object { $_.ToString() } | Add-Content -LiteralPath $log -Encoding UTF8",
        "  'RC=0' | Add-Content -LiteralPath $log -Encoding UTF8",
        "} catch {",
        "  ($_ | Out-String) | Add-Content -LiteralPath $log -Encoding UTF8",
        "  'RC=1' | Add-Content -LiteralPath $log -Encoding UTF8",
        "}",
    ]
    with open(inner, "w", encoding="utf-8-sig") as f:
        f.write("\r\n".join(body) + "\r\n")
    if is_elevated():
        ps_run(["-File", inner], timeout=timeout)
    else:
        ps_run(["-Command",
                f"Start-Process -FilePath '{PS}' -Verb RunAs -Wait -WindowStyle Hidden "
                f"-ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','{inner}')"],
               timeout=timeout)
    try:
        with open(out_log, "r", encoding="utf-8-sig", errors="replace") as f:
            txt = f.read().strip()
    except Exception:
        txt = ""
    return "RC=0" in txt, "\n".join(ln for ln in txt.splitlines() if ln.strip() != "RC=0")


def task_info():
    """返回一段人能看懂的计划任务状态（哨兵任务 + 可能还留着的旧每日任务）。"""
    r = ps_task("query")
    raw = (r.stdout or "").strip()
    if not raw:
        return "未安装计划任务"
    lines = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if ":" not in ln:
            continue
        name, rest = ln.split(":", 1)
        name, rest = name.strip(), rest.strip()
        is_watch = (name == WATCH_TASK_NAME)
        if rest == "NONE":
            if is_watch:
                lines.append("哨兵任务：未安装　→ 点下面「安装 / 更新计划任务」")
            continue
        m = re.search(r"STATE=(\S+);\s*NEXT=([^;]*);\s*LAST=([^;]*);"
                      r"\s*TRIGGERS=([^;]*)(?:;\s*LIMIT=(.*))?", rest)
        if not m:
            lines.append(f"{name}：{rest}")
            continue
        state, nxt, last, trig, limit = (x.strip() if x else ""
                                         for x in m.groups())
        label = "哨兵任务" if is_watch else f"旧任务（{name}）"
        warn = ""
        if is_watch and limit and limit not in ("PT0S", "P0D"):
            # 限时若不是「不限时」，常驻程序会被系统定时杀掉，表现为「过一会儿就没动静」
            warn = f"　⚠ 限时={limit}（应当是不限时，请重新安装一次）"
        lines.append(f"{label}：{state}　下次 {nxt or '-'}　上次 {last or '-'}　"
                     f"触发器 {trig or '-'}{warn}")
    return "\n".join(lines) or "未安装计划任务"


def startup_link():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                        "Start Menu", "Programs", "Startup", "win升级报告.lnk")


def install_startup():
    ps1 = os.path.join(LOG_DIR, "_mklnk.ps1")
    link = startup_link()
    # 免管理员的备用方案：登录时启动哨兵（和计划任务干的是同一件事）
    exe, targs = watch_target()
    body = ("$ws = New-Object -ComObject WScript.Shell\n"
            f"$s = $ws.CreateShortcut('{link}')\n"
            f"$s.TargetPath = '{exe}'\n"
            f"$s.Arguments = '{targs}'\n"
            f"$s.WorkingDirectory = '{BASE_DIR}'\n"
            "$s.WindowStyle = 7\n"
            "$s.Description = 'win升级报告：登录时启动哨兵（常驻检测）'\n"
            "$s.Save()\n")
    with open(ps1, "w", encoding="utf-8-sig") as f:
        f.write(body)
    return ps_run(["-File", ps1], timeout=60)


def toggle_startup():
    link = startup_link()
    if os.path.exists(link):
        try:
            os.remove(link)
            return True, "已取消登录自启"
        except Exception as e:
            return False, f"删除失败：{e}"
    install_startup()
    return (os.path.exists(link), "已设置登录自启"
            if os.path.exists(link) else "设置失败")


# =========================================================== 小工具 / 错误日志

def _now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def _as_int(value, default=0):
    try:
        if value is None or value == "":
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "on", "是")


def _error_log_path():
    return os.path.join(LOG_DIR, "gui_error.log")


def write_error_line(text):
    """把一行错误写进 logs\\gui_error.log（写不进去也不能影响界面）。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(_error_log_path(), "a", encoding="utf-8") as f:
            f.write(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
    except Exception:
        pass


def log_exception(context):
    """记录当前异常堆栈。所有 JS API 的异常都走这里，绝不穿透给前端。"""
    try:
        write_error_line(context + "\n" + traceback.format_exc())
    except Exception:
        pass


def _guard(fn):
    """给每个 JS API 方法兜底：任何异常都记日志并返回人话错误。"""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception:
            log_exception(f"{fn.__name__}() 出错")
            return {"ok": False,
                    "error": "界面后台出了点状况，已经记到日志里；可以点「体检并自动修复」试试。"}

    return wrapper


def _normalize_quiet_hours(spec):
    """"23:00-07:00" -> 规范化后的字符串；不合规返回 None。"""
    try:
        a, b = str(spec).split("-", 1)
        a, b = a.strip(), b.strip()
        for t in (a, b):
            hh, mm = t.split(":")
            dt.time(int(hh), int(mm))
        return f"{a}-{b}"
    except Exception:
        return None


def _normalize_check_time(spec):
    """旧的「每天检测时间」：不合法就退回 12:00，绝不因此挡住保存。"""
    try:
        hh, mm = str(spec or "").strip().split(":")
        dt.time(int(hh), int(mm))
        return f"{int(hh):02d}:{int(mm):02d}"
    except Exception:
        return "12:00"


_REPORT_NAME_RE = re.compile(r"更新报告_([0-9]+(?:-[0-9]+)*)_(\d{4}-\d{2}-\d{2})")
_REPORT_EMBED_CSS = """<style id="winupd-embed">
/* 这份样式是设置界面在 iframe 里内嵌报告时注入的：去掉页面自己的背景、留白和阴影，
   让报告看起来是界面的一部分而不是另一个网站。 */
html,body{background:#fff !important;padding:0 !important;margin:0 !important;color-scheme:light}
body{color:#1C1B19 !important}
main{box-shadow:none !important;border-radius:0 !important;max-width:560px !important;
 margin:0 auto !important;padding:24px 28px !important;background:#fff !important}
a{color:#1F5AE0 !important}
/* 应用内嵌字号：报告页自带的 PAGE 样式是「网页阅读」尺寸（h1 27px 等），
   塞进窄面板后标题会被折成好几行、正文也偏大。这里整体降一档；
   阅读器里再用 560px 的行宽上限，避免一行拉到 60 多个汉字。 */
body{font-family:"Segoe UI Variable Text","Segoe UI","Microsoft YaHei UI","Microsoft YaHei",sans-serif !important;
 font-size:13.5px !important;line-height:1.7 !important}
main{padding:24px 28px !important}
h1{font-size:21px !important;line-height:1.35 !important;margin:0 0 8px !important}
h2{font-size:16.5px !important;margin:22px 0 8px !important;padding-bottom:5px !important}
h3{font-size:14.5px !important;margin:16px 0 6px !important}
h4{font-size:13.5px !important}
p,li{font-size:13.5px !important;margin:6px 0 !important}
ul,ol{padding-left:20px !important}
table{font-size:12.5px !important}
code,pre{font-size:12px !important}
blockquote{font-size:13px !important}
/* 滚动条也走应用自己的样式，不再出现 Windows 默认的宽灰条 */
html{scrollbar-gutter:stable}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#D8D3CA;border:3px solid #fff;
 background-clip:padding-box;border-radius:8px}
::-webkit-scrollbar-thumb:hover{background:#C7C1B6;background-clip:padding-box}
/* 右侧预览面板只有 300～500px：把缩进收小，正文能多放几个字。 */
@media (max-width:620px){
 main{max-width:none !important;padding:20px 22px !important}
 h1{font-size:19px !important}
 h2{font-size:16px !important}
 p,li{font-size:13px !important;line-height:1.65 !important}
}
@media (prefers-color-scheme:dark){
 html,body{background:#fff !important;color:#1C1B19 !important}
 body{color:#1C1B19 !important}
 main{background:#fff !important;color:#1C1B19 !important;box-shadow:none !important}
 h1,h2,h3,h4,p,li,td,th,blockquote{color:#1C1B19 !important}
 h2{border-color:#E7E3DC !important}
 code,pre{background:#F6F5F2 !important;color:#1C1B19 !important;border-color:#E7E3DC !important}
 th{background:#FBFAF7 !important}
 th,td,hr{border-color:#E7E3DC !important}
 blockquote{background:#F4F8FF !important}
 a{color:#1F5AE0 !important}
}
</style>"""


def _inject_report_css(html):
    """把「贴合应用内嵌」的 CSS 注入到报告 HTML 里（放在 </style> 之前，不破坏原样式）。"""
    try:
        low = html.lower()
        if "</style>" in low:
            i = low.rfind("</style>")
            return html[:i] + _REPORT_EMBED_CSS + html[i:]
        if "</head>" in low:
            i = low.rfind("</head>")
            return html[:i] + _REPORT_EMBED_CSS + html[i:]
        return _REPORT_EMBED_CSS + html
    except Exception:
        return html


def _html_title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    if not m:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()[:120]


def _row_sort_key(c):
    """更新线排序：Flight Hub 在前按 FH_ORDER，uupdump 在后按 UUP_ORDER，再按名称。"""
    name = c.get("name") or c.get("id") or ""
    if c.get("source") == "flighthub":
        folder = c.get("folder") or ""
        order = ch_mod.FH_ORDER.index(folder) if folder in ch_mod.FH_ORDER else 99
        return (0, order, name)
    cat = c.get("category") or ""
    order = ch_mod.UUP_ORDER.index(cat) if cat in ch_mod.UUP_ORDER else 99
    return (1, order, name)


# =========================================================== 自绘标题栏用的 Win32
# 窗口是 frameless 的：原生标题栏、边框、缩放边都不存在，最小化/最大化/缩放
# 由前端按钮 + 这里的 Win32 调用接管。句柄一律声明成指针，免得 64 位下被截断。
VK_LBUTTON = 0x01
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SW_RESTORE = 9
MONITOR_DEFAULTTONEAREST = 2
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
RESIZE_MIN_W = 960          # 逻辑像素；实际 clamp 时按窗口所在显示器 DPI 换算
RESIZE_MIN_H = 640
RESIZE_POLL_SECONDS = 0.012
RESIZE_MAX_SECONDS = 60


class _WinRect(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", _WinRect),
                ("rcWork", _WinRect), ("dwFlags", wt.DWORD)]


_WIN32_READY = False
_u32 = None
_dwm = None


def _win32():
    """拿到 (user32, dwmapi) 并声明函数签名。只初始化一次。

    ★ 必须用独立的 WinDLL 实例，不能改 ctypes.windll.user32 上的函数签名：
      pywebview 自己也调 windll.user32.SetWindowPos，它给 cx/cy 传的是 None
      （配合 SWP_NOSIZE）。我们一旦在共享实例上把参数声明成 c_int，它的
      `.pywebview-drag-region` 拖动就会抛 "argument 5: TypeError: wrong type"。
    """
    global _WIN32_READY, _u32, _dwm
    if _u32 is None:
        _u32 = ctypes.WinDLL("user32")
        _dwm = ctypes.WinDLL("dwmapi")
    u, d = _u32, _dwm
    if not _WIN32_READY:
        try:
            u.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
            u.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WinRect)]
            u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_uint]
            u.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            u.MonitorFromWindow.restype = ctypes.c_void_p
            u.GetMonitorInfoW.argtypes = [ctypes.c_void_p,
                                          ctypes.POINTER(_MonitorInfo)]
            u.GetAsyncKeyState.argtypes = [ctypes.c_int]
            u.GetDpiForWindow.argtypes = [ctypes.c_void_p]
            u.IsWindow.argtypes = [ctypes.c_void_p]
            u.IsIconic.argtypes = [ctypes.c_void_p]
            u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
            u.BringWindowToTop.argtypes = [ctypes.c_void_p]
            u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
            u.FindWindowW.restype = ctypes.c_void_p
            u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,
                                                   ctypes.POINTER(wt.DWORD)]
            d.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                                ctypes.c_void_p, ctypes.c_uint]
            d.DwmSetWindowAttribute.restype = ctypes.c_long
            _WIN32_READY = True
        except Exception:
            pass
    return u, d


# ================================================================== JS 后端

class GuiApi:
    """pywebview 的 js_api 后端。

    所有方法都在 pywebview 的工作线程里被调用（每一次调用一个线程），所以：
      * 共享数据一律走 self._lock（RLock）；
      * 后台线程只往 self._events 里追加事件，绝不直接碰 WebView 对象；
      * 前端每 1000ms 调一次 poll()，一次把事件全部取走。
    """

    _INT_KEYS = ("max_tokens", "request_timeout", "retries", "max_workers",
                 "max_context_chars", "interval_days", "keep_reports",
                 "notify_on_error_after", "watch_interval_minutes",
                 "game_exit_hold_seconds", "tick_seconds")
    _FLOAT_KEYS = ("temperature",)
    _BOOL_KEYS = ("notify", "merge_notifications", "include_official_text",
                  "disable_thinking", "auto_discover_channels", "watch_enabled",
                  "game_mode_enabled", "run_once_per_day", "check_at_logon",
                  "tray_hint_shown", "open_report_on_click")
    _STR_KEYS = ("api_base", "api_key", "model", "proxy", "detail", "app_id",
                 "report_dir", "silent_until", "check_time", "uup_url",
                 "tray_style", "quiet_hours")
    _KNOWN_KEYS = frozenset(DEFAULTS.keys())
    _LABELS = {
        "watch_interval_minutes": "多久检查一次（分钟）",
        "game_exit_hold_seconds": "退出全屏后确认几秒",
        "notify_on_error_after": "连续失败几次后提醒我",
        "keep_reports": "每份报告最多保留几份",
        "max_tokens": "单次回答最多多少词",
        "request_timeout": "网络超时（秒）",
        "retries": "失败重试几次",
        "max_context_chars": "喂给 AI 的原文上限",
        "max_workers": "同时抓几条线",
        "interval_days": "间隔天数",
        "tick_seconds": "哨兵醒来间隔",
        "temperature": "随机程度",
    }

    def __init__(self):
        self._lock = threading.RLock()
        self._cfg = load_config()
        self._state = load_state(force=True)
        self._rows = []            # 更新线列表（含预设）
        self._events = []          # 待前端取走的事件
        self._task_text = "正在查询计划任务…"
        self._task_querying = False
        self._busy_text = ""       # 非空 = 有一个长操作在跑
        self._live_active = False
        self._live_lines = []
        self._live_rc = None
        # ★ 窗口对象必须是私有属性：pywebview 会递归 dir() 所有公开属性来生成
        #   JS API 表，公开的窗口属性会把 .NET / WinForms / COM 对象全遍历一遍，
        #   在 stderr 刷一堆 "Error while processing window.native..."。
        self._window = None
        self._hwnd_cache = 0
        self._maximized = False          # 自绘最大化的状态（poll 里同步给前端）
        self._normal_rect = None         # 还原时用的原矩形 (x, y, w, h)
        self._max_lock = threading.Lock()
        self._resize_alive = False
        self._reload_rows()
        self._query_task_info_async()
        # 只用来响应“重复启动时把已有窗口提到前台”，不常驻任何 WebView
        self._show_event = None

    # ============================================================ 初始数据

    @_guard
    def bootstrap(self):
        """首屏要用的全部数据。慢的（计划任务）已经在后台查了，不等它。"""
        with self._lock:
            self._cfg = load_config()
            self._state = load_state(force=True)
            self._reload_rows()
            cfg = self._cfg
            state = self._state
            channels = self._channels_payload()
            watch = self._watch_payload()
            task_text = self._task_text
            task_querying = self._task_querying
        if not task_querying:
            self._query_task_info_async()
        return {
            "ok": True,
            "app": self._app_info(),
            "config": cfg,
            "state": state,
            "watch": watch,
            "channels": channels,
            "reports": self._collect_reports(),
            "tray_styles": self._tray_styles(cfg),
            "detail_options": list(DETAIL_OPTIONS),
            "task_text": task_text,
            "startup": {"enabled": os.path.exists(startup_link())},
            "now": _now_iso(),
        }

    @_guard
    def poll(self):
        """前端每秒调一次：轻量状态 + 本秒内的事件。"""
        with self._lock:
            watch = self._watch_payload()
            task_text = self._task_text
            live = {
                "active": bool(self._live_active),
                "lines": list(self._live_lines[-400:]),
                "rc": self._live_rc,
            }
            events = self._events[:]
            self._events.clear()
            window = {"maximized": bool(self._maximized)}
        return {
            "ok": True,
            "now": _now_iso(),
            "watch": watch,
            "startup": {"enabled": os.path.exists(startup_link())},
            "window": window,
            "task_text": task_text,
            "live": live,
            "events": events,
        }

    # ============================================================ 更新线

    @_guard
    def channels(self):
        with self._lock:
            self._state = load_state(force=True)
            try:
                disk_cfg = load_config()
            except Exception:
                disk_cfg = self._cfg
            self._merge_rows_from_cfg(disk_cfg)
            self._cfg = disk_cfg
            payload = self._channels_payload()
        return {"ok": True, "channels": payload}

    @_guard
    def set_channel_enabled(self, id=None, enabled=False):
        cid = str(id or "").strip()
        val = _as_bool(enabled)
        with self._lock:
            c = self._find_row(cid)
            if not c:
                return {"ok": False, "error": "没找到这条更新线",
                        "channels": self._channels_payload()}
            c["enabled"] = val
            c.pop("_preset", None)
            self._persist_channels()
            name = c.get("name") or cid
            payload = self._channels_payload()
        return {"ok": True, "channels": payload,
                "message": f"{name}：{'已启用' if val else '已停用'}"}

    @_guard
    def set_channels_enabled(self, enabled=False):
        val = _as_bool(enabled)
        with self._lock:
            for c in self._rows:
                c["enabled"] = val
                c.pop("_preset", None)
            self._persist_channels()
            payload = self._channels_payload()
        return {"ok": True, "channels": payload,
                "message": "已全部启用" if val else "已全部停用"}

    @_guard
    def set_channel_arch(self, id=None, arch="amd64"):
        cid = str(id or "").strip()
        want = str(arch or "").strip().lower()
        if want not in ("amd64", "arm64"):
            return {"ok": False, "error": "架构只能选 amd64（普通电脑）或 arm64（ARM 电脑）",
                    "channels": self._channels_payload()}
        with self._lock:
            c = self._find_row(cid)
            if not c:
                return {"ok": False, "error": "没找到这条更新线",
                        "channels": self._channels_payload()}
            c["arch"] = want
            c.pop("_preset", None)
            self._persist_channels()
            name = c.get("name") or cid
            payload = self._channels_payload()
        return {"ok": True, "channels": payload,
                "message": f"{name} 的架构已改为 {want}"}

    @_guard
    def add_channel(self, text=None):
        raw = str(text or "").strip()
        with self._lock:
            if not raw:
                return {"ok": False,
                        "error": "先填一个分类名或 uupdump 网址，例如 w11-26h2",
                        "channels": self._channels_payload()}
            if raw.lower().startswith("http") or "category:" in raw.lower():
                m = re.search(r"category:([a-z0-9\-]+)", raw, re.I)
                if not m:
                    return {"ok": False,
                            "error": "网址里要带 category:xxx，或者直接填分类名，例如 w11-26h2",
                            "channels": self._channels_payload()}
                new = ch_mod.uup_channel(m.group(1).lower())
                new["url"] = raw
            else:
                new = ch_mod.uup_channel(raw.lower())
            new = ch_mod.norm_channel(new)
            new["enabled"] = True
            exist = self._find_row(new["id"])
            if exist:
                exist["enabled"] = True
                exist.pop("_preset", None)
                self._persist_channels()
                payload = self._channels_payload()
                return {"ok": True, "channels": payload,
                        "message": f"{exist['name']} 本来就在列表里，已经帮你启用"}
            new.pop("_preset", None)
            self._rows.append(new)
            self._rows.sort(key=_row_sort_key)
            self._persist_channels()
            payload = self._channels_payload()
        return {"ok": True, "channels": payload,
                "message": f"已添加并启用 {new['name']}"}

    @_guard
    def discover(self):
        if not self._begin_long("正在从微软看板抓更新线…"):
            return {"ok": False, "error": self._busy_error()}

        def work():
            import source
            source.configure(dict(self._cfg))
            data = source.flighthub()
            with self._lock:
                known = {c["id"] for c in self._rows}
                added = 0
                for folder in (data or {}):
                    cid = "fh:" + folder
                    if cid in known:
                        continue
                    c = ch_mod.norm_channel(ch_mod.fh_channel(folder))
                    c["enabled"] = False
                    c["_preset"] = True
                    self._rows.append(c)
                    added += 1
                self._rows.sort(key=_row_sort_key)
                payload = self._channels_payload()
            return {"total_online": len(data or {}), "added": added,
                    "channels": payload}

        def done(res, err):
            if err or not res:
                self._push_event({"type": "done", "kind": "discover", "ok": False,
                                  "text": f"抓取失败：{err or '没有解析到更新线'}"})
                return
            n, added = res["total_online"], res["added"]
            text = (f"微软看板现有 {n} 条 Insider 线"
                    + (f"，新发现 {added} 条" if added else "，没有新的"))
            self._push_event({"type": "discover", "ok": True, "added": added,
                              "total": n, "text": text,
                              "channels": res["channels"]})
            self._push_event({"type": "done", "kind": "discover", "ok": True,
                              "text": text})

        self._run_in_thread("抓取可选更新线", work, done)
        return {"ok": True, "started": True}

    @_guard
    def ignore_version(self, id=None):
        cid = str(id or "").strip()
        with self._lock:
            c = self._find_row(cid)
            cs = ((self._state.get("channels") or {}).get(cid) or {})
            ver = cs.get("last_version")
            if not c:
                return {"ok": False, "error": "没找到这条更新线",
                        "channels": self._channels_payload()}
            if not ver:
                return {"ok": False, "error": "这条线还没有记录版本，没法忽略",
                        "channels": self._channels_payload()}
            cs = channel_state(self._state, cid)
            cs["ignored"] = sorted(set([str(x) for x in (cs.get("ignored") or [])]
                                       + [str(ver)]))
            try:
                save_state(self._state)
            except Exception as e:
                log_exception("保存忽略版本")
                return {"ok": False, "error": f"记不进去：{e}",
                        "channels": self._channels_payload()}
            payload = self._channels_payload()
        return {"ok": True, "channels": payload,
                "message": f"已忽略 {ver}：以后不再为这个版本生成报告"}

    @_guard
    def clear_ignored(self, id=None):
        cid = str(id or "").strip()
        with self._lock:
            c = self._find_row(cid)
            if not c:
                return {"ok": False, "error": "没找到这条更新线",
                        "channels": self._channels_payload()}
            cs = channel_state(self._state, cid)
            cs["ignored"] = []
            try:
                save_state(self._state)
            except Exception as e:
                log_exception("清除忽略列表")
                return {"ok": False, "error": f"记不进去：{e}",
                        "channels": self._channels_payload()}
            payload = self._channels_payload()
        return {"ok": True, "channels": payload, "message": "已清除忽略列表"}

    # ============================================================ 配置

    @_guard
    def save_config(self, partial=None):
        """前端自动保存：只传改动过的键，后端做与旧版 _apply() 相同的清洗。"""
        if not isinstance(partial, dict):
            return {"ok": False, "error": "没有收到要保存的内容"}
        with self._lock:
            cfg = load_config()
            err = self._merge_partial(cfg, partial)
            if err:
                return {"ok": False, "error": err}
            self._merge_rows_from_cfg(cfg)
            cfg = self._cfg_with_rows(cfg)
            cfg["check_time"] = _normalize_check_time(cfg.get("check_time"))
            cfg["game_ignore"] = [str(x).strip()
                                  for x in (cfg.get("game_ignore") or [])
                                  if str(x).strip()]
            try:
                save_config(cfg)
            except Exception as e:
                log_exception("保存设置")
                return {"ok": False, "error": f"保存失败：{e}"}
            self._cfg = cfg
            self._state = load_state(force=True)
            try:
                online = bool(load_watch().get("online"))
            except Exception:
                online = False
            # 「后台监控」被关掉时，顺手让正在跑的那个哨兵也退干净
            if not cfg.get("watch_enabled", True) and online:
                request_exit()
        return {"ok": True, "config": cfg, "message": "已保存"}

    def _merge_partial(self, cfg, partial):
        """把前端传来的改动叠到 cfg 上；返回空串表示成功，否则返回人话错误。"""
        for key, val in partial.items():
            if key in ("channels", "schema") or key not in self._KNOWN_KEYS:
                continue                      # 不认识的键直接忽略
            label = self._LABELS.get(key, key)
            if key in self._INT_KEYS:
                try:
                    if isinstance(val, bool):
                        cfg[key] = int(val)
                    elif isinstance(val, (int, float)):
                        cfg[key] = int(val)
                    else:
                        s = str(val).strip()
                        cfg[key] = int(s) if s else 0
                except Exception:
                    return f"「{label}」需要填整数，现在是「{val}」"
            elif key in self._FLOAT_KEYS:
                try:
                    cfg[key] = float(str(val).strip())
                except Exception:
                    return f"「{label}」需要填数字，现在是「{val}」"
            elif key in self._BOOL_KEYS:
                cfg[key] = _as_bool(val)
            elif key in self._STR_KEYS:
                if key == "quiet_hours":
                    qh = str(val or "").strip()
                    if qh:
                        norm = _normalize_quiet_hours(qh)
                        if norm is None:
                            return "静默时段格式应为 HH:MM-HH:MM，例如 23:00-07:00"
                        cfg["quiet_hours"] = norm
                    else:
                        cfg["quiet_hours"] = ""
                elif key == "detail":
                    d = str(val or "").strip()
                    if d not in DETAIL_OPTIONS:
                        return "报告详细程度只能是：" + "、".join(DETAIL_OPTIONS)
                    cfg["detail"] = d
                elif key == "check_time":
                    cfg["check_time"] = _normalize_check_time(val)
                else:
                    cfg[key] = str(val if val is not None else "").strip()
            elif key == "game_ignore":
                if isinstance(val, str):
                    val = [val]
                cfg["game_ignore"] = [str(x).strip() for x in (val or [])
                                      if str(x).strip()]

        # 数值范围（与旧版 _apply() 一致）
        cfg["watch_interval_minutes"] = max(
            1, min(1440, _as_int(cfg.get("watch_interval_minutes"), 5)))
        cfg["game_exit_hold_seconds"] = max(
            0, min(3600, _as_int(cfg.get("game_exit_hold_seconds"), 0)))
        cfg["max_workers"] = max(1, min(16, _as_int(cfg.get("max_workers"), 4)))
        cfg["tick_seconds"] = max(2, min(60, _as_int(cfg.get("tick_seconds"), 5)))
        cfg["interval_days"] = max(1, _as_int(cfg.get("interval_days"), 1))
        for k in ("keep_reports", "max_tokens", "request_timeout", "retries",
                  "max_context_chars", "notify_on_error_after"):
            if k == "notify_on_error_after":
                cfg[k] = max(0, _as_int(cfg.get(k), 3))
            else:
                cfg[k] = max(0, _as_int(cfg.get(k), 0))
        try:
            cfg["temperature"] = float(cfg.get("temperature"))
        except Exception:
            return "「随机程度」需要填数字"
        if cfg.get("detail") not in DETAIL_OPTIONS:
            cfg["detail"] = "标准"
        return ""

    @_guard
    def quiet_now(self):
        with self._lock:
            cfg = load_config()
        cur = (cfg.get("silent_until") or "").strip()
        active = False
        if cur:
            try:
                active = dt.datetime.fromisoformat(cur) > dt.datetime.now()
            except Exception:
                active = False
        if active:
            cfg["silent_until"] = ""
            msg = "已取消手动静默，后台监控马上恢复检测。"
        else:
            until = dt.datetime.now() + dt.timedelta(hours=2)
            cfg["silent_until"] = until.isoformat(timespec="seconds")
            msg = (f"已静默到 {until:%H:%M}（后台监控最多 5 秒后生效），"
                   "到点自动恢复正常。")
        cfg["game_ignore"] = [str(x).strip() for x in (cfg.get("game_ignore") or [])
                              if str(x).strip()]
        try:
            save_config(cfg)
        except Exception as e:
            log_exception("保存手动静默")
            return {"ok": False, "error": f"保存失败：{e}"}
        with self._lock:
            self._cfg = cfg
        return {"ok": True, "config": cfg, "message": msg}

    @_guard
    def ignore_foreground(self):
        try:
            import gamesense
            exe = gamesense.current_foreground()
        except Exception as e:
            log_exception("读取当前前台程序")
            return {"ok": False, "error": f"取不到当前前台程序：{e}"}
        if not exe:
            return {"ok": False, "error": "取不到当前前台程序（先点一下你想忽略的那个窗口再来）"}
        name = os.path.basename(exe)
        with self._lock:
            cfg = load_config()
        lst = list(cfg.get("game_ignore") or [])
        if name.lower() in [str(x).lower() for x in lst]:
            return {"ok": True, "config": cfg,
                    "message": f"{name} 已经在忽略名单里了"}
        lst.append(name)
        cfg["game_ignore"] = lst
        try:
            save_config(cfg)
        except Exception as e:
            log_exception("保存忽略名单")
            return {"ok": False, "error": f"保存失败：{e}"}
        with self._lock:
            self._cfg = cfg
        return {"ok": True, "config": cfg,
                "message": f"已把 {name} 加进忽略名单，以后不会因为它进静默模式。"}

    @_guard
    def set_tray_style(self, id=None):
        sid = str(id or "").strip()
        try:
            default_id, styles = tray_mod.load_styles()
        except Exception:
            styles, default_id = [], "default"
        known = {s.get("id") for s in styles} or {default_id}
        if sid not in known:
            return {"ok": False, "error": "没有这个托盘图标样式"}
        label = next((s.get("name") or sid for s in styles if s.get("id") == sid), sid)
        with self._lock:
            cfg = load_config()
            cfg["tray_style"] = sid
            try:
                save_config(cfg)
            except Exception as e:
                log_exception("保存托盘样式")
                return {"ok": False, "error": f"保存失败：{e}"}
            self._cfg = cfg
        try:
            online = bool(load_watch().get("online"))
        except Exception:
            online = False
        msg = (f"任务栏图标已换成「{label}」，后台监控几秒内会换过来（看右下角托盘）。"
               if online else
               f"任务栏图标已设为「{label}」。后台监控没在跑，等它起来就是这个样式了。")
        return {"ok": True, "message": msg}

    # ============================================================ 检测 / 通知

    @_guard
    def check_channel(self, id=None):
        cid = str(id or "").strip()
        with self._lock:
            c = self._find_row(cid)
            if not c:
                return {"ok": False, "error": "没找到这条更新线"}
            name = c.get("name") or cid
            try:
                online = bool(load_watch().get("online"))
            except Exception:
                online = False
        note = f"正在检测 {name}"
        if online:
            note += "（后台监控也在跑，两边可能同时写状态）"
        if not self._run_check_live(["--only", cid], note=note):
            return {"ok": False, "error": self._busy_error()}
        return {"ok": True, "started": True}

    @_guard
    def check_now(self):
        try:
            w = load_watch()
        except Exception:
            w = {"online": False}
        if w.get("online"):
            request_check_now()
            if w.get("mode") == "game":
                msg = "后台正在全屏静默中，请求已记下；游戏一关就立刻检测。"
            else:
                msg = "已通知后台立刻检测（最多 5 秒后开始），结果和通知都由它来出。"
            return {"ok": True, "started": True, "message": msg}
        if not self._run_check_live(["--force"], note="正在检测"):
            return {"ok": False, "started": False, "error": self._busy_error()}
        return {"ok": True, "started": True,
                "message": "后台监控没在运行，已经在后台单独跑了一次检测，"
                           "过程显示在「日志与诊断」里。"}

    @_guard
    def toggle_watch(self):
        with self._lock:
            cfg = load_config()
        try:
            online = bool(load_watch().get("online"))
        except Exception:
            online = False
        if online:
            try:
                selfcheck.stop_sentinel()
            except Exception:
                log_exception("停止后台监控")
            self._refresh_cfg()
            return {"ok": True, "online": False,
                    "message": "已停止后台监控，托盘图标几秒内消失。"}
        if not resolve_api_key(cfg):
            return {"ok": False, "online": False,
                    "error": "先去「设置」页填一个 AI 的 Key —— 不填的话就算发现新版本也写不出中文报告。"}
        try:
            ok, msg = selfcheck.start_sentinel()
        except Exception as e:
            log_exception("启动后台监控")
            return {"ok": False, "online": False, "error": f"启动失败：{e}"}
        if not ok:
            return {"ok": False, "online": False, "error": msg}
        self._refresh_cfg()
        return {"ok": True, "online": True,
                "message": "已经启动，几秒后右下角会出现托盘图标。"
                           "（要是没看到，点任务栏那个 ∧ 展开一下）"}

    @_guard
    def test_toast(self):
        def work():
            notify.register_app(self._cfg.get("app_id") or "WinUpdReport.App")
            return notify.show("win升级报告 · 测试通知",
                               "看到这条说明通知通道正常，点一下试试能不能打开总览页。",
                               arg1="index")

        def done(res, err):
            ok = bool(res and res[0])
            if ok:
                text = "测试通知已发送（点它试试能不能打开总览页）"
            else:
                detail = err or (res[1] if res and len(res) > 1 else "未知原因")
                text = f"发送失败：{detail}"
            self._push_event({"type": "done", "kind": "toast", "ok": ok, "text": text})

        if not self._begin_long("正在发一条测试通知…"):
            return {"ok": False, "error": self._busy_error()}
        self._run_in_thread("发测试通知", work, done)
        return {"ok": True, "started": True}

    @_guard
    def test_api(self):
        with self._lock:
            cfg = dict(self._cfg)
        key = resolve_api_key(cfg)
        if not key:
            return {"ok": False, "error": "还没填 AI 的 Key：先在「设置」页粘贴一个再试"}

        def work():
            return deepseek_api.summarize(cfg, key, "只回复两个字：正常", timeout=60)

        def done(out, err):
            if err:
                self._push_event({"type": "done", "kind": "api_test", "ok": False,
                                  "text": f"AI 测试没通过：{err}"})
                return
            model = cfg.get("model") or "AI"
            reply = (out or "").strip()[:30]
            self._push_event({"type": "done", "kind": "api_test", "ok": True,
                              "text": f"AI 可用：模型 {model} 回复「{reply}」"})

        if not self._begin_long(f"正在测试 AI 的 Key（{mask_key(key)}）…"):
            return {"ok": False, "error": self._busy_error()}
        self._run_in_thread("测试 AI 的 Key", work, done)
        return {"ok": True, "started": True}

    # ============================================================ 自启 / 诊断

    @_guard
    def run_selfcheck(self):
        def work():
            return selfcheck.check_all(fix=True)

        def done(res, err):
            if err or not res:
                text = f"体检失败：{err or '没有结果'}"
                self._push_event({"type": "done", "kind": "selfcheck", "ok": False,
                                  "text": text})
                return
            head = selfcheck.summary(res)
            items = [{"name": str(r.get("name") or ""),
                      "status": str(r.get("status") or ""),
                      "msg": str(r.get("msg") or "")} for r in res]
            self._push_event({"type": "selfcheck", "ok": True, "summary": head,
                              "items": items})
            self._push_event({"type": "done", "kind": "selfcheck", "ok": True,
                              "text": "体检完成：" + head})
            self._refresh_cfg()

        if not self._begin_long("正在体检并自动修复…"):
            return {"ok": False, "error": self._busy_error()}
        self._run_in_thread("体检并自动修复", work, done)
        return {"ok": True, "started": True}

    @_guard
    def install_task(self):
        with self._lock:
            cfg = dict(self._cfg)

        def work():
            notify.register_app(cfg.get("app_id") or "WinUpdReport.App")
            res = ps_task_elevated("install", mode="watch",
                                   also_remove=DAILY_TASK_NAME)
            return res, self._query_task_info_text()

        def done(res, err):
            task_text = ""
            if err or not res:
                ok, text = False, f"安装出错：{err or '没有结果'}"
            else:
                (installed, msg), task_text = res
                ok = bool(installed)
                msg = msg or ""
                if ok:
                    text = ("计划任务已装好：登录时自动启动，每隔几分钟看一次官方看板，"
                            "不限时、崩了会自动重启（旧的每日任务已卸掉）。")
                elif "取消" in msg or "canceled" in msg.lower() or "cancelled" in msg.lower():
                    text = "UAC 被取消。可以改用「一键设置开机自启」这个免管理员方案。"
                else:
                    text = "安装失败：" + (msg[:260] or "未知原因")
            if task_text:
                with self._lock:
                    self._task_text = task_text
                self._push_event({"type": "task_info", "text": task_text})
            self._push_event({"type": "done", "kind": "task_install", "ok": ok,
                              "text": text})

        if not self._begin_long("正在申请管理员权限（会弹 UAC，点「是」继续）…"):
            return {"ok": False, "error": self._busy_error()}
        self._run_in_thread("安装计划任务", work, done)
        return {"ok": True, "started": True}

    @_guard
    def remove_task(self):
        def work():
            res = ps_task_elevated("remove", mode="watch",
                                   also_remove=DAILY_TASK_NAME)
            return res, self._query_task_info_text()

        def done(res, err):
            task_text = ""
            if err or not res:
                ok, text = False, f"删除出错：{err or '没有结果'}"
            else:
                (removed, msg), task_text = res
                ok = bool(removed)
                text = "计划任务已删除" if ok else "删除失败：" + (msg or "未知原因")[:200]
            if task_text:
                with self._lock:
                    self._task_text = task_text
                self._push_event({"type": "task_info", "text": task_text})
            self._push_event({"type": "done", "kind": "task_remove", "ok": ok,
                              "text": text})

        if not self._begin_long("正在申请管理员权限删除计划任务…"):
            return {"ok": False, "error": self._busy_error()}
        self._run_in_thread("删除计划任务", work, done)
        return {"ok": True, "started": True}

    @_guard
    def toggle_startup(self):
        def work():
            # 模块级同名 helper（见文件前半部分）
            return toggle_startup()

        def done(res, err):
            if err or not res:
                ok, text = False, f"设置开机自启出错：{err or '没有结果'}"
            else:
                ok, msg = res
                text = msg or ("已设置登录自启" if ok else "设置失败")
            self._push_event({"type": "done", "kind": "startup", "ok": bool(ok),
                              "text": text})

        if not self._begin_long("正在设置登录自启…"):
            return {"ok": False, "error": self._busy_error()}
        self._run_in_thread("设置登录自启", work, done)
        return {"ok": True, "started": True}

    @_guard
    def register_app(self):
        app_id = self._cfg.get("app_id") or "WinUpdReport.App"
        try:
            ok = notify.register_app(app_id)
        except Exception as e:
            log_exception("注册通知 / 协议")
            return {"ok": False, "error": f"注册失败：{e}"}
        if ok:
            return {"ok": True,
                    "message": "已写入注册表：通知来源和 winupdrept: 协议都注册好了"}
        return {"ok": False, "error": "注册表写入失败，可能是权限问题"}

    @_guard
    def make_shortcut(self, where="desktop"):
        wh = str(where or "desktop").strip().lower()
        if wh not in ("desktop", "startmenu"):
            wh = "desktop"
        exe = sys.executable if FROZEN else pythonw()
        targ = "" if FROZEN else f'"{os.path.join(BASE_DIR, "app.py")}"'
        name = "win升级报告.lnk"
        if wh == "desktop":
            folder = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
        else:
            folder = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                                  "Start Menu", "Programs")
        link = os.path.join(folder, name)
        ps1 = os.path.join(LOG_DIR, "_mkshortcut.ps1")
        body = ("$ws = New-Object -ComObject WScript.Shell\n"
                f"$s = $ws.CreateShortcut('{link}')\n"
                f"$s.TargetPath = '{exe}'\n"
                + (f"$s.Arguments = '{targ}'\n" if targ else "")
                + f"$s.WorkingDirectory = '{BASE_DIR}'\n"
                f"$s.IconLocation = '{resource_path('icon.ico')}'\n"
                "$s.Description = 'win升级报告：监控 Windows 更新线'\n"
                "$s.Save()\n")
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(ps1, "w", encoding="utf-8-sig") as f:
                f.write(body)
            ps_run(["-File", ps1], timeout=60)
        except Exception as e:
            log_exception("创建快捷方式")
            return {"ok": False, "error": f"创建快捷方式失败：{e}"}
        if os.path.exists(link):
            return {"ok": True, "message": f"快捷方式已创建：{link}"}
        return {"ok": False, "error": "快捷方式没创建出来，过一会儿再试一次"}

    @_guard
    def refresh_task_info(self):
        self._query_task_info_async()
        return {"ok": True, "started": True}

    # ============================================================ 日志

    @_guard
    def read_log(self):
        try:
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()[-60_000:]
        except Exception:
            txt = "(还没有日志)"
        return {"ok": True, "text": txt, "path": LOG_PATH}

    @_guard
    def clear_log(self):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(LOG_PATH, "w", encoding="utf-8"):
                pass
        except Exception as e:
            return {"ok": False, "error": f"清空失败：{e}"}
        return {"ok": True, "message": "日志已清空"}

    # ============================================================ 报告

    @_guard
    def reports(self):
        with self._lock:
            self._state = load_state(force=True)
            items = self._collect_reports()
        return {"ok": True, "reports": items}

    @_guard
    def report_html(self, file=None):
        path = self._resolve_report_path(file)
        if not path:
            return {"ok": False, "error": "找不到这份报告，可能已经被删掉了"}
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in (".md", ".markdown", ".txt"):
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    md = f.read()
                title = os.path.splitext(os.path.basename(path))[0]
                # render_page 内部会用 str.format，标题里的大括号要转义
                safe_title = title.replace("{", "{{").replace("}", "}}")
                html = mdlite.render_page(md, safe_title)
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    html = f.read()
                title = _html_title(html) or os.path.splitext(
                    os.path.basename(path))[0]
        except Exception as e:
            log_exception("读取报告")
            return {"ok": False, "error": f"读不出这份报告：{e}"}
        return {"ok": True, "html": _inject_report_css(html), "title": title}

    # ============================================================ 外部打开 / 窗口

    @_guard
    def open_external(self, kind="", path=""):
        k = str(kind or "").strip().lower()
        p = str(path or "").strip()
        cfg = self._cfg
        report_dir = cfg.get("report_dir") or REPORT_DIR
        try:
            if k in ("browser", "url", "link"):
                return self._open_in_browser(p)
            if k == "overview":
                spawn_view("index")
                return {"ok": True, "message": "已在浏览器里打开总览页"}
            if k == "log":
                target = LOG_PATH if os.path.exists(LOG_PATH) else LOG_DIR
                os.startfile(target)                                   # noqa: S606
                return {"ok": True, "message": "已打开日志文件"}
            if k == "report_folder":
                self._ensure_dir(report_dir)
                os.startfile(report_dir)                               # noqa: S606
                return {"ok": True, "message": "已打开报告文件夹"}
            if k == "app_folder":
                d = (os.path.dirname(os.path.abspath(sys.executable))
                     if FROZEN else BASE_DIR)
                os.startfile(d)                                        # noqa: S606
                return {"ok": True, "message": "已打开程序文件夹"}
            if k == "folder":
                return self._open_folder(p or report_dir, report_dir)
            return {"ok": False, "error": f"不认识这个打开方式：{kind}"}
        except Exception as e:
            log_exception("打开外部程序")
            return {"ok": False, "error": f"打不开：{type(e).__name__}: {e}"}

    @_guard
    def window_minimize(self):
        win = self._window
        if win is None:
            return {"ok": False, "error": "窗口还没准备好，稍等一下"}
        try:
            win.minimize()
        except Exception as e:
            log_exception("最小化窗口")
            return {"ok": False, "error": f"最小化失败了：{e}"}
        return {"ok": True}

    @_guard
    def window_toggle_max(self):
        """自绘最大化：不用 pywebview 的 maximize()（无边框 WinForms 最大化会盖住任务栏）。"""
        u, _dwm = _win32()
        hwnd = self._hwnd()
        if not hwnd:
            return {"ok": False, "error": "窗口还没准备好，稍等一下",
                    "maximized": bool(self._maximized)}
        with self._max_lock:
            try:
                if u.IsIconic(ctypes.c_void_p(hwnd)):
                    u.ShowWindow(ctypes.c_void_p(hwnd), SW_RESTORE)   # 从任务栏还原
                if self._maximized:
                    rect = self._normal_rect
                    if rect:
                        u.SetWindowPos(ctypes.c_void_p(hwnd), None,
                                       int(rect[0]), int(rect[1]),
                                       int(rect[2]), int(rect[3]),
                                       SWP_NOZORDER | SWP_NOACTIVATE)
                    self._apply_corner(DWMWCP_ROUND)
                    self._maximized = False
                else:
                    rc = _WinRect()
                    u.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rc))
                    normal = (rc.left, rc.top, rc.right - rc.left,
                              rc.bottom - rc.top)
                    mon = u.MonitorFromWindow(ctypes.c_void_p(hwnd),
                                              MONITOR_DEFAULTTONEAREST)
                    mi = _MonitorInfo()
                    mi.cbSize = ctypes.sizeof(_MonitorInfo)
                    if not u.GetMonitorInfoW(ctypes.c_void_p(mon),
                                             ctypes.byref(mi)):
                        return {"ok": False, "maximized": False,
                                "error": "算不出屏幕可用区域，先别最大化"}
                    work = mi.rcWork
                    u.SetWindowPos(ctypes.c_void_p(hwnd), None,
                                   int(work.left), int(work.top),
                                   int(work.right - work.left),
                                   int(work.bottom - work.top),
                                   SWP_NOZORDER | SWP_NOACTIVATE)
                    self._apply_corner(DWMWCP_DONOTROUND)
                    self._normal_rect = normal
                    self._maximized = True
                return {"ok": True, "maximized": bool(self._maximized)}
            except Exception as e:
                log_exception("切换最大化")
                return {"ok": False, "maximized": bool(self._maximized),
                        "error": f"切换最大化失败了：{e}"}

    @_guard
    def begin_resize(self, edge="e"):
        """开始八向缩放：立即返回，后台线程跟着鼠标完成（前端 8 个透明抓手）。"""
        want = str(edge or "").strip().lower()
        if want not in ("n", "s", "e", "w", "ne", "nw", "se", "sw"):
            return {"ok": False, "error": "不认识的缩放方向"}
        ok, err = self._start_resize(want)
        if not ok:
            return {"ok": False, "error": err}
        return {"ok": True}

    @_guard
    def window_close(self):
        """只关窗口：后台哨兵是独立进程，照旧跑。窗口进程一起退出，不常驻。"""
        self._schedule_destroy()
        return {"ok": True}

    @_guard
    def close_window(self):
        """旧名字，保留转给 window_close()。"""
        return self.window_close()

    @_guard
    def quit_all(self):
        try:
            selfcheck.stop_sentinel()
        except Exception:
            log_exception("完全退出时停止后台监控")
        self._schedule_destroy()
        return {"ok": True}

    # ======================================================== 内部实现（不暴露给 JS）

    def _hwnd(self):
        """懒获取窗口句柄：优先 window.native.Handle，失败就用标题兜底。"""
        with self._lock:
            cached = self._hwnd_cache
        if cached:
            try:
                u, _d = _win32()
                if u.IsWindow(ctypes.c_void_p(cached)):
                    return cached
            except Exception:
                pass
        hwnd = 0
        win = self._window
        if win is not None:
            try:
                native = getattr(win, "native", None)
                if native is not None:
                    hwnd = int(native.Handle.ToInt32())
            except Exception:
                hwnd = 0
        if not hwnd:
            try:
                u, _d = _win32()
                h = int(u.FindWindowW(None, APP_TITLE))
                # 只认自己进程的窗口：别的地方也可能有个同名窗口（比如预览工具）
                if h:
                    pid = wt.DWORD(0)
                    u.GetWindowThreadProcessId(ctypes.c_void_p(h),
                                               ctypes.byref(pid))
                    if pid.value == os.getpid():
                        hwnd = h
            except Exception:
                hwnd = 0
        with self._lock:
            self._hwnd_cache = hwnd
        return hwnd

    def _apply_corner(self, preference):
        """Win11 圆角（Win10 会失败，失败忽略即可）。"""
        hwnd = self._hwnd()
        if not hwnd:
            return False
        try:
            _u, dwm = _win32()
            pref = ctypes.c_int(int(preference))
            hr = dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd),
                                           DWMWA_WINDOW_CORNER_PREFERENCE,
                                           ctypes.byref(pref),
                                           ctypes.sizeof(pref))
            return hr == 0
        except Exception:
            return False

    def _start_resize(self, edge):
        """后台跟踪鼠标完成缩放。返回 (是否已开始, 错误文案)。"""
        u, _d = _win32()
        hwnd = self._hwnd()
        if not hwnd:
            return False, "窗口还没准备好，稍等一下"
        with self._lock:
            if self._maximized:
                return True, ""            # 最大化时不用拖边框
            if self._resize_alive:
                return True, ""            # 上一个缩放还没结束，忽略这次
            self._resize_alive = True

        def work():
            try:
                pt0 = wt.POINT()
                u.GetCursorPos(ctypes.byref(pt0))
                rc = _WinRect()
                u.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rc))
                left0, top0, right0, bottom0 = rc.left, rc.top, rc.right, rc.bottom
                started = time.time()
                while time.time() - started < RESIZE_MAX_SECONDS:
                    if not (u.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
                        break           # 松开左键 = 结束
                    pt = wt.POINT()
                    u.GetCursorPos(ctypes.byref(pt))
                    dx, dy = pt.x - pt0.x, pt.y - pt0.y
                    left, top, right, bottom = left0, top0, right0, bottom0
                    if "w" in edge:
                        left = left0 + dx
                    if "e" in edge:
                        right = right0 + dx
                    if "n" in edge:
                        top = top0 + dy
                    if "s" in edge:
                        bottom = bottom0 + dy
                    try:
                        scale = u.GetDpiForWindow(ctypes.c_void_p(hwnd)) / 96.0
                    except Exception:
                        scale = 1.0
                    scale = scale or 1.0
                    min_w = int(round(RESIZE_MIN_W * scale))
                    min_h = int(round(RESIZE_MIN_H * scale))
                    if right - left < min_w:
                        if "w" in edge:
                            left = right - min_w
                        else:
                            right = left + min_w
                    if bottom - top < min_h:
                        if "n" in edge:
                            top = bottom - min_h
                        else:
                            bottom = top + min_h
                    u.SetWindowPos(ctypes.c_void_p(hwnd), None,
                                   int(left), int(top),
                                   int(right - left), int(bottom - top),
                                   SWP_NOZORDER | SWP_NOACTIVATE)
                    time.sleep(RESIZE_POLL_SECONDS)
            except Exception:
                log_exception("拖动缩放窗口")
            finally:
                with self._lock:
                    self._resize_alive = False

        threading.Thread(target=work, daemon=True, name="gui-resize").start()
        return True, ""

    def _fix_initial_size(self, width, height):
        """frameless 切换会把窗口缩掉一圈（FormBorderStyle.None 让窗体改用原客户区大小），
        窗口显示后按设计尺寸校正一次，并在当前显示器工作区里居中。"""
        u, _d = _win32()
        hwnd = self._hwnd()
        if not hwnd:
            return False
        try:
            scale = u.GetDpiForWindow(ctypes.c_void_p(hwnd)) / 96.0
        except Exception:
            scale = 1.0
        scale = scale or 1.0
        phys_w = int(round(width * scale))
        phys_h = int(round(height * scale))
        x, y = 0, 0
        try:
            mon = u.MonitorFromWindow(ctypes.c_void_p(hwnd),
                                      MONITOR_DEFAULTTONEAREST)
            mi = _MonitorInfo()
            mi.cbSize = ctypes.sizeof(_MonitorInfo)
            if u.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi)):
                work = mi.rcWork
                x = work.left + max(0, (work.right - work.left - phys_w) // 2)
                y = work.top + max(0, (work.bottom - work.top - phys_h) // 2)
        except Exception:
            rc = _WinRect()
            u.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rc))
            x, y = rc.left, rc.top
        u.SetWindowPos(ctypes.c_void_p(hwnd), None, int(x), int(y),
                       phys_w, phys_h, SWP_NOZORDER | SWP_NOACTIVATE)
        return True

    # ------------------------------------------------- 重复启动时提到前台
    # 不再隐藏待命：窗口关掉进程就退出，空闲时只有后台哨兵一个进程。
    # 这里只留一个很轻的监听线程：用户双击 exe 时，第二个进程会发事件，
    # 已有窗口把它提到前台（不会开第二个 WebView）。

    def start_show_watcher(self):
        self._show_event = hotwin.create_event(hotwin.GUI_SHOW_EVENT)
        threading.Thread(target=self._show_loop, daemon=True,
                         name="gui-show").start()

    def _show_loop(self):
        while True:
            if hotwin.wait_event(self._show_event, 500):
                self._present_window()

    def _present_window(self):
        """把已有窗口提到前台（重复启动 / 再点托盘时用）。"""
        window = self._window
        if window is None:
            return
        try:
            hwnd = self._hwnd()
        except Exception:
            hwnd = 0
        try:
            u, _d = _win32()
            if hwnd and u.IsIconic(ctypes.c_void_p(hwnd)):
                u.ShowWindow(ctypes.c_void_p(hwnd), SW_RESTORE)
            window.show()
            if hwnd:
                u.BringWindowToTop(ctypes.c_void_p(hwnd))
                u.SetForegroundWindow(ctypes.c_void_p(hwnd))
        except Exception:
            log_exception("把窗口提到前台")

    def _close_show_handle(self):
        with self._lock:
            handle = self._show_event
            if handle:
                hotwin.close_handle(handle)
                self._show_event = None

    def _schedule_destroy(self):
        """先让 JS 拿到返回值，再关窗口；关窗 = 进程退出（后台哨兵是独立进程）。"""
        window = self._window
        if window is None:
            return

        def do_destroy():
            try:
                window.destroy()
            except Exception:
                log_exception("关闭窗口")

        timer = threading.Timer(0.15, do_destroy)
        timer.daemon = True
        timer.start()

    def _open_in_browser(self, path):
        p = str(path or "").strip()
        if not p:
            return {"ok": False, "error": "没有要打开的报告或网址"}
        low = p.lower()
        if low.startswith(("http://", "https://", "file://")):
            webbrowser.open(p)
            return {"ok": True, "message": "已在浏览器里打开"}
        target = p if os.path.isabs(p) else os.path.join(BASE_DIR, p)
        if not os.path.isfile(target) and os.path.isfile(p):
            target = p
        if not os.path.isfile(target):
            return {"ok": False, "error": f"找不到这个文件：{p}"}
        try:
            if target.lower().endswith((".md", ".markdown", ".txt")):
                with open(target, "r", encoding="utf-8", errors="replace") as f:
                    md = f.read()
                title = os.path.splitext(os.path.basename(target))[0]
                html_path = os.path.splitext(target)[0] + ".html"
                try:
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(mdlite.render_page(
                            md, title.replace("{", "{{").replace("}", "}}")))
                except Exception:
                    html_path = target
                webbrowser.open("file:///" + os.path.abspath(html_path).replace("\\", "/"))
            else:
                webbrowser.open("file:///" + os.path.abspath(target).replace("\\", "/"))
        except Exception as e:
            log_exception("在浏览器里打开")
            return {"ok": False, "error": f"打不开：{e}"}
        return {"ok": True, "message": "已在浏览器里打开"}

    def _open_folder(self, target, report_dir):
        target = str(target or "").strip()
        if not target:
            target = report_dir
        if not os.path.isdir(target):
            # 报告文件夹在第一次生成报告前可能还不存在，顺手建出来；
            # 其它的路径不存在就老实报错，别乱建目录。
            try:
                in_report_dir = (os.path.normcase(os.path.abspath(target)).startswith(
                    os.path.normcase(os.path.abspath(report_dir))))
            except Exception:
                in_report_dir = False
            if in_report_dir:
                self._ensure_dir(target)
        if not os.path.isdir(target):
            return {"ok": False, "error": f"这个文件夹还不存在：{target}"}
        os.startfile(target)                                           # noqa: S606
        return {"ok": True, "message": "已打开文件夹"}

    @staticmethod
    def _ensure_dir(path):
        try:
            os.makedirs(path, exist_ok=True)
            return True
        except Exception:
            return False

    def _resolve_report_path(self, file):
        raw = str(file or "").strip()
        if not raw:
            return ""
        base = self._cfg.get("report_dir") or REPORT_DIR
        candidates = [raw]
        if not os.path.isabs(raw):
            candidates.append(os.path.join(BASE_DIR, raw))
            candidates.append(os.path.join(base, raw))
        for p in candidates:
            try:
                if os.path.isfile(p):
                    return os.path.abspath(p)
            except Exception:
                continue
        return ""

    # ---------------------------------------------------------- 行 / 数据组装

    def _reload_rows(self):
        """界面列表 = 配置里的线 + 预设里还没加进来的线（灰显）。"""
        cfg = self._cfg
        cfg_ids = {c["id"] for c in cfg.get("channels", [])}
        rows = [ch_mod.norm_channel(c) for c in cfg.get("channels", [])]
        for c in ch_mod.all_presets():
            c = ch_mod.norm_channel(c)
            if c["id"] not in cfg_ids:
                c["enabled"] = False
                c["_preset"] = True
                rows.append(c)
        rows.sort(key=_row_sort_key)
        self._rows = rows

    def _merge_rows_from_cfg(self, cfg):
        """盘上多出来的线（比如后台监控自动收录的）补进内存列表。"""
        known = {c["id"] for c in self._rows}
        changed = False
        for raw in (cfg.get("channels") or []):
            try:
                c = ch_mod.norm_channel(raw)
            except Exception:
                continue
            if c["id"] in known:
                continue
            c.pop("_preset", None)
            self._rows.append(c)
            changed = True
        if changed:
            self._rows.sort(key=_row_sort_key)

    def _find_row(self, cid):
        cid = str(cid or "").strip()
        if not cid:
            return None
        return next((c for c in self._rows if c["id"] == cid), None)

    def _cfg_with_rows(self, base):
        """把内存里的线写回配置。只保留「启用的线 + 本来就在配置里的线」。"""
        cfg = dict(base)
        was = {c["id"] for c in (base.get("channels") or [])}
        keep = []
        for c in self._rows:
            if not (c["enabled"] or c["id"] in was):
                continue
            item = {"id": c["id"], "source": c["source"],
                    "name": c.get("name"), "enabled": bool(c["enabled"]),
                    "arch": c.get("arch") or "amd64"}
            if c["source"] == "flighthub":
                item["folder"] = c.get("folder")
            else:
                item["category"] = c.get("category")
                item["url"] = c.get("url")
            keep.append(item)
        cfg["channels"] = [ch_mod.norm_channel(x) for x in keep]
        cfg["schema"] = 3
        return cfg

    def _persist_channels(self):
        """线列表的启用/停用/架构/添加立刻写盘（前端是自动保存，没有「保存」按钮）。"""
        cfg = self._cfg_with_rows(dict(self._cfg))
        try:
            save_config(cfg)
        except Exception as e:
            log_exception("保存更新线")
            raise RuntimeError(f"存不进去：{e}")
        self._cfg = cfg
        return cfg

    def _channels_payload(self):
        return [self._channel_row(c) for c in self._rows]

    @staticmethod
    def _report_dict(r):
        """state.json 里的报告条目：把可能存成相对路径的 file / html 补成绝对路径。"""
        d = dict(r)
        for key in ("file", "html"):
            v = str(d.get(key) or "")
            if v and not os.path.isabs(v):
                d[key] = os.path.join(BASE_DIR, v)
        return d

    def _channel_row(self, c):
        cs = ((self._state.get("channels") or {}).get(c["id"]) or {})
        reports = [self._report_dict(r) for r in (cs.get("reports") or [])
                   if isinstance(r, dict)]
        row = {
            "id": c["id"],
            "name": c.get("name") or c["id"],
            "source": c.get("source") or "flighthub",
            "enabled": bool(c.get("enabled")),
            "arch": c.get("arch") or "amd64",
            "preset": bool(c.get("_preset")),
            "state": {
                "last_version": str(cs.get("last_version") or ""),
                "last_check_date": str(cs.get("last_check_date") or ""),
                "last_report": str(cs.get("last_report") or ""),
                "last_error": str(cs.get("last_error") or ""),
                "fail_count": _as_int(cs.get("fail_count"), 0),
                "ignored": [str(x) for x in (cs.get("ignored") or [])],
                "reports": reports,
            },
            "report_count": len(reports),
        }
        if c.get("source") == "flighthub":
            row["folder"] = c.get("folder") or ""
        else:
            row["category"] = c.get("category") or ""
            row["url"] = c.get("url") or ""
        return row

    def _watch_payload(self):
        try:
            w = load_watch()
        except Exception:
            log_exception("读取后台状态")
            w = {"online": False}
        cfg = self._cfg
        online = bool(w.get("online"))
        mode = (w.get("mode") or "normal") if online else "stopped"
        if mode not in ("normal", "game", "paused", "stopped"):
            mode = "normal" if online else "stopped"
        return {
            "online": online,
            "mode": mode,
            "last_check": str(w.get("last_check") or ""),
            "last_change": str(w.get("last_change") or ""),
            "interval_minutes": _as_int(w.get("interval_minutes")
                                        or cfg.get("watch_interval_minutes"), 5),
            "tray": bool(w.get("tray")),
            "checks": _as_int(w.get("checks"), 0),
            "errors": _as_int(w.get("errors"), 0),
            "last_result": str(w.get("last_result") or ""),
            "manual_until": str(w.get("manual_until") or ""),
            "game_exe": str(w.get("game_exe") or ""),
            "stale_seconds": _as_int(w.get("stale_seconds"), -1),
        }

    def _app_info(self):
        try:
            exe, args = watch_target()
        except Exception:
            exe, args = sys.executable, ""
        return {
            "title": APP_TITLE,
            "frozen": FROZEN,
            "is_frozen": FROZEN,
            "base_dir": BASE_DIR,
            "code_dir": (os.path.dirname(os.path.abspath(sys.executable))
                         if FROZEN else BASE_DIR),
            "exe": app_exe() or exe,
            "log_path": LOG_PATH,
            "report_dir": self._cfg.get("report_dir") or REPORT_DIR,
            "task_name": TASK_NAME,
            "startup_link": startup_link(),
            "watch_cmd": f"{exe} {args}".strip(),
            "webui_dir": resource_path("webui"),
            "icon": resource_path("icon.ico"),
        }

    @staticmethod
    def _tray_styles(cfg):
        out = []
        try:
            default_id, styles = tray_mod.load_styles()
        except Exception:
            log_exception("读取托盘图标样式")
            return out
        cur = (cfg.get("tray_style") or "").strip() or default_id
        ids = {s.get("id") for s in styles}
        if cur not in ids:
            cur = default_id
        for s in styles:
            sid = s.get("id") or ""
            if not sid:
                continue
            preview = ""
            try:
                p = tray_mod.preview_path(sid)
                if p and os.path.exists(p):
                    with open(p, "rb") as f:
                        preview = ("data:image/png;base64,"
                                   + base64.b64encode(f.read()).decode("ascii"))
            except Exception:
                preview = ""
            out.append({"id": sid, "name": s.get("name") or sid,
                        "preview": preview, "active": sid == cur})
        return out

    # ---------------------------------------------------------- 报告列表

    @staticmethod
    def _file_key(path):
        try:
            return os.path.normcase(os.path.abspath(str(path or "")))
        except Exception:
            return str(path or "")

    @staticmethod
    def _mtime_iso(path):
        try:
            return dt.datetime.fromtimestamp(
                os.path.getmtime(path)).isoformat(timespec="seconds")
        except Exception:
            return ""

    @staticmethod
    def _date_to_iso(date):
        s = str(date or "").strip()
        if not s:
            return ""
        try:
            dt.date.fromisoformat(s[:10])
            return s[:10] + "T00:00:00"
        except Exception:
            return ""

    def _collect_reports(self):
        """全部报告，按时间倒序：先取 state.json 里记着的，再补扫报告目录。"""
        cfg = self._cfg
        base = cfg.get("report_dir") or REPORT_DIR
        names, by_slug = {}, {}
        for raw in (cfg.get("channels") or []):
            try:
                c = ch_mod.norm_channel(raw)
            except Exception:
                continue
            names[c["id"]] = c.get("name") or c["id"]
            by_slug.setdefault(reporter.chan_slug(c["id"]),
                               (c["id"], c.get("name") or c["id"]))
        with self._lock:
            state = self._state
        items, seen = [], set()
        for cid, cs in (state.get("channels") or {}).items():
            if not isinstance(cs, dict):
                continue
            cname = names.get(cid)
            if not cname:
                try:
                    cname = ch_mod.norm_channel({"id": cid}).get("name") or cid
                except Exception:
                    cname = cid
            for r in (cs.get("reports") or []):
                if not isinstance(r, dict):
                    continue
                f = str(r.get("file") or "")
                key = self._file_key(f)
                if key in seen:
                    continue
                seen.add(key)
                items.append(self._report_item(
                    cid, cname, r.get("build"), r.get("date"), f,
                    r.get("html"), r.get("summary"), cs))
        for path in self._scan_report_files(base):
            key = self._file_key(path)
            if key in seen:
                continue
            seen.add(key)
            items.append(self._report_item_from_path(path, by_slug))
        items.sort(key=lambda x: (x.get("mtime") or "", x.get("build") or ""),
                   reverse=True)
        return items

    def _report_item(self, cid, cname, build, date, file, html, summary, cs=None):
        f = str(file or "")
        h = str(html or "")
        if h and not os.path.isabs(h):
            h = os.path.join(BASE_DIR, h)
        mtime = self._mtime_iso(f) or self._date_to_iso(date)
        if not mtime and cs:
            mtime = str(cs.get("last_report_at") or "")
        return {
            "channel_id": cid,
            "channel_name": cname or cid,
            "build": str(build or ""),
            "date": str(date or ""),
            "file": f,
            "html": h if (h and os.path.exists(h)) else "",
            "summary": str(summary or ""),
            "mtime": mtime,
        }

    def _report_item_from_path(self, path, by_slug):
        fn = os.path.basename(path)
        m = _REPORT_NAME_RE.search(fn)
        build = m.group(1).replace("-", ".", 1) if m else ""
        date = m.group(2) if m else ""
        slug = os.path.basename(os.path.dirname(path))
        cid, cname = by_slug.get(slug, (slug, slug))
        summary = ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                summary = reporter.one_line_summary(f.read(20000))
        except Exception:
            summary = ""
        html_path = os.path.splitext(path)[0] + ".html"
        return {
            "channel_id": cid,
            "channel_name": cname,
            "build": build,
            "date": date,
            "file": path,
            "html": html_path if os.path.exists(html_path) else "",
            "summary": summary,
            "mtime": self._mtime_iso(path),
        }

    @staticmethod
    def _scan_report_files(base):
        out = []
        try:
            for root, _dirs, files in os.walk(base):
                for fn in files:
                    if fn.lower().endswith(".md"):
                        out.append(os.path.join(root, fn))
        except Exception:
            log_exception("扫描报告目录")
        return out

    # ---------------------------------------------------------- 后台任务 / 事件

    def _push_event(self, event):
        with self._lock:
            self._events.append(event)

    def _begin_long(self, text):
        """占用「同一时间只做一个长操作」的锁；已有操作在跑时返回 False。"""
        with self._lock:
            if self._busy_text:
                return False
            self._busy_text = text or "处理中…"
        self._push_event({"type": "busy", "active": True, "text": self._busy_text})
        return True

    def _end_long(self):
        with self._lock:
            self._busy_text = ""
        self._push_event({"type": "busy", "active": False, "text": ""})

    def _busy_error(self):
        with self._lock:
            busy = self._busy_text or "别的操作"
        return f"上一个操作还没结束（{busy}），稍等一下再试"

    def _run_in_thread(self, label, work, done=None, exclusive=True):
        """后台线程干活；done(res, err) 里只能发事件，绝不碰 WebView。"""

        def runner():
            res = err = None
            try:
                res = work()
            except Exception as e:
                err = e
                log_exception(f"后台任务「{label}」")
            try:
                if done:
                    done(res, err)
            except Exception:
                log_exception(f"后台任务「{label}」的收尾")
            finally:
                if exclusive:
                    self._end_long()

        threading.Thread(target=runner, daemon=True,
                         name="gui-" + (label or "task")[:12]).start()

    def _refresh_cfg(self):
        """只把配置里的标量重读一遍，不动内存里的线列表。"""
        try:
            cfg = load_config()
        except Exception:
            return
        with self._lock:
            self._cfg = cfg
            try:
                self._state = load_state(force=True)
            except Exception:
                pass

    def _query_task_info_text(self):
        try:
            return task_info() or "未安装计划任务"
        except Exception as e:
            log_exception("查询计划任务")
            return f"查询计划任务失败：{e}"

    def _query_task_info_async(self):
        """计划任务查询要 2 秒，放后台；结果缓存，poll().task_text 返回。"""
        with self._lock:
            if self._task_querying:
                return
            self._task_querying = True

        def work():
            return self._query_task_info_text()

        def done(text, err):
            with self._lock:
                self._task_text = (text if not err else f"查询计划任务失败：{err}") \
                    or "未安装计划任务"
                self._task_querying = False
                task_text = self._task_text
            self._push_event({"type": "task_info", "text": task_text})

        self._run_in_thread("查询计划任务", work, done, exclusive=False)

    def _report_keys(self):
        keys = set()
        with self._lock:
            state = self._state
        for cs in ((state.get("channels") or {}).values()):
            if not isinstance(cs, dict):
                continue
            for r in (cs.get("reports") or []):
                if isinstance(r, dict):
                    keys.add(self._file_key(r.get("file")))
        return keys

    def _run_check_live(self, extra=None, note="正在检测"):
        """后台跑一次 checker，stdout 累积进 live。返回 False 表示已有任务在跑。"""
        args = ["--force", "--verbose"] + list(extra or [])
        cmd = check_cmd(args, console=False)
        env = child_env({"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        if not self._begin_long(note + "…（过程显示在「日志与诊断」里）"):
            return False
        with self._lock:
            self._live_active = True
            self._live_lines = []
            self._live_rc = None
        before = self._report_keys()

        def work():
            proc = subprocess.Popen(cmd, cwd=BASE_DIR, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace",
                                    env=env, creationflags=NO_WINDOW)
            try:
                for line in proc.stdout:
                    with self._lock:
                        self._live_lines.append(line.rstrip())
                        if len(self._live_lines) > 400:
                            del self._live_lines[:-400]
            finally:
                try:
                    proc.stdout.close()
                except Exception:
                    pass
                rc = proc.wait()
            return rc

        def done(rc, err):
            with self._lock:
                self._live_active = False
                self._live_rc = rc
                try:
                    self._state = load_state(force=True)
                except Exception:
                    pass
            if err:
                self._push_event({"type": "done", "kind": "check", "ok": False,
                                  "text": f"检测出错：{err}"})
                return
            if rc == 0:
                text = "检测完成。有更新的话报告和通知已经发出去了。"
            else:
                text = f"检测结束了，但退出码是 {rc}，去「日志与诊断」看看上面的输出"
            self._push_event({"type": "done", "kind": "check", "ok": rc == 0,
                              "text": text})
            with self._lock:
                new_reports = bool(self._report_keys() - before)
                channels = self._channels_payload()
            if new_reports:
                self._push_event({"type": "reports", "reports": self._collect_reports()})
            self._push_event({"type": "channels", "channels": channels})

        self._run_in_thread("检测", work, done)
        return True


# ================================================================== 入口

def main():
    """起一个 frameless 原生窗口（WebView2），标题栏由页面自己画。

    窗口进程不常驻：关掉窗口就退出，空闲时只留后台哨兵一个进程（约 55MB）。
    重复启动（双击两下 / 托盘再点）只会把已有窗口提到前台，不会开第二个。
    """
    # ★ 先抢互斥体再 import webview：重复启动（双击两下 / 托盘连点）时，
    #   后一个进程几十毫秒就能退出，不会真去建第二个 WebView2。
    mutex, already = hotwin.create_mutex(hotwin.GUI_MUTEX)
    if already:
        hotwin.signal_gui_show()
        hotwin.close_handle(mutex)
        return 0

    api = None
    try:
        import webview                      # 放在函数里：import gui 时不加载界面依赖

        api = GuiApi()
        index_path = resource_path(os.path.join("webui", "index.html"))
        if not os.path.exists(index_path):
            write_error_line(f"界面文件不存在：{index_path}")
        window = webview.create_window(
            APP_TITLE,
            url=index_path,
            js_api=api,
            width=WINDOW_W,
            height=WINDOW_H,
            min_size=(960, 640),
            frameless=True,                 # 不要原生标题栏/边框，标题栏由页面自绘
            easy_drag=False,                # 整窗任意位置都能拖会很难用，只让标题栏拖
            shadow=True,                    # 保留 DWM 阴影（pywebview 会开）
            background_color="#F6F5F2",
            text_select=True,
        )
        api._window = window
        api.start_show_watcher()

        def on_shown():
            # 窗口真正出现后才有句柄：开 Win11 圆角（Win10 会失败，忽略即可），
            # 并把被 frameless 缩掉的尺寸补回设计值。
            try:
                api._apply_corner(DWMWCP_ROUND)
            except Exception:
                log_exception("设置窗口圆角")
            try:
                api._fix_initial_size(WINDOW_W, WINDOW_H)
            except Exception:
                log_exception("校正窗口初始尺寸")

        try:
            window.events.shown += on_shown
        except Exception:
            pass
        icon = resource_path("icon.ico")
        webview.start(gui="edgechromium", private_mode=True,
                      icon=icon if os.path.exists(icon) else None)
    finally:
        if api is not None:
            api._close_show_handle()
        hotwin.close_handle(mutex)
    return 0


if __name__ == "__main__":
    sys.exit(main())
