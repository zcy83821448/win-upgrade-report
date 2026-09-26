# -*- coding: utf-8 -*-
"""报告查看器：把报告 Markdown 渲染成排版好的页面并在浏览器里打开。

由通知点击（winupdrept: 协议）或手动调用：
    pythonw viewer.py winupdrept:index              总览页
    pythonw viewer.py winupdrept:folder             报告文件夹
    pythonw viewer.py winupdrept:log                运行日志
    pythonw viewer.py winupdrept:r/<频道>/<构建号>    某一份具体报告
    pythonw viewer.py "路径\\xxx.md"                 指定报告
    pythonw viewer.py                              最新一份报告
"""
import os
import sys
import glob
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, REPORT_DIR                  # noqa: E402
from mdlite import render_page, render_raw                  # noqa: E402
import reporter                                             # noqa: E402


def render_and_open(md_path):
    with open(md_path, "r", encoding="utf-8") as f:
        md = f.read()
    title = os.path.splitext(os.path.basename(md_path))[0]
    html_path = os.path.splitext(md_path)[0] + ".html"
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(render_page(md, title))
    except Exception:
        html_path = md_path
    webbrowser.open("file:///" + html_path.replace("\\", "/"))
    return html_path


def newest_report(report_dir):
    files = glob.glob(os.path.join(report_dir, "**", "*.md"), recursive=True)
    files = [f for f in files if "_view" not in os.path.basename(f)]
    return max(files, key=os.path.getmtime) if files else None


def find_by_arg(cfg, arg):
    """r/<频道目录>/<构建号> -> 报告文件路径"""
    parts = arg.split("/")
    if len(parts) < 3:
        return None
    base = cfg.get("report_dir") or REPORT_DIR
    chan, build = parts[1], parts[2].replace(".", "-")
    pats = [os.path.join(base, chan, f"*{build}*.html"),
            os.path.join(base, chan, f"*{build}*.md")]
    for p in pats:
        hits = sorted(glob.glob(p), key=os.path.getmtime, reverse=True)
        if hits:
            return hits[0]
    return None


def main():
    arg = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    cfg = load_config()
    report_dir = cfg.get("report_dir") or REPORT_DIR
    low = arg.lower()

    if low.startswith("winupdrept:"):
        arg = arg.split(":", 1)[1]
        low = arg.lower()

    if low.startswith("http"):
        webbrowser.open(arg)
        return 0
    if low in ("folder", "--folder"):
        os.startfile(report_dir)                    # noqa: S606
        return 0
    if low in ("log", "--log"):
        log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "checker.log")
        os.startfile(log if os.path.exists(log) else os.path.dirname(log))  # noqa: S606
        return 0
    if low in ("index", "--index"):
        idx = os.path.join(report_dir, reporter.INDEX_NAME)
        if not os.path.exists(idx):
            from config import load_state
            st = load_state()
            names = {c["id"]: c.get("name", c["id"]) for c in cfg.get("channels", [])}
            reporter.write_index(cfg, st, names)
        webbrowser.open("file:///" + idx.replace("\\", "/"))
        return 0

    if low.startswith("r/"):
        target = find_by_arg(cfg, arg)
        if target:
            if target.endswith(".html"):
                webbrowser.open("file:///" + target.replace("\\", "/"))
                return 0
            render_and_open(target)
            return 0

    if arg and os.path.isfile(arg):
        return 0 if render_and_open(arg) else 1

    target = newest_report(report_dir)
    if not target:
        os.startfile(report_dir)                    # noqa: S606
        return 1
    render_and_open(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
