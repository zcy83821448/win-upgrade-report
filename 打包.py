# -*- coding: utf-8 -*-
"""打包成「绿色文件夹版」。

    python 打包.py                打绿色文件夹版
    python 打包.py --zip          顺带压成一个可直接发布的 zip
    python 打包.py --verify       打完顺便跑一次自检

为什么是绿色文件夹版
    程序要带 Python 运行时、pythonnet 和 WebView2 桥，单独一个 exe 每次
    启动都得先解压到 %TEMP%\\_MEIxxxx，慢，而且容易被临时文件清理工具、
    杀毒软件干扰。绿色文件夹版没有解包这一步：
      * 启动更快（冷启动约 1 秒，托盘再打开是毫秒级）
      * 完全没有临时目录，整类问题从根上不存在
      * 托盘图标的路径也是固定的（图标"显示/隐藏"设置不会每次启动就作废）
    代价是得到一个文件夹而不是一个文件，压缩成 zip 发布即可。

打包出来的东西
    绿色版：应用程序\\win升级报告\\             整个文件夹（里面是 exe + _internal）
            应用程序\\win升级报告\\使用说明.txt
            应用程序\\win升级报告-绿色版.zip       （加 --zip 才有）

数据（config.json / state.json / reports / logs）放在 exe 同目录 —— 也就是绿色文件夹里，
所以整包可以拷走、解压即用。
"""
import os
import shutil
import subprocess
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE, "应用程序")
BUILD_DIR = os.path.join(BASE, "build")
EXE_NAME = "win升级报告"
GREEN_DIR = os.path.join(APP_DIR, EXE_NAME)                 # 绿色版整个文件夹
ZIP_PATH = os.path.join(APP_DIR, f"{EXE_NAME}-绿色版.zip")   # 发布用的 zip
HIDDEN = ["gui", "checker", "viewer", "reporter", "source", "deepseek_api",
          "notify", "channels", "config", "mdlite", "app", "watch", "gamesense",
          "tray", "selfcheck", "hotwin",
          # 界面层：pywebview（WebView2 原生窗口）。平台模块是运行时动态导入的，
          # PyInstaller 静态分析看不到，必须显式写出来；clr 是 pythonnet 的入口。
          "webview", "webview.platforms.winforms", "webview.platforms.win32",
          "webview.http", "clr", "clr_loader"]
# 用不到的模块一律别打进来。PyInstaller 会把 pywebview 里所有平台的
# import 都分析一遍，环境里装了 PyQt5 就会把 47MB 的 Qt 拖进安装包；
# win32com/Pythonwin 也是只在老代码里用过、现在完全没用的东西。
# 这些文件不会在启动时 import，但它们会让杀毒软件每次启动多扫几十 MB。
EXCLUDES = [
    "PyQt5", "sip", "qtpy",
    "webview.platforms.qt", "webview.platforms.gtk",
    "webview.platforms.cocoa", "webview.platforms.android",
    "webview.platforms.cef", "webview.platforms.mshtml",
    "win32com", "pywin", "Pythonwin", "win32ui", "win32api",
    "pythoncom", "pywintypes", "tkinter", "_tkinter",
]
DATA = ["toast.ps1", "task.ps1", "icon.ico", "tray.ico"]
DATA_DIRS = ["icons", "webui"]   # icons: 托盘图标样式；webui: 设置界面的 HTML/CSS/JS

# 绿色文件夹里属于「用户数据」的，重新打包时必须原样保留：
# PyInstaller 会先删掉整个 dist 目录再生成，不备份的话用户的 Key、历史报告、
# 日志就一起没了。
KEEP_DATA = ["config.json", "state.json", "reports", "logs"]

