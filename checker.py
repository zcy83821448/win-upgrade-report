# -*- coding: utf-8 -*-
"""主程序：静默检测所有启用的更新线，发现新构建就生成报告并发 Windows 通知。

用法:
    pythonw checker.py                  # 正常检测（计划任务用这个）
    python checker.py --force           # 忽略「今天跑过」和间隔限制
    python checker.py --dry-run         # 只抓数据，不调 API、不写文件、不通知
    python checker.py --verbose         # 过程打印到控制台
    python checker.py --only <频道id>    # 只测某一条线（可重复）
    python checker.py --list-channels   # 列出当前所有更新线和状态
    python checker.py --no-notify       # 这次不发通知
"""
import os
import re
import sys
import glob
import time
import datetime as dt
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (load_config, save_config, load_state, save_state,      # noqa: E402
                    channel_state, resolve_api_key, ensure_dirs,
                    REPORT_DIR, LOG_DIR)
import channels as ch_mod                                                  # noqa: E402
import source                                                              # noqa: E402
import deepseek_api                                                        # noqa: E402
import reporter                                                            # noqa: E402
import notify                                                              # noqa: E402

LOG_PATH = os.path.join(LOG_DIR, "checker.log")
MAX_LOG_BYTES = 1024 * 1024
VERBOSE = "--verbose" in sys.argv
DRY = "--dry-run" in sys.argv
FORCE = "--force" in sys.argv
NO_NOTIFY = "--no-notify" in sys.argv


