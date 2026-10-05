# -*- coding: utf-8 -*-
"""程序入口：打包成 exe 之后由它按参数分流。

    win升级报告.exe                    打开设置界面（默认）
    win升级报告.exe --watch            常驻哨兵：一直开着，每隔几分钟问一次官方看板
                                       （计划任务 / 登录自启用这个；没窗口）
    win升级报告.exe --watch --once     只跑一轮就退出（排查用）
    win升级报告.exe --watch --status   看哨兵现在活着没有
    win升级报告.exe --check [参数]     手动跑一次检测
    win升级报告.exe --view <参数>      报告查看器（通知点击用这个）
    win升级报告.exe --list-channels    列出更新线
    win升级报告.exe --selftest         自检：环境、配置、数据目录、依赖

源码运行时可以直接用 python app.py <同样的参数>。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

USAGE = __doc__
_LINES = []


def out(*parts):
    """打包成窗口程序后没有控制台，sys.stdout 可能是 None，所以既打印也留底。"""
    line = " ".join(str(p) for p in parts)
    _LINES.append(line)
    try:
        print(line, flush=True)
    except Exception:
        pass


def _flush(lines_path=None):
    try:
        import config
        path = lines_path or os.path.join(config.LOG_DIR, "自检报告.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(_LINES) + "\n")
        return path
    except Exception:
        return ""


def _selftest():
    import config
    import notify
    import reporter

    out("win升级报告 自检")
    out("  运行模式    :", "打包 exe" if config.is_frozen() else "源码")
    out("  程序所在目录:", os.path.dirname(os.path.abspath(sys.executable))
        if config.is_frozen() else os.path.dirname(os.path.abspath(__file__)))
    out("  数据目录    :", config.BASE_DIR)
    out("  config.json :", os.path.exists(config.CONFIG_PATH), config.CONFIG_PATH)
    out("  state.json  :", os.path.exists(config.STATE_PATH))
    out("  报告目录    :", os.path.isdir(config.REPORT_DIR), config.REPORT_DIR)
    out("  日志目录    :", os.path.isdir(config.LOG_DIR))
    for name in ("toast.ps1", "task.ps1", "icon.ico"):
        p = config.resource_path(name)
        out(f"  资源 {name:11s}: {'OK  ' if os.path.exists(p) else '缺失'} {p}")

    cfg = config.load_config()
    st = config.load_state()
    enabled = [c for c in cfg.get("channels", []) if c["enabled"]]
    out(f"  已配置更新线: {len(cfg.get('channels') or [])} 条，启用 {len(enabled)} 条")
    for c in enabled:
        cs = (st.get("channels") or {}).get(c["id"], {})
        out(f"      [x] {c['id']:32s} 当前 {cs.get('last_version') or '未记录'}")
    key = config.resolve_api_key(cfg)
    out("  API Key     :", ("已填 " + config.mask_key(key)) if key else "没填！")
    out("  模型        :", cfg.get("model"))
    out("  检测节奏    :",
        f"哨兵每 {cfg.get('watch_interval_minutes')} 分钟看一次官方看板"
        + ("（已开启）" if cfg.get("watch_enabled", True) else "（已关闭）")
        + ("；玩游戏时彻底静默" if cfg.get("game_mode_enabled", True) else ""))
    try:
        w = config.load_watch()
        out("  哨兵进程    :",
            (f"运行中，进程 {w.get('pid')}，上次问官方 {w.get('last_check') or '还没问过'}")
            if w.get("online") else "没有在运行（计划任务装了吗？）")
    except Exception as e:
        out("  哨兵进程    : 查询失败 ->", e)
    try:
        import gamesense
        r = gamesense.check(ignore=cfg.get("game_ignore") or [])
        out("  游戏判定    :",
            ("现在判定为「在玩」：" + (r["exe"] or "全屏应用")) if r["gaming"]
            else "现在判定为「没在玩」")
    except Exception as e:
        out("  游戏判定    : 失败 ->", e)
    try:
        import time as _t
        import tray as _tray
        _ic = config.resource_path("icon.ico")
        _tr = _tray.Tray(_ic, tip="win升级报告 自检")
        _ok = _tr.start()
        _t.sleep(0.8)
        _rect = _tr.icon_rect()
        _tr.stop()
        out("  托盘图标    :",
            f"可以创建（位置 {_rect}）" if _ok else
            f"创建失败 -> {_tr._error or '未知原因'}")
    except Exception as e:
        out("  托盘图标    : 失败 ->", e)
    try:
        import tkinter  # noqa: F401
        out("  tkinter     : OK")
    except Exception as e:
        out("  tkinter     : 不可用 ->", e)
    if "--with-gui" in sys.argv:
        try:
            import tkinter as tk
            import gui
            root = tk.Tk()
            root.withdraw()
            gui.App(root)
            root.update()
            out("  界面构建     : OK（设置界面能正常打开）")
            root.destroy()
        except Exception as e:
            import traceback
            out("  界面构建     : 失败 ->", e)
            out(traceback.format_exc()[-600:])
    try:
        notify.register_app(cfg.get("app_id") or "WinUpdReport.App")
        out("  通知/协议注册: OK")
    except Exception as e:
        out("  通知/协议注册: 失败 ->", e)
    try:
        names = {c["id"]: c["name"] for c in cfg["channels"]}
        reporter.write_index(cfg, st, names)
        out("  总览页       : 可生成")
    except Exception as e:
        out("  总览页       : 失败 ->", e)
    out("自检结束。")
    path = _flush()
    out("（以上内容也写到了", path, "）")
    _flush()          # 把最后这行也补进文件
    return 0


def _task_mode(rest):
    """命令行装/卸/查计划任务：
        win升级报告.exe --task query      查状态
        win升级报告.exe --task install    装哨兵任务（会弹 UAC，顺手卸掉旧的每日任务）
        win升级报告.exe --task remove     删任务（会弹 UAC）
    """
    import config
    import gui
    sub = (rest[0].lower() if rest else "query")
    if sub == "query":
        out(gui.task_info())
        out("哨兵运行目标:", " ".join(str(x) for x in gui.watch_target()))
        out("（--task install 装的就是它：登录时启动、每几分钟看一次官方看板）")
    elif sub in ("install", "daily", "install-daily", "remove"):
        mode = "daily" if "daily" in sub else "watch"
        verb = "remove" if sub == "remove" else "install"
        ok, msg = gui.ps_task_elevated(verb, mode=mode,
                                       also_remove=gui.DAILY_TASK_NAME)
        cfg = config.load_config()
        want = ("已删除哨兵任务和旧的每日任务" if verb == "remove" else
                f"已装哨兵任务：登录时启动，每 "
                f"{cfg.get('watch_interval_minutes') or 5} 分钟看一次，不限时、崩了自动重启")
        out(("成功" if ok else "失败") + ":", msg or want)
    else:
        out("未知子命令:", sub, "（用 query / install / remove）")
    path = _flush(os.path.join(config.LOG_DIR, "task_cli.txt"))
    out("（也写到了", path, "）")
    _flush(os.path.join(config.LOG_DIR, "task_cli.txt"))
    return 0


def main():
    args = sys.argv[1:]
    mode = args[0].lower() if args else ""
    rest = args[1:]
    argv0 = sys.argv[0]

    if mode in ("--help", "-h", "help", "/?"):
        out(USAGE)
        path = _flush()
        try:
            import tkinter.messagebox as mb
            mb.showinfo("win升级报告 · 用法", USAGE)
        except Exception:
            pass
        if path:
            try:
                os.startfile(path)                                   # noqa: S606
            except Exception:
                pass
        return 0
    if mode in ("--selftest", "selftest"):
        return _selftest()

    if mode in ("--check", "check"):
        sys.argv = [argv0] + rest
        import checker
        return checker.main()
    if mode in ("--watch", "watch"):
        # 常驻哨兵。计划任务和「登录自启」快捷方式都指向这个模式。
        sys.argv = [argv0] + rest
        import watch
        return watch.main()
    if mode in ("--task", "task"):
        return _task_mode(rest)
    if mode in ("--view", "view"):
        sys.argv = [argv0] + rest
        import viewer
        return viewer.main()
    if mode in ("--list-channels", "list-channels"):
        sys.argv = [argv0, "--list-channels"] + rest
        import checker
        return checker.main()

    # 默认：设置界面
    sys.argv = [argv0] + rest
    import gui
    return gui.main()


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except SystemExit:
        raise
    except Exception:
        import traceback
        try:
            import config
            with open(os.path.join(config.LOG_DIR, "gui_error.log"), "a",
                      encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        try:
            import tkinter.messagebox as mb
            mb.showerror("win升级报告", "程序出错：\n\n" + traceback.format_exc()[-800:])
        except Exception:
            pass
        sys.exit(1)
