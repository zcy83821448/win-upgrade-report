# -*- coding: utf-8 -*-
"""设置界面：挑更新线、改 API / 时间 / 间隔，装计划任务，看日志。"""
import os
import sys
import queue
import threading
import subprocess
import datetime as dt
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (load_config, save_config, load_state, channel_state,   # noqa: E402
                    resolve_api_key, mask_key, BASE_DIR, REPORT_DIR, LOG_DIR,
                    resource_path, is_frozen, app_exe,
                    load_watch, request_check_now)
import channels as ch_mod                                                   # noqa: E402
import notify                                                               # noqa: E402
import reporter                                                             # noqa: E402
import deepseek_api                                                         # noqa: E402

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


def run_background(args):
    """后台静默跑一次检测，不看输出。"""
    return subprocess.Popen(check_cmd(args), cwd=BASE_DIR, creationflags=NO_WINDOW)


def spawn_view(arg):
    """打开查看器 / 总览页，不等待。"""
    return subprocess.Popen(view_cmd(arg), cwd=BASE_DIR, creationflags=NO_WINDOW)


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


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.state = load_state()
        self.rows = []          # 界面里的更新线列表
        self._busy = False
        self._task_text = "正在查询计划任务…"
        self._results = queue.Queue()
        self._live_lines = []
        self.log_tab = None
        root.title(APP_TITLE)
        root.geometry("880x640")
        root.minsize(820, 560)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        self.t_chan = ttk.Frame(nb, padding=10)
        self.t_detect = ttk.Frame(nb, padding=12)
        self.t_api = ttk.Frame(nb, padding=12)
        self.t_task = ttk.Frame(nb, padding=12)
        self.t_log = ttk.Frame(nb, padding=12)
        nb.add(self.t_chan, text="更新线")
        nb.add(self.t_detect, text="检测与通知")
        nb.add(self.t_api, text="DeepSeek API")
        nb.add(self.t_task, text="计划任务")
        nb.add(self.t_log, text="状态与日志")
        self.nb = nb
        self.log_tab = self.t_log
        nb.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        self.v = {}
        self._build_chan(self.t_chan)
        self._build_detect(self.t_detect)
        self._build_api(self.t_api)
        self._build_task(self.t_task)
        self._build_log(self.t_log)

        bar = ttk.Frame(root, padding=(12, 0, 12, 4))
        bar.pack(fill="x")
        self.status = ttk.Label(bar, text="", foreground="#0a6cff", wraplength=820,
                                justify="left")
        self.status.pack(anchor="w")

        btns = ttk.Frame(root, padding=(12, 4, 12, 12))
        btns.pack(fill="x")
        ttk.Button(btns, text="保存设置", command=self.save).pack(side="left")
        self.btn_check = ttk.Button(btns, text="立即检测全部（过程显示在日志里）",
                                    command=lambda: self.run_check_live())
        self.btn_check.pack(side="left", padx=6)
        self.btn_toast = ttk.Button(btns, text="发测试通知", command=self.test_toast)
        self.btn_toast.pack(side="left")
        self.btn_close = ttk.Button(btns, text="关闭", command=root.destroy)
        self.btn_close.pack(side="right")

        self.reload_channels()
        self.refresh_status()
        self.refresh_task_info_async()      # 查计划任务要 2 秒，放后台
        self.root.after(100, self._poll_results)   # 主线程轮询后台结果

    # ================================================ 后台任务（不卡界面）
    def busy_run(self, fn, done=None, msg="处理中…", widgets=(), lock=True):
        """把 fn 丢到线程里跑，完成后回主线程调 done(result, error)。

        Tk 只能在主线程碰：工作线程把结果丢进队列，主线程的轮询器取出来再更新界面。
        lock=False 用于启动时的只读查询，不占用「同一时间只做一个操作」的锁。
        """
        if lock and self._busy:
            self.set_status("上一个操作还没结束，稍等一下", "#c00")
            return
        self._busy = self._busy or lock
        for w in widgets:
            try:
                w.configure(state="disabled")
            except Exception:
                pass
        if msg:
            self.set_status(msg)

        def worker():
            try:
                res, err = fn(), None
            except Exception as e:
                res, err = None, e
            # 这里绝对不能碰任何 Tk 对象，只放队列
            self._results.put((res, err, done, widgets, lock))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_results(self):
        """主线程轮询：先刷新实时输出，再取走工作线程的成果。"""
        if self._live_lines:
            lines, self._live_lines = self._live_lines[:], []
            self.append_log(lines)
            self.set_status(lines[-1][:120])
        try:
            while True:
                res, err, done, widgets, lock = self._results.get_nowait()
                self._busy_done(res, err, done, widgets, lock)
        except queue.Empty:
            pass
        except Exception as e:
            self.set_status(f"后台任务回调出错：{e}", "#c00")
        self.root.after(100, self._poll_results)

    def append_log(self, lines):
        try:
            self.logbox.configure(state="normal")
            self.logbox.insert("end", "\n".join(lines) + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        except Exception:
            pass

    def _busy_done(self, res, err, done, widgets, lock=True):
        if lock:
            self._busy = False
        for w in widgets:
            try:
                w.configure(state="normal")
            except Exception:
                pass
        if done:
            try:
                done(res, err)
            except Exception as e:
                self.set_status(f"回调出错：{e}", "#c00")
        elif err:
            self.set_status(f"出错：{err}", "#c00")

    def refresh_task_info_async(self, after=None):
        """计划任务状态只在装/卸之后才会变，所以查一次缓存起来，别每次点按钮都查。
        只读查询，不占锁、不改状态栏，免得刚开窗口的 2 秒里用户点什么都被挡。"""
        self.busy_run(task_info,
                      lambda r, e: self._set_task_text(r if not e else f"查询失败：{e}",
                                                       now=after),
                      msg=None, lock=False)

    def _set_task_text(self, text, now=None):
        self._task_text = text or "未安装计划任务"
        try:
            self.task_lbl.configure(text=self._task_text)
        except Exception:
            pass
        if now:
            now()

    def on_tab_changed(self, event=None):
        try:
            if self.nb.nametowidget(self.nb.select()) is self.log_tab:
                self.load_log()
        except Exception:
            pass

    # ======================================================== 更新线
    def _build_chan(self, p):
        top = ttk.Frame(p)
        top.pack(fill="x")
        ttk.Label(top, text="监控哪些更新线", font=("", 11, "bold")).pack(side="left")
        self.btn_discover = ttk.Button(top, text="从 Flight Hub 刷新频道列表",
                                       command=self.discover)
        self.btn_discover.pack(side="right")
        ttk.Label(p, text="双击一行 = 启用/停用；选中一行在下面看详情。"
                          "Insider 线来自微软 Flight Hub，uupdump 线用于正式版/零售版本。",
                  foreground="#888").pack(anchor="w", pady=(2, 6))

        mid = ttk.Frame(p)
        mid.pack(fill="both", expand=True)
        cols = ("on", "name", "src", "ver", "chk", "rep")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=13,
                                 selectmode="browse")
        for c, txt, w in (("on", "启用", 48), ("name", "更新线", 240),
                          ("src", "来源", 90), ("ver", "当前记录版本", 130),
                          ("chk", "上次检测", 100), ("rep", "最近报告", 110)):
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor="w" if c in ("name", "src") else "center")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("off", foreground="#9aa0ad")
        self.tree.bind("<Double-1>", self.toggle_row)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_detail())

        add = ttk.Frame(p)
        add.pack(fill="x", pady=(6, 0))
        ttk.Label(add, text="添加自定义 uupdump 分类/网址").pack(side="left")
        self.custom = tk.StringVar()
        ttk.Entry(add, textvariable=self.custom, width=34).pack(side="left", padx=6)
        ttk.Button(add, text="添加", command=self.add_custom).pack(side="left")
        ttk.Button(add, text="启用/停用选中", command=self.toggle_sel).pack(side="left", padx=8)
        ttk.Button(add, text="全部启用", command=lambda: self.set_all(True)).pack(side="left")
        ttk.Button(add, text="全部停用", command=lambda: self.set_all(False)).pack(side="left", padx=4)

        det = ttk.LabelFrame(p, text="选中这条线的操作", padding=8)
        det.pack(fill="x", pady=(8, 0))
        self.detail = ttk.Label(det, text="选一行看看", justify="left")
        self.detail.grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        ttk.Button(det, text="只检测这条线（弹窗）",
                   command=self.check_selected).grid(row=1, column=0, padx=(0, 6))
        ttk.Button(det, text="打开最近报告",
                   command=self.open_selected_report).grid(row=1, column=1, padx=6)
        ttk.Button(det, text="打开报告文件夹",
                   command=self.open_selected_dir).grid(row=1, column=2, padx=6)
        ttk.Button(det, text="忽略当前版本",
                   command=self.ignore_current).grid(row=1, column=3, padx=6)
        ttk.Button(det, text="清除忽略",
                   command=self.clear_ignored).grid(row=1, column=4, padx=6)
        ttk.Label(det, text="架构").grid(row=1, column=5, padx=(16, 2))
        self.arch = ttk.Combobox(det, values=["amd64", "arm64"], width=7, state="readonly")
        self.arch.grid(row=1, column=6)
        self.arch.bind("<<ComboboxSelected>>", self.set_arch)

    def reload_channels(self):
        """界面列表 = 配置里的线 + 预设里还没加进来的线（灰显）。"""
        cfg_ids = {c["id"] for c in self.cfg.get("channels", [])}
        self.rows = [ch_mod.norm_channel(c) for c in self.cfg.get("channels", [])]
        for c in ch_mod.all_presets():
            c = ch_mod.norm_channel(c)
            if c["id"] not in cfg_ids:
                c["enabled"] = False
                c["_preset"] = True
                self.rows.append(c)
        self.rows.sort(key=lambda c: (0 if c["source"] == "flighthub" else 1,
                                      ch_mod.FH_ORDER.index(c["folder"])
                                      if c["source"] == "flighthub"
                                      and c.get("folder") in ch_mod.FH_ORDER else 99,
                                      c.get("name", "")))
        self.refresh_tree()

    def refresh_tree(self):
        sel = self.selected_id()
        self.tree.delete(*self.tree.get_children())
        for c in self.rows:
            cs = (self.state.get("channels") or {}).get(c["id"], {})
            rep = cs.get("last_report") or ""
            self.tree.insert("", "end", iid=c["id"], tags=() if c["enabled"] else ("off",),
                             values=("☑" if c["enabled"] else "☐", c.get("name", c["id"]),
                                     "Flight Hub" if c["source"] == "flighthub" else "uupdump",
                                     cs.get("last_version") or "—",
                                     cs.get("last_check_date") or "—",
                                     os.path.basename(rep)[:24] if rep else "—"))
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)

    def selected_id(self):
        s = self.tree.selection()
        return s[0] if s else ""

    def row_by_id(self, cid):
        return next((c for c in self.rows if c["id"] == cid), None)

    def show_detail(self):
        c = self.row_by_id(self.selected_id())
        if not c:
            self.detail.configure(text="选一行看看")
            return
        cs = (self.state.get("channels") or {}).get(c["id"], {})
        ig = cs.get("ignored") or []
        extra = f"\n来源参数：{'Flight Hub 目录 ' + c.get('folder','') if c['source']=='flighthub' else c.get('category','')}"
        self.detail.configure(text=(
            f"{c['name']}　（{'已启用' if c['enabled'] else '未启用'}）\n"
            f"当前记录版本：{cs.get('last_version') or '未记录'}　"
            f"上次检测：{cs.get('last_check_date') or '从未'}　"
            f"连续失败：{cs.get('fail_count') or 0}{extra}\n"
            f"忽略的版本：{('、'.join(ig) if ig else '无')}"))
        self.arch.set(c.get("arch") or "amd64")

    # ---- 更新线操作
    def toggle_row(self, event=None):
        cid = self.selected_id()
        c = self.row_by_id(cid)
        if c:
            self.set_enabled(c, not c["enabled"])
            self.refresh_tree()

    def toggle_sel(self):
        c = self.row_by_id(self.selected_id())
        if c:
            self.set_enabled(c, not c["enabled"])
            self.refresh_tree()

    def set_all(self, val):
        for c in self.rows:
            c["enabled"] = bool(val)
            c.pop("_preset", None)
        self.refresh_tree()
        self.set_status(f"已{'全部启用' if val else '全部停用'}（记得保存）")

    def set_enabled(self, c, val):
        c["enabled"] = bool(val)
        c.pop("_preset", None)
        self.set_status(f"{c['name']}：{'启用' if val else '停用'}（记得保存）")

    def set_arch(self, event=None):
        c = self.row_by_id(self.selected_id())
        if c:
            c["arch"] = self.arch.get()
            self.set_status(f"{c['name']} 架构改为 {c['arch']}（记得保存）")

    def add_custom(self):
        raw = (self.custom.get() or "").strip()
        if not raw:
            return
        if raw.startswith("http") or "category:" in raw:
            import re
            m = re.search(r"category:([a-z0-9\-]+)", raw)
            cat = m.group(1) if m else None
            if not cat:
                messagebox.showinfo(APP_TITLE, "网址里要带 category:xxx，或者直接填分类名，"
                                               "例如 w11-26h2")
                return
            new = ch_mod.uup_channel(cat)
            new["url"] = raw
        else:
            new = ch_mod.uup_channel(raw)
        new["enabled"] = True
        exist = self.row_by_id(new["id"])
        if exist:
            exist["enabled"] = True
            exist.pop("_preset", None)
            self.refresh_tree()
            self.tree.selection_set(new["id"])
            self.show_detail()
            self.set_status(f"{exist['name']} 本来就在列表里，已经帮你启用（记得保存）")
            return
        self.rows.append(new)
        self.custom.set("")
        self.refresh_tree()
        self.tree.selection_set(new["id"])
        self.show_detail()
        self.set_status(f"已添加并启用 {new['name']}，点「保存设置」生效")

    def discover(self):
        cfg = self._apply()
        if cfg is None:
            return
        self.cfg = cfg
        import source
        source.configure(cfg)
        self.busy_run(source.flighthub, self._discover_done,
                      msg="正在从 Flight Hub 抓频道列表（约 1-2 秒）…",
                      widgets=(self.btn_discover,))

    def _discover_done(self, data, err):
        if err or not data:
            self.set_status(f"抓取失败：{err or '没有解析到频道'}", "#c00")
            return
        added = []
        known = {c["id"] for c in self.rows}
        for folder, d in data.items():
            cid = "fh:" + folder
            note = f"{d['latest']['build']}（{d['latest'].get('date','')}）"
            if cid in known:
                continue
            c = ch_mod.fh_channel(folder)
            c["_preset"] = True
            added.append((c, note))
            self.rows.append(c)
        self.rows.sort(key=lambda c: (0 if c["source"] == "flighthub" else 1, c.get("name", "")))
        self.refresh_tree()
        msg = f"Flight Hub 现有 {len(data)} 条 Insider 线" + (
            f"，新发现 {len(added)} 条已加入列表" if added else "，没有新的")
        self.set_status(msg + "。想盯哪条就双击启用，然后保存。")
        for c, note in added[:8]:
            self.detail.configure(text=f"新发现：{c['name']} 最新构建 {note}")

    def check_selected(self):
        cid = self.selected_id()
        if not cid:
            return
        if not self.save(quiet=True):
            return
        self.run_check_live(["--only", cid], note=f"正在检测 {cid}")

    def run_check_live(self, extra=None, note="正在检测"):
        """跑一次检测，把过程实时显示在「状态与日志」页里，不弹控制台。"""
        args = ["--force", "--verbose"] + list(extra or [])
        cmd = check_cmd(args, console=False)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        self._live_lines = []
        if load_watch().get("online"):
            note += "；注意哨兵正在运行"

        def pump():
            proc = subprocess.Popen(cmd, cwd=BASE_DIR, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", env=env, creationflags=NO_WINDOW)
            for line in proc.stdout:
                self._live_lines.append(line.rstrip())
            proc.wait()
            return proc.returncode

        self.nb.select(self.log_tab)
        self.busy_run(pump, self._check_done, msg=f"{note}…（过程显示在日志里）",
                      widgets=(self.btn_check,))
        self.load_log()

    def _check_done(self, rc, err):
        if err:
            self.set_status(f"检测出错：{err}", "#c00")
        elif rc == 0:
            self.set_status("检测完成。上面是这次的完整过程；有更新的话通知已经发出去了。")
        else:
            self.set_status(f"检测结束但退出码是 {rc}，看上面的日志找原因", "#c00")
        self.refresh_status()

    def open_selected_report(self):
        c = self.row_by_id(self.selected_id())
        if not c:
            return
        cs = (self.state.get("channels") or {}).get(c["id"], {})
        rep = cs.get("last_report")
        if rep and os.path.exists(rep):
            spawn_view(rep)
        else:
            self.set_status("这条线还没有报告", "#c00")

    def open_selected_dir(self):
        c = self.row_by_id(self.selected_id())
        if c:
            os.startfile(reporter.chan_dir(self.cfg, c["id"]))      # noqa: S606

    def _mutate_state(self, fn, ok_msg):
        c = self.row_by_id(self.selected_id())
        if not c:
            return
        cs = channel_state(self.state, c["id"])
        fn(cs)
        from config import save_state
        save_state(self.state)
        self.show_detail()
        self.refresh_tree()
        self.set_status(ok_msg)

    def ignore_current(self):
        c = self.row_by_id(self.selected_id())
        cs = (self.state.get("channels") or {}).get(c["id"], {}) if c else {}
        ver = cs.get("last_version")
        if not ver:
            self.set_status("这条线还没有记录版本，没法忽略", "#c00")
            return

        def fn(s):
            s["ignored"] = sorted(set((s.get("ignored") or []) + [ver]))
        self._mutate_state(fn, f"已忽略 {ver}：以后不再为这个版本生成报告")

    def clear_ignored(self):
        self._mutate_state(lambda s: s.update(ignored=[]), "已清除忽略列表")

    # ======================================================== 检测与通知
    def _entry(self, p, row, label, key, width=None, hint="", col=1, show=None):
        ttk.Label(p, text=label).grid(row=row, column=0, sticky="w", pady=3)
        var = tk.StringVar(value=str(self.cfg.get(key, "")))
        e = ttk.Entry(p, textvariable=var, width=width or 40, show=show or "")
        e.grid(row=row, column=col, sticky="w", padx=6)
        self.v[key] = var
        if hint:
            ttk.Label(p, text=hint, foreground="#888").grid(row=row, column=col + 1,
                                                            sticky="w")
        return e

    def _check(self, p, row, label, key, hint=""):
        var = tk.BooleanVar(value=bool(self.cfg.get(key, True)))
        cb = ttk.Checkbutton(p, text=label, variable=var)
        cb.grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
        self.v[key] = var
        if hint:
            ttk.Label(p, text=hint, foreground="#888").grid(row=row, column=2, sticky="w")
        return cb

    def _build_detect(self, p):
        # ---------- 哨兵：每隔几分钟问一次官方看板 ----------
        self._check(p, 0, "开启即时提醒（哨兵常驻：登录后一直开着）", "watch_enabled")
        self._entry(p, 1, "每隔几分钟看一次", "watch_interval_minutes", 6,
                    "只问「官网变了没有」；没变化时传输 0 字节，也不调 AI")
        ttk.Label(p, text="官方看板一变，就抓发布说明 → 让 AI 写成中文报告 → 弹一条通知。\n"
                          "从「官网发布」到「你收到通知」通常 2～5 分钟"
                          "（其中 AI 总结约占 30～90 秒）。\n"
                          "没新版本时不发任何通知，日志也不刷。",
                  foreground="#888", justify="left").grid(row=2, column=1, columnspan=2,
                                                          sticky="w", pady=(0, 8))

        # ---------- 玩游戏时彻底静默 ----------
        self._check(p, 3, "玩游戏时彻底静默（不联网、不调 AI、不通知、不写盘）",
                    "game_mode_enabled")
        self._entry(p, 4, "游戏关闭后确认几秒才恢复", "game_exit_hold_seconds", 6,
                    "防止切进切出时通知乱弹；恢复后会立刻补查一次")
        ttk.Label(p, text="判定方式：有窗口铺满整块屏幕 + 没有标题栏 + 不是系统组件/叠加层。\n"
                          "（无边框全屏的游戏正好符合这个形状。）",
                  foreground="#888", justify="left").grid(row=5, column=1, columnspan=2,
                                                          sticky="w", pady=(0, 4))
        self.btn_quiet = ttk.Button(p, text="现在静默 2 小时（手动）",
                                    command=self.quiet_now)
        self.btn_quiet.grid(row=6, column=1, sticky="w", pady=(0, 2))
        self.btn_ignore = ttk.Button(p, text="把当前前台程序加进忽略名单",
                                     command=self.ignore_foreground)
        self.btn_ignore.grid(row=6, column=2, sticky="w", padx=6, pady=(0, 2))
        self.quiet_lbl = ttk.Label(p, text="", foreground="#333", justify="left")
        self.quiet_lbl.grid(row=7, column=1, columnspan=2, sticky="w", pady=(0, 6))

        ttk.Separator(p, orient="horizontal").grid(row=8, column=0, columnspan=3,
                                                   sticky="ew", pady=8)
        # ---------- 通知 ----------
        self._check(p, 9, "发现新版本时发 Windows 通知", "notify")
        self._check(p, 10, "多条线同时更新时合并成一条通知", "merge_notifications")
        self._entry(p, 11, "连续失败几次后通知我", "notify_on_error_after", 6,
                    "0 = 出错也不通知")
        self._entry(p, 12, "静默时段", "quiet_hours", 16,
                    "例如 23:00-07:00：这期间先攒着不出声，出了时段再补发；留空则不限")
        ttk.Separator(p, orient="horizontal").grid(row=13, column=0, columnspan=3,
                                                   sticky="ew", pady=8)
        ttk.Label(p, text="报告详细程度").grid(row=14, column=0, sticky="w", pady=3)
        self.detail_var = tk.StringVar(value=self.cfg.get("detail") or "标准")
        ttk.Combobox(p, textvariable=self.detail_var, state="readonly", width=8,
                     values=list(deepseek_api.DETAIL_SPEC.keys())
                     ).grid(row=14, column=1, sticky="w", padx=6)
        self._check(p, 15, "报告末尾附上官方原文全文", "include_official_text")
        self._entry(p, 16, "每个频道最多保留报告数", "keep_reports", 8)
        self._check(p, 17, "自动收录 Flight Hub 上新出现的更新线（默认不启用）",
                    "auto_discover_channels")

    def quiet_now(self):
        """手动静默：游戏识别不出来时兜底用（点一下 = 静默 2 小时，再点 = 取消）。"""
        if not self.save(quiet=True):
            return
        cur = (self.cfg.get("silent_until") or "").strip()
        active = False
        if cur:
            try:
                active = dt.datetime.fromisoformat(cur) > dt.datetime.now()
            except Exception:
                active = False
        if active:
            self.cfg["silent_until"] = ""
            save_config(self.cfg)
            self.set_status("已取消手动静默，哨兵马上恢复检测。")
        else:
            until = dt.datetime.now() + dt.timedelta(hours=2)
            self.cfg["silent_until"] = until.isoformat(timespec="seconds")
            save_config(self.cfg)
            self.set_status(f"已静默到 {until:%H:%M}（哨兵最多 5 秒后生效），"
                            f"到点自动恢复正常。")
        self.refresh_status()

    def ignore_foreground(self):
        """误判兜底：把某个程序加进忽略名单，以后不再因为它进静默。"""
        try:
            import gamesense
            exe = gamesense.current_foreground()
        except Exception as e:
            self.set_status(f"取不到当前前台程序：{e}", "#c00")
            return
        if not exe:
            self.set_status("取不到当前前台程序", "#c00")
            return
        name = os.path.basename(exe)
        if not self.save(quiet=True):
            return
        lst = list(self.cfg.get("game_ignore") or [])
        if name.lower() in [str(x).lower() for x in lst]:
            self.set_status(f"{name} 已经在忽略名单里了")
            return
        lst.append(name)
        self.cfg["game_ignore"] = lst
        save_config(self.cfg)
        self.set_status(f"已把 {name} 加进忽略名单，以后不会因为它进静默模式。")
        self.refresh_status()

    # ======================================================== API
    def _build_api(self, p):
        self._entry(p, 0, "API 地址", "api_base")
        self._entry(p, 1, "模型名称", "model")
        e = self._entry(p, 2, "API Key", "api_key", 44,
                        "直接在框里粘贴你的 Key，保存在本机 config.json 里", show="•")
        self.show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(p, text="显示", variable=self.show_key,
                        command=lambda: e.config(show="" if self.show_key.get() else "•")
                        ).grid(row=2, column=3, sticky="w", padx=4)
        self._check(p, 3, "关闭思考模式（thinking.type = disabled）", "disable_thinking")
        self._entry(p, 4, "max_tokens", "max_tokens", 8)
        self._entry(p, 5, "temperature", "temperature", 8)
        self._entry(p, 6, "请求超时（秒）", "request_timeout", 8)
        self._entry(p, 7, "网络重试次数", "retries", 6)
        self._entry(p, 8, "并发抓取线程数", "max_workers", 6,
                    "同时抓几条更新线；1 = 串行。只有多条 uupdump 线时才有区别")
        self._entry(p, 9, "代理（可选）", "proxy", 30, "例如 http://127.0.0.1:7897；留空直连")
        self._entry(p, 10, "喂给模型的官网原文上限（字符）", "max_context_chars", 10)
        self.btn_apitest = ttk.Button(p, text="测试 Key 与模型", command=self.test_api)
        self.btn_apitest.grid(row=11, column=0, columnspan=2, sticky="w", pady=(10, 0))

    # ======================================================== 计划任务
    def _build_task(self, p):
        ttk.Label(p, text="计划任务名").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Label(p, text=TASK_NAME).grid(row=0, column=1, sticky="w", padx=6)
        self.task_lbl = ttk.Label(p, text="", foreground="#333", justify="left")
        self.task_lbl.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 10))
        self.btn_task_install = ttk.Button(p, text="安装 / 更新计划任务",
                                           command=self.install_task)
        self.btn_task_install.grid(row=2, column=0, sticky="w")
        self.btn_task_remove = ttk.Button(p, text="删除计划任务",
                                          command=self.remove_task)
        self.btn_task_remove.grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(p, text="（注册计划任务要管理员权限，会弹一次 UAC）",
                  foreground="#888").grid(row=2, column=2, sticky="w")
        ttk.Label(p, text=("这个任务干什么：登录时悄悄启动哨兵，一直开着；每几分钟问一次官方\n"
                           "看板，只有真出了新版本才通知你。任务设成「不限时 + 崩了自动重启」，\n"
                           "不会被系统定时杀掉。安装时会顺手把旧的每日任务卸掉（已不需要）。"),
                  foreground="#333", justify="left").grid(row=3, column=0, columnspan=4,
                                                          sticky="w", pady=(8, 2))
        self.logon_lbl = ttk.Label(p, text="", foreground="#333", justify="left")
        self.logon_lbl.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(p, text="刷新哨兵状态", command=self.refresh_logon_hint
                   ).grid(row=5, column=0, sticky="w", pady=6)
        ttk.Button(p, text="立刻静默跑一次（手动检测）",
                   command=lambda: self.run_silent(["--force"])
                   ).grid(row=5, column=1, columnspan=2, sticky="w")
        self.btn_startup = ttk.Button(p, text="装/卸 登录自启（免管理员备用）",
                                      command=self.toggle_startup)
        self.btn_startup.grid(row=6, column=0, columnspan=2, sticky="w")
        self.startup_lbl = ttk.Label(p, text="", foreground="#333")
        self.startup_lbl.grid(row=7, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Separator(p, orient="horizontal").grid(row=8, column=0, columnspan=4,
                                                   sticky="ew", pady=10)
        ttk.Label(p, text="程序目录").grid(row=9, column=0, sticky="w")
        ttk.Label(p, text=BASE_DIR, foreground="#666").grid(row=9, column=1, columnspan=3,
                                                            sticky="w")
        ttk.Label(p, text="运行方式").grid(row=10, column=0, sticky="w")
        _exe, _args = watch_target()
        ttk.Label(p, text=f"{_exe} {_args}", foreground="#666").grid(
            row=10, column=1, columnspan=3, sticky="w")
        ttk.Button(p, text="注册通知 / 协议", command=self.reg).grid(row=11, column=0,
                                                                    sticky="w", pady=8)
        ttk.Button(p, text="在桌面放快捷方式",
                   command=lambda: self.make_shortcut("desktop")).grid(row=11, column=1,
                                                                       sticky="w")
        ttk.Button(p, text="放进开始菜单",
                   command=lambda: self.make_shortcut("startmenu")).grid(row=11, column=2,
                                                                         sticky="w")
        self.refresh_logon_hint()

    # ---- 哨兵状态
    def refresh_logon_hint(self):
        """在「计划任务」页显示哨兵现在是死是活。"""
        try:
            w = load_watch()
            if w.get("online"):
                mode = {"game": "游戏静默中", "paused": "已暂停（没启用）"}.get(
                    w.get("mode"), "正常")
                txt = (f"哨兵：运行中（进程 {w.get('pid')}）　状态：{mode}\n"
                       f"上次问官方：{w.get('last_check') or '还没问过'}"
                       f"　上次有新版本：{w.get('last_change') or '还没有过'}"
                       f"　间隔：每 {w.get('interval_minutes')} 分钟"
                       f"　累计检测 {w.get('checks')} 次")
                if w.get("game_exe"):
                    txt += f"\n因为检测到全屏程序而静默：{w.get('game_exe')}"
                if w.get("manual_until"):
                    txt += f"\n手动静默到：{w.get('manual_until')}"
                if w.get("last_result"):
                    txt += f"\n最近结果：{w.get('last_result')}"
            else:
                txt = ("哨兵：没有在运行。\n"
                       "刚开机的话等几秒再点「刷新哨兵状态」；一直是这样就重新装一次计划任务，"
                       "或改用下面的「登录自启」。")
            self.logon_lbl.configure(text=txt)
        except Exception:
            pass

    # ======================================================== 日志
    def _build_log(self, p):
        top = ttk.Frame(p)
        top.pack(fill="x")
        ttk.Button(top, text="刷新", command=self.refresh_status).pack(side="left")
        ttk.Button(top, text="打开日志文件",
                   command=lambda: os.startfile(LOG_PATH if os.path.exists(LOG_PATH)
                                                else LOG_DIR)).pack(side="left", padx=6)
        ttk.Button(top, text="清空日志", command=self.clear_log).pack(side="left")
        ttk.Button(top, text="打开总览页", command=self.open_index).pack(side="left", padx=6)
        self.summary_lbl = ttk.Label(p, text="", justify="left")
        self.summary_lbl.pack(anchor="w", pady=(8, 6))
        self.logbox = tk.Text(p, height=20, wrap="none", font=("Consolas", 9))
        sb = ttk.Scrollbar(p, orient="vertical", command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.logbox.pack(fill="both", expand=True)
        self.logbox.configure(state="disabled")

    def load_log(self):
        try:
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()[-60_000:]
        except Exception:
            txt = "(还没有日志)"
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.insert("1.0", txt)
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def clear_log(self):
        try:
            open(LOG_PATH, "w", encoding="utf-8").close()
        except Exception as e:
            self.set_status(f"清空失败：{e}", "#c00")
        self.load_log()

    def make_shortcut(self, where="desktop"):
        """在桌面 / 开始菜单放一个快捷方式，直接打开这个程序。"""
        exe = sys.executable if FROZEN else pythonw()
        targ = "" if FROZEN else f'"{CHECKER}" gui'
        name = "win升级报告.lnk"
        if where == "desktop":
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
        with open(ps1, "w", encoding="utf-8-sig") as f:
            f.write(body)
        ps_run(["-File", ps1], timeout=60)
        if os.path.exists(link):
            self.set_status(f"快捷方式已创建：{link}")
        else:
            self.set_status("快捷方式创建失败，看日志", "#c00")

    def open_app_folder(self):
        os.startfile(os.path.dirname(os.path.abspath(sys.executable))
                     if FROZEN else BASE_DIR)                    # noqa: S606

    def open_index(self):
        spawn_view("index")

    # ======================================================== 通用动作
    def _apply(self):
        cfg = dict(self.cfg)
        for k, var in self.v.items():
            val = var.get()
            if isinstance(var, tk.BooleanVar):
                cfg[k] = bool(val)
            elif k in ("max_tokens", "request_timeout", "retries", "max_workers",
                       "max_context_chars", "interval_days", "keep_reports",
                       "notify_on_error_after", "watch_interval_minutes",
                       "game_exit_hold_seconds", "tick_seconds"):
                try:
                    cfg[k] = int(str(val).strip() or 0)
                except ValueError:
                    messagebox.showerror(APP_TITLE, f"{k} 需要是整数：{val}")
                    return None
            elif k == "temperature":
                try:
                    cfg[k] = float(str(val).strip())
                except ValueError:
                    messagebox.showerror(APP_TITLE, f"temperature 需要是数字：{val}")
                    return None
            else:
                cfg[k] = str(val).strip()
        cfg["detail"] = self.detail_var.get()
        cfg["schema"] = 3

        # 旧版的「每天检测时间」现在只留给手动 --check 用，界面上不再暴露。
        # 这里顺手把格式收拾干净；万一存的是坏值就退回默认，不能因为它挡住保存。
        t = (cfg.get("check_time") or "").strip()
        try:
            hh, mm = t.split(":")
            dt.time(int(hh), int(mm))
            cfg["check_time"] = f"{int(hh):02d}:{int(mm):02d}"
        except Exception:
            cfg["check_time"] = "12:00"
        qh = (cfg.get("quiet_hours") or "").strip()
        if qh:
            try:
                a, b = qh.split("-")
                dt.time(*[int(x) for x in a.strip().split(":")])
                dt.time(*[int(x) for x in b.strip().split(":")])
                cfg["quiet_hours"] = f"{a.strip()}-{b.strip()}"
            except Exception:
                messagebox.showerror(APP_TITLE, "静默时段格式应为 HH:MM-HH:MM，例如 23:00-07:00")
                return None
        cfg["interval_days"] = max(1, int(cfg.get("interval_days") or 1))
        cfg["max_workers"] = max(1, min(16, int(cfg.get("max_workers") or 4)))
        # 哨兵的节奏：太小会给微软服务器添麻烦，太大又失去「马上知道」的意义
        cfg["watch_interval_minutes"] = max(
            1, min(1440, int(cfg.get("watch_interval_minutes") or 5)))
        cfg["game_exit_hold_seconds"] = max(
            0, min(3600, int(cfg.get("game_exit_hold_seconds") or 60)))
        cfg["tick_seconds"] = max(2, min(60, int(cfg.get("tick_seconds") or 5)))
        cfg["game_ignore"] = [str(x).strip() for x in (cfg.get("game_ignore") or [])
                              if str(x).strip()]

        # 只保留：启用的线 + 本来就配置过的线
        was = {c["id"] for c in self.cfg.get("channels", [])}
        keep = [{"id": c["id"], "source": c["source"], "name": c.get("name"),
                 "enabled": bool(c["enabled"]), "arch": c.get("arch") or "amd64"}
                | ({"folder": c["folder"]} if c["source"] == "flighthub"
                   else {"category": c["category"], "url": c.get("url")})
                for c in self.rows if c["enabled"] or c["id"] in was]
        cfg["channels"] = [ch_mod.norm_channel(c) for c in keep]
        self.cfg = cfg
        return cfg

    def save(self, quiet=False):
        cfg = self._apply()
        if cfg is None:
            return False
        save_config(cfg)
        self.reload_channels()
        if not quiet:
            n = sum(1 for c in self.rows if c["enabled"])
            has_task = ("哨兵任务" in (self._task_text or "")
                        and "未安装" not in (self._task_text or ""))
            self.set_status(f"已保存：监控 {n} 条更新线。"
                            + ("哨兵会马上重读设置，间隔、游戏静默这些改动立刻生效，"
                               "不用重装计划任务。"
                               if has_task else
                               "还没装计划任务，去「计划任务」页装一个。"))
        self.refresh_status()
        return True

    def set_status(self, text, color="#0a6cff"):
        self.status.configure(text=text, foreground=color)

    def run_silent(self, args=None):
        """手动跑一次检测。

        哨兵在跑的时候就留言让它自己去查 —— 这样 state.json 只有一个写入者，
        不会两个进程抢着写、把对方的记录覆盖掉（那会导致重复通知）。
        """
        w = load_watch()
        if w.get("online"):
            request_check_now()
            if w.get("mode") == "game":
                self.set_status("哨兵正在游戏静默中，你的请求已经记下；"
                                "游戏一关就立刻检测。")
            else:
                self.set_status("已通知哨兵立刻检测（最多 5 秒后开始），"
                                "结果和通知都由它来出，看「状态与日志」页。")
            return
        run_background(args or ["--force"])
        self.set_status("哨兵没在运行，已在后台单独跑了一次，"
                        "完事看「状态与日志」页和通知。")

    def test_toast(self):
        notify.register_app(self.cfg.get("app_id") or "WinUpdReport.App")
        self.busy_run(
            lambda: notify.show("win升级报告 · 测试通知",
                                "看到这条说明通知通道正常，点一下试试能不能打开总览页。",
                                arg1="index"),
            lambda r, e: self.set_status(
                "测试通知已发送（点它试试能不能打开总览页）" if r and r[0]
                else f"发送失败：{e or (r[1] if r else '')}", "#0a6cff" if r and r[0] else "#c00"),
            msg="正在发通知…", widgets=(self.btn_toast, self.btn_close))

    def reg(self):
        ok = notify.register_app(self.cfg.get("app_id") or "WinUpdReport.App")
        self.set_status("已写入注册表：通知来源 AUMID + winupdrept: 协议" if ok
                        else "注册失败", "#0a6cff" if ok else "#c00")

    def test_api(self):
        if not self.save(quiet=True):
            return
        key = resolve_api_key(self.cfg)
        if not key:
            self.set_status("还没填 API Key：在上面「API Key」框里粘贴一个再试", "#c00")
            return
        import deepseek_api

        def call():
            return deepseek_api.summarize(self.cfg, key, "只回复两个字：正常", timeout=60)

        def done(out, err):
            if err:
                self.set_status(f"API 测试失败：{err}", "#c00")
            else:
                self.set_status(f"API 可用：模型 {self.cfg['model']} 回复「{(out or '')[:30]}」")
        self.busy_run(call, done, msg=f"正在测试 {self.cfg['model']}（{mask_key(key)}）…",
                      widgets=(self.btn_apitest,))

    def install_task(self):
        if not self.save(quiet=True):
            return
        notify.register_app(self.cfg.get("app_id") or "WinUpdReport.App")
        self.busy_run(
            # 装哨兵任务，同时把旧的每日任务卸掉（哨兵已经取代它了）
            lambda: ps_task_elevated("install", mode="watch",
                                     also_remove=DAILY_TASK_NAME),
            self._install_done,
            msg="正在申请管理员权限（弹出 UAC 请点「是」，界面会一直等到你点完）…",
            widgets=(self.btn_task_install, self.btn_task_remove))

    def _install_done(self, res, err):
        if err:
            self.set_status(f"安装出错：{err}", "#c00")
        else:
            ok, msg = res
            if ok:
                self.set_status(
                    f"哨兵任务已安装：登录时启动，每 "
                    f"{self.cfg.get('watch_interval_minutes') or 5} 分钟看一次官方看板，"
                    f"不限时、崩了会自动重启；旧的每日任务已卸掉。")
            elif "取消" in msg or "canceled" in msg.lower():
                self.set_status("UAC 被取消。可以改用「装/卸 登录自启」这个免管理员方案。",
                                "#c00")
            else:
                self.set_status("安装失败：" + (msg or "未知原因")[:260], "#c00")
        self.refresh_status()
        self.refresh_task_info_async()

    def remove_task(self):
        self.busy_run(lambda: ps_task_elevated("remove", mode="watch",
                                               also_remove=DAILY_TASK_NAME),
                      self._remove_done,
                      msg="正在申请管理员权限删除计划任务…",
                      widgets=(self.btn_task_install, self.btn_task_remove))

    def _remove_done(self, res, err):
        if err:
            self.set_status(f"删除出错：{err}", "#c00")
        else:
            ok, msg = res
            self.set_status("计划任务已删除" if ok else f"删除失败：{msg[:200]}",
                            "#0a6cff" if ok else "#c00")
        self.refresh_status()
        self.refresh_task_info_async()

    def toggle_startup(self):
        self.busy_run(toggle_startup, self._startup_done, msg="正在设置登录自启…",
                      widgets=(self.btn_startup,))

    def _startup_done(self, res, err):
        if err:
            self.set_status(f"设置出错：{err}", "#c00")
        else:
            ok, msg = res
            self.set_status(msg, "#0a6cff" if ok else "#c00")
        self.refresh_status()

    def refresh_status(self):
        """只读本地状态文件，不碰 PowerShell、不读日志，所以可以随时调。"""
        st = load_state()
        self.state = st
        lines = []
        for c in self.cfg.get("channels", []):
            cs = (st.get("channels") or {}).get(c["id"], {})
            lines.append(f"　{'☑' if c['enabled'] else '☐'} {c['name']}："
                         f"{cs.get('last_version') or '未记录'}（检测 {cs.get('last_check_date') or '从未'}）")
        pend = len(st.get("pending_notify") or [])
        logon_date = st.get("last_logon_date") or ""

        # 哨兵现在怎么样（有没有在跑、是不是因为游戏静默了）
        w = load_watch()
        if w.get("online"):
            mode = {"game": "游戏静默中", "paused": "已暂停（没启用）"}.get(
                w.get("mode"), "正常")
            watch_txt = (f"哨兵：运行中　状态：{mode}　"
                         f"上次问官方：{w.get('last_check') or '还没问过'}　"
                         f"每 {w.get('interval_minutes')} 分钟一次")
        else:
            watch_txt = ("哨兵：没有在运行　→ 到「计划任务」页装一次，"
                         "或者看那边写的排查办法")

        sumtxt = (watch_txt + "\n"
                  + "上次运行：" + (st.get("last_run_date") or "从未")
                  + (f"　开机补跑：{logon_date}" if logon_date else "")
                  + f"　待补发通知：{pend} 条　"
                  + ("最近错误：" + (st.get("last_error") or "无")[:160]
                     if st.get("last_error") else "最近错误：无")
                  + "\n各条线状态：\n" + "\n".join(lines))
        self.summary_lbl.configure(text=sumtxt)

        # 手动静默 / 忽略名单
        su = (self.cfg.get("silent_until") or "").strip()
        active = False
        if su:
            try:
                active = dt.datetime.fromisoformat(su) > dt.datetime.now()
            except Exception:
                active = False
        ign = self.cfg.get("game_ignore") or []
        try:
            self.quiet_lbl.configure(
                text=((f"手动静默到 {su[:16].replace('T', ' ')}" if active
                       else "没有手动静默")
                      + f"　忽略名单 {len(ign)} 个" + (f"（{'、'.join(ign[:4])}）"
                                                      if ign else "")
                      + "　误判时点「把当前前台程序加进忽略名单」"))
            self.btn_quiet.configure(text="取消手动静默" if active
                                     else "现在静默 2 小时（手动）")
        except Exception:
            pass

        self.task_lbl.configure(text=self._task_text)
        self.refresh_logon_hint()
        try:
            self.startup_lbl.configure(
                text="登录自启：" + ("已开启" if os.path.exists(startup_link()) else "未开启"))
        except Exception:
            pass
        try:
            if self.nb.nametowidget(self.nb.select()) is self.log_tab:
                self.load_log()
        except Exception:
            pass


def main():
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.25)
    except Exception:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