README_TXT = """win升级报告
============

怎么用（绿色文件夹版）
----------------------
整个文件夹解压到哪都行（桌面、D 盘、U 盘都可以），双击里面的
「win升级报告.exe」就打开设置窗口。不需要安装，也不需要管理员权限。

设置窗口是原生窗口：没有浏览器、没有地址栏，整个窗口（标题栏、最小化/最大化/关闭按钮）
都是程序自己画的，拖动标题栏移动，四边四角可以缩放。界面用 WebView2 渲染，
Win10/11 一般自带；老机器缺了会提示装一下 Edge WebView2 Runtime。
后台哨兵不依赖它，只有设置窗口需要。

为什么是文件夹：程序要带 Python 运行时和 WebView2 的 .NET 桥，做成单个 exe
的话每次启动都得先解压到临时目录，慢，而且容易被杀毒软件、清理工具干扰。
文件夹版没有这一步，启动更快，也没有临时目录可以出问题。

文件夹里其它东西（_internal、webui 等）是程序运行需要的，别删；
也别把 exe 单独拖出来，那样它找不到自己的零件。

你的数据（config.json、报告、日志）就存在这个文件夹里，
所以整个文件夹可以直接拷到别的电脑上接着用。

它做什么
--------
登录后常驻一个小小的「哨兵」，每隔几分钟问一次微软官方看板「有没有变」：

  * 官方没发新版本 —— 服务器只回一句「没变」，传输 0 字节。
    不解析、不调 AI、不发通知、日志也不刷，等于什么都没干。
  * 官方发了新版本 —— 抓官方发布说明 → 让 AI 写成中文报告 → 存成文件
    → 弹一条通知。通知上两个按钮：〔查看报告〕打开本机的中文报告，
    〔官方原文〕打开微软那篇说明。

从「微软发布」到「你收到通知」通常 2 ～ 5 分钟（其中 AI 总结占 30 ～ 90 秒）。
以前是每天 12:00 查一次，经常要等到第二天中午才知道；现在不用等了。

AI 只干一件事
-------------
判断有没有新版本、比构建号、解析网页，全是普通代码，不花 AI 额度。
AI 只用来把抓到的官方说明总结成中文报告，而且：
  * 没新版本时，一次都不调
  * 同一个版本只调一次（不重复总结、不重复收费）

玩游戏时彻底静默
----------------
判定到你在玩全屏游戏（无边框全屏也算）时，工具会彻底什么都不干：
不联网、不调 AI、不通知、不写盘。游戏一关，立刻补查一次。

判定规则：有窗口铺满整块屏幕 + 没有标题栏 + 不是系统组件/叠加层。
如果某个程序被误判（例如某个全屏播放器），在设置窗口「通知」页点
「把当前前台程序加进忽略名单」就行；也可以用「现在静默 2 小时」手动闭嘴。
（全屏看视频也会触发这个安静模式 —— 这是故意的，不想在你专注时打扰你。）

出问题了怎么办：点「体检并自动修复」
------------------------------------
左侧栏底部有个「体检并自动修复」按钮（托盘右键菜单里也有）。它会自己检查
8 个地方，**能自己修的直接修掉**，然后用人话告诉你结果，比如：

    ✔ 后台监控：本来没在跑，我已经帮你启动了
    ✔ 开机自动启动：本来没设，我已经帮你设好了
    ✔ 临时文件残留：清掉了 1 个以前没删干净的临时目录
    ✓ 连微软官网：能连上（200）

它会检查：存报告的位置能不能写、AI 的 Key 填没填、有没有勾更新线、
后台在不在跑、托盘图标挂上没挂上、开机自启设没设、有没有自己留下的垃圾临时文件、
能不能连上微软官网。不用你懂技术，跑一遍就知道哪儿不对。

如果设置窗口本身打不开：右键托盘图标 →「打开程序文件夹」，
直接双击里面的 win升级报告.exe 就行。

托盘图标：一眼看到它在后台跑
------------------------------
哨兵一启动，任务栏右下角就有「win升级报告」的托盘图标 —— 图标在 = 它在跑。
鼠标悬停能看到状态和上次检查时间。右键菜单可以：打开设置窗口 / 立刻检测一次 /
静默 2 小时 / 打开报告总览 / 打开日志 / 完全关闭后台监控。

看不到图标？Windows 会把新出现的托盘图标默认塞进「隐藏的图标」（任务栏那个 ∧）里。
一次性设置：设置 → 个性化 → 任务栏 → 其他系统托盘图标 → 把 win升级报告 打开。

图标样式可以换
--------------
托盘图标有 9 套样式（线条粗细：细/标准/粗  ×  箭头占位：小/标准/大）。
在设置窗口「通知」页最下面的「任务栏图标」里挑，选完立刻生效，不用重启哨兵。
每款都带一张实际效果的预览图。

为什么不是选「16px / 20px」：托盘槽位大小是系统定的（你这台是 16x16），
选哪一档分辨率都不会让屏幕上的图标变大变小；真正改变观感的是「箭头占多大地方」，
所以做成了「占位」这个维度。每套 .ico 里仍然装齐了 16/20/24/32/40/48/64/256 八档。

两种关闭方式
------------
窗口标题栏是程序自己画的：右上角是最小化 / 最大化 / 关闭，左侧栏底部是
「关闭窗口」和「完全退出」（不弹确认框，点哪个就干哪个）：

  * 〔关闭窗口〕（标题栏 × 或左侧栏底部）
      - 只关设置窗口，后台哨兵继续跑，有新版本照样通知你。
        随时双击托盘图标就能重新打开设置。
  * 〔完全退出〕（左侧栏底部）
      - 连后台哨兵一起停掉，托盘图标消失，以后开机也不自动起。
        想恢复：重新双击 exe，点概览页右上角的「开启后台监控」。
  * 拖动标题栏移动窗口；双击标题栏最大化/还原；拖四边四角缩放。

命令行的用法
------------
win升级报告.exe                     打开设置窗口
win升级报告.exe --watch             常驻哨兵（计划任务 / 登录自启用这个）
win升级报告.exe --watch --status    看哨兵现在活着没有
win升级报告.exe --watch --once      只跑一轮就退出（排查用）
win升级报告.exe --watch --no-tray   不挂托盘图标（排查图标问题时用）
win升级报告.exe --check             手动跑一次检测
win升级报告.exe --list-channels     列出更新线和当前记录
win升级报告.exe --view index        打开报告总览页
win升级报告.exe --task query        查计划任务状态（含限时设置）
win升级报告.exe --selftest          自检，结果写在 ..\\logs\\自检报告.txt

数据放在哪
----------
就在这个文件夹里：config.json / state.json / reports / logs。
所以整个文件夹拷到哪都能接着用（包含你的 API Key 和全部历史报告）。

需要管理员权限的操作
--------------------
「安装 / 更新计划任务」会弹一次 UAC（Windows 计划任务必须提权才能注册）。
安装时会顺手把旧版的每日任务（WinUpdReport_Daily）卸掉，它已经不需要了。
不想给权限就用「自启与后台」页的「一键设置开机自启」，效果一样
（往「启动」文件夹放个快捷方式，登录时启动哨兵）。

排查「怎么没动静了」
--------------------
先点左侧栏底部的「体检并自动修复」—— 绝大多数情况它自己就修好了，
还会用人话告诉你哪儿不对。还不行的话：
1. 「概览」页顶部状态卡片 → 是「后台正在运行」还是「后台没在运行」。
2. 「自启与后台」页 → 看后台状态、托盘图标挂上没有。
3. 「日志与诊断」页 → 看 logs\\checker.log 里 [哨兵] 开头的行。
4. 命令行跑一次：win升级报告.exe --watch --status
"""


