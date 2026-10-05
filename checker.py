# -*- coding: utf-8 -*-
"""检测核心：探所有启用的更新线，发现新构建就生成中文报告并发 Windows 通知。

这个文件里最重要的东西是 run_check()：**一轮完整的检测**。
它有两个调用者：

    checker.main()   —— 命令行 / 手动跑一次（--check）
    watch.py         —— 常驻哨兵，每隔几分钟调一次

哨兵是**在同一个进程里直接调 run_check()**，而不是另外起一个进程。这样
state.json 永远只有一个写入者，哨兵和设置界面不会互相把记录覆盖掉。

关于 AI 的边界（重要）：
    AI **只**用来把抓到的官方发布说明总结成中文报告，别的什么都不干。
    判断有没有新版本、比构建号、解析页面全是普通代码。所以没新版本时
    一次 AI 都不会调；同一个版本也只调一次（靠 notified_builds / reported_version 去重）。

用法:
    pythonw checker.py                  # 跑一次检测
    python checker.py --dry-run         # 只抓数据，不调 API、不写文件、不通知
    python checker.py --verbose         # 过程打印到控制台
    python checker.py --only <频道id>    # 只测某一条线（可重复）
    python checker.py --list-channels   # 列出当前所有更新线和状态
    python checker.py --no-notify       # 这次不发通知
    （--force / --at-logon 是旧版留下的参数，现在没有「一天只跑一次」的限制了，
      传了也不报错，只是为了老的快捷方式还能用。）
"""
import os
import re
import sys
import glob
import time
import datetime as dt
import traceback
import concurrent.futures

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
AT_LOGON = "--at-logon" in sys.argv


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

# 旧版这里有一个 should_skip()：靠「今天跑过没有」和「间隔几天」来决定要不要
# 跳过这次。现在节奏交给常驻哨兵（每 N 分钟看一次「变了没有」），一天只跑一次
# 的限制就没有意义了，而且会让人手动点「立刻检测」时莫名其妙什么都不发生。
# 所以这个判断整个删掉了：**每次 run_check() 都真的去查一次**。
# state 里的 last_run_date / last_check_date 保留，只用来在界面上显示。


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

def probe_channel(ch, fh_data=None, fh_failed=False, timeout=None, settings=None):
    """探一条线的最新版本，返回 {'build':..., 'url':..., 'kind':..., 'date':...}"""
    if ch["source"] == "flighthub":
        # Flight Hub 只抓一次，多条 Insider 线共用外面抓好的结果
        if fh_failed:
            raise source.FetchError("Flight Hub 本次抓取失败（多条线共用一次抓取，不重试）")
        data = fh_data if fh_data is not None else source.flighthub(settings=settings)
        folder = ch["folder"]
        if folder not in data:
            raise source.FetchError(f"Flight Hub 上没有 {folder} 这条线")
        item = data[folder]["latest"]
        return {"build": item["build"], "url": item.get("url", ""),
                "kind": "Flight Hub 官方说明", "date": item.get("date", "")}
    pick, rows = source.uupdump_latest(ch["category"], ch.get("arch") or "amd64",
                                       timeout=timeout, settings=settings)
    return {"build": pick["build"], "url": "", "kind": "uupdump",
            "date": pick.get("date", ""), "name": pick.get("name", "")}


def _probe_one(ch, fh_data, fh_failed, st):
    """探一条线，把异常收成 (info, err)，供串行/并发两条路径共用。"""
    try:
        return probe_channel(ch, fh_data, fh_failed,
                             timeout=st["timeout"], settings=st), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def probe_all(active, fh_data, fh_failed, cfg):
    """并发探测所有更新线，返回 [(channel, info 或 None, 错误), ...]，顺序同 active。

    每条 uupdump 线都是一次独立的网页请求，串行做就是几个 RTT 叠加；等网络时
    GIL 是释放的，所以线程在这里真能提速。Flight Hub 那边只有一次抓取（外面已经
    抓好共用），不参与并发。

    结果按原顺序返回，后面的写日志、写报告仍然串行按序做——日志不会乱，也不会
    同时往 DeepSeek 发一堆请求。
    """
    st = source.settings_snapshot()
    workers = max(1, min(int(cfg.get("max_workers") or 4), len(active)))
    if len(active) <= 1 or workers <= 1:
        return [(ch,) + _probe_one(ch, fh_data, fh_failed, st) for ch in active]

    def job(ch):
        return (ch,) + _probe_one(ch, fh_data, fh_failed, st)

    try:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="probe") as pool:
            pairs = list(pool.map(job, active))
    except Exception as e:
        # 起不了线程池就退回串行，功能不受影响
        log(f"并发探测不可用（{type(e).__name__}: {e}），改回串行", "WARN")
        pairs = [(ch,) + _probe_one(ch, fh_data, fh_failed, st) for ch in active]

    log(f"并发抓取 {len(active)} 条线（{workers} 个线程）")
    return pairs


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
    # 顺带把官方说明的网址一起给出去：通知上的「官方原文」按钮要用它
    return md_path, summary, err, notes_url