def log(msg, level="INFO"):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} [{level}] {msg}"
    if VERBOSE:
        try:
            print(line)
        except Exception:
            pass
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_LOG_BYTES:
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                tail = f.read()[-MAX_LOG_BYTES // 2:]
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                f.write("=== 日志已截断 ===\n" + tail)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ 节奏

def should_skip(cfg, state):
    if FORCE or "--only" in sys.argv:
        return None
    today = dt.date.today().isoformat()
    if cfg.get("run_once_per_day", True) and state.get("last_run_date") == today:
        return "今天已经运行过了"
    days = max(1, int(cfg.get("interval_days") or 1))
    last = (state.get("last_check_date") or "")[:10]
    if last:
        try:
            if (dt.date.today() - dt.date.fromisoformat(last)).days < days:
                return f"间隔设置是每 {days} 天一次，上次检测 {last}，还没到时间"
        except ValueError:
            pass
    return None


def in_quiet_hours(spec, now=None):
    """"23:00-07:00" -> True/False；空或格式不对就不算静默时段。"""
    if not spec or "-" not in spec:
        return False
    try:
        a, b = spec.split("-", 1)
        ah, am = (int(x) for x in a.strip().split(":"))
        bh, bm = (int(x) for x in b.strip().split(":"))
    except Exception:
        return False
    now = now or dt.datetime.now()
    cur, start, end = now.hour * 60 + now.minute, ah * 60 + am, bh * 60 + bm
    return (start <= cur < end) if start <= end else (cur >= start or cur < end)


# ------------------------------------------------------------ 取最新版本

def probe_channel(cfg, ch, fh_data=None, fh_failed=False):
    """返回 {'build':..., 'url':..., 'kind':..., 'date':...}"""
    if ch["source"] == "flighthub":
        if fh_failed:
            raise source.FetchError("Flight Hub 本次抓取失败（多条线共用一次抓取，不重试）")
        data = fh_data if fh_data is not None else source.flighthub()
        folder = ch["folder"]
        if folder not in data:
            raise source.FetchError(f"Flight Hub 上没有 {folder} 这条线")
        item = data[folder]["latest"]
        return {"build": item["build"], "url": item.get("url", ""),
                "kind": "Flight Hub 官方说明", "date": item.get("date", "")}
    pick, rows = source.uupdump_latest(ch["category"], ch.get("arch") or "amd64")
    return {"build": pick["build"], "url": "", "kind": "uupdump",
            "date": pick.get("date", ""), "name": pick.get("name", "")}


# ------------------------------------------------------------ 生成一份报告

def make_report(cfg, ch, cs, info, prev, today):
    build = info["build"]
    notes_url, notes, kind = "", "", ""
    try:
        notes_url, notes, kind = source.official_notes(
            build, hints=[info["url"]] if info.get("url") else [],
            major=(re.findall(r"\d{4,6}", build) or [""])[0])
    except Exception as e:
        log(f"  [{ch['name']}] 取官方说明失败：{e}", "WARN")

    if notes:
        notes = notes[:int(cfg.get("max_context_chars") or 16000)]
        log(f"  [{ch['name']}] 官方说明 {len(notes)} 字（{kind}）：{notes_url}")
    else:
        log(f"  [{ch['name']}] 没取到官方说明，让模型据构建号说明", "WARN")

    err = None
    try:
        key = resolve_api_key(cfg)
        if not key:
            raise RuntimeError("还没填 API Key，打开设置界面「DeepSeek API」页填一个")
        prompt = deepseek_api.build_prompt(
            ch["name"], build, prev, notes_url, kind, notes, today,
            detail=cfg.get("detail") or "标准")
        md = deepseek_api.summarize(cfg, key, prompt,
                                    timeout=int(cfg.get("request_timeout") or 180) + 60)
        if not md.lstrip().startswith("#"):
            md = f"# {ch['name']} 更新报告：{build}\n\n{md}"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        log(f"  [{ch['name']}] AI 概述失败，用兜底报告：{err}", "ERROR")
        md = deepseek_api.fallback_report(ch["name"], build, prev, today,
                                          notes_url, notes, err)

    if cfg.get("include_official_text") and notes:
        md = md.rstrip() + "\n\n---\n\n## 附：官方发布说明原文\n\n```\n" + notes + "\n```\n"

    md_path, html_path = reporter.write(cfg, ch["id"], build, md)
    reporter.prune(cfg, ch["id"])
    summary = reporter.one_line_summary(md)
    cs["reports"] = ([{"build": build, "date": today, "file": md_path,
                       "html": html_path, "summary": summary}]
                     + [r for r in cs.get("reports", []) if r.get("build") != build])[:60]
    cs["last_report"] = md_path
    cs["last_report_at"] = dt.datetime.now().isoformat(timespec="seconds")
    return md_path, summary, err


# ---------------------------------------------------------------- 主流程

def main():
    only = [sys.argv[i + 1] for i, a in enumerate(sys.argv)
            if a == "--only" and i + 1 < len(sys.argv)]

    cfg = load_config()
    state = load_state()
    ensure_dirs(cfg)
    source.configure(cfg)

    chans = [ch_mod.norm_channel(c) for c in cfg.get("channels", [])]

    if "--list-channels" in sys.argv:
        for c in chans:
            cs = (state.get("channels") or {}).get(c["id"], {})
            line = (f"[{'x' if c['enabled'] else ' '}] {c['id']:34s} "
                    f"{c['name'][:34]:36s} 当前={cs.get('last_version') or '未记录':16s} "
                    f"上次检测={cs.get('last_check_date') or '从未'}")
            try:
                print(line)
            except Exception:
                log(line)
        return 0

    if only:
        chans = [c for c in chans if c["id"] in only or c.get("category") in only
                 or c.get("folder") in only]
        if not chans:
            log("--only 没匹配到任何更新线", "ERROR")
            return 2

    active = [c for c in chans if c["enabled"] or only]
    if not active:
        log("没有任何启用的更新线，去设置界面勾几条", "WARN")
        return 0

    skip = should_skip(cfg, state)
    if skip:
        log(f"跳过：{skip}")
        return 0

    today = dt.date.today().isoformat()
    log("=" * 60)
    log(f"开始检测 {len(active)} 条更新线：" + "，".join(c["name"] for c in active))

    # Flight Hub 只抓一次，多条线共用
    fh_data, fh_err = None, ""
    if any(c["source"] == "flighthub" for c in active):
        try:
            fh_data = source.flighthub()
            log(f"Flight Hub 解析到 {len(fh_data)} 条 Insider 线")
        except Exception as e:
            fh_err = f"{type(e).__name__}: {e}"
            log(f"Flight Hub 抓取失败：{fh_err}", "ERROR")

    if fh_data and cfg.get("auto_discover_channels", True):
        chans, added = ch_mod.merge_discovered(chans, fh_data)
        if added:
            log("发现新更新线（已加入列表，默认未启用）：" +
                "，".join(c["name"] for c in added))
            cfg["channels"] = chans

    updates, errors = [], []
    for ch in active:
        cs = channel_state(state, ch["id"])
        try:
            info = probe_channel(cfg, ch, fh_data, fh_failed=bool(fh_err))
        except Exception as e:
            msg = f"{ch['name']}：取值失败 {type(e).__name__}: {e}"
            log("  " + msg, "ERROR")
            errors.append(msg)
            cs["fail_count"] = int(cs.get("fail_count") or 0) + 1
            cs["last_error"] = msg
            continue

        build = info["build"]
        cs["fail_count"] = 0
        cs["last_error"] = ""
        cs["last_check_date"] = today
        prev = cs.get("last_version") or ""

        if not prev:
            cs["last_version"] = build
            cs["last_version_date"] = info.get("date", "")
            log(f"  [{ch['name']}] 首次记录基线 {build}，不发报告")
            continue

        if ch_mod.build_sort_key(build) <= ch_mod.build_sort_key(prev) or build == prev:
            if build != prev:
                log(f"  [{ch['name']}] 页面上的 {build} 不比记录的 {prev} 新，先不动")
            else:
                log(f"  [{ch['name']}] 无变化（{build}）")
            continue

        if build in (cs.get("ignored") or []):
            log(f"  [{ch['name']}] {build} 在你忽略列表里，跳过")
            cs["last_version"] = build
            continue

        log(f"  [{ch['name']}] ★ 发现新版本 {prev} → {build}")
        if DRY:
            updates.append({"ch": ch, "build": build, "prev": prev, "summary": "",
                            "md": "", "html": "", "dry": True})
            continue

        try:
            md_path, summary, err = make_report(cfg, ch, cs, info, prev, today)
            log(f"  [{ch['name']}] 报告：{md_path}")
            cs["last_version"] = build
            cs["last_version_date"] = info.get("date", "")
            updates.append({"ch": ch, "build": build, "prev": prev,
                            "summary": summary, "md": md_path,
                            "html": os.path.splitext(md_path)[0] + ".html",
                            "err": err})
        except Exception as e:
            msg = f"{ch['name']}：写报告失败 {type(e).__name__}: {e}"
            log("  " + msg, "ERROR")
            log(traceback.format_exc(), "ERROR")
            errors.append(msg)
            cs["fail_count"] = int(cs.get("fail_count") or 0) + 1

    state["last_run_date"] = today
    state["last_check_date"] = today
    state["last_error"] = "; ".join(errors[-3:])

    if not DRY:
        try:
            names = {c["id"]: c["name"] for c in cfg["channels"]}
            idx = reporter.write_index(cfg, state, names)
            log(f"总览页：{idx}")
        except Exception as e:
            log(f"总览页生成失败：{e}", "WARN")

    # ---- 通知 ----
    if DRY:
        log(f"dry-run：{len(updates)} 条线有新版本，未写文件、未通知")
        return 0

    if updates and cfg.get("notify", True) and not NO_NOTIFY:
        if in_quiet_hours(cfg.get("quiet_hours")):
            state.setdefault("pending_notify", []).extend(
                [{"cid": u["ch"]["id"], "name": u["ch"]["name"], "build": u["build"],
                  "prev": u["prev"], "summary": u["summary"], "html": u["html"]}
                 for u in updates])
            log(f"现在是静默时段，{len(updates)} 条通知先攒着，出了时段再发")
        else:
            pending = state.get("pending_notify") or []
            state["pending_notify"] = []
            send_notifications(cfg, updates)
            if pending:
                send_pending(cfg, pending)
    elif updates:
        log("有更新但配置关闭了通知（或本次 --no-notify）")

    # 错误通知
    threshold = int(cfg.get("notify_on_error_after") or 0)
    if errors and threshold > 0:
        total_fail = sum(int((state["channels"].get(c["id"]) or {}).get("fail_count") or 0)
                         for c in active)
        if total_fail >= threshold:
            notify.register_app(cfg.get("app_id") or "WinUpdReport.App")
            notify.show("win升级报告 · 检测出错了",
                        f"连续 {threshold} 次以上取不到数据。{errors[-1][:120]}",
                        app_id=cfg.get("app_id") or "WinUpdReport.App",
                        button1="打开日志", button2="打开总览",
                        arg1="log", arg2="index")
            log("已发送错误通知", "WARN")

    save_config(cfg)
    save_state(state)
    log(f"完成：本次 {len(updates)} 条线有更新，{len(errors)} 个错误")
    return 0


def report_arg(cid, build):
    """通知里带的点击参数：纯 ASCII，viewer.py 据此定位那一份报告。"""
    return "r/" + reporter.chan_slug(cid) + "/" + str(build).replace(".", "-")


def send_notifications(cfg, updates):
    app_id = cfg.get("app_id") or "WinUpdReport.App"
    notify.register_app(app_id)
    if len(updates) == 1:
        u = updates[0]
        notify.show(f"{u['ch']['name']} 有新版本：{u['build']}",
                    (u["summary"] or f"上一版 {u['prev']} → {u['build']}")[:180],
                    app_id=app_id, arg1=report_arg(u["ch"]["id"], u["build"]))
        return
    if cfg.get("merge_notifications", True):
        lines = [f"· {u['ch']['name']}：{u['prev']} → {u['build']}" for u in updates[:6]]
        if len(updates) > 6:
            lines.append(f"…等共 {len(updates)} 条线")
        notify.show(f"有 {len(updates)} 条更新线出了新版本",
                    "\n".join(lines), app_id=app_id, arg1="index")
        return
    for u in updates:
        notify.show(f"{u['ch']['name']} 有新版本：{u['build']}",
                    (u["summary"] or "")[:180] or f"上一版 {u['prev']}",
                    app_id=app_id, arg1=report_arg(u["ch"]["id"], u["build"]))


def send_pending(cfg, pending):
    """把静默时段攒下的通知合并成一条补发。"""
    if not pending:
        return
    app_id = cfg.get("app_id") or "WinUpdReport.App"
    if len(pending) == 1:
        p = pending[0]
        notify.show(f"{p['name']} 有新版本：{p['build']}",
                    (p.get("summary") or "")[:180], app_id=app_id, arg1="index")
        return
    lines = [f"· {p['name']}：{p.get('prev', '')} → {p['build']}" for p in pending[:6]]
    notify.show(f"这段时间有 {len(pending)} 条更新（之前是静默时段）",
                "\n".join(lines), app_id=app_id, arg1="index")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        try:
            log("未捕获异常：\n" + traceback.format_exc(), "ERROR")
        except Exception:
            pass
        sys.exit(9)
