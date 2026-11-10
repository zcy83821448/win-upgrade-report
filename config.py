# -*- coding: utf-8 -*-
"""配置与状态。所有文件都在本脚本所在目录下。

这一层负责整个程序的「落盘可靠性」，动之前先看完：

* 配置/状态/watcher 心跳都可能有**两个进程同时读写**（设置窗口 + 常驻哨兵），
  所以写盘统一走 `_write_json`：唯一临时文件 → 校验 → 原子替换 → 失败重试。
* 所有写操作通过一个**跨进程命名互斥体**串行（`data_lock()`），
  Linux 上没这层也无所谓，Windows 上 `os.replace` 遇到别人正在读会直接
  PermissionError，所以重试比锁本身还重要。
* 写之前把上一份好文件复制成 `.bak`；读的时候主文件坏了会自动从 `.bak` 恢复，
  并把坏文件改名留证、写进日志——绝不静默把用户配置重置成默认值。
"""
import os
import re
import sys
import json
import copy
import time
import shutil
import datetime as dt
import contextlib
import ctypes
import ctypes.wintypes as wt

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
    """找打包进去的静态文件（toast.ps1 / task.ps1 / icon.ico / webui 等）。"""
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
#   * 它写得比 state.json 频繁得多（每十几秒一次），分开放就不会和检测结果互相打架
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
    # 设置界面/托盘里的手动静默：存一个截止时间（ISO 字符串），
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
    "open_report_on_click": False,    # 点报告时直接用系统浏览器打开；关着就在界面里读
    "app_id": "WinUpdReport.App",
    "report_dir": REPORT_DIR,
    "max_context_chars": 16000,
    "keep_reports": 200,              # 每个频道最多保留多少份报告

    # ---- 个性化（背景图 + 从图片取色）----
    "personalize_bg": "",             # 背景图路径（相对程序目录，如 personalize/bg.jpg）
    "personalize_accent": "",         # 从背景图算出的强调色 #RRGGBB；空 = 默认墨蓝
    "personalize_blur": 15,           # 信息卡片背后的高斯模糊（px）
    "personalize_card_alpha": 70,     # 信息卡片白色蒙层浓度（%）
    "personalize_scrim_alpha": 0,     # 整张背景图的蒙层（%），深色图调高更好读
}

DEFAULT_STATE = {
    "schema": SCHEMA,
    "channels": {},          # id -> {last_version, last_check_date, last_report, reports[], ignored[], fail_count}
    "last_run_date": "",     # 最近一次「定时」检测的日期
    "last_logon_date": "",   # 最近一次「开机/登录补跑」的日期
    "pending_notify": [],    # 静默时段攒下来的通知
    "last_error": "",
    "first_seen": "",
    "error_notified": "",    # 已经为这一轮连续失败提醒过一次（避免每 5 分钟弹一次）
}

# ============================================================ 跨进程写锁
# 一个进程里可能同时有 GUI 线程 + 后台线程写盘；GUI 和哨兵又是两个进程。
# 命名互斥体在 Windows 上天然跨进程、进程崩溃时由系统自动释放（WAIT_ABANDONED），
# 不会留下「死锁文件」。
DATA_LOCK_NAME = r"Local\WinUpdReportDataLock"
WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 0x80
LOCK_TIMEOUT_MS = 5000

_k32 = None
try:
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateMutexW.restype = ctypes.c_void_p
    _k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    _k32.WaitForSingleObject.restype = wt.DWORD
    _k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wt.DWORD]
    _k32.ReleaseMutex.restype = wt.BOOL
    _k32.ReleaseMutex.argtypes = [ctypes.c_void_p]
    _k32.CloseHandle.restype = wt.BOOL
    _k32.CloseHandle.argtypes = [ctypes.c_void_p]
except Exception:                                    # 非 Windows / 极度受限环境
    _k32 = None


