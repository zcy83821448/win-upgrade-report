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
          "notify", "channels", "config", "mdlite", "app"]
DATA = ["toast.ps1", "task.ps1", "icon.ico"]

README_TXT = """win升级报告
============

双击 win升级报告.exe 打开设置界面。

它做什么
--------
每天定时（默认 12:00）静默去微软官方看板查你勾选的 Windows 更新线，
有新构建就用 DeepSeek 把官方发布说明整理成中文报告，然后弹一条通知。
检测过程没有窗口、不打扰你，只有真的出了新版本才通知一次。

命令行的用法
------------
win升级报告.exe                     打开设置界面
win升级报告.exe --check             跑一次检测（计划任务用的就是这个）
win升级报告.exe --check --force     忽略「今天跑过」，立刻检测
win升级报告.exe --list-channels     列出更新线和当前记录
win升级报告.exe --view index        打开报告总览页
win升级报告.exe --selftest          自检，结果写在 ..\\logs\\自检报告.txt

数据放在哪
----------
config.json / state.json / reports / logs 在上一级目录（也就是 win升级报告 文件夹里）。
想让它完全独立：把这些一起拷进本文件夹，exe 会优先用同目录的数据。

需要管理员权限的操作
--------------------
「安装 / 更新计划任务」会弹一次 UAC（Windows 计划任务必须提权才能注册）。
不想给权限就用「装/卸 登录自启」。
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
