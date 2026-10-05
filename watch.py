# -*- coding: utf-8 -*-
"""哨兵：常驻后台的小程序，每隔几分钟问一次官方看板「变了没有」。

它在整个工具里的位置
--------------------
    登录时由计划任务悄悄启动（没有窗口、不打扰）
    └─ 同时挂一个**系统托盘图标**（用户能一眼看到它在后台活着）
    ├─ 每 5 秒醒一次（很便宜，实测一次判定约 0.26 毫秒）
    │    ├─ 看用户是不是在玩全屏游戏
    │    ├─ 看看设置界面/托盘有没有要求「立刻检测」或「完全关闭」
    │    └─ 刷新托盘图标的悬停提示
    ├─ 到点（默认 5 分钟）就问 Flight Hub「变了没有」
    │    ├─ 没变：服务器回 304，传输 0 字节 → 接着睡，什么都不做
    │    └─ 变了 → 交给 checker.run_check()：
    │             抓官方发布说明 → AI 总结成中文报告 → 存文件 → 发唯一一条通知
    └─ 托盘右键菜单：打开设置 / 立刻检测 / 静默 2 小时 / 看报告 / 看日志 / 完全关闭

★ 托盘图标为什么挂在哨兵身上而不是设置界面里
    设置界面是个开完就关的窗口。图标挂它身上的话，用户一关窗口图标就没了，
    那正好回答不了「它到底还在不在后台跑」。挂在哨兵上 → 图标在 = 它在跑。

三条硬规矩（都是明确要求的）
--------------------------
1. **AI 只在确认出现新版本之后才被调用，而且同一个版本只调一次。**
   判断有没有新版本、比构建号、解析页面，全是普通代码；没新版本时一次 AI 都不调。
2. **没新版本时不发任何通知**，日志也不刷（安静模式）。
3. **玩游戏时彻底什么都不干**，连网页都不爬；游戏一关，立刻补查一次。

用法:
    pythonw watch.py            常驻（计划任务 / 登录自启用这个）
    python  watch.py --once     只跑一轮就退出（排查用）
    python  watch.py --status   看一眼哨兵现在活着没有
    python  watch.py --no-tray  不挂托盘图标（排查图标相关问题时用）
    python  watch.py --verbose  过程打印到控制台
"""
import os
import sys
import time
import ctypes
import subprocess
import datetime as dt
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (load_config, load_state, load_watch, save_watch,   # noqa: E402
                    take_check_now, take_exit_request, request_check_now,
                    request_exit, patch_config, ensure_dirs, resource_path,
                    child_env, BASE_DIR, LOG_DIR, is_frozen)
import source                                                         # noqa: E402
import gamesense                                                      # noqa: E402
import checker                                                        # noqa: E402
import tray as tray_mod                                               # noqa: E402

VERBOSE = "--verbose" in sys.argv
ONCE = "--once" in sys.argv
NO_TRAY = "--no-tray" in sys.argv
MUTEX_NAME = "Local\\WinUpdReportWatch"
ERROR_ALREADY_EXISTS = 183
HEARTBEAT_SECONDS = 30      # 心跳写这么勤就够了，不必每 5 秒写一次盘
FLUSH_SECONDS = 60          # 隔多久看一眼有没有攒着的通知要补发
NO_WINDOW = 0x08000000

# 托盘线程读这个字典来决定菜单文字和悬停提示。主循环每一轮整体更新，
# 读的一方拿到的要么是旧的要么是新的，不会读到写了一半的状态。
STATE = {"mode": "normal", "last_check": "", "game_exe": "",
         "interval": 5, "silent": False}


def say(msg, level="INFO"):
    """写进和检测同一份日志，前缀标出是哨兵说的。"""
    try:
        checker.log(f"[哨兵] {msg}", level)
    except Exception:
        pass
    if VERBOSE:
        try:
            print(f"[哨兵] {msg}", flush=True)
        except Exception:
            pass


# ------------------------------------------------------------- 托盘要用的动作

def _pythonw():
    exe = sys.executable or ""
    if exe.lower().endswith("python.exe"):
        cand = exe[:-len("python.exe")] + "pythonw.exe"
        return cand if os.path.exists(cand) else exe
    return exe


