# -*- coding: utf-8 -*-
"""配置与状态。所有文件都在本脚本所在目录下。"""
import os
import re
import sys
import json
import copy
import datetime as dt

import channels as ch_mod


def _code_dir():
    """代码/资源所在目录。打包后是 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _resource_dir():
    """打包后静态资源被解到 _MEIPASS；源码运行时就是代码目录。"""
    return getattr(sys, "_MEIPASS", None) or _code_dir()


def _resolve_base_dir():
    """数据目录（config.json / state.json / reports / logs 放哪）。

    打包后按顺序找：exe 同目录 -> 上一级目录（当前开发布局就是这样，app 在
    「应用程序」子目录里，数据在上面一层）。都没有就用 exe 同目录，形成一个
    可以整个拷走、自带数据的独立文件夹。
    """
    here = _code_dir()
    if not getattr(sys, "frozen", False):
        return here
    cands = [here, os.path.dirname(here)]
    for d in cands:
        if os.path.exists(os.path.join(d, "config.json")):
            return d
    for d in cands:
        if (os.path.exists(os.path.join(d, "state.json"))
                or os.path.exists(os.path.join(d, "reports"))):
            return d
    return here


BASE_DIR = _resolve_base_dir()


def resource_path(name):
    """找打包进去的静态文件（toast.ps1 / task.ps1 / icon.ico）。"""
    for d in (_resource_dir(), BASE_DIR, _code_dir()):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return os.path.join(_resource_dir(), name)


def app_exe():
    """打包后返回 exe 路径；源码运行时返回 sys.executable。"""
    return sys.executable if getattr(sys, "frozen", False) else ""


def is_frozen():
    return bool(getattr(sys, "frozen", False))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")
REPORT_DIR = os.path.join(BASE_DIR, "reports")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# 哨兵（常驻进程）的「心跳」单独放一个文件：
#   * 它写得比 state.json 频繁得多（每几秒一次），分开放就不会和检测结果互相打架
#   * 设置界面读它就能显示「运行中 / 已停止、上次检查几点」，不用去问进程
WATCH_PATH = os.path.join(LOG_DIR, "watch.json")
# 设置界面点「立刻检测」时留一个请求文件，让哨兵自己去查。
# 这样 state.json 永远只有一个写入者，不会两个进程抢着写、把对方的记录覆盖掉。
CHECK_NOW_PATH = os.path.join(LOG_DIR, "check_now.req")
# 设置界面/托盘菜单点「完全关闭」时留一个退出请求，哨兵看到就干净退出
EXIT_REQ_PATH = os.path.join(LOG_DIR, "exit.req")

SCHEMA = 3

DEFAULTS = {
    "schema": SCHEMA,

    # ---- 监控哪些更新线 ----
    "channels": copy.deepcopy(ch_mod.DEFAULT_CHANNELS),
    "auto_discover_channels": True,   # 每次运行时把 Flight Hub 上新出现的频道补进列表

    # ---- API ----
    "api_base": "https://api.deepseek.com",
    "api_key": "",                    # 在设置界面的「DeepSeek API」页直接填
    "model": "deepseek-flash",
    "disable_thinking": True,
    "max_tokens": 1600,
    "temperature": 0.3,
    "request_timeout": 60,            # 单次请求超时（秒）
    "retries": 2,                     # 网络请求重试次数
    "max_workers": 4,                 # 同时抓几条更新线（并发探测的线程数）
    "proxy": "",                      # 例如 http://127.0.0.1:7897，留空直连

    # ---- 检测节奏（v3：哨兵常驻，每隔 N 分钟看一眼官方看板）----
    # 核心：只问「上次之后变了没有」。没变时微软服务器回 304，传输 0 字节，
    # 也不解析、不调 AI。所以 5 分钟一次几乎没有任何成本。
    "watch_enabled": True,
    "watch_interval_minutes": 5,      # 每隔几分钟看一次
    "tick_seconds": 5,                # 哨兵醒来的间隔：顺便用来响应「立刻检测」和游戏判定
    # ---- 玩游戏时彻底静默 ----
    "game_mode_enabled": True,        # 判定在玩全屏游戏/全屏应用时：不联网、不调 AI、不通知、不写盘
    "game_exit_hold_seconds": 60,     # 连续这么久都被判定「没在玩」才退出静默（防切进切出乱弹）
    "game_ignore": [],                # 额外的忽略名单（进程名），误判时加进来
    # 设置界面里的「现在静默 2 小时」：存一个截止时间（ISO 字符串），
    # 哨兵读到它就会闭嘴到那个时间为止；空字符串表示不静默。
    "silent_until": "",
    # 托盘图标第一次挂上时，弹一次气泡告诉用户「我在后台跑」以及看不到图标怎么办。
    # 只提示一次，之后不再打扰。
    "tray_hint_shown": False,
    # 托盘图标样式（icons/styles.json 里的 id）。设置界面可以直接换，
    # 哨兵每轮都会重读配置，所以换完几秒内托盘图标就会变，不用重启。
    "tray_style": "std-std",
    "quiet_hours": "",                # 例如 23:00-07:00：这期间发现更新先攒着，出了时段再通知
    "notify_on_error_after": 3,       # 连续失败几次后发一次错误通知，0 = 不通知
    # ---- 以下是 v2「每天定时」的遗留项，只给手动 --check 用，哨兵流程不再依赖 ----
    "check_time": "12:00",
    "interval_days": 1,
    "run_once_per_day": True,
    "check_at_logon": False,

    # ---- 报告 / 通知 ----
    "notify": True,
    "merge_notifications": True,      # 一次发现多条线更新时合并成一条通知
    "detail": "标准",                  # 简短 / 标准 / 详细
    "include_official_text": False,   # 报告末尾附官方原文
    "app_id": "WinUpdReport.App",
    "report_dir": REPORT_DIR,
    "max_context_chars": 16000,
    "keep_reports": 200,              # 每个频道最多保留多少份报告
}

DEFAULT_STATE = {
    "schema": SCHEMA,
    "channels": {},          # id -> {last_version, last_check_date, last_report, reports[], ignored[], fail_count}
    "last_run_date": "",     # 最近一次「定时」检测的日期
    "last_logon_date": "",   # 最近一次「开机/登录补跑」的日期
    "pending_notify": [],    # 静默时段攒下来的通知
    "last_error": "",
    "first_seen": "",
}


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return copy.deepcopy(default)


# --------------------------------------------------------------- 配置

def load_config():
    cfg = copy.deepcopy(DEFAULTS)
    raw = _read_json(CONFIG_PATH, {})
    if raw:
        cfg.update(raw)
        ver = int(raw.get("schema") or 1)
        # v1 -> v2：以前只能盯一条 uupdump 链接
        if ver < 2:
            url = raw.get("uup_url") or ""
            m = re.search(r"category:([a-z0-9\-]+)", url)
            cat = m.group(1) if m else "w11-26h2-experimental"
            cfg["channels"] = [ch_mod.norm_channel(c)
                               for c in copy.deepcopy(ch_mod.DEFAULT_CHANNELS)]
            if cat != "w11-26h2-experimental":
                # 老配置盯的是别的线，照原样搬过来并启用
                old = ch_mod.uup_channel(cat)
                old["enabled"] = True
                cfg["channels"].append(old)
        # v2 -> v3：从「每天定时跑一次」改成「哨兵常驻，每隔 N 分钟看一次」。
        # 新增的键由 DEFAULTS 自动补齐，这里只需要表达「改用哨兵」这个意图：
        # 老配置原来是 daily + 开机补跑，对应过来就是哨兵常驻 + 登录时启动。
        if ver < 3:
            cfg["watch_enabled"] = True
        # api_key_file / api_key_index 已废弃：Key 现在只在设置界面里手填。
        # 读进来就丢掉，免得又写回 config.json。
        for k in ("api_key_file", "api_key_index"):
            cfg.pop(k, None)
    cfg["schema"] = SCHEMA
    cfg["channels"] = [ch_mod.norm_channel(c) for c in (cfg.get("channels") or [])]
    if not cfg["channels"]:
        cfg["channels"] = [ch_mod.norm_channel(c)
                           for c in copy.deepcopy(ch_mod.DEFAULT_CHANNELS)]
    return cfg


def save_config(cfg):
    cfg = dict(cfg)
    cfg["schema"] = SCHEMA
    cfg["channels"] = [ch_mod.norm_channel(c) for c in cfg.get("channels", [])]
    _write_json(CONFIG_PATH, cfg)


def _write_json(path, obj):
    """先写临时文件再替换：读的人永远不会看到写了一半的半个 JSON。

    哨兵是常驻进程、设置界面随时可能保存配置，两边同时读写同一个文件是有可能的，
    所以这里必须保证「要么是旧的完整内容，要么是新的完整内容」。
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# --------------------------------------------------------------- 状态

