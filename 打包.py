# -*- coding: utf-8 -*-
"""打包成「绿色文件夹版」（默认）或「单文件版」（可选）。

    python 打包.py                打绿色文件夹版（推荐）—— 默认就是这个
    python 打包.py --zip          顺带压成一个可直接发布的 zip
    python 打包.py --onefile      打单文件版（备用）
    python 打包.py --verify       打完顺便跑一次自检

为什么默认改成绿色文件夹版
    单文件 exe 每次启动都要把自己解包到 %TEMP%\\_MEIxxxx，由此带来一串
    和临时目录有关的怪问题（解包失败、删不掉、子进程复用了别人的目录……），
    而且启动要 2 秒。绿色文件夹版没有解包这一步：
      * 启动只要 0.2 秒
      * 完全没有临时目录，整类问题从根上不存在
      * 托盘图标的路径也是固定的（图标"显示/隐藏"设置不会每次启动就作废）
    代价是得到一个文件夹而不是一个文件，压缩成 zip 发布即可。

打包出来的东西
    绿色版：应用程序\\win升级报告\\             整个文件夹（里面是 exe + _internal）
            应用程序\\win升级报告\\使用说明.txt
            应用程序\\win升级报告-v2.3-绿色版.zip   （加 --zip 才有）
    单文件：应用程序\\win升级报告.exe

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
ONEFILE = "--onefile" in sys.argv          # 默认绿色文件夹版；要单文件才加这个开关
GREEN_DIR = os.path.join(APP_DIR, EXE_NAME)                 # 绿色版整个文件夹
ZIP_PATH = os.path.join(APP_DIR, f"{EXE_NAME}-绿色版.zip")   # 发布用的 zip
HIDDEN = ["gui", "checker", "viewer", "reporter", "source", "deepseek_api",
          "notify", "channels", "config", "mdlite", "app", "watch", "gamesense",
          "tray", "selfcheck"]
DATA = ["toast.ps1", "task.ps1", "icon.ico", "tray.ico"]
DATA_DIRS = ["icons"]      # 托盘图标样式（9 套 .ico + 预览图 + styles.json）

README_TXT = """win升级报告
============

怎么用（绿色文件夹版）
----------------------
整个文件夹解压到哪都行（桌面、D 盘、U 盘都可以），双击里面的
「win升级报告.exe」就打开设置界面。不需要安装，也不需要管理员权限。

为什么是文件夹而不是一个 exe：单文件版每次启动都要把自己解压到临时目录，
启动慢（2 秒），而且容易被临时文件清理工具、杀毒软件干扰，冒出一些
莫名其妙的报错。文件夹版没有这一步 —— 启动 0.2 秒，也没有临时目录可以出问题。

文件夹里其它东西（_internal 等）是程序运行需要的，别删；
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
如果某个程序被误判（例如某个全屏播放器），在设置界面点
「把当前前台程序加进忽略名单」就行；也可以用「现在静默 2 小时」手动闭嘴。
（全屏看视频也会触发这个安静模式 —— 这是故意的，不想在你专注时打扰你。）

出问题了怎么办：点「体检并自动修复」
------------------------------------
界面左下角有个「体检并自动修复」按钮（托盘右键菜单里也有）。它会自己检查
8 个地方，**能自己修的直接修掉**，然后用人话告诉你结果，比如：

    ✔ 后台监控：本来没在跑，我已经帮你启动了
    ✔ 开机自动启动：本来没设，我已经帮你设好了
    ✔ 临时文件残留：清掉了 1 个以前没删干净的临时目录
    ✓ 连微软官网：能连上（200）

它会检查：存报告的位置能不能写、AI 的 Key 填没填、有没有勾更新线、
后台在不在跑、托盘图标挂上没挂上、开机自启设没设、有没有自己留下的垃圾临时文件、
能不能连上微软官网。不用你懂技术，跑一遍就知道哪儿不对。

如果设置界面本身打不开：右键托盘图标 →「打开程序文件夹」，
直接双击里面的 win升级报告.exe 就行。

托盘图标：一眼看到它在后台跑
------------------------------
哨兵一启动，任务栏右下角就有「win升级报告」的托盘图标 —— 图标在 = 它在跑。
鼠标悬停能看到状态和上次检查时间。右键菜单可以：打开设置界面 / 立刻检测一次 /
静默 2 小时 / 打开报告总览 / 打开日志 / 完全关闭后台监控。

看不到图标？Windows 会把新出现的托盘图标默认塞进「隐藏的图标」（任务栏那个 ∧）里。
一次性设置：设置 → 个性化 → 任务栏 → 其他系统托盘图标 → 把 win升级报告 打开。

图标样式可以换
--------------
托盘图标有 9 套样式（线条粗细：细/标准/粗  ×  箭头占位：小/标准/大）。
在设置界面「检测与通知」页最下面的「任务栏图标样式」下拉框里挑，
选完立刻生效，不用重启哨兵。下面还会显示一张实际效果的预览图。

为什么不是选「16px / 20px」：托盘槽位大小是系统定的（你这台是 16x16），
选哪一档分辨率都不会让屏幕上的图标变大变小；真正改变观感的是「箭头占多大地方」，
所以做成了「占位」这个维度。每套 .ico 里仍然装齐了 16/20/24/32/40/48/64/256 八档。

