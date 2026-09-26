# -*- coding: utf-8 -*-
"""配置与状态。所有文件都在本脚本所在目录下。"""
import os
import re
import sys
import json
import copy

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

SCHEMA = 2

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
    "proxy": "",                      # 例如 http://127.0.0.1:7897，留空直连

    # ---- 检测节奏 ----
    "check_time": "12:00",
    "interval_days": 1,
    "run_once_per_day": True,
    "quiet_hours": "",                # 例如 23:00-07:00：这期间发现更新先攒着，出了时段再通知
    "notify_on_error_after": 3,       # 连续失败几次后发一次错误通知，0 = 不通知

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
    "last_run_date": "",
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
        # v1 -> v2：以前只能盯一条 uupdump 链接
        if int(raw.get("schema") or 1) < SCHEMA:
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
            cfg["schema"] = SCHEMA
        # api_key_file / api_key_index 已废弃：Key 现在只在设置界面里手填。
        # 读进来就丢掉，免得又写回 config.json。
        for k in ("api_key_file", "api_key_index"):
            cfg.pop(k, None)
    cfg["channels"] = [ch_mod.norm_channel(c) for c in (cfg.get("channels") or [])]
    if not cfg["channels"]:
        cfg["channels"] = [ch_mod.norm_channel(c)
                           for c in copy.deepcopy(ch_mod.DEFAULT_CHANNELS)]
    return cfg


def save_config(cfg):
    cfg = dict(cfg)
    cfg["schema"] = SCHEMA
    cfg["channels"] = [ch_mod.norm_channel(c) for c in cfg.get("channels", [])]
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------- 状态

_state_cache = None


def load_state():
    global _state_cache
    if _state_cache is None:
        st = _read_json(STATE_PATH, {})
        if st and int(st.get("schema") or 1) < SCHEMA:
            st = migrate_state(st)
        merged = copy.deepcopy(DEFAULT_STATE)
        merged.update(st or {})
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
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def channel_state(state, cid):
    cs = state["channels"].setdefault(cid, {
        "last_version": "", "last_check_date": "", "last_report": "",
        "reports": [], "ignored": [], "fail_count": 0})
    cs.setdefault("reports", [])
    cs.setdefault("ignored", [])
    cs.setdefault("fail_count", 0)
    return cs


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