def _warn(msg):
    """把「存储层自救」这类事件写进程序日志，界面「日志与诊断」里能看到。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} [WARN] [存储] {msg}"
        p = os.path.join(LOG_DIR, "checker.log")
        # 这个日志由 checker 负责轮转；这里只是偶尔追加一行，不会把文件撑爆。
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


@contextlib.contextmanager
def data_lock(timeout_ms=LOCK_TIMEOUT_MS):
    """跨进程写锁。取不到锁也继续执行（靠唯一临时文件和重试兜底），只是记一笔。"""
    handle = None
    acquired = False
    if _k32 is not None:
        try:
            handle = _k32.CreateMutexW(None, False, DATA_LOCK_NAME)
            if handle:
                r = _k32.WaitForSingleObject(handle, int(timeout_ms))
                acquired = r in (WAIT_OBJECT_0, WAIT_ABANDONED)
        except Exception:
            acquired = False
    if not acquired:
        _warn("写盘锁等待超时/不可用，改用「唯一临时文件 + 重试」继续写")
    try:
        yield acquired
    finally:
        if handle:
            try:
                if acquired:
                    _k32.ReleaseMutex(handle)
            except Exception:
                pass
            try:
                _k32.CloseHandle(handle)
            except Exception:
                pass


# ============================================================ 原子写 / 容错读

def _unique_tmp(path):
    """临时文件名必须带进程/线程/纳秒：两个进程共用一个 `.tmp` 时内容会交错，
    实测会把 JSON 写成「Extra data」坏文件——这是这层要根治的第一个坑。"""
    import threading
    return (f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
            f".{time.time_ns() % 10 ** 9}")


def _remove_quietly(path):
    try:
        os.remove(path)
    except Exception:
        pass


def _replace_with_retry(src, dst, attempts=15, base_delay=0.02):
    """Windows 上目标文件被别人以读取方式打开时，os.replace 会抛 PermissionError。

    那通常只持续几毫秒（别人 JSON 读到一半），所以短暂退避重试即可；重试到上限
    还不行就抛出去，让上层看到「确实存不进去」而不是假装成功。
    """
    last = None
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            last = e
        except OSError as e:
            last = e
        time.sleep(base_delay * (1 + min(i, 10) * 0.5))
    raise last if last is not None else OSError(f"无法替换 {dst}")


def _backup_previous(path):
    """.bak 永远保留「上一份完整可读的文件」，供损坏时恢复。"""
    try:
        if os.path.exists(path):
            shutil.copyfile(path, path + ".bak")
    except Exception:
        pass


def _write_json(path, obj, backup=False):
    """先写唯一临时文件 -> 回读校验 -> 原子替换。读的人永远看不到写了一半的 JSON。"""
    data = json.dumps(obj, ensure_ascii=False, indent=2)
    tmp = _unique_tmp(path)
    ok = False
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        # 发布前回读一次：序列化/编码问题必须在替换前发现，不能换进去再坏。
        with open(tmp, "r", encoding="utf-8") as f:
            json.load(f)
        if backup:
            _backup_previous(path)
        _replace_with_retry(tmp, path)
        ok = True
    finally:
        if not ok:
            _remove_quietly(tmp)


def _restore_from_file(src, dst):
    """把 src 的内容原子地写回 dst（用于 .bak 恢复）。"""
    tmp = _unique_tmp(dst)
    try:
        shutil.copyfile(src, tmp)
        _replace_with_retry(tmp, dst)
    finally:
        _remove_quietly(tmp)


def _read_json(path, default):
    """读 JSON；主文件坏了自动从 .bak 恢复，坏文件改名留证，绝不静默重置用户数据。"""
    def _load(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    last_err = None
    corrupt = False
    for attempt in range(6):
        try:
            return _load(path)
        except FileNotFoundError:
            last_err = None
            break
        except json.JSONDecodeError as e:
            last_err = e
            corrupt = True
            break
        except OSError as e:              # 杀软/别人正在替换：短暂重试
            last_err = e
            time.sleep(0.03 * (attempt + 1))

    bak = path + ".bak"
    try:
        bak_data = _load(bak)
    except Exception:
        bak_data = None
    if bak_data is not None:
        _warn(f"{os.path.basename(path)} 读取失败（{type(last_err).__name__ if last_err else '缺失'}），"
              f"已从 {os.path.basename(bak)} 自动恢复")
        try:
            _restore_from_file(bak, path)
        except Exception:
            pass
        return bak_data

    if os.path.exists(path):
        if corrupt:
            broken = f"{path}.corrupt-{dt.datetime.now():%Y%m%d-%H%M%S}"
            try:
                os.replace(path, broken)
                _warn(f"{os.path.basename(path)} 内容损坏且没有可用备份，"
                      f"已改名保留为 {os.path.basename(broken)}，本次使用默认值")
            except Exception:
                _warn(f"{os.path.basename(path)} 内容损坏且改名失败，本次使用默认值")
        elif last_err is not None:
            _warn(f"{os.path.basename(path)} 暂时读不出来（{type(last_err).__name__}: {last_err}），"
                  f"本次使用默认值")
    return copy.deepcopy(default)


# --------------------------------------------------------------- 配置

def _load_config_impl():
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


def load_config():
    return _load_config_impl()


def save_config(cfg):
    cfg = dict(cfg)
    cfg["schema"] = SCHEMA
    cfg["channels"] = [ch_mod.norm_channel(c) for c in cfg.get("channels", [])]
    with data_lock():
        _write_json(CONFIG_PATH, cfg, backup=True)


def merge_channels(new_channels):
    """把「自动发现的新频道」并进配置，只新增不覆盖。

    这是修「哨兵整份回写配置、把用户刚改的设置覆盖掉」的关键：
    哨兵检测结束时只调用它，而不是 save_config(旧快照)。

    返回合并后的完整配置；`added` 是真正新增的频道列表。
    """
    added = []
    with data_lock():
        cfg = _load_config_impl()
        known = {c["id"] for c in cfg["channels"]}
        for raw in (new_channels or []):
            try:
                c = ch_mod.norm_channel(raw)
            except Exception:
                continue
            if c["id"] in known:
                continue
            cfg["channels"].append(c)
            known.add(c["id"])
            added.append(c)
        if added:
            _write_json(CONFIG_PATH, cfg, backup=True)
    return cfg, added


def patch_config(**kv):
    """只改几个键（读-改-写，全程持锁）。

    设置界面和哨兵都可能用它切开关（比如「完全关闭」把 watch_enabled 设成 False）。
    哨兵每一轮都会重读配置，所以改完不用重启它。
    """
    with data_lock():
        cfg = _load_config_impl()
        cfg.update(kv)
        cfg["schema"] = SCHEMA
        cfg["channels"] = [ch_mod.norm_channel(c) for c in cfg.get("channels", [])]
        _write_json(CONFIG_PATH, cfg, backup=True)
    return cfg


# --------------------------------------------------------------- 状态

_state_cache = None


def _read_state_merged():
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
    return merged


def load_state(force=False):
    """读状态。force=True 时丢掉缓存重新读盘——

    哨兵是常驻进程，设置界面可能刚改过东西，所以它每一轮都要拿最新的，
    不能一直用进程启动时读到的那一份。
    """
    global _state_cache
    if _state_cache is None or force:
        _state_cache = _read_state_merged()
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


def _merge_state_with_disk(state):
    """保存状态前和磁盘对一次账，保住别人（尤其设置界面）刚写的「忽略列表」。

    场景：哨兵在生成报告（可能几分钟），期间用户在界面点了「忽略这个版本」。
    哨兵结束时如果整份覆盖，用户的忽略就丢了，下一轮还会重复报告/重复通知。
    """
    disk = _read_json(STATE_PATH, {})
    if not isinstance(disk, dict) or not disk:
        return state
    merged = copy.deepcopy(state)
    mch = merged.setdefault("channels", {})
    for cid, dcs in (disk.get("channels") or {}).items():
        if not isinstance(dcs, dict):
            continue
        if cid not in mch or not isinstance(mch[cid], dict):
            mch[cid] = copy.deepcopy(dcs)
            continue
        mem = mch[cid]
        disk_ignored = [str(x) for x in (dcs.get("ignored") or [])]
        mem_ignored = [str(x) for x in (mem.get("ignored") or [])]
        merged_ignored = sorted(set(disk_ignored) | set(mem_ignored))
        mem["ignored"] = merged_ignored
        for k, v in dcs.items():
            if k not in mem:              # 新版本程序加的字段，老进程不要弄丢
                mem[k] = copy.deepcopy(v)
    for k, v in disk.items():
        if k not in merged:
            merged[k] = copy.deepcopy(v)
    return merged


def save_state(state, merge_disk=True):
    """保存状态。merge_disk=True 时先合并磁盘上的频道状态（保住 ignored）。"""
    global _state_cache
    with data_lock():
        if merge_disk:
            state = _merge_state_with_disk(state)
        # 写盘前补 schema：少了它，下一次 load_state 会把这份状态误当成 v1
        # 去做「扁平结构搬家」，把 channels 整个清掉（测试里真踩到过）。
        state["schema"] = SCHEMA
        _write_json(STATE_PATH, state, backup=True)
    _state_cache = state
    return state


def update_state(mutator):
    """锁内「读最新状态 -> 改 -> 写」，给设置界面这类小改动用。

    返回 (新状态, mutator 的返回值)。这样界面点「忽略/恢复」不会再用
    几分钟前缓存的状态覆盖后台刚写好的 last_version / reports。
    """
    global _state_cache
    with data_lock():
        st = _read_state_merged()
        result = mutator(st)
        _write_json(STATE_PATH, st, backup=True)
    _state_cache = st
    return st, result


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


# ------------------------------------------------------------- 通用原子写

def atomic_write_text(path, text):
    """给报告/总览这类 HTML/Markdown 用：写一半时被浏览器打开会很难看。"""
    tmp = _unique_tmp(path)
    ok = False
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        _replace_with_retry(tmp, path)
        ok = True
    finally:
        if not ok:
            _remove_quietly(tmp)


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
    d["online"] = stale < WATCH_ONLINE_SECONDS
    d["stale_seconds"] = int(stale) if stale < 1e9 else -1
    return d


# 心跳每 HEARTBEAT_SECONDS 写一次，超过 WATCH_ONLINE_SECONDS 没动静就算停了。
# 存盘心跳由独立线程负责，所以即使主循环正在抓网页 / 等 AI（几十秒到几分钟），
# 界面也不会误显示「后台已停止」。
WATCH_ONLINE_SECONDS = 90


def save_watch(info):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        _write_json(WATCH_PATH, info, backup=False)
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


def child_env(extra=None):
    """给「由我们派生出去的子进程」一份干净的环境变量。

    ★ 这是踩了两次坑才定下来的，动之前先看完：

    单文件 exe 启动时会把自己解包到 %TEMP%\\_MEIxxxx，并把这个路径写进环境变量
    _MEIPASS2 交给它启动的子进程。子进程看到 _MEIPASS2 就**复用同一个目录、
    不再自己解包**（PyInstaller 本来是为了省时间）。于是出两个问题：

      1) 界面里点「开启后台监控」→ 派生出的哨兵住进了**界面的**临时目录。
         界面一退出就去删那个目录，可哨兵还在里面跑着、DLL 还映射着，删不掉，
         弹出：Warning  Failed to remove temporary directory: ...\\_MEIxxxx
         万一哪次删成功了，还在跑的哨兵会当场崩。

      2) 反过来，托盘的「打开设置界面」复用哨兵的目录；哨兵一退出把目录删了，
         设置界面下次就起不来，报 Failed to start embedded python interpreter。

    所以规矩很简单：**凡是我们自己派生我们的 exe / 我们的 .py，一定先把这个
    变量摘掉**，让子进程解包自己的一份、自己管自己的目录，谁也不欠谁。
    代价是每次派生多花 1~2 秒，换来绝对不出这类怪问题。
    """
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("_MEI") or k.startswith("_PYI"):
            env.pop(k, None)
    if extra:
        env.update(extra)
    return env


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