# ---------------------------------------------------------------- 主流程

def run_check(cfg, state, only=None, dry=False, do_notify=True, label="检测",
              cond=None, quiet=False, should_notify=None):
    """跑一轮完整检测，返回结果字典。

    整个工具唯一「干活」的地方，两个调用者共用：
        * checker.main()  —— 命令行 / 设置界面点「立刻检测」
        * watch.py        —— 常驻哨兵，每隔几分钟调一次

    cond          传入 source.Conditional 时，会先问官方看板「变了没有」：
                  没变化就直接结束，传输 0 字节、不解析、不调 AI。哨兵走这条路。
                  不传则每次都拿全文（手动检测用，保证一定拿到最新数据）。
    quiet         哨兵用：没变化时不写任何日志，免得日志每 5 分钟多一行。
    should_notify 最后一道闸门。写报告要花几十秒，这期间用户可能开始玩游戏了，
                  所以真发通知之前再问一次「现在方便打扰吗」。返回 False 就把通知
                  攒起来，等方便了再补发——**不会丢，也不会重复**。
    """
    today = dt.date.today().isoformat()
    chans = [ch_mod.norm_channel(c) for c in cfg.get("channels", [])]
    if only:
        chans = [c for c in chans if c["id"] in only or c.get("category") in only
                 or c.get("folder") in only]
    active = [c for c in chans if c["enabled"] or only]
    if not active:
        if not quiet:
            log("没有任何启用的更新线，去设置界面勾几条", "WARN")
        return {"updates": [], "errors": [], "checked": 0, "changed": False,
                "skip": "没有启用的更新线"}

    if not quiet:
        log("=" * 60)
        log(f"开始检测（{label}）{len(active)} 条更新线："
            + "，".join(c["name"] for c in active))

    # ---- Flight Hub 只抓一次，多条 Insider 线共用 ----
    fh_data, fh_err, fh_unchanged = None, "", False
    if any(c["source"] == "flighthub" for c in active):
        try:
            if cond is not None:
                status, fh_data = source.flighthub_conditional(
                    cond, settings=source.settings_snapshot())
                if status == 304:
                    # 一点都没变：0 字节到手，后面的活全都不用干
                    fh_unchanged = True
            else:
                fh_data = source.flighthub(settings=source.settings_snapshot())
            if fh_data is not None and not quiet:
                log(f"官方看板有变化，解析到 {len(fh_data)} 条 Insider 线")
        except Exception as e:
            fh_err = f"{type(e).__name__}: {e}"
            log(f"Flight Hub 抓取失败：{fh_err}", "ERROR")

    # 看板没变的话，依赖它的那几条线这一轮就不用管了；
    # 但如果还开着 uupdump 的线，那些还是要单独查（它们和看板无关）。
    active_probe = [c for c in active
                    if not (fh_unchanged and c["source"] == "flighthub")]
    if not active_probe:
        if not quiet:
            log("官方看板没有变化（304，0 字节），这轮什么都不做")
        return {"updates": [], "errors": [], "checked": len(active),
                "changed": False, "skip": "没变化"}

    if fh_data and cfg.get("auto_discover_channels", True):
        chans, added = ch_mod.merge_discovered(chans, fh_data)
        if added:
            log("发现新更新线（已加入列表，默认未启用）：" +
                "，".join(c["name"] for c in added))
            cfg["channels"] = chans

    updates, errors = [], []
    # 先把所有线一次性探完（并发），再按原顺序逐条处理：写日志、调 AI 仍然串行，
    # 免得日志串行错乱、也免得同时往 DeepSeek 发一堆请求。
    for ch, info, perr in probe_all(active_probe, fh_data, bool(fh_err), cfg):
        cs = channel_state(state, ch["id"])
        if info is None:
            msg = f"{ch['name']}：取值失败 {perr}"
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
            elif not quiet:
                log(f"  [{ch['name']}] 无变化（{build}）")
            continue

        if build in (cs.get("ignored") or []):
            log(f"  [{ch['name']}] {build} 在你忽略列表里，跳过")
            cs["last_version"] = build
            continue

        log(f"  [{ch['name']}] ★ 发现新版本 {prev} → {build}")
        if dry:
            updates.append({"ch": ch, "build": build, "prev": prev, "summary": "",
                            "md": "", "html": "", "url": info.get("url", ""),
                            "dry": True})
            continue

        try:
            md_path, summary, err, notes_url = make_report(cfg, ch, cs, info,
                                                           prev, today)
            log(f"  [{ch['name']}] 报告：{md_path}")
            cs["last_version"] = build
            cs["last_version_date"] = info.get("date", "")
            cs["reported_version"] = build      # 这个版本报告写完了，别再总结第二次
            updates.append({"ch": ch, "build": build, "prev": prev,
                            "summary": summary, "md": md_path,
                            "html": os.path.splitext(md_path)[0] + ".html",
                            "url": notes_url or info.get("url", ""),
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

    if not dry:
        try:
            names = {c["id"]: c["name"] for c in cfg["channels"]}
            idx = reporter.write_index(cfg, state, names)
            log(f"总览页：{idx}")
        except Exception as e:
            log(f"总览页生成失败：{e}", "WARN")

    if dry:
        log(f"dry-run：{len(updates)} 条线有新版本，未写文件、未通知")
        return {"updates": updates, "errors": errors, "checked": len(active),
                "changed": bool(updates), "skip": ""}

    # 先把「检测结果」落盘，再去发通知。顺序很重要：
    # 万一下面发通知那一步出问题，也不会因为状态没存上，导致下一轮又把同一个
    # 版本当成新的、再吵你一遍。
    save_config(cfg)
    save_state(state)

    # ---- 通知 ----
    # 规矩：**只有真的出了新版本才发通知**。没新版本时这里一个字都不发；
    # 已经为某个版本提醒过的，也绝不再提第二次（靠 notified_builds 去重）。
    fresh = [u for u in updates
             if u["build"] not in (channel_state(state, u["ch"]["id"])
                                   .get("notified_builds") or [])]
    queued = [{"cid": u["ch"]["id"], "name": u["ch"]["name"], "build": u["build"],
               "prev": u["prev"], "summary": u["summary"], "html": u["html"],
               "url": u.get("url", "")} for u in fresh]

    if fresh and cfg.get("notify", True) and do_notify:
        if should_notify is not None and not should_notify():
            # 刚才还在写报告，现在用户已经进游戏了 —— 先攒着，游戏关了再发
            state.setdefault("pending_notify", []).extend(queued)
            log(f"现在不方便打扰（游戏静默中），{len(fresh)} 条通知先攒着")
        elif in_quiet_hours(cfg.get("quiet_hours")):
            state.setdefault("pending_notify", []).extend(queued)
            log(f"现在是静默时段，{len(fresh)} 条通知先攒着，出了时段再发")
        else:
            # 先记账再发：保证「同一个版本只提醒一次」不会因为发送失败而破功
            mark_notified(state, [u["ch"]["id"] for u in fresh],
                          [u["build"] for u in fresh])
            save_state(state)
            sent = send_notifications(cfg, fresh)
            missed = [q for q in queued if q["build"] not in sent]
            if missed:
                # 没发出去的不丢掉，留下来待会儿重试（极少发生）
                for q in missed:
                    q["tries"] = int(q.get("tries") or 0) + 1
                state.setdefault("pending_notify", []).extend(missed)
                save_state(state)
                log(f"有 {len(missed)} 条通知没发出去，先留着待会儿重试", "WARN")
    elif fresh:
        log("有更新但配置关闭了通知（或本次 --no-notify）")
    elif updates:
        log("发现的新版本之前已经提醒过了，静默忽略，不重复发通知")

    # 之前攒下的（静默时段 / 游戏静默期间留下的）在这里补发
    if do_notify and cfg.get("notify", True):
        flush_pending(cfg, state)

    # 错误通知：连续取不到数据时才说一声（这个不算「重复通知」）
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

    save_state(state)          # 通知的记账（已提醒 / 待重试）也一起落盘
    log(f"完成：本次 {len(updates)} 条线有更新，{len(errors)} 个错误")
    return {"updates": updates, "errors": errors, "checked": len(active),
            "changed": bool(updates), "skip": ""}


def mark_notified(state, cids, builds):
    """记下「这个版本已经吵过用户了」，同一个版本以后不会再发通知。"""
    for cid, build in zip(cids, builds):
        cs = channel_state(state, cid)
        lst = cs.setdefault("notified_builds", [])
        if build not in lst:
            lst.append(build)
        del lst[:-20]        # 只留最近 20 个，别让状态文件无限长大


def flush_pending(cfg, state):
    """把攒着的通知补发出去。

    什么时候会攒下来：静默时段里发现的、或者「报告刚写完用户就进游戏了」。
    哨兵每一轮都会调一次这个函数（没东西可发时它立刻返回，几乎不花时间），
    所以攒下的通知**一定会在方便的时候补上，既不会丢也不会重复**。
    """
    pending = state.get("pending_notify") or []
    if not pending or not cfg.get("notify", True):
        return 0
    if in_quiet_hours(cfg.get("quiet_hours")):
        return 0

    # 反复发不出去的（例如通知通道坏了）重试几次就放弃，免得一直堆着
    alive = [p for p in pending if int(p.get("tries") or 0) < 5]
    dead = [p for p in pending if int(p.get("tries") or 0) >= 5]
    if dead:
        state["pending_notify"] = alive
        log(f"{len(dead)} 条通知重试多次仍发不出去，放弃（报告文件还在，"
            f"可以在总览页里看）", "WARN")
    if not alive:
        save_state(state)
        return 0

    done = send_pending(cfg, alive)
    rest = []
    for p in alive:
        if p["build"] in done:
            continue
        p["tries"] = int(p.get("tries") or 0) + 1
        rest.append(p)
    state["pending_notify"] = rest
    mark_notified(state, [p["cid"] for p in alive if p["build"] in done],
                  [p["build"] for p in alive if p["build"] in done])
    save_state(state)
    if done:
        log(f"补发了 {len(done)} 条之前攒着的通知")
    return len(done)


def main():
    only = [sys.argv[i + 1] for i, a in enumerate(sys.argv)
            if a == "--only" and i + 1 < len(sys.argv)]

    cfg = load_config()
    state = load_state(force=True)
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

    if only and not [c for c in chans
                     if c["id"] in only or c.get("category") in only
                     or c.get("folder") in only]:
        log("--only 没匹配到任何更新线", "ERROR")
        return 2

    run_check(cfg, state, only=only, dry=DRY, do_notify=not NO_NOTIFY,
              label="手动检测")
    return 0


def report_arg(cid, build):
    """通知里带的点击参数：纯 ASCII，viewer.py 据此定位那一份报告。"""
    return "r/" + reporter.chan_slug(cid) + "/" + str(build).replace(".", "-")


def _show_one(app_id, title, body, arg1=None, url=None):
    """发一条通知。有官方原文链接时，第二个按钮就直接指向那篇官方说明。

    （viewer.py 已经支持打开网址，所以这里不用改查看器。）
    """
    kw = {"app_id": app_id, "arg1": arg1 or "index",
          "button1": "查看报告" if arg1 else "打开总览"}
    if url:
        kw["arg2"], kw["button2"] = url, "官方原文"
    else:
        kw["arg2"], kw["button2"] = "index", "打开总览"
    ok, _msg = notify.show(title, body, **kw)
    return bool(ok)


def send_notifications(cfg, updates):
    """给这批新版本发通知。返回**成功发出**的构建号列表，用来记账去重。"""
    app_id = cfg.get("app_id") or "WinUpdReport.App"
    notify.register_app(app_id)
    sent = []

    if len(updates) == 1:
        u = updates[0]
        title = f"{u['ch']['name']} 有新版本：{u['build']}"
        body = (u.get("summary") or f"上一版 {u['prev']} → {u['build']}")[:200]
        if _show_one(app_id, title, body, report_arg(u["ch"]["id"], u["build"]),
                     u.get("url")):
            sent.append(u["build"])
        return sent

    if cfg.get("merge_notifications", True):
        lines = [f"· {u['ch']['name']}：{u['prev']} → {u['build']}"
                 for u in updates[:6]]
        if len(updates) > 6:
            lines.append(f"…等共 {len(updates)} 条线")
        if _show_one(app_id, f"有 {len(updates)} 条更新线出了新版本",
                     "\n".join(lines), "index", None):
            sent = [u["build"] for u in updates]
        return sent

    for u in updates:
        title = f"{u['ch']['name']} 有新版本：{u['build']}"
        body = (u.get("summary") or "")[:200] or f"上一版 {u['prev']}"
        if _show_one(app_id, title, body, report_arg(u["ch"]["id"], u["build"]),
                     u.get("url")):
            sent.append(u["build"])
    return sent


def send_pending(cfg, pending):
    """把静默时段攒下的通知补发。返回成功发出的构建号列表。"""
    if not pending:
        return []
    app_id = cfg.get("app_id") or "WinUpdReport.App"
    notify.register_app(app_id)

    if len(pending) == 1:
        p = pending[0]
        ok = _show_one(app_id, f"{p['name']} 有新版本：{p['build']}",
                       (p.get("summary") or "")[:200], "index", p.get("url"))
        return [p["build"]] if ok else []

    lines = [f"· {p['name']}：{p.get('prev', '')} → {p['build']}"
             for p in pending[:6]]
    if len(pending) > 6:
        lines.append(f"…等共 {len(pending)} 条")
    ok = _show_one(app_id, f"这段时间有 {len(pending)} 条更新（之前是静默时段）",
                   "\n".join(lines), "index", None)
    return [p["build"] for p in pending] if ok else []


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        try:
            log("未捕获异常：\n" + traceback.format_exc(), "ERROR")
        except Exception:
            pass
        sys.exit(9)
