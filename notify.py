# -*- coding: utf-8 -*-
"""Windows 通知（Toast）。同时负责注册 AUMID 和自定义协议，让点击能打开报告。

通知的可点击参数（都是纯 ASCII，避免中文在协议里出问题）：
  index                 总览页
  folder                报告文件夹
  log                   日志文件
  r/<频道目录>/<构建号>    某一份具体报告
"""
import os
import sys
import subprocess
import winreg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import BASE_DIR, resource_path, is_frozen, app_exe   # noqa: E402

TOAST_PS1 = resource_path("toast.ps1")
VIEWER_PY = os.path.join(BASE_DIR, "viewer.py")
PS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                  r"System32\WindowsPowerShell\v1.0\powershell.exe")
PROTOCOL = "winupdrept"
NO_WINDOW = 0x08000000


def _pythonw():
    exe = sys.executable or ""
    cand = exe[:-len("python.exe")] + "pythonw.exe" if exe.lower().endswith("python.exe") else exe
    return cand if os.path.exists(cand) else exe


def _handler_command():
    """点击通知时执行什么：打包后让 exe 自己进 viewer 模式，源码运行调 pythonw。"""
    if is_frozen():
        return f'"{app_exe()}" --view "%1"'
    return f'"{_pythonw()}" "{VIEWER_PY}" "%1"'


def ensure_bom(path):
    """PowerShell 5.1 会把没有 BOM 的 .ps1 按 ANSI 解码，中文注释会破坏脚本语法。
    这里保证目标脚本带 UTF-8 BOM（编辑过之后自动补回）。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
        if not data.startswith(b"\xef\xbb\xbf"):
            with open(path, "wb") as f:
                f.write(b"\xef\xbb\xbf" + data)
    except Exception:
        pass


def _set(root, path, name, value):
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def register_app(app_id):
    ok = True
    try:
        base = r"SOFTWARE\Classes\AppUserModelId" + "\\" + app_id
        _set(winreg.HKEY_CURRENT_USER, base, "DisplayName", "win升级报告")
        icon = resource_path("icon.ico")
        if os.path.exists(icon):
            _set(winreg.HKEY_CURRENT_USER, base, "IconUri", icon)
    except Exception:
        ok = False
    try:
        base = r"SOFTWARE\Classes" + "\\" + PROTOCOL
        _set(winreg.HKEY_CURRENT_USER, base, "", "URL:win upgrade report")
        _set(winreg.HKEY_CURRENT_USER, base, "URL Protocol", "")
        _set(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command", "",
             _handler_command())
    except Exception:
        ok = False
    return ok


def show(title, body, app_id="WinUpdReport.App", arg1="index", arg2="folder",
         button1="查看报告", button2="打开总览", silent=False):
    if not os.path.exists(TOAST_PS1):
        return False, "toast.ps1 不存在"
    ensure_bom(TOAST_PS1)
    cmd = [PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-WindowStyle", "Hidden", "-File", TOAST_PS1,
           "-AppId", app_id, "-Title", title, "-Body", body, "-Protocol", PROTOCOL,
           "-Arg1", arg1 or "", "-Arg2", arg2 or "",
           "-Button1", button1 or "", "-Button2", button2 or ""]
    if silent:
        cmd.append("-Silent")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace",
                           creationflags=NO_WINDOW)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    if p.returncode != 0 or "OK" not in (p.stdout or ""):
        return False, (p.stderr or p.stdout or "").strip()[:400]
    return True, ""


if __name__ == "__main__":
    print("注册 AUMID / 协议:", register_app("WinUpdReport.App"))
    if "--test" in sys.argv:
        print(show("win升级报告 · 测试通知",
                   "看到这条说明通知通道正常，点一下试试能不能打开总览页。",
                   arg1="index"))