def _clean_env():
    """给子进程一份干净的环境变量。

    实现就在 config.child_env()，两个地方共用同一份逻辑，免得以后只改一边。
    完整原因（为什么要摘掉 _MEIPASS2）写在那个函数的注释里，值得看一眼。
    """
    return child_env()


def _spawn(args):
    try:
        subprocess.Popen(args, cwd=BASE_DIR, creationflags=NO_WINDOW,
                         env=_clean_env())
        return True
    except Exception as e:
        say(f"启动外部程序失败：{e}", "WARN")
        return False


def open_program_folder():
    """打开程序所在的文件夹。

    这是「万一设置界面起不来」的兜底出口：让用户能自己去双击那个 exe。
    """
    d = (os.path.dirname(os.path.abspath(sys.executable))
         if is_frozen() else BASE_DIR)
    try:
        os.startfile(d)                    # noqa: S606
        return True
    except Exception:
        return False


def open_settings():
    """从托盘打开设置界面（打包后就是再跑一次自己，不带参数）。"""
    if is_frozen():
        return _spawn([sys.executable])
    return _spawn([_pythonw(), os.path.join(BASE_DIR, "gui.py")])


def open_viewer(arg="index"):
    if is_frozen():
        return _spawn([sys.executable, "--view", arg])
    return _spawn([_pythonw(), os.path.join(BASE_DIR, "viewer.py"), arg])


def open_log():
    try:
        p = os.path.join(LOG_DIR, "checker.log")
        os.startfile(p if os.path.exists(p) else LOG_DIR)      # noqa: S606
        return True
    except Exception:
        return False


def tray_menu():
    """托盘右键菜单。每次点右键时现场生成，所以状态永远是最新的。"""
    st = STATE
    if st.get("silent"):
        mode = "手动静默中"
    else:
        # 说「全屏中」而不是「游戏静默中」：实测全屏看视频也会触发，
        # 写「游戏」会让用户莫名其妙（我没玩游戏啊）。
        mode = {"game": "全屏中（先不打扰你）", "paused": "已暂停"}.get(
            st.get("mode"), "运行中")
    items = [
        {"id": "", "label": f"状态：{mode}", "enabled": False},
        {"id": "", "label": f"上次问官方：{st.get('last_check') or '还没问过'}",
         "enabled": False},
    ]
    if st.get("game_exe"):
        items.append({"id": "", "enabled": False,
                      "label": "全屏的程序：" + os.path.basename(st["game_exe"])})
    items += [
        {"sep": True},
        {"id": "open", "label": "打开设置界面"},
        {"id": "check", "label": "立刻检测一次"},
        {"id": "silent", "label": ("取消静默" if st.get("silent")
                                   else "静默 2 小时")},
        {"sep": True},
        {"id": "index", "label": "打开报告总览"},
        {"id": "log", "label": "打开日志"},
        {"id": "folder", "label": "打开程序文件夹（界面打不开时用）"},
        {"sep": True},
        {"id": "quit", "label": "完全关闭后台监控"},
    ]
    return items


def tray_action(name):
    """托盘菜单被点了。这里只做「写文件 / 起进程」这类线程安全的动作，
    真正的开关状态由主循环下一轮读配置时生效。"""
    if name == "open":
        open_settings()
    elif name == "check":
        say("托盘菜单：立刻检测一次")
        request_check_now()
    elif name == "silent":
        cur = (load_config().get("silent_until") or "").strip()
        active = False
        if cur:
            try:
                active = dt.datetime.fromisoformat(cur) > dt.datetime.now()
            except Exception:
                active = False
        if active:
            patch_config(silent_until="")
            say("托盘菜单：取消手动静默")
        else:
            until = dt.datetime.now() + dt.timedelta(hours=2)
            patch_config(silent_until=until.isoformat(timespec="seconds"))
            say(f"托盘菜单：静默到 {until:%H:%M}")
    elif name == "index":
        open_viewer("index")
    elif name == "log":
        open_log()
    elif name == "folder":
        say("托盘菜单：打开程序文件夹")
        open_program_folder()
    elif name == "quit":
        say("托盘菜单：完全关闭后台监控")
        # 先关开关再发退出请求：这样即使计划任务把它重启，它一启动就自己退出
        patch_config(watch_enabled=False)
        request_exit()