_state_cache = None


def load_state(force=False):
    """读状态。force=True 时丢掉缓存重新读盘——

    哨兵是常驻进程，设置界面可能刚改过东西，所以它每一轮都要拿最新的，
    不能一直用进程启动时读到的那一份。
    """
    global _state_cache
    if _state_cache is None or force:
        st = _read_json(STATE_PATH, {})
        # 只有 v1（很老的那种扁平结构）才需要搬家。
        # 注意这里必须写 < 2：v2 -> v3 只是多了几个字段，结构没变，
        # 要是误当成 v1 去迁移，会把已有的频道记录全清掉。
        if st and int(st.get("schema") or 1) < 2:
            st = migrate_state(st)
        merged = copy.deepcopy(DEFAULT_STATE)
        merged.update(st or {})
        merged["schema"] = SCHEMA
        merged.setdefault("channels", {})
        merged.setdefault("pending_notify", [])
        _state_cache = merged
    return _state_cache


def migrate_state(old):
    """把 v1 的扁平状态挪到对应频道下。"""
    new = copy.deepcopy(DEFAULT_STATE)
    build = old.get("last_version")
    if build:
        cid = "fh:experimental"
        new["channels"][cid] = {
            "last_version": build,
            "last_check_date": old.get("last_check_date", ""),
            "last_report": old.get("last_report", ""),
            "reports": ([{"build": build, "date": old.get("last_check_date", ""),
                          "file": old.get("last_report", ""), "summary": ""}]
                        if old.get("last_report") else []),
            "ignored": [], "fail_count": 0,
        }
    new["last_run_date"] = old.get("last_run_date", "")
    return new


