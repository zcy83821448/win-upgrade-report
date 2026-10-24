# -*- coding: utf-8 -*-
"""进程间「热启动」用的几个 Win32 内核对象（纯 ctypes）。

设置界面（gui.py）和后台哨兵（watch.py）共用这几个命名对象：

    互斥体 Local\\WinUpdReportGui        谁创建成功，谁就是当前唯一的设置窗口
    事件   Local\\WinUpdReportGuiShow    "把窗口拿出来"（托盘点了）
    事件   Local\\WinUpdReportGuiQuit    "该退了"（完全关闭后台监控时）
    互斥体 Local\\WinUpdReportWatch      哨兵在不在跑（GUI 用它判断要不要常驻）

这样做不是为了好看，是为了**点托盘时不再启动一个新的 Python 进程**：
窗口早就隐藏着等在那里，点一下只是 SetEvent + ShowWindow，实测 20 毫秒。
冷启动一个 PyInstaller + WebView2 进程要 1 秒以上（杀毒软件扫一遍更久），
那才是用户感觉「打开要 5～7 秒」的来源。
"""
import ctypes
from ctypes import wintypes as wt

# 内核对象名。Local\ 命名空间 = 当前登录会话，不会跨用户串。
GUI_MUTEX = r"Local\WinUpdReportGui"
GUI_SHOW_EVENT = r"Local\WinUpdReportGuiShow"
GUI_QUIT_EVENT = r"Local\WinUpdReportGuiQuit"
WATCH_MUTEX = r"Local\WinUpdReportWatch"

WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
SYNCHRONIZE = 0x00100000
EVENT_MODIFY_STATE = 0x0002
ERROR_ALREADY_EXISTS = 183

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = ctypes.c_void_p
_k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
_k32.OpenMutexW.restype = ctypes.c_void_p
_k32.OpenMutexW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_k32.CreateEventW.restype = ctypes.c_void_p
_k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
_k32.OpenEventW.restype = ctypes.c_void_p
_k32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_k32.SetEvent.restype = wt.BOOL
_k32.SetEvent.argtypes = [ctypes.c_void_p]
_k32.WaitForSingleObject.restype = wt.DWORD
_k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wt.DWORD]
_k32.CloseHandle.restype = wt.BOOL
_k32.CloseHandle.argtypes = [ctypes.c_void_p]


def close_handle(handle):
    try:
        if handle:
            _k32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        pass


def create_mutex(name):
    """建（或打开）命名互斥体。返回 (句柄, 是不是本来就有别人在)。"""
    try:
        handle = _k32.CreateMutexW(None, False, name)
        already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        return handle, already
    except Exception:
        return None, False


def mutex_exists(name):
    """只看一眼有没有这个互斥体，不创建、不占住它。"""
    try:
        handle = _k32.OpenMutexW(SYNCHRONIZE, False, name)
        if not handle:
            return False
        close_handle(handle)
        return True
    except Exception:
        return False


def create_event(name):
    """建（或打开）自动复位事件。句柄要一直拿着。"""
    try:
        return _k32.CreateEventW(None, False, False, name)
    except Exception:
        return None


def open_event(name, modify=False):
    try:
        access = SYNCHRONIZE | (EVENT_MODIFY_STATE if modify else 0)
        return _k32.OpenEventW(access, False, name)
    except Exception:
        return None


def set_event(handle):
    try:
        return bool(_k32.SetEvent(ctypes.c_void_p(handle)))
    except Exception:
        return False


def wait_event(handle, timeout_ms):
    """True = 事件被触发；False = 超时/句柄无效。"""
    if not handle:
        return False
    try:
        return _k32.WaitForSingleObject(
            ctypes.c_void_p(handle), int(timeout_ms)) == WAIT_OBJECT_0
    except Exception:
        return False


def signal_event_by_name(name):
    """不长期持有句柄的进程用这个：打开 -> SetEvent -> 关掉。"""
    handle = open_event(name, modify=True)
    if not handle:
        return False
    try:
        return set_event(handle)
    finally:
        close_handle(handle)


# ------------------------------------------------------------------ 快捷判断
def watchdog_alive():
    return mutex_exists(WATCH_MUTEX)


def gui_alive():
    return mutex_exists(GUI_MUTEX)


def signal_gui_show():
    return signal_event_by_name(GUI_SHOW_EVENT)


def signal_gui_quit():
    return signal_event_by_name(GUI_QUIT_EVENT)