# ------------------------------------------------------------------ 单实例

def acquire_single():
    """保证同一时间只有一个哨兵在跑，返回 (句柄, 是否已经有别人在跑)。

    重复登录、任务被触发两次、用户又手动开了一次，都不会变成两个进程
    （两个的话会重复发通知，还会互相覆盖 state.json，也会出现两个托盘图标）。
    句柄要一直拿着，句柄一被回收锁就没了。
    """
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = ctypes.c_void_p
        handle = k32.CreateMutexW(None, False, MUTEX_NAME)
        try:
            code = ctypes.GetLastError()
        except Exception:
            code = k32.GetLastError()
        return handle, (code == ERROR_ALREADY_EXISTS)
    except Exception:
        return None, False          # 取不到锁也照常跑，不能因为这个不工作


def busy_now(cfg, silent_until=0.0):
    """现在「不方便打扰」吗？写报告要几十秒，发通知前再确认一次。"""
    if time.time() < silent_until:
        return True
    if not bool(cfg.get("game_mode_enabled", True)):
        return False
    try:
        r = gamesense.check(ignore=cfg.get("game_ignore") or [],
                            own_pid=os.getpid())
        return bool(r["gaming"])
    except Exception:
        return False


def show_status():
    w = load_watch()
    if not w.get("online"):
        print("哨兵：没有在运行（或者刚刚停了）")
        if w:
            print(f"  最后的记录：{w.get('last_tick') or '无'}"
                  f"　模式：{w.get('mode') or '?'}")
        return 1
    mode = {"game": "全屏中（先不打扰你）", "paused": "已暂停（没后台监控）"}.get(
        w.get("mode"), "正常")
    print(f"哨兵：运行中（进程 {w.get('pid')}）")
    print(f"  当前状态  ：{mode}"
          + (f"　因为：{w.get('game_exe')}" if w.get("game_exe") else ""))
    print(f"  启动于    ：{w.get('started')}")
    print(f"  心跳      ：{w.get('last_tick')}（{w.get('stale_seconds')} 秒前）")
    print(f"  上次问官方：{w.get('last_check') or '还没问过'}")
    print(f"  上次有新版本：{w.get('last_change') or '还没有过'}")
    print(f"  检查间隔  ：每 {w.get('interval_minutes')} 分钟")
    print(f"  托盘图标  ：{'已挂上' if w.get('tray') else '没有（不影响检测）'}")
    print(f"  累计      ：问了 {w.get('checks')} 次，出错 {w.get('errors')} 次")
    if w.get("last_result"):
        print(f"  最近结果  ：{w.get('last_result')}")
    if w.get("manual_until"):
        print(f"  手动静默到：{w.get('manual_until')}")
    return 0