def save_state(state):
    global _state_cache
    _state_cache = state
    _write_json(STATE_PATH, state)


def channel_state(state, cid):
    cs = state["channels"].setdefault(cid, {
        "last_version": "", "last_check_date": "", "last_report": "",
        "reports": [], "ignored": [], "fail_count": 0})
    cs.setdefault("reports", [])
    cs.setdefault("ignored", [])
    cs.setdefault("fail_count", 0)
    # v3 新增：用于「同一个版本只提醒一次」。last_version 只管「我记到哪了」，
    # 这两个才管「我有没有为它吵过用户 / 写过报告」，两边分开才不会重复。
    cs.setdefault("reported_version", "")
    cs.setdefault("notified_builds", [])
    return cs


# --------------------------------------------------------- 哨兵的心跳

def load_watch():
    """读哨兵心跳。哨兵不在跑、或者已经很久没动静，就返回 dict(online=False)。"""
    d = _read_json(WATCH_PATH, {})
    if not isinstance(d, dict) or not d:
        return {"online": False}
    try:
        last = dt.datetime.fromisoformat(d.get("last_tick") or "")
        stale = (dt.datetime.now() - last).total_seconds()
    except Exception:
        stale = 1e9
    d["online"] = stale < 60        # 每几秒一次心跳，超过 60 秒没动静就算停了
    d["stale_seconds"] = int(stale) if stale < 1e9 else -1
    return d


def save_watch(info):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        _write_json(WATCH_PATH, info)
    except Exception:
        pass


def request_check_now():
    """设置界面点「立刻检测」：留个请求文件，让哨兵自己去查。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(CHECK_NOW_PATH, "w", encoding="utf-8") as f:
            f.write(dt.datetime.now().isoformat(timespec="seconds"))
        return True
    except Exception:
        return False


def take_check_now():
    """哨兵取走请求（取到就删掉，避免重复触发）。"""
    try:
        if os.path.exists(CHECK_NOW_PATH):
            os.remove(CHECK_NOW_PATH)
            return True
    except Exception:
        pass
    return False


def request_exit():
    """请哨兵「完全关闭」：设置界面和托盘菜单都走这里。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(EXIT_REQ_PATH, "w", encoding="utf-8") as f:
            f.write(dt.datetime.now().isoformat(timespec="seconds"))
        return True
    except Exception:
        return False


def take_exit_request():
    """哨兵取走退出请求。"""
    try:
        if os.path.exists(EXIT_REQ_PATH):
            os.remove(EXIT_REQ_PATH)
            return True
    except Exception:
        pass
    return False


def patch_config(**kv):
    """只改几个键（读-改-写）。

    设置界面和哨兵都可能用它切开关（比如「完全关闭」把 watch_enabled 设成 False）。
    哨兵每一轮都会重读配置，所以改完不用重启它。
    """
    cfg = load_config()
    cfg.update(kv)
    save_config(cfg)
    return cfg


# --------------------------------------------------------------- 杂项

def resolve_api_key(cfg):
    return (cfg.get("api_key") or "").strip()


def mask_key(key):
    """给界面和日志用的脱敏形式：sk-abcd…wxyz。key 太短就整体打码。"""
    key = (key or "").strip()
    if len(key) < 12:
        return "*" * len(key)
    return f"{key[:7]}…{key[-4:]}"


def ensure_dirs(cfg=None):
    for d in (REPORT_DIR, LOG_DIR, (cfg or {}).get("report_dir") or REPORT_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
