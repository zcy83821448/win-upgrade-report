# -*- coding: utf-8 -*-
"""判断「用户是不是在玩全屏游戏」，好让工具彻底闭嘴。

为什么这么麻烦
--------------
实测发现，光看「有没有窗口铺满屏幕」会严重误判。这台机器上没玩游戏的时候，
就有 3 个铺满整屏、还没有标题栏的窗口，全都不是游戏：

    explorer.exe        [Progman]                   → 它就是桌面本身
    TextInputHost.exe   [Windows.UI.Core.CoreWindow] → 系统标记为「其实看不见」
    NVIDIA Overlay.exe  [CEF-OSC-WIDGET]             → 叠加层（分层窗口）

同样，「微软官方那个『现在该不该打扰用户』的接口」也不能单独用：实测在
普通桌面状态下它就返回「全屏忙」，信它的话工具会永久静默。

所以判定只能靠一组**通用特征**，不能只看尺寸、也不能维护游戏名单：

    铺满整块屏幕 + 没有标题栏 + 不是隐形窗口 + 不是分层叠加层
    + 不是工具窗口 + 不是桌面外壳  →  判定「在玩全屏游戏」

无边框全屏的游戏窗口恰好就是这个形状（铺满屏幕、没有标题栏、不是叠加层），
所以这个规则能认出它；上面那三类干扰窗口各自踩中一条排除规则，会被正确放行。

成本：扫一遍所有窗口约 0.3 毫秒（实测）。每 5 秒一次 = 单核的 0.006%。
"""
import ctypes
import ctypes.wintypes as wt
import os

_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
try:
    _dwm = ctypes.windll.dwmapi
except Exception:                                    # 理论上不会发生
    _dwm = None

try:
    # 高分屏下窗口坐标才和显示器坐标一致，不然会误判
    _u32.SetProcessDPIAware()
except Exception:
    pass

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION = 0x00C00000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_CLOAKED = 14
MONITOR_DEFAULTTONEAREST = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WM_CLOSE = 0x0010

# 兜底保险：这些进程永远不算「在玩游戏」。
# 正常情况下上面那套通用规则已经能把它们挡掉，这里只是再上一道锁，
# 免得某个系统更新改了窗口样式之后突然开始误判。
ALWAYS_IGNORE = {
    "explorer.exe", "textinputhost.exe", "shellexperiencehost.exe",
    "searchhost.exe", "startmenuexperiencehost.exe", "dwm.exe",
    "sihost.exe", "lockapp.exe", "applicationframehost.exe",
    "nvidia overlay.exe", "nvidia share.exe", "nvidia app.exe",
    "gamebar.exe", "gamebarpresencewriter.exe", "widgets.exe",
}


class _RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", wt.DWORD)]


_ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _style(hwnd, index):
    """取窗口样式。按 32 位无符号处理，免得高位被当成负数。"""
    try:
        return int(_u32.GetWindowLongW(hwnd, index)) & 0xFFFFFFFF
    except Exception:
        return 0


def _exe_of(pid):
    if not pid:
        return ""
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return ""
    finally:
        _k32.CloseHandle(h)


def _class_of(hwnd):
    try:
        buf = ctypes.create_unicode_buffer(256)
        _u32.GetClassNameW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def _title_of(hwnd):
    try:
        n = _u32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        _u32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value
    except Exception:
        return ""


def _cloaked(hwnd):
    """DWM 的「其实看不见」标记。UWP 窗口藏起来时就是这个状态。"""
    if _dwm is None:
        return 0
    v = ctypes.c_int(0)
    try:
        _dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED,
                                   ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        return 0
    return v.value


def _covers_monitor(hwnd):
    """窗口是不是把整块所属显示器都盖住了（任务栏也算，最大化窗口不算）。"""
    rc = _RECT()
    if not _u32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return False, (0, 0)
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w <= 0 or h <= 0:
        return False, (w, h)
    mi = _MONITORINFO()
    mi.cbSize = ctypes.sizeof(mi)
    mon = _u32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not _u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return False, (w, h)
    m = mi.rcMonitor
    ok = (rc.left <= m.left and rc.top <= m.top
          and rc.right >= m.right and rc.bottom >= m.bottom)
    return ok, (w, h)


def _ignored(exe, ignore):
    name = os.path.basename(exe or "").lower()
    if not name:
        return False
    if name in ALWAYS_IGNORE:
        return True
    low = (exe or "").lower()
    for item in (ignore or []):
        it = str(item).strip().lower()
        if not it:
            continue
        if it == name or it == low or (len(it) > 2 and it in low):
            return True
    return False


def scan(ignore=None, own_pid=None):
    """找出所有「像游戏的全屏窗口」。返回列表，每项带排除理由。"""
    found = []
    shell = _u32.GetShellWindow()
    desktop = _u32.GetDesktopWindow()

    def visit(hwnd, _):
        try:
            if not _u32.IsWindowVisible(hwnd):
                return True
            if hwnd in (shell, desktop):
                return True

            covers, size = _covers_monitor(hwnd)
            if not covers:
                return True
            if _style(hwnd, GWL_STYLE) & WS_CAPTION:
                return True                       # 有标题栏 → 普通窗口，不是全屏游戏
            if _cloaked(hwnd):
                return True                       # 系统说它其实看不见（例如输入法宿主）
            ex = _style(hwnd, GWL_EXSTYLE)
            if ex & WS_EX_LAYERED:
                return True                       # 分层窗口 → 叠加层（例如 NVIDIA Overlay）
            if ex & WS_EX_TOOLWINDOW:
                return True                       # 工具窗口 → 系统组件

            pid = wt.DWORD(0)
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if own_pid and pid.value == int(own_pid):
                return True                       # 自己
            exe = _exe_of(pid.value)
            if _ignored(exe, ignore):
                return True

            found.append({"exe": exe, "name": os.path.basename(exe or ""),
                          "pid": pid.value, "cls": _class_of(hwnd),
                          "title": _title_of(hwnd), "size": size})
        except Exception:
            pass
        return True

    try:
        _u32.EnumWindows(_ENUMPROC(visit), 0)
    except Exception:
        pass
    return found


def check(ignore=None, own_pid=None):
    """判断现在是不是「在玩全屏游戏」。

    返回字典：
        gaming      True/False
        exe         命中程序的完整路径（用来给用户看「因为谁静默了」）
        name        程序名
        title/cls   窗口标题和类名（排查误判时有用）
        count       命中几个
    """
    hits = scan(ignore=ignore, own_pid=own_pid)
    if not hits:
        return {"gaming": False, "exe": "", "name": "", "title": "",
                "cls": "", "count": 0}
    first = hits[0]
    return {"gaming": True, "exe": first["exe"], "name": first["name"],
            "title": first["title"], "cls": first["cls"], "count": len(hits)}


def current_foreground():
    """前台窗口属于哪个程序（设置界面里做「一键把当前程序加进忽略名单」用）。"""
    hwnd = _u32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wt.DWORD(0)
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return _exe_of(pid.value)


if __name__ == "__main__":
    import time
    r = check()
    print("现在在玩游戏吗：", "是" if r["gaming"] else "否")
    if r["gaming"]:
        print("  因为：", r["exe"], r["title"], r["cls"], r["size"] if "size" in r else "")
    n = 2000
    t = time.time()
    for _ in range(n):
        check()
    print(f"扫一次平均 {(time.time() - t) / n * 1000:.3f} 毫秒")
