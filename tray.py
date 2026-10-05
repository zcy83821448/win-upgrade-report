# -*- coding: utf-8 -*-
"""系统托盘图标（纯 ctypes 调 Win32，不依赖任何第三方库）。

★ 为什么托盘图标挂在「哨兵」身上，而不是设置界面里？
    设置界面是个开完就关的窗口。图标要是挂在它身上，用户一关窗口图标就没了，
    那正好回答不了用户真正关心的问题：「它到底还在不在后台跑？」
    所以图标必须挂在**一直活着的哨兵**进程上 —— 只要图标还在，就说明它在跑。

★ 为什么不装 pystray / Pillow？
    会让 exe 白白多出十几 MB，而且这两个都不是标准库。这里直接用
    Win32 的 Shell_NotifyIcon，几十行 ctypes 就够了。

★ 安全性：整个托盘跑在一个独立线程里，自己跑消息循环。任何异常最坏的结果
    只是「没有图标」，绝不影响检测主循环（外层有 try/except 兜住）。

用法：
    t = Tray(icon_path, menu_provider, on_default)
    t.start()                     # 起线程，图标出现
    t.set_tip("运行中 · 上次检查 12:34")
    t.balloon("标题", "内容")     # 气泡提示（可选）
    t.stop()                      # 移除图标，线程退出
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import threading
import traceback

from config import resource_path

_u32 = ctypes.windll.user32
_shell = ctypes.windll.shell32
_k32 = ctypes.windll.kernel32

# ---------------------------------------------------------------- 常量
WM_APP = 0x8000
WM_TRAY = WM_APP + 1        # 托盘图标事件回调
WM_TIP = WM_APP + 2         # 外部要求刷新提示文字
WM_STOP = WM_APP + 3        # 外部要求退出

NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO, NIF_SHOWTIP = 0x01, 0x02, 0x04, 0x10, 0x80
NOTIFYICON_VERSION_4 = 4

WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0202, 0x0203, 0x0205
WM_DESTROY, WM_NULL = 0x0002, 0x0000
MF_STRING, MF_SEPARATOR, MF_GRAYED, MF_CHECKED = 0x0, 0x800, 0x1, 0x8
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x0010, 0x0040
IDI_APPLICATION = 32512
NIIF_INFO = 0x1


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class _NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD),
                ("hWnd", ctypes.c_void_p),
                ("uID", ctypes.c_uint),
                ("uFlags", ctypes.c_uint),
                ("uCallbackMessage", ctypes.c_uint),
                ("hIcon", ctypes.c_void_p),
                ("szTip", ctypes.c_wchar * 128),
                ("dwState", wt.DWORD),
                ("dwStateMask", wt.DWORD),
                ("szInfo", ctypes.c_wchar * 256),
                ("uVersion", ctypes.c_uint),
                ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", wt.DWORD),
                ("guidItem", _GUID),
                ("hBalloonIcon", ctypes.c_void_p)]


class _WNDCLASS(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint),
                ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p)]


class _NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", ctypes.c_void_p),
                ("uID", ctypes.c_uint), ("guidItem", _GUID)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]


_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                              ctypes.c_void_p, ctypes.c_void_p)

# 显式声明签名：64 位下不声明会把句柄截断成 32 位，那是最经典的坑
_u32.CreateWindowExW.restype = ctypes.c_void_p
_u32.CreateWindowExW.argtypes = [wt.DWORD, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                 wt.DWORD, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                 ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
_u32.DefWindowProcW.restype = ctypes.c_void_p
_u32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                ctypes.c_void_p, ctypes.c_void_p]
_u32.LoadImageW.restype = ctypes.c_void_p
_u32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                            ctypes.c_int, ctypes.c_int, ctypes.c_uint]
_u32.LoadIconW.restype = ctypes.c_void_p
_u32.LoadIconW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_u32.CreatePopupMenu.restype = ctypes.c_void_p
_u32.TrackPopupMenu.restype = ctypes.c_int
_u32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
_k32.GetModuleHandleW.restype = ctypes.c_void_p
_k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]

# 下面这些都要显式声明：所有「句柄」参数必须按 64 位指针传。
# 不声明的话 ctypes 会按 32 位整数转，HMENU/HWND 会被截断成半个地址——
# 表现就是「菜单偶尔点不出来」「图标删不掉」，而且很难查。
_u32.AppendMenuW.restype = wt.BOOL
_u32.AppendMenuW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                             ctypes.c_size_t, ctypes.c_wchar_p]
_u32.TrackPopupMenu.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                ctypes.c_void_p]
_u32.DestroyMenu.restype = wt.BOOL
_u32.DestroyMenu.argtypes = [ctypes.c_void_p]
_u32.SetForegroundWindow.restype = wt.BOOL
_u32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
_u32.PostMessageW.restype = wt.BOOL
_u32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                              ctypes.c_size_t, ctypes.c_ssize_t]
_u32.DestroyWindow.restype = wt.BOOL
_u32.DestroyWindow.argtypes = [ctypes.c_void_p]
_u32.RegisterClassW.restype = wt.WORD
_u32.RegisterClassW.argtypes = [ctypes.c_void_p]
_u32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), ctypes.c_void_p,
                             ctypes.c_uint, ctypes.c_uint]
_u32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
_u32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
_u32.PostQuitMessage.argtypes = [ctypes.c_int]
_u32.DestroyIcon.restype = wt.BOOL
_u32.DestroyIcon.argtypes = [ctypes.c_void_p]
_shell.Shell_NotifyIconW.restype = wt.BOOL
_shell.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.c_void_p]
_shell.Shell_NotifyIconGetRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]


# --------------------------------------------------------------- 图标样式

def load_styles():
    """读 icons/styles.json（由 做图标.py 生成）。

    返回 (默认样式 id, 样式列表)。文件不在或者读坏了，就退回「只有一种样式」，
    保证托盘怎么都能显示出来。
    """
    try:
        p = resource_path(os.path.join("icons", "styles.json"))
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        styles = [s for s in (d.get("styles") or []) if s.get("ico")]
        if styles:
            return (d.get("default") or styles[0]["id"]), styles
    except Exception:
        pass
    return "default", [{"id": "default", "name": "默认",
                        "ico": "tray.ico", "preview": ""}]


def _style_file(style_id, key):
    _d, styles = load_styles()
    for s in styles:
        if s.get("id") == style_id:
            fn = s.get(key)
            if fn:
                p = resource_path(os.path.join("icons", fn))
                if os.path.exists(p):
                    return p
    return ""


def icon_path(style_id):
    """取某个样式的 .ico 完整路径；找不到就逐级退回 tray.ico / icon.ico。"""
    p = _style_file(style_id, "ico")
    if p:
        return p
    for name in ("tray.ico", "icon.ico"):
        q = resource_path(name)
        if os.path.exists(q):
            return q
    return ""


def preview_path(style_id):
    """取某个样式的预览 PNG（设置界面里显示用，tkinter 读不了 ICO）。"""
    return _style_file(style_id, "preview")


class Tray:
    """托盘图标。

    menu_provider() 每次右键时被调用，返回菜单项列表，例如：
        [{"id": "open", "label": "打开设置界面"},
         {"sep": True},
         {"id": "quit", "label": "完全关闭", "enabled": True, "checked": False}]
    on_default() 双击图标时调用。
    """

    CLASS_NAME = "WinUpdReportTrayWnd"

    def __init__(self, icon_path=None, menu_provider=None, on_default=None,
                 on_action=None, tip="win升级报告"):
        self.icon_path = icon_path or ""
        self.menu_provider = menu_provider
        self.on_default = on_default
        self.on_action = on_action
        self._tip = tip[:127]
        self._hwnd = None
        self._hicon = None
        self._thread = None
        self._ready = threading.Event()
        self._error = ""
        self._alive = False
        self._balloon_req = None
        self._balloon_shown = False
        self._icon_from_file = False
        self._lock = threading.Lock()
        self._wndproc = _WNDPROC(self._on_message)   # 必须留住引用，否则被回收

    # ------------------------------------------------------------ 对外接口
    def start(self):
        """起线程并等图标就绪。失败也不抛异常，只返回 False。"""
        self._thread = threading.Thread(target=self._run, name="tray",
                                        daemon=True)
        self._thread.start()
        self._ready.wait(6)
        return self._alive

    def set_tip(self, text):
        """更新鼠标悬停时显示的提示文字。"""
        with self._lock:
            self._tip = (text or "")[:127]
        if self._hwnd:
            _u32.PostMessageW(self._hwnd, WM_TIP, 0, 0)

    def set_icon(self, path):
        """换一个图标文件，不用重启进程。

        用户在设置界面里换样式后，哨兵下一轮就会调这里把托盘图标换掉。
        """
        if not self._hwnd or not path or not os.path.exists(path):
            return False
        h = _u32.LoadImageW(None, path, IMAGE_ICON, 0, 0,
                            LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if not h:
            return False
        old = self._hicon
        self._hicon = h
        _shell.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid(NIF_ICON)))
        # 旧图标是我们自己从文件加载的，要销毁，免得一次换一个攒着不放
        try:
            if old and self._icon_from_file:
                _u32.DestroyIcon(ctypes.c_void_p(old))
        except Exception:
            pass
        self._icon_from_file = True
        return True

    def balloon(self, title, text):
        """弹一个气泡提示（图标旁边那种）。"""
        self._balloon_req = ((title or "")[:63], (text or "")[:255])
        if self._hwnd:
            _u32.PostMessageW(self._hwnd, WM_TIP, 0, 0)

    def stop(self):
        if self._hwnd:
            _u32.PostMessageW(self._hwnd, WM_STOP, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(3)

    @property
    def alive(self):
        return self._alive

    def icon_rect(self):
        """查托盘图标在屏幕上的位置（拿来验证图标真的注册上了）。"""
        if not self._hwnd:
            return None
        nid = _NOTIFYICONIDENTIFIER()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self._hwnd
        nid.uID = 1
        rc = _RECT()
        hr = _shell.Shell_NotifyIconGetRect(ctypes.byref(nid), ctypes.byref(rc))
        if hr != 0:
            return None
        return (rc.left, rc.top, rc.right, rc.bottom)

    # ------------------------------------------------------------ 内部实现
    def _nid(self, flags):
        nid = _NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._hicon
        nid.szTip = self._tip
        return nid

    def _run(self):
        try:
            hinst = _k32.GetModuleHandleW(None)
            wc = _WNDCLASS()
            wc.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p)
            wc.hInstance = hinst
            wc.lpszClassName = self.CLASS_NAME
            _u32.RegisterClassW(ctypes.byref(wc))

            # 建一个永远不显示的普通窗口：托盘回调消息要落到它身上。
            # （不用 message-only 窗口：那种窗口上弹右键菜单容易出问题。）
            self._hwnd = _u32.CreateWindowExW(
                0, self.CLASS_NAME, "win升级报告 托盘", 0, 0, 0, 0, 0,
                None, None, hinst, None)
            if not self._hwnd:
                self._error = "CreateWindowEx 失败"
                return

            self._hicon = None
            self._icon_from_file = False
            if self.icon_path and os.path.exists(self.icon_path):
                self._hicon = _u32.LoadImageW(None, self.icon_path, IMAGE_ICON,
                                              0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
                self._icon_from_file = bool(self._hicon)
            if not self._hicon:
                self._hicon = _u32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

            # 加图标 + 设成 v4 行为（v4 下右键/左键的坐标会带在 lParam 里）
            if not _shell.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid(
                    NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP))):
                self._error = "Shell_NotifyIcon(NIM_ADD) 失败"
                return
            nid = self._nid(0)
            nid.uVersion = NOTIFYICON_VERSION_4
            _shell.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))

            self._alive = True
            self._ready.set()

            # 自己的消息循环
            msg = wt.MSG()
            while _u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                _u32.TranslateMessage(ctypes.byref(msg))
                _u32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            self._error = traceback.format_exc()[-400:]
        finally:
            try:
                if self._hwnd:
                    _shell.Shell_NotifyIconW(NIM_DELETE,
                                             ctypes.byref(self._nid(0)))
            except Exception:
                pass
            self._alive = False
            self._ready.set()

    def _on_message(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                event = (lparam & 0xFFFF) if lparam else 0
                if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    if self.on_default:
                        self.on_default()
                elif event == WM_RBUTTONUP:
                    self._popup_menu()
                return 0
            if msg == WM_TIP:
                self._apply_tip()
                return 0
            if msg == WM_STOP:
                _shell.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid(0)))
                _u32.DestroyWindow(hwnd)
                _u32.PostQuitMessage(0)
                return 0
            if msg == WM_DESTROY:
                _u32.PostQuitMessage(0)
                return 0
        except Exception:
            pass
        return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _apply_tip(self):
        """把提示文字 / 气泡刷新到图标上。"""
        with self._lock:
            balloon = self._balloon_req
            self._balloon_req = None
        nid = self._nid(NIF_TIP | NIF_SHOWTIP)
        _shell.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        if balloon and not self._balloon_shown:
            self._balloon_shown = True
            nid2 = self._nid(NIF_INFO)
            nid2.szInfoTitle = balloon[0]
            nid2.szInfo = balloon[1]
            nid2.dwInfoFlags = NIIF_INFO
            _shell.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid2))

    def _popup_menu(self):
        items = []
        try:
            items = self.menu_provider() if self.menu_provider else []
        except Exception:
            items = []
        hmenu = _u32.CreatePopupMenu()
        ids = {}
        seq = 1000
        for it in items:
            if it.get("sep"):
                _u32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                continue
            seq += 1
            flags = MF_STRING
            if not it.get("enabled", True):
                flags |= MF_GRAYED
            if it.get("checked"):
                flags |= MF_CHECKED
            _u32.AppendMenuW(hmenu, flags, seq, it.get("label") or it.get("id"))
            ids[seq] = it.get("id")

        pt = wt.POINT()
        _u32.GetCursorPos(ctypes.byref(pt))
        _u32.SetForegroundWindow(self._hwnd)      # 不加这句菜单点外面不消失
        cmd = _u32.TrackPopupMenu(hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD |
                                  TPM_NONOTIFY, pt.x, pt.y, 0, self._hwnd, None)
        _u32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        _u32.DestroyMenu(hmenu)

        action = ids.get(cmd)
        if action and self.on_action:
            try:
                self.on_action(action)
            except Exception:
                pass


if __name__ == "__main__":
    # 自检：把图标显示出来，验证「注册成功 → 能查到位置 → 移除后消失」。
    # 右键图标能看到测试菜单；双击图标会打印一行。
    import sys
    import time

    here = os.path.dirname(os.path.abspath(__file__))
    holder = {}

    def _menu():
        return [{"id": "status", "label": "自检：图标正常（不可点）", "enabled": False},
                {"sep": True},
                {"id": "ping", "label": "点我一下（会打印一行）"},
                {"id": "quit", "label": "退出自检"}]

    def _action(name):
        print(f"菜单被点了: {name}", flush=True)
        if name == "quit":
            holder["t"].stop()

    t = Tray(os.path.join(here, "icon.ico"), menu_provider=_menu,
             on_default=lambda: print("双击了图标", flush=True),
             on_action=_action, tip="win升级报告 托盘自检")
    holder["t"] = t
    ok = t.start()
    print(f"图标注册: {'成功' if ok else '失败'}　错误: {t._error or '无'}", flush=True)
    time.sleep(1)
    print(f"图标位置: {t.icon_rect()}", flush=True)
    t.set_tip("win升级报告 · 托盘自检中（20 秒后自动移除）")
    for _ in range(20):
        time.sleep(1)
    print(f"移除前图标位置: {t.icon_rect()}", flush=True)
    t.stop()
    time.sleep(1)
    print(f"移除后图标位置: {t.icon_rect()}　（None 表示已经收掉了）", flush=True)
    sys.exit(0 if ok else 1)

