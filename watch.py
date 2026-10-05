# -*- coding: utf-8 -*-
"""哨兵：常驻后台的小程序，每隔几分钟问一次官方看板「变了没有」。

它在整个工具里的位置
--------------------
    登录时由计划任务悄悄启动（没有窗口、不打扰）
    └─ 每 5 秒醒一次（很便宜，实测一次判定约 0.26 毫秒）
         ├─ 先看用户是不是在玩全屏游戏
         │    ├─ 在玩 → **彻底静默**：不联网、不调 AI、不发通知、不写盘
         │    └─ 不玩 → 继续
         ├─ 到点（默认 5 分钟）就问 Flight Hub「变了没有」
         │    ├─ 没变：服务器回 304，传输 0 字节 → 接着睡，什么都不做
         │    └─ 变了 → 交给 checker.run_check()：
         │             抓官方发布说明 → AI 总结成中文报告 → 存文件 → 发唯一一条通知
         └─ 顺手看看设置界面有没有留言说「立刻检测」

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
    python  watch.py --verbose  过程打印到控制台
"""
import os
import sys
import time
import ctypes
import datetime as dt
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (load_config, load_state, load_watch, save_watch,   # noqa: E402
                    take_check_now, ensure_dirs)
import source                                                         # noqa: E402
import gamesense                                                      # noqa: E402
import checker                                                        # noqa: E402

VERBOSE = "--verbose" in sys.argv
ONCE = "--once" in sys.argv
MUTEX_NAME = "Local\\WinUpdReportWatch"
ERROR_ALREADY_EXISTS = 183
HEARTBEAT_SECONDS = 30      # 心跳写这么勤就够了，不必每 5 秒写一次盘
FLUSH_SECONDS = 60          # 隔多久看一眼有没有攒着的通知要补发


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


def acquire_single():
    """保证同一时间只有一个哨兵在跑，返回 (句柄, 是否已经有别人在跑)。

    重复登录、任务被触发两次、用户又手动开了一次，都不会变成两个进程
    （两个的话会重复发通知，还会互相覆盖 state.json）。
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
    mode = {"game": "游戏静默中", "paused": "已暂停（没启用）"}.get(
        w.get("mode"), "正常")
    print(f"哨兵：运行中（进程 {w.get('pid')}）")
    print(f"  当前状态  ：{mode}"
          + (f"　因为：{w.get('game_exe')}" if w.get("game_exe") else ""))
    print(f"  启动于    ：{w.get('started')}")
    print(f"  心跳      ：{w.get('last_tick')}（{w.get('stale_seconds')} 秒前）")
    print(f"  上次问官方：{w.get('last_check') or '还没问过'}")
    print(f"  上次有新版本：{w.get('last_change') or '还没有过'}")
    print(f"  检查间隔  ：每 {w.get('interval_minutes')} 分钟")
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
        say("已经有一个哨兵在跑了，这次直接退出（避免重复通知）", "WARN")
        return 0

    started = dt.datetime.now()
    say(f"哨兵启动（进程 {os.getpid()}）")

    cond = source.Conditional()     # 记住「上次拿到的版本标记」，用来问「变了没有」
    next_poll = 0.0                 # 0 = 立刻先查一次（登录后正好补上关机期间的变化）
    next_flush = 0.0
    last_hb = 0.0
    last_check = ""
    last_change = ""
    last_result = ""
    in_game = False
    game_exe = ""
    clear_streak = 0
    silent_until = 0.0              # 设置界面里「现在静默」的截止时间
    ticks = checks = errcount = 0

    while True:
        try:
            cfg = load_config()             # 每轮重读：设置界面改了什么立刻生效
            source.configure(cfg)

            tick = max(2, int(cfg.get("tick_seconds") or 5))
            interval = max(1, int(cfg.get("watch_interval_minutes") or 5)) * 60
            enabled = bool(cfg.get("watch_enabled", True))
            game_on = bool(cfg.get("game_mode_enabled", True))
            hold = max(0, int(cfg.get("game_exit_hold_seconds") or 60))
            now = time.time()
            ticks += 1

            # 设置界面里的「现在静默 2 小时」：config.json 里放一个截止时间
            su = (cfg.get("silent_until") or "").strip()
            silent_until = 0.0
            if su:
                try:
                    silent_until = dt.datetime.fromisoformat(su).timestamp()
                except Exception:
                    silent_until = 0.0

            # ---- 第 1 步：现在该不该闭嘴 ----
            if now < silent_until:
                gaming, game_exe = True, "（设置界面里手动静默）"
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
                    say(f"进入静默：{game_exe} 正在全屏运行。"
                        f"这段时间不联网、不调 AI、不通知。")
            else:
                if in_game:
                    clear_streak += 1
                    # 连续 hold 秒都判定「没在玩」才真的退出，免得切进切出时通知乱弹
                    if hold <= 0 or clear_streak * tick >= hold:
                        in_game = False
                        game_exe = ""
                        clear_streak = 0
                        next_poll = 0        # 补查一次：玩游戏期间可能发了新版本
                        last_hb = 0
                        say("退出静默（游戏已关闭），立刻补查一次")
                else:
                    clear_streak = 0

            # ---- 第 2 步：不静默才做正事 ----
            if not in_game:
                if take_check_now():
                    say("设置界面要求立刻检测一次")
                    next_poll = 0

                if enabled and now >= next_poll:
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
                            last_result = ""      # 没变化：不写日志、不刷屏
                    except Exception as e:
                        errcount += 1
                        last_result = f"{type(e).__name__}: {e}"
                        say("这轮检测抛异常：\n" + traceback.format_exc(), "ERROR")

                # 攒着的通知（静默时段或游戏期间留下的）定期补发
                if enabled and now >= next_flush:
                    next_flush = now + FLUSH_SECONDS
                    try:
                        st = load_state(force=True)
                        if st.get("pending_notify"):
                            checker.flush_pending(cfg, st)
                    except Exception:
                        pass

            # ---- 第 3 步：写心跳，让设置界面看得出哨兵是死是活 ----
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
            say("收到中断，哨兵退出")
            return 0
        except Exception:
            # 主循环绝不能因为一次意外就死掉。记下来，歇 10 秒继续。
            try:
                checker.log("哨兵主循环出错：\n" + traceback.format_exc(), "ERROR")
            except Exception:
                pass
            time.sleep(10)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except Exception:
        try:
            checker.log("哨兵未捕获异常：\n" + traceback.format_exc(), "ERROR")
        except Exception:
            pass
        sys.exit(9)