def main():
    if "--status" in sys.argv:
        return show_status()

    cfg = load_config()
    ensure_dirs(cfg)

    handle, already = acquire_single()          # noqa: F841  句柄要一直拿着
    if already:
        say("已经有一个哨兵在跑了，这次直接退出（避免重复通知、重复图标）", "WARN")
        return 0

    # 「完全关闭」后标志是 False：这时候连启动都不要启动，
    # 免得计划任务每次登录又把它拉起来（用户会以为关不掉）。
    if not bool(cfg.get("watch_enabled", True)):
        say("后台监控处于关闭状态，哨兵不启动"
            "（在设置界面点「启动后台监控」即可恢复）")
        return 0

    started = dt.datetime.now()
    say(f"哨兵启动（进程 {os.getpid()}）")

    cond = source.Conditional()     # 记住「上次拿到的版本标记」，用来问「变了没有」
    tray = None
    tray_style = ""
    if not NO_TRAY:
        # 托盘图标样式：icons\ 下有 9 套（线条粗细 × 箭头占位大小），用户在设置
        # 界面里随便挑。哨兵每轮都会重读配置，所以换样式是现场换图标，不用重启。
        # 程序自己的 icon.ico 一直不变：它要出现在资源管理器里，浅色背景上
        # 纯白线条会看不见。
        tray_style = ((cfg.get("tray_style") or "").strip()
                      or tray_mod.load_styles()[0])
        tray = tray_mod.Tray(tray_mod.icon_path(tray_style),
                             menu_provider=tray_menu,
                             on_default=open_settings, on_action=tray_action,
                             tip="win升级报告 · 正在启动")
        if tray.start():
            say("托盘图标已挂上（看不到的话可能在任务栏的「隐藏的图标」里）")
            if not cfg.get("tray_hint_shown"):
                tray.balloon(
                    "win升级报告 已在后台运行",
                    "右键这个图标：打开设置 / 立刻检测 / 静默 / 完全关闭。"
                    "如果任务栏看不到它，去「设置 → 个性化 → 任务栏 → "
                    "其他系统托盘图标」把 win升级报告 打开。")
                patch_config(tray_hint_shown=True)
        else:
            say(f"托盘图标没能挂上（不影响检测）：{tray._error or '未知原因'}",
                "WARN")

    next_poll = 0.0                 # 0 = 立刻先查一次（登录后正好补上关机期间的变化）
    next_flush = 0.0
    last_hb = 0.0
    last_tip = ""
    last_check = ""
    last_change = ""
    last_result = ""
    in_game = False
    game_exe = ""
    clear_streak = 0
    silent_until = 0.0              # 设置界面/托盘里「静默 2 小时」的截止时间
    ticks = checks = errcount = 0
    quit_reason = ""

    try:
        while True:
            try:
                cfg = load_config()         # 每轮重读：设置界面改了什么立刻生效
                source.configure(cfg)

                tick = max(2, int(cfg.get("tick_seconds") or 5))
                interval = max(1, int(cfg.get("watch_interval_minutes") or 5)) * 60
                enabled = bool(cfg.get("watch_enabled", True))
                game_on = bool(cfg.get("game_mode_enabled", True))
                hold = max(0, int(cfg.get("game_exit_hold_seconds") or 60))
                now = time.time()
                ticks += 1

                # ---- 要不要退出（「完全关闭」）----
                if take_exit_request():
                    quit_reason = "收到「完全关闭」请求"
                    break
                if not enabled:
                    quit_reason = "设置里关掉了后台监控"
                    break

                # 手动静默：config 里放一个截止时间
                su = (cfg.get("silent_until") or "").strip()
                silent_until = 0.0
                if su:
                    try:
                        silent_until = dt.datetime.fromisoformat(su).timestamp()
                    except Exception:
                        silent_until = 0.0

                # ---- 第 1 步：现在该不该闭嘴 ----
                if now < silent_until:
                    gaming, game_exe = True, "（手动静默）"
                elif game_on:
                    r = gamesense.check(ignore=cfg.get("game_ignore") or [],
                                        own_pid=os.getpid())
                    gaming = bool(r["gaming"])
                    if gaming:
                        game_exe = r["exe"] or "（全屏应用）"
                else:
                    gaming = False

                if gaming:
                    clear_streak = 0
                    if not in_game:
                        in_game = True
                        last_hb = 0
                        say(f"进入安静模式：{game_exe} 正在全屏。"
                            f"这段时间不联网、不调 AI、不通知。")
                else:
                    if in_game:
                        clear_streak += 1
                        # 连续 hold 秒都判定「没在玩」才真退出，免得切进切出乱弹
                        if hold <= 0 or clear_streak * tick >= hold:
                            in_game = False
                            game_exe = ""
                            clear_streak = 0
                            next_poll = 0     # 补查：玩游戏期间可能发了新版本
                            last_hb = 0
                            say("退出全屏，立刻补查一次")
                    else:
                        clear_streak = 0

                # ---- 第 2 步：不静默才做正事 ----
                if not in_game:
                    if take_check_now():
                        say("收到「立刻检测」请求")
                        next_poll = 0

                    if now >= next_poll:
                        # 先把下次时间排好：就算这轮抛异常也不会变成每 5 秒狂重试
                        next_poll = time.time() + interval
                        state = load_state(force=True)
                        last_check = dt.datetime.now().isoformat(timespec="seconds")
                        try:
                            res = checker.run_check(
                                cfg, state, cond=cond, quiet=True, label="哨兵",
                                should_notify=lambda: not busy_now(cfg, silent_until))
                            checks += 1
                            if res.get("errors"):
                                errcount += len(res["errors"])
                                last_result = res["errors"][-1]
                                say("这轮有问题：" + last_result, "ERROR")
                            elif res.get("changed"):
                                last_change = last_check
                                last_result = f"{len(res['updates'])} 条线有新版本"
                                say("已发现新版本并处理：" + last_result)
                            else:
                                last_result = ""     # 没变化：不写日志、不刷屏
                        except Exception as e:
                            errcount += 1
                            last_result = f"{type(e).__name__}: {e}"
                            say("这轮检测抛异常：\n" + traceback.format_exc(),
                                "ERROR")

                    # 攒着的通知（静默时段或游戏期间留下的）定期补发
                    if now >= next_flush:
                        next_flush = now + FLUSH_SECONDS
                        try:
                            st = load_state(force=True)
                            if st.get("pending_notify"):
                                checker.flush_pending(cfg, st)
                        except Exception:
                            pass

                # ---- 第 3 步：刷新托盘提示 + 写心跳 ----
                if tray is not None and tray.alive:
                    # 样式被改过就现场换图标。换失败也记下来，免得每轮重试刷屏。
                    want = (cfg.get("tray_style") or "").strip()
                    if want and want != tray_style:
                        if tray.set_icon(tray_mod.icon_path(want)):
                            say(f"托盘图标样式已切换：{want}")
                        else:
                            say(f"托盘图标样式切换失败：{want}", "WARN")
                        tray_style = want

                    if now < silent_until:
                        mode_txt = "手动静默中"
                    elif in_game:
                        mode_txt = "全屏中（先不打扰你）"
                    else:
                        mode_txt = "运行中"
                    tip = (f"win升级报告 · {mode_txt}"
                           f"　上次检查 {last_check[11:19] if last_check else '—'}"
                           f"　每 {interval // 60} 分钟一次")
                    if tip != last_tip:
                        last_tip = tip
                        tray.set_tip(tip)

                STATE.update({
                    "mode": ("game" if in_game
                             else ("paused" if not enabled else "normal")),
                    "last_check": last_check,
                    "game_exe": game_exe,
                    "interval": interval // 60,
                    "silent": now < silent_until,
                })

                if last_hb == 0 or now - last_hb >= HEARTBEAT_SECONDS:
                    last_hb = now
                    save_watch({
                        "pid": os.getpid(),
                        "started": started.isoformat(timespec="seconds"),
                        "last_tick": dt.datetime.now().isoformat(timespec="seconds"),
                        "last_check": last_check,
                        "last_change": last_change,
                        "mode": ("game" if in_game
                                 else ("paused" if not enabled else "normal")),
                        "game_exe": game_exe,
                        "interval_minutes": interval // 60,
                        "tray": bool(tray is not None and tray.alive),
                        "ticks": ticks, "checks": checks, "errors": errcount,
                        "last_result": last_result[:300],
                        "manual_until": (
                            dt.datetime.fromtimestamp(silent_until)
                            .isoformat(timespec="seconds")
                            if now < silent_until else ""),
                    })

                if ONCE:
                    say(f"--once：跑了 1 轮（第 {ticks} 次醒，检测 {checks} 次，"
                        f"游戏静默中={in_game}）")
                    return 0

                time.sleep(tick)

            except KeyboardInterrupt:
                quit_reason = "收到中断"
                break
            except Exception:
                # 主循环绝不能因为一次意外就死掉。记下来，歇 10 秒继续。
                try:
                    checker.log("哨兵主循环出错：\n" + traceback.format_exc(),
                                "ERROR")
                except Exception:
                    pass
                time.sleep(10)
    finally:
        if tray is not None:
            tray.stop()
            say("托盘图标已移除")
        if quit_reason:
            say(f"哨兵退出（{quit_reason}）")
        # 把心跳写清楚，免得界面一直显示「运行中」（last_tick 空了就等于离线）
        try:
            w = load_watch()
            w["last_tick"] = ""
            w["mode"] = "stopped"
            w["tray"] = False
            save_watch(w)
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except Exception:
        try:
            checker.log("哨兵未捕获异常：\n" + traceback.format_exc(), "ERROR")
        except Exception:
            pass
        sys.exit(9)