def run(cmd, **kw):
    print(">", " ".join(cmd))
    return subprocess.call(cmd, **kw)


def make_zip(src_dir, zip_path, top_name, exclude=()):
    """把绿色文件夹压成发布用的 zip。

    注意压缩包里要带一层同名目录（解压出来就是一个 win升级报告 文件夹，
    而不是一堆散文件散在当前目录里）。
    exclude 里的名字（config.json / state.json / reports / logs）不打进去：
    发布包不该带用户自己的 Key 和历史数据。
    """
    if os.path.exists(zip_path):
        os.remove(zip_path)
    excl = {os.path.normcase(os.path.join(src_dir, e)) for e in exclude}

    def excluded(full):
        n = os.path.normcase(full)
        return any(n == e or n.startswith(e + os.sep) for e in excl)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(src_dir):
            for f in files:
                full = os.path.join(root, f)
                if excluded(full):
                    continue
                rel = os.path.relpath(full, src_dir)
                z.write(full, os.path.join(top_name, rel))
    return zip_path


def _backup_user_data():
    """把绿色文件夹里的用户数据临时备份出来（打包会被清空目录）。"""
    import tempfile
    bak = tempfile.mkdtemp(prefix="winupd_pkg_")
    kept = []
    for name in KEEP_DATA:
        src = os.path.join(GREEN_DIR, name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(bak, name)
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            kept.append(name)
        except Exception as e:                                   # noqa: BLE001
            print("  备份", name, "失败：", e)
    print("  已备份用户数据：", "、".join(kept) if kept else "（没有）")
    return bak, kept


def _restore_user_data(bak, kept):
    """打包完成后把用户数据放回去。"""
    for name in kept:
        src = os.path.join(bak, name)
        dst = os.path.join(GREEN_DIR, name)
        try:
            if os.path.isdir(src):
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            print("  已还原", name)
        except Exception as e:                                   # noqa: BLE001
            print("  还原", name, "失败：", e)
    shutil.rmtree(bak, ignore_errors=True)


def main():
    os.makedirs(APP_DIR, exist_ok=True)
    for name in DATA:
        p = os.path.join(BASE, name)
        if not os.path.exists(p):
            print("缺少资源文件:", p)
            return 2
    for d in DATA_DIRS:
        p = os.path.join(BASE, d)
        if not os.path.isdir(p):
            print("缺少资源目录:", p)
            return 2

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onedir", "--noconsole",
           "--name", EXE_NAME,
           "--icon", os.path.join(BASE, "icon.ico"),
           "--distpath", APP_DIR,
           "--workpath", BUILD_DIR,
           "--specpath", BUILD_DIR,
           "--log-level", "WARN"]
    for n in HIDDEN:
        cmd += ["--hidden-import", n]
    for n in EXCLUDES:
        cmd += ["--exclude-module", n]
    for d in DATA:
        cmd += ["--add-data", f"{os.path.join(BASE, d)};."]
    for d in DATA_DIRS:
        cmd += ["--add-data", f"{os.path.join(BASE, d)};{d}"]
    cmd.append(os.path.join(BASE, "app.py"))

    # 绿色文件夹版里可能有用户自己的 config.json / 历史报告 / 日志。
    # PyInstaller 会整个清掉目标目录，所以先备份、打包后原样放回。
    bak, kept = _backup_user_data()

    try:
        rc = run(cmd, cwd=BASE)
    finally:
        if bak:
            _restore_user_data(bak, kept)
    if rc != 0:
        print("PyInstaller 失败，退出码", rc)
        return rc

    # ---------------- 绿色文件夹版 ----------------
    exe = os.path.join(GREEN_DIR, EXE_NAME + ".exe")
    if not os.path.exists(exe):
        print("没找到产物:", exe)
        return 3
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _d, fs in os.walk(GREEN_DIR) for f in fs)
    print(f"\n打包完成（绿色文件夹版）: {GREEN_DIR}")
    print(f"  文件夹总大小 {total / 1024 / 1024:.1f} MB（启动不需要解包）")

    # 说明文件放进文件夹里，解压出来就是一个自解释的目录
    with open(os.path.join(GREEN_DIR, "使用说明.txt"), "w",
              encoding="utf-8") as f:
        f.write(README_TXT)
    print("已写 使用说明.txt")
    # 注意：_internal 里的东西一个都别删。base_library.zip 是 Python 标准库，
    # 删了程序直接跑不起来（别问怎么知道的）。

    if "--zip" in sys.argv:
        zp = make_zip(GREEN_DIR, ZIP_PATH, EXE_NAME, exclude=KEEP_DATA)
        print(f"已打包发布用的 zip: {zp}"
              f"  ({os.path.getsize(zp) / 1024 / 1024:.1f} MB)")

    print("\n【这台机器怎么用】装完直接双击 exe 就打开设置窗口；")
    print("想让它在后台一直盯着，进「自启与后台」页点「一键设置开机自启」。")

    if "--verify" in sys.argv:
        print("\n跑一次自检（窗口程序没有控制台，结果看日志文件）…")
        subprocess.call([exe, "--selftest"], cwd=os.path.dirname(exe))
        import time
        time.sleep(2)
        # 打包后 BASE_DIR 是 exe 同目录（配置在那里），源码运行时是工程目录。
        log = ""
        for cand in (os.path.join(os.path.dirname(exe), "logs", "自检报告.txt"),
                     os.path.join(BASE, "logs", "自检报告.txt")):
            if os.path.exists(cand):
                log = cand
                break
        if log:
            print("-" * 60)
            with open(log, encoding="utf-8") as f:
                print(f.read())
            print("-" * 60)
        else:
            print("没生成自检报告，检查", log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
