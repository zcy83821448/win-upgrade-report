# -*- coding: utf-8 -*-
"""WPF 设置界面的本地服务进程（无窗口）。

界面（C#）通过命名管道发 JSON 行请求，这里复用原来的 GuiApi 数据/动作逻辑，
所以配置读写、加锁、报告生成、托盘、通知、自启、体检等行为与旧界面完全一致。

用法：
    win升级报告.exe --ui-service                     打包后由界面自动拉起
    python ui_service.py --data-dir <数据目录>        源码调试

协议：一行一个 UTF-8 JSON
    请求  {"id":1,"cmd":"bootstrap","args":{}}
    响应  {"id":1,"ok":true,"result":{...}}
    出错  {"id":1,"ok":false,"error":"..."}
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import html as _html
import json
import os
import queue
import sys
import threading
import time
import traceback

PIPE_PREFIX = "winupdreport-ui"
SERVICE_VERSION = 1
IDLE_ACCEPT_SECONDS = 45
IDLE_CONNECTED_SECONDS = 600

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_DEBUG = bool(os.environ.get("WINUPD_UI_DEBUG"))
_DEBUG_PATH = os.path.join(os.environ.get("TEMP", "."), "winupd_ui_service_debug.log")


def _dbg(text):
    if not _DEBUG:
        return
    try:
        with open(_DEBUG_PATH, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), text))
    except Exception:
        pass


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wt.DWORD),
                ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wt.BOOL)]


_PIPE_ACCESS_DUPLEX = 0x00000003
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_READMODE_BYTE = 0x00000000
_PIPE_WAIT = 0x00000000
_PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_ERROR_PIPE_CONNECTED = 535
_ERROR_PIPE_BUSY = 231

_kernel32.CreateNamedPipeW.argtypes = [
    wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD,
    ctypes.POINTER(_SECURITY_ATTRIBUTES)]
_kernel32.CreateNamedPipeW.restype = wt.HANDLE
_kernel32.ConnectNamedPipe.argtypes = [wt.HANDLE, ctypes.c_void_p]
_kernel32.ConnectNamedPipe.restype = wt.BOOL
_kernel32.DisconnectNamedPipe.argtypes = [wt.HANDLE]
_kernel32.DisconnectNamedPipe.restype = wt.BOOL
_kernel32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                               ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_kernel32.ReadFile.restype = wt.BOOL
_kernel32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_char_p, wt.DWORD,
                                ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_kernel32.WriteFile.restype = wt.BOOL
_kernel32.PeekNamedPipe.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                                    ctypes.POINTER(wt.DWORD),
                                    ctypes.POINTER(wt.DWORD),
                                    ctypes.POINTER(wt.DWORD)]
_kernel32.PeekNamedPipe.restype = wt.BOOL
_kernel32.FlushFileBuffers.argtypes = [wt.HANDLE]
_kernel32.CloseHandle.argtypes = [wt.HANDLE]
_kernel32.CloseHandle.restype = wt.BOOL


def default_pipe_name():
    """按用户 + 程序目录区分，避免开发版和正式版互相串线。"""
    import hashlib
    try:
        import getpass
        user = getpass.getuser()
    except Exception:
        user = "user"
    base = os.environ.get("WINUPD_DATA_DIR") or os.path.dirname(
        os.path.abspath(sys.executable if getattr(sys, "frozen", False)
                         else __file__))
    digest = hashlib.sha1((user + "|" + base).encode("utf-8")).hexdigest()[:10]
    return "winupdreport-ui-" + digest


def _read_pipe(handle, size=65536):
    buf = ctypes.create_string_buffer(size)
    read = wt.DWORD(0)
    ok = _kernel32.ReadFile(handle, buf, size, ctypes.byref(read), None)
    if not ok:
        return b""
    return buf.raw[:read.value]


def _write_pipe(handle, payload):
    offset = 0
    total = len(payload)
    while offset < total:
        chunk = payload[offset:offset + 65536]
        written = wt.DWORD(0)
        ok = _kernel32.WriteFile(handle, chunk, len(chunk),
                                 ctypes.byref(written), None)
        if not ok or written.value <= 0:
            return False
        offset += written.value
    return True


def _html_to_blocks(path):
    """兜底：没有 .md 时把 HTML 去标签成段落块。"""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_data(self, data):
            t = data.strip()
            if t:
                self.parts.append(t)

    p = P()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            p.feed(f.read())
    except Exception:
        return []
    return [{"t": "p", "spans": [{"t": "text", "v": x}]} for x in p.parts]


def _patch_data_dir(data_dir):
    """在导入 gui/reporter 之前把数据目录改掉（源码调试用）。"""
    if not data_dir:
        return
    os.environ["WINUPD_DATA_DIR"] = os.path.abspath(data_dir)
    import config
    base = os.path.abspath(data_dir)
    config.BASE_DIR = base
    config.CONFIG_PATH = os.path.join(base, "config.json")
    config.STATE_PATH = os.path.join(base, "state.json")
    config.REPORT_DIR = os.path.join(base, "reports")
    config.LOG_DIR = os.path.join(base, "logs")


class Service:
    def __init__(self, api, pipe_name):
        self._api = api
        self._pipe_name = pipe_name
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._connected = False
        self._last_activity = time.time()
        self._handle = None
        self._responses = None
        self._pending_shutdown = False
        self._stdout = []

    # -------------------------------------------------- 命令
    def _allowed(self):
        from gui import GuiApi
        names = []
        for name in dir(GuiApi):
            if name.startswith("_") or name in ("wrapper",):
                continue
            # 只排除「必须由界面进程自己干」的方法：窗口控制用的是 pywebview
            # 的窗口对象，选图用的是 pywebview 的对话框，这里都没有。
            # list_windows 是纯枚举（只读），新版界面的「选择程序…」要用它。
            if name in ("begin_resize", "window_close", "window_minimize",
                        "window_toggle_max", "start_show_watcher",
                        "close_window", "pick_personal_image"):
                continue
            fn = getattr(GuiApi, name)
            if callable(fn):
                names.append(name)
        return set(names)

    def _dispatch(self, req):
        cmd = str(req.get("cmd") or "")
        args = req.get("args") or {}
        if cmd == "ping":
            return {"ok": True, "version": SERVICE_VERSION, "pid": os.getpid()}
        if cmd == "shutdown":
            return {"ok": True, "bye": True}
        if cmd == "report_doc":
            return self._report_doc(str((args or {}).get("file") or ""))
        if cmd == "bootstrap":
            result = self._api.bootstrap()
            try:
                pers = result.get("personalize") or {}
                pers.pop("bg_url", None)
                try:
                    bg_path = self._api._personalize_path()  # noqa: SLF001
                except Exception:
                    bg_path = ""
                pers["bg_path"] = bg_path if bg_path and os.path.isfile(bg_path) else ""
                result["personalize"] = pers
                result["ui"] = {"pipe": self._pipe_name,
                                "data_dir": self._base_dir()}
            except Exception:
                self._log("[ui-service] bootstrap 整理失败\n" + traceback.format_exc())
            return result
        if cmd == "ui_meta":
            import config
            return {"ok": True, "version": SERVICE_VERSION,
                    "frozen": bool(getattr(sys, "frozen", False)),
                    "base_dir": config.BASE_DIR,
                    "log_path": os.path.join(config.LOG_DIR, "checker.log"),
                    "python": sys.version.split()[0]}
        if cmd not in self._allowed():
            return {"ok": False, "error": "不支持的界面命令：" + cmd}
        fn = getattr(self._api, cmd)
        if isinstance(args, dict):
            result = fn(**args)
        elif isinstance(args, list):
            result = fn(*args)
        else:
            result = fn()
        return result

    def _report_doc(self, file):
        import config
        try:
            path = self._api._resolve_report_path(file)  # noqa: SLF001
        except Exception:
            path = file
        if not path:
            return {"ok": False, "error": "没有指定报告"}
        if path.lower().endswith(".html"):
            md_path = os.path.splitext(path)[0] + ".md"
        else:
            md_path = path
        if os.path.isfile(md_path):
            import mdblocks
            try:
                with open(md_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except Exception as e:
                return {"ok": False, "error": "读报告失败：%s" % e}
            blocks = mdblocks.to_blocks(text)
            title = mdblocks.title_of(blocks)
            return {"ok": True, "source": "md", "file": md_path,
                    "title": title, "blocks": blocks}
        if os.path.isfile(path):
            blocks = _html_to_blocks(path)
            if blocks:
                return {"ok": True, "source": "html", "file": path,
                        "title": os.path.splitext(os.path.basename(path))[0],
                        "blocks": blocks}
        return {"ok": False, "error": "报告文件不存在：%s" % (md_path or path)}

    # -------------------------------------------------- 管道
    def _log(self, text):
        try:
            import gui
            gui.write_error_line(text)
        except Exception:
            pass

    @staticmethod
    def _base_dir():
        try:
            import config
            return config.BASE_DIR
        except Exception:
            return ""

    def _process(self, conn_handle, req, is_last=False):
        rid = req.get("id")
        _dbg("dispatch begin cmd=%s id=%s" % (req.get("cmd"), rid))
        try:
            result = self._dispatch(req)
            ok = True
            err = ""
        except Exception:
            ok = False
            result = None
            err = traceback.format_exc(limit=1).strip().splitlines()[-1]
            self._log("[ui-service] 命令 %s 出错\n%s"
                      % (req.get("cmd"), traceback.format_exc()))
        _dbg("dispatch done cmd=%s ok=%s" % (req.get("cmd"), ok))
        with self._lock:
            self._last_activity = time.time()
        resp = {"id": rid, "ok": ok, "result": result, "error": err}
        payload = json.dumps(resp, ensure_ascii=False, default=str).encode("utf-8") + b"\n"
        if isinstance(result, dict) and result.get("bye"):
            self._pending_shutdown = True
        if is_last:
            self._pending_shutdown = True
        if self._responses is not None:
            self._responses.put(payload)
        else:
            _write_pipe(conn_handle, payload)

    def _handle_line(self, handle, line):
        line = line.strip()
        if not line:
            return
        try:
            req = json.loads(line.decode("utf-8", "replace"))
        except Exception:
            with self._write_lock:
                try:
                    _write_pipe(handle, b'{"id":0,"ok":false,"error":"bad json"}\n')
                except Exception:
                    pass
            return
        threading.Thread(target=self._process, args=(handle, req),
                         daemon=True).start()

    def _serve_once(self, handle, out_handle=None):
        """单线程收/发：同一句柄上并发 ReadFile + WriteFile 会互相卡住，
        所以这里用 PeekNamedPipe 轮询，响应也回到本线程写。"""
        buf = b""
        self._responses = queue.Queue()
        self._pending_shutdown = False
        _dbg("serve_once enter")
        with self._lock:
            self._connected = True
            self._last_activity = time.time()
        try:
            while not self._stop.is_set():
                wrote_any = False
                while True:
                    try:
                        payload = self._responses.get_nowait()
                    except queue.Empty:
                        break
                    _dbg("write response bytes=%d" % len(payload))
                    if not _write_pipe(out_handle if out_handle is not None else handle, payload):
                        return
                    wrote_any = True
                if self._pending_shutdown:
                    self._stop.set()
                    return
                avail = wt.DWORD(0)
                ok = _kernel32.PeekNamedPipe(handle, None, 0, None,
                                             ctypes.byref(avail), None)
                if not ok:
                    _dbg("peek failed err=%s" % ctypes.get_last_error())
                    return
                if avail.value:
                    data = _read_pipe(handle)
                    _dbg("read returned %d bytes" % len(data))
                    if not data:
                        return
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        _dbg("request line: %s" % line[:100])
                        self._handle_line(handle, line)
                elif not wrote_any:
                    time.sleep(0.012)
        finally:
            with self._lock:
                self._connected = False
            self._responses = None
            _dbg("serve_once leave")

    def _idle_watchdog(self):
        while not self._stop.is_set():
            time.sleep(2)
            now = time.time()
            with self._lock:
                connected = self._connected
                idle = now - self._last_activity
            if connected and idle > IDLE_CONNECTED_SECONDS:
                os._exit(0)
            if not connected and idle > IDLE_ACCEPT_SECONDS:
                os._exit(0)

    def run(self):
        """两条单向管道：客户端写 in、读 out。
        同步句柄上「一个线程阻塞 ReadFile + 另一个线程 WriteFile」会互相卡住，
        所以收发分开成两条管道，各自只有一个方向。"""
        name_in = r"\\.\pipe" + "\\" + self._pipe_name
        name_out = name_in + "-out"
        _dbg("service run pipe=%s" % name_in)
        threading.Thread(target=self._idle_watchdog, name="ui-idle",
                         daemon=True).start()

        def _make(name):
            return _kernel32.CreateNamedPipeW(
                name,
                _PIPE_ACCESS_DUPLEX,
                _PIPE_TYPE_BYTE | _PIPE_READMODE_BYTE | _PIPE_WAIT
                | _PIPE_REJECT_REMOTE_CLIENTS,
                1, 65536, 65536, 0, None)

        while not self._stop.is_set():
            h_in = _make(name_in)
            err = ctypes.get_last_error()
            if h_in == _INVALID_HANDLE or h_in is None:
                if err in (_ERROR_PIPE_BUSY, 5):
                    time.sleep(0.2)
                    continue
                self._log("[ui-service] 创建命名管道失败，错误码 %s" % err)
                return 1
            h_out = _make(name_out)
            if h_out == _INVALID_HANDLE or h_out is None:
                _kernel32.CloseHandle(h_in)
                time.sleep(0.2)
                continue
            try:
                _dbg("Connect in")
                ok = _kernel32.ConnectNamedPipe(h_in, None)
                if not ok and ctypes.get_last_error() != _ERROR_PIPE_CONNECTED:
                    continue
                _dbg("Connect out")
                ok = _kernel32.ConnectNamedPipe(h_out, None)
                if not ok and ctypes.get_last_error() != _ERROR_PIPE_CONNECTED:
                    continue
                self._serve_once(h_in, h_out)
                _dbg("after serve_once")
            finally:
                for h in (h_in, h_out):
                    try:
                        _kernel32.DisconnectNamedPipe(h)
                    except Exception:
                        pass
                    try:
                        _kernel32.CloseHandle(h)
                    except Exception:
                        pass
                _dbg("pipe instances closed")
        _dbg("service exit")
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--pipe", default="")
    parser.add_argument("--data-dir", default="")
    args, _unknown = parser.parse_known_args(argv or sys.argv[1:])
    _patch_data_dir(args.data_dir)
    import gui
    api = gui.GuiApi()
    pipe = args.pipe or default_pipe_name()
    return Service(api, pipe).run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        try:
            import gui
            gui.write_error_line("[ui-service] 启动失败\n" + traceback.format_exc())
        except Exception:
            pass
        sys.exit(1)




