# -*- coding: utf-8 -*-
"""把整个工具打包成单个 exe，输出到「应用程序」目录。

    python 打包.py            打包
    python 打包.py --verify   打包完顺便跑一次自检

打包出来的东西：
    应用程序\win升级报告.exe                双击 = 设置界面；计划任务/通知协议都指向它
    应用程序\使用说明.txt                   给用户看的说明

数据（config.json / state.json / reports / logs）仍然放在上一级目录，exe 会自动找到；
把 config.json 等一起放进「应用程序」里也能用，那样这个文件夹就是完全独立、可整体拷走的。
"""
import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE, "应用程序")
BUILD_DIR = os.path.join(BASE, "build")
EXE_NAME = "win升级报告"
HIDDEN = ["gui", "checker", "viewer", "reporter", "source", "deepseek_api",
          "notify", "channels", "config", "mdlite", "app", "watch", "gamesense",
          "tray"]
DATA = ["toast.ps1", "task.ps1", "icon.ico"]

README_TXT = """win升级报告
============

双击 win升级报告.exe 打开设置界面。

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

托盘图标：一眼看到它在后台跑
------------------------------
哨兵一启动，任务栏右下角就有「win升级报告」的托盘图标 —— 图标在 = 它在跑。
鼠标悬停能看到状态和上次检查时间。右键菜单可以：打开设置界面 / 立刻检测一次 /
静默 2 小时 / 打开报告总览 / 打开日志 / 完全关闭后台监控。

看不到图标？Windows 会把新出现的托盘图标默认塞进「隐藏的图标」（任务栏那个 ∧）里。
一次性设置：设置 → 个性化 → 任务栏 → 其他系统托盘图标 → 把 win升级报告 打开。

两种关闭方式
------------
设置界面右下角有两个按钮；点窗口右上角的 × 也会问你一次：
  * 关闭到托盘 —— 只关设置窗口，后台哨兵继续跑，有新版本照样通知你。
    随时双击托盘图标就能重新打开设置。
  * 完全关闭后台监控 —— 连后台哨兵一起停掉，托盘图标消失，以后开机也不自动起。
    计划任务本身留着，回「计划任务」页点「启动后台监控」就能恢复。

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
config.json / state.json / reports / logs 在上一级目录（也就是 win升级报告 文件夹里）。
想让它完全独立：把这些一起拷进本文件夹，exe 会优先用同目录的数据。

需要管理员权限的操作
--------------------
「安装 / 更新计划任务」会弹一次 UAC（Windows 计划任务必须提权才能注册）。
安装时会顺手把旧版的每日任务（WinUpdReport_Daily）卸掉，它已经不需要了。
不想给权限就用「装/卸 登录自启」，效果一样（也是登录时启动哨兵）。

排查「怎么没动静了」
--------------------
1. 设置界面「计划任务」页 → 看「哨兵：运行中 / 没有在运行」。
2. 「状态与日志」页 → 看 logs\\checker.log 里 [哨兵] 开头的行。
3. 命令行跑一次：win升级报告.exe --watch --status
"""


def run(cmd, **kw):
    print(">", " ".join(cmd))
    return subprocess.call(cmd, **kw)


def main():
    os.makedirs(APP_DIR, exist_ok=True)
    for name in DATA:
        p = os.path.join(BASE, name)
        if not os.path.exists(p):
            print("缺少资源文件:", p)
            return 2

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onefile", "--noconsole",
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
    cmd.append(os.path.join(BASE, "app.py"))

    rc = run(cmd, cwd=BASE)
    if rc != 0:
        print("PyInstaller 失败，退出码", rc)
        return rc

    exe = os.path.join(APP_DIR, EXE_NAME + ".exe")
    if not os.path.exists(exe):
        print("没找到产物:", exe)
        return 3
    size = os.path.getsize(exe) / 1024 / 1024
    print(f"\n打包完成: {exe}  ({size:.1f} MB)")

    with open(os.path.join(APP_DIR, "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(README_TXT)
    print("已写使用说明.txt")

    if "--verify" in sys.argv:
        print("\n跑一次自检（窗口程序没有控制台，结果看日志文件）…")
        subprocess.call([exe, "--selftest"], cwd=BASE)
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