两种关闭方式
------------
设置界面右下角的按钮会跟着后台状态变（不弹确认框，点哪个就干哪个）：

  * 后台在跑时：〔关闭窗口（后台继续跑）〕＋〔完全退出（连后台一起停）〕
      - 关闭窗口：只关设置窗口，后台哨兵继续跑，有新版本照样通知你。
        随时双击托盘图标就能重新打开设置。
      - 完全退出：连后台哨兵一起停掉，托盘图标消失，以后开机也不自动起。
        想恢复：重新双击 exe，点顶部那个「开启后台监控」。
  * 后台没跑时：只显示〔关闭窗口〕—— 另一个按钮这时候没意义，就藏起来了。
    点窗口右上角的 × 等同于「关闭窗口」。

命令行的用法
------------
win升级报告.exe                     打开设置界面
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
不想给权限就用「开机自启」页的「一键设置开机自启」，效果一样
（往「启动」文件夹放个快捷方式，登录时启动哨兵）。

排查「怎么没动静了」
--------------------
先点界面左下角的「体检并自动修复」—— 绝大多数情况它自己就修好了，
还会用人话告诉你哪儿不对。还不行的话：
1. 界面顶部的状态卡片 → 是「后台正在运行」还是「后台没在运行」。
2. 「开机自启」页 → 看后台状态、托盘图标挂上没有。
3. 「日志与诊断」页 → 看 logs\\checker.log 里 [哨兵] 开头的行。
4. 命令行跑一次：win升级报告.exe --watch --status
"""


def run(cmd, **kw):
    print(">", " ".join(cmd))
    return subprocess.call(cmd, **kw)


def make_zip(src_dir, zip_path, top_name):
    """把绿色文件夹压成发布用的 zip。

    注意压缩包里要带一层同名目录（解压出来就是一个 win升级报告 文件夹，
    而不是一堆散文件散在当前目录里）。
    """
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(src_dir):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, src_dir)
                z.write(full, os.path.join(top_name, rel))
    return zip_path


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
           "--onefile" if ONEFILE else "--onedir", "--noconsole",
           "--name", EXE_NAME,
           "--icon", os.path.join(BASE, "icon.ico"),
           "--distpath", APP_DIR,
           "--workpath", BUILD_DIR,
           "--specpath", BUILD_DIR,
           "--log-level", "WARN"]
    for n in HIDDEN:
        cmd += ["--hidden-import", n]
    for d in DATA:
        cmd += ["--add-data", f"{os.path.join(BASE, d)};."]
    for d in DATA_DIRS:
        cmd += ["--add-data", f"{os.path.join(BASE, d)};{d}"]
    cmd.append(os.path.join(BASE, "app.py"))

    rc = run(cmd, cwd=BASE)
    if rc != 0:
        print("PyInstaller 失败，退出码", rc)
        return rc

    if ONEFILE:
        # ---------------- 单文件版（备用方案）----------------
        exe = os.path.join(APP_DIR, EXE_NAME + ".exe")
        if not os.path.exists(exe):
            print("没找到产物:", exe)
            return 3
        size = os.path.getsize(exe) / 1024 / 1024
        print(f"\n打包完成（单文件版）: {exe}  ({size:.1f} MB)")
        with open(os.path.join(APP_DIR, "使用说明.txt"), "w",
                  encoding="utf-8") as f:
            f.write(README_TXT)
        print("已写使用说明.txt")
    else:
        # ---------------- 绿色文件夹版（推荐）----------------
        exe = os.path.join(GREEN_DIR, EXE_NAME + ".exe")
        if not os.path.exists(exe):
            print("没找到产物:", exe)
            return 3
        total = sum(os.path.getsize(os.path.join(r, f))
                    for r, _d, fs in os.walk(GREEN_DIR) for f in fs)
        print(f"\n打包完成（绿色文件夹版）: {GREEN_DIR}")
        print(f"  文件夹总大小 {total / 1024 / 1024:.1f} MB"
              f"　（启动不需要解包，所以比单文件版更快）")

        # 说明文件放进文件夹里，解压出来就是一个自解释的目录
        with open(os.path.join(GREEN_DIR, "使用说明.txt"), "w",
                  encoding="utf-8") as f:
            f.write(README_TXT)
        print("已写 使用说明.txt")
        # 注意：_internal 里的东西一个都别删。base_library.zip 是 Python 标准库，
        # 删了程序直接跑不起来（别问怎么知道的）。

        if "--zip" in sys.argv:
            zp = make_zip(GREEN_DIR, ZIP_PATH, EXE_NAME)
            print(f"已打包发布用的 zip: {zp}"
                  f"  ({os.path.getsize(zp) / 1024 / 1024:.1f} MB)")

    print("\n【这台机器怎么用】装完直接双击 exe 就打开设置界面；")
    print("想让它在后台一直盯着，进「开机自启」页点「一键设置开机自启」。")

    if "--verify" in sys.argv:
        print("\n跑一次自检（窗口程序没有控制台，结果看日志文件）…")
        subprocess.call([exe, "--selftest"], cwd=os.path.dirname(exe))
        import time
        time.sleep(2)
        log = os.path.join(BASE, "logs", "自检报告.txt")
        if os.path.exists(log):
            print("-" * 60)
            with open(log, encoding="utf-8") as f:
                print(f.read())
            print("-" * 60)
        else:
            print("没生成自检报告，检查", log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
