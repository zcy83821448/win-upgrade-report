# -*- coding: utf-8 -*-
"""体检与自动修复：让工具自己发现、自己修，然后用人话告诉你。

为什么要有这个模块
------------------
前几轮踩的坑，用户看到的是一句英文报错：
    Failed to start embedded python interpreter!
    Failed to remove temporary directory: ...\\_MEI306122
这些既看不懂、也没法自己处理 —— 那不叫工具，那叫把内部实现漏给了用户。
成熟一点的做法是：

    1. **能自己修的，直接修，别问。**（后台没跑就拉起来；开机自启没了就装回去；
       自己以前留下的垃圾临时目录就清掉）
    2. **修不了的，用人话说清「哪里不对 + 你点哪里」**，不出现术语。
    3. 每次检查都产出一份短报告，界面/托盘直接显示。

用法
----
    python selfcheck.py            命令行跑一次（会真的尝试修复），打印报告

返回结构
--------
    run() -> [{"name": 项目, "status": "ok|fixed|warn|fail", "msg": 人话说明}]
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (load_config, save_config, load_watch, patch_config,   # noqa: E402
                    request_exit, take_exit_request, child_env, is_frozen,
                    BASE_DIR, LOG_DIR, REPORT_DIR, CONFIG_PATH)
import channels as ch_mod                                                 # noqa: E402

NO_WINDOW = 0x08000000


# --------------------------------------------------------- 启停后台（给界面和体检共用）

def pythonw_exe():
    """拿 pythonw.exe（源码运行时用它才不弹黑窗）。"""
    exe = sys.executable or ""
    if exe.lower().endswith("python.exe"):
        cand = exe[:-len("python.exe")] + "pythonw.exe"
        return cand if os.path.exists(cand) else exe
    return exe


def sentinel_command():
    if is_frozen():
        return [sys.executable, "--watch"]
    return [pythonw_exe(), os.path.join(BASE_DIR, "watch.py")]


def online():
    """后台哨兵在不在跑（看它写的心跳）。"""
    try:
        return bool(load_watch().get("online"))
    except Exception:
        return False


def start_sentinel():
    """把后台哨兵拉起来。返回 (成功?, 说明)。

    注意 env=child_env()：不摘掉 _MEIPASS2 的话，这个哨兵会住进调用者
    （比如设置界面）自己的临时解包目录，调用者一退出就删不掉那个目录。
    """
    patch_config(watch_enabled=True)
    if online():
        return True, "后台已经在跑了"
    # ★ 先把可能残留的「退出请求」吃掉。这是实测踩到的坑：
    #   先 request_exit() 停掉旧哨兵（旧的可能已经死了，没人消费这条留言），
    #   再启动新的 —— 新的启动瞬间就读到那条旧留言，直接自杀。
    take_exit_request()
    try:
        subprocess.Popen(sentinel_command(), cwd=BASE_DIR,
                         creationflags=NO_WINDOW, env=child_env())
    except Exception as e:
        return False, f"启动失败：{type(e).__name__}"
    return True, "已启动"


def stop_sentinel():
    """停掉后台哨兵。"""
    patch_config(watch_enabled=False)
    request_exit()


# ------------------------------------------------------------------ 各项检查

def _can_write(path):
    try:
        os.makedirs(path, exist_ok=True)
        p = os.path.join(path, "_wtest.tmp")
        with open(p, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(p)
        return True
    except Exception:
        return False


def _our_temp_dirs():
    """找出「我们自己以前解包剩下的临时目录」。

    靠特征文件认（包里一定有 toast.ps1 / task.ps1），这样绝不会误删别人的东西；
    当前进程自己正在用的那个也排除掉。
    """
    base = os.environ.get("TEMP") or tempfile.gettempdir()
    mine = os.path.abspath(getattr(sys, "_MEIPASS", "") or "")
    out = []
    try:
        for name in os.listdir(base):
            if not name.startswith("_MEI"):
                continue
            p = os.path.join(base, name)
            if not os.path.isdir(p) or os.path.abspath(p) == mine:
                continue
            if any(os.path.exists(os.path.join(p, f))
                   for f in ("toast.ps1", "task.ps1", "icon.ico")):
                out.append(p)
    except Exception:
        pass
    return out


def _autostart_state():
    """开机自启装了没有。返回 (有没有装, 装的哪种)。"""
    # 延迟导入 gui：它反过来要导入本模块，模块级互相 import 会成环。
    try:
        import gui
        if os.path.exists(gui.startup_link()):
            return True, "登录自启"
    except Exception:
        pass
    try:
        import gui
        txt = gui.task_info() or ""
        if "未安装" not in txt:
            return True, "计划任务"
    except Exception:
        pass
    return False, ""


def check_all(fix=True):
    """跑一遍体检。fix=True 时能修的当场修掉。

    返回 [{"name","status","msg"}]，status: ok / fixed / warn / fail
    """
    cfg = load_config()
    res = []

    def add(name, status, msg):
        res.append({"name": name, "status": status, "msg": msg})

    # 1) 数据目录能不能写 —— 写不进去后面全是白搭
    if _can_write(LOG_DIR) and _can_write(REPORT_DIR):
        add("存报告的位置", "ok", "能正常读写")
    else:
        add("存报告的位置", "fail",
            f"写不进去：{BASE_DIR}。检查一下这个文件夹的权限，或者杀软是不是拦了。")

    # 2) AI 的 Key
    if (cfg.get("api_key") or "").strip():
        add("AI 的 Key", "ok", "已填写")
    else:
        add("AI 的 Key", "warn",
            "还没填。去「设置」页填一个，不填的话发现新版本也写不出中文报告。")

    # 3) 有没有勾更新线
    names = [c["name"] for c in cfg.get("channels", []) if c["enabled"]]
    if names:
        add("要盯的更新线", "ok", "、".join(names))
    else:
        add("要盯的更新线", "warn", "一条都没勾。去「更新线」页勾一条，它才有东西可查。")

    # 4) 后台在不在跑
    want = bool(cfg.get("watch_enabled", True))
    running = online()
    if running:
        add("后台监控", "ok", "正在运行")
    elif not want:
        add("后台监控", "ok", "现在是关着的（你之前关掉过）。要开就点「开启后台监控」。")
    elif fix:
        ok, msg = start_sentinel()
        if ok:
            # 单文件版要解包、启动后还要先跑一次检测，所以最多等 20 秒再看
            for _ in range(10):
                time.sleep(2)
                if online():
                    break
            if online():
                add("后台监控", "fixed", "本来没在跑，我已经帮你启动了")
            else:
                add("后台监控", "warn",
                    "试着启动了，但还没看到它上线。过一会儿再体检一次看看。")
        else:
            add("后台监控", "fail", msg)
    else:
        add("后台监控", "warn", "没有在运行")

    # 5) 托盘图标（只关心「在跑但没图标」这种半死不活的状态）
    w = load_watch()
    if online() and not w.get("tray"):
        add("右下角托盘图标", "warn",
            "后台在跑但没挂上图标。可以在托盘里「完全关闭后台监控」再点「开启后台监控」重来一次。")
    elif online():
        add("右下角托盘图标", "ok", "已经挂上了")
    else:
        add("右下角托盘图标", "ok", "后台没在跑，所以暂时没有图标（这是正常的）")

    # 6) 开机自启
    if not want:
        add("开机自动启动", "ok", "后台是关着的，就不管这个了")
    else:
        has, how = _autostart_state()
        if has:
            add("开机自动启动", "ok", f"已设置（{how}）")
        elif fix:
            try:
                import gui
                gui.install_startup()
                has2, how2 = _autostart_state()
                if has2:
                    add("开机自动启动", "fixed",
                        "本来没设，我已经帮你设好了（往「启动」文件夹放了个快捷方式，不用管理员权限）")
                else:
                    add("开机自动启动", "warn",
                        "想帮你设但没成功。到「开机自启」页点一下「一键设置开机自启」。")
            except Exception as e:
                add("开机自动启动", "warn",
                    f"想帮你设但出错了（{type(e).__name__}）。到「开机自启」页手动点一下。")
        else:
            add("开机自动启动", "warn", "还没设置")

    # 7) 自己以前留下的垃圾临时目录
    stale = _our_temp_dirs()
    if not stale:
        add("临时文件残留", "ok", "没有残留")
    elif fix:
        gone = 0
        for p in stale:
            try:
                shutil.rmtree(p, ignore_errors=False)
                gone += 1
            except Exception:
                pass                       # 还在被某个进程用着，删不掉就算了
        if gone == len(stale):
            add("临时文件残留", "fixed", f"清掉了 {gone} 个以前没删干净的临时目录")
        elif gone:
            add("临时文件残留", "fixed",
                f"清掉了 {gone} 个；还有 {len(stale) - gone} 个正在被使用，先留着")
        else:
            add("临时文件残留", "ok", "有残留但都在使用中，不用管")
    else:
        add("临时文件残留", "warn", f"发现 {len(stale)} 个残留目录")

    # 8) 能不能连上微软官网（真发一次请求，没变化时是 0 字节，很便宜）
    try:
        import source
        source.configure(cfg)
        st, _ = source.Conditional().get(ch_mod.FLIGHTHUB_URL, timeout=20)
        add("连微软官网", "ok", f"能连上（{st}）")
    except Exception as e:
        hint = ""
        if not (cfg.get("proxy") or "").strip():
            hint = "　如果你平时要挂代理上网，「设置」页的高级选项里可以填代理。"
        add("连微软官网", "warn",
            f"连不上（{type(e).__name__}）。{hint}")

    return res


def summary(results):
    """把报告压成一句人话。"""
    bad = [r for r in results if r["status"] in ("warn", "fail")]
    fixed = [r for r in results if r["status"] == "fixed"]
    parts = [f"检查了 {len(results)} 项"]
    parts.append(f"自动修好 {len(fixed)} 项" if fixed else "不用修")
    if bad:
        parts.append(f"有 {len(bad)} 项需要你看一眼")
    else:
        parts.append("全部正常")
    return "，".join(parts)


def report_lines(results):
    """给人看的报告正文。"""
    mark = {"ok": "✓", "fixed": "✔", "warn": "!", "fail": "×"}
    lines = []
    for r in results:
        lines.append(f"{mark.get(r['status'], '?')} {r['name']}：{r['msg']}")
    return lines


if __name__ == "__main__":
    for it in check_all(fix=True):
        print(f"[{it['status']:5s}] {it['name']}：{it['msg']}")
    print()
    print(summary(check_all(fix=False)))
