# -*- coding: utf-8 -*-
"""生成托盘图标样式家族（极简线条箭头）和预览图。

    python 做图标.py            生成 icons\\ 下的全部图标 + 预览 + 样式清单
    python 做图标.py --open     顺便用系统默认看图程序打开总览预览

为什么是两个维度
----------------
你系统实测：托盘小图标槽位 = 16x16（100% DPI）。也就是说「在任务栏里用 16px
还是 20px」并不会改变屏幕上的大小（槽位由系统定），真正能改变观感的是：

    * 线条粗细 —— 细 / 标准 / 粗
    * 箭头占位 —— 小 / 标准 / 大   （箭头在 16 像素画布里占多大）

所以这里生成 3 x 3 = 9 套样式，每套都是一个**完整的多尺寸 ICO**
（16/20/24/32/40/48/64/256），换台高分屏电脑或改缩放比例时系统也能挑到合适的那档。

产出
----
    icons\\tray-<粗细>-<占位>.ico        9 套图标
    icons\\tray-<...>-preview.png        9 张给设置界面用的预览（tkinter 读不了 ICO）
    icons\\styles.json                  样式清单，界面和哨兵都读它
    icons\\总览预览.png                  给「照片」看的总览图
"""
import io
import json
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(HERE, "icons")

# ---- 两个维度 -----------------------------------------------------------------
WEIGHTS = [("thin", "细", 0.078), ("std", "标准", 0.100), ("bold", "粗", 0.130)]
FILLS = [("sm", "小", 0.52), ("std", "标准", 0.64), ("lg", "大", 0.80)]
DEFAULT_ID = "std-std"

# ---- 箭头几何（单位坐标 0~1，y 向下）：一根竖杆 + 两笔箭头 --------------------
BASE_GEO = [
    ((0.50, 0.82), (0.50, 0.20)),
    ((0.21, 0.49), (0.50, 0.20)),
    ((0.79, 0.49), (0.50, 0.20)),
]
BASE_FILL = 0.64          # 上面这套几何的占位比例
CENTER = (0.50, 0.51)

HALO = 0.045              # 光晕比线宽多出来的部分
HALO_ALPHA = 170          # 光晕透明度（浅色任务栏下靠它看得见）
SS = 8                    # 超采样倍数
SIZES = [16, 20, 24, 32, 40, 48, 64, 256]
LINE_RGB = (255, 255, 255)


def style_id(weight_key, fill_key):
    return f"{weight_key}-{fill_key}"


def geo_for(fill):
    """按占位比例缩放箭头几何。"""
    s = fill / BASE_FILL
    out = []
    for (x1, y1), (x2, y2) in BASE_GEO:
        out.append((
            (CENTER[0] + (x1 - CENTER[0]) * s, CENTER[1] + (y1 - CENTER[1]) * s),
            (CENTER[0] + (x2 - CENTER[0]) * s, CENTER[1] + (y2 - CENTER[1]) * s)))
    return out


def _mask(px, geo, width):
    """把三条线段画成蒙版（L 模式）。端点补圆点 => 圆头线帽。"""
    m = Image.new("L", (px, px), 0)
    d = ImageDraw.Draw(m)
    w = max(1, int(round(width)))
    for (x1, y1), (x2, y2) in geo:
        a, b = (x1 * px, y1 * px), (x2 * px, y2 * px)
        d.line([a, b], fill=255, width=w, joint="curve")
        r = w / 2.0
        for (cx, cy) in (a, b):
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return m


def render(size, stroke, fill):
    """渲染单个尺寸：先在大图上画、再降采样，所以线条干净、不断不糊。"""
    geo = geo_for(fill)
    px = size * SS
    core = _mask(px, geo, stroke * px)
    halo = _mask(px, geo, (stroke + HALO) * px)

    out = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    dark = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    dark.putalpha(halo.point(lambda v: v * HALO_ALPHA // 255))
    out = Image.alpha_composite(out, dark)
    white = Image.new("RGBA", (px, px), LINE_RGB + (255,))
    white.putalpha(core)
    out = Image.alpha_composite(out, white)
    return out.resize((size, size), Image.LANCZOS)


def write_ico(path, images):
    """自己拼 ICO 容器：每档尺寸都是独立渲染好的 PNG，所以每档都清晰。"""
    blobs = []
    for _s, im in images:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        blobs.append(buf.getvalue())
    n = len(images)
    head = struct.pack("<HHH", 0, 1, n)
    offset = 6 + 16 * n
    dirs = b""
    for (size, _im), blob in zip(images, blobs):
        wh = 0 if size >= 256 else size
        dirs += struct.pack("<BBBBHHII", wh, wh, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    with open(path, "wb") as f:
        f.write(head + dirs + b"".join(blobs))


def _font(size, bold=False):
    names = ("msyhbd.ttc", "msyh.ttc") if bold else ("msyh.ttc", "msyhbd.ttc")
    for n in names:
        p = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", n)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


# ------------------------------------------------------------------ 各种小图

def gui_preview(stroke, fill, path):
    """给设置界面用的小预览：深色条上放 16 / 24 / 32 三档 + 一个放大版。"""
    W, H = 250, 62
    img = Image.new("RGB", (W, H), (32, 32, 32))
    d = ImageDraw.Draw(img)
    x = 14
    for s in (16, 24, 32):
        ic = render(s, stroke, fill)
        img.paste(ic, (x, (H - s) // 2), ic)
        x += s + 20
    big = render(48, stroke, fill)
    img.paste(big, (W - 62, (H - 48) // 2), big)
    d.rectangle([0, 0, W - 1, H - 1], outline=(70, 70, 70))
    img.save(path, "PNG")


def contact_sheet(styles, path):
    """总览预览：每种样式在深色/浅色条上的真实尺寸效果。"""
    W = 1280
    row_h = 104
    H = 168 + row_h * len(styles) + 92
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f_title = _font(30, bold=True)
    f_sub = _font(15)
    f_name = _font(17, bold=True)
    f_small = _font(12)

    d.text((44, 26), "托盘图标样式：极简线条箭头（9 套）", font=f_title, fill=(17, 17, 17))
    d.text((44, 68), "你系统实测：托盘槽位 = 16 x 16 像素（100% DPI）。"
                     "所以下面每套都按真实 16px 展示，旁边是放大版方便看细节。",
           font=f_sub, fill=(110, 110, 110))
    d.text((44, 92), "竖排是「线条粗细」：细 / 标准 / 粗　　横排是「箭头占位」：小 / 标准 / 大",
           font=f_sub, fill=(110, 110, 110))
    d.text((44, 116), "深色条 = Windows 11 默认任务栏；浅色条 = 切成浅色主题的样子。"
                      "白色线条外面有一层淡描边，所以两边都看得清。",
           font=f_sub, fill=(110, 110, 110))

    x_name, x_dark, x_light = 44, 300, 810
    strip_w, strip_h = 490, 76

    y = 160
    for st in styles:
        d.text((x_name, y + 30), st["weight_zh"], font=f_name, fill=(30, 30, 30))
        d.text((x_name, y + 52), "· " + st["fill_zh"], font=f_small, fill=(120, 120, 120))
        if st["id"] == DEFAULT_ID:
            d.text((x_name, y + 6), "默认", font=f_small, fill=(10, 108, 255))

        d.rounded_rectangle([x_dark, y, x_dark + strip_w, y + strip_h],
                            radius=8, fill=(32, 32, 32))
        x = x_dark + 22
        for s in (16, 24, 32, 48):
            ic = render(s, st["stroke"], st["fill_ratio"])
            img.paste(ic, (x, y + (strip_h - s) // 2), ic)
            x += s + 26
        big = render(64, st["stroke"], st["fill_ratio"])
        img.paste(big, (x_dark + strip_w - 84, y + 6), big)

        d.rounded_rectangle([x_light, y, x_light + strip_w, y + strip_h],
                            radius=8, fill=(243, 243, 243))
        x = x_light + 22
        for s in (16, 24, 32, 48):
            ic = render(s, st["stroke"], st["fill_ratio"])
            img.paste(ic, (x, y + (strip_h - s) // 2), ic)
            x += s + 26
        big = render(64, st["stroke"], st["fill_ratio"])
        img.paste(big, (x_light + strip_w - 84, y + 6), big)

        y += row_h

    d.text((44, y + 16), "每套 .ico 里都装了 16/20/24/32/40/48/64/256 八个尺寸，"
                         "换到 125% / 150% 缩放的电脑上系统会自动挑合适的那档。",
           font=f_sub, fill=(90, 90, 90))
    d.text((44, y + 42), "设置界面「检测与通知」页可以直接切换样式，"
                         "换完哨兵几秒内就会把托盘图标换掉，不用重启。",
           font=f_sub, fill=(90, 90, 90))
    d.text((44, y + 68), "程序自己的图标 icon.ico 没动：它要显示在资源管理器里，"
                         "浅色背景上纯白线条会看不见。",
           font=f_sub, fill=(160, 120, 60))
    img.save(path, "PNG")
    return path


def main():
    os.makedirs(ICON_DIR, exist_ok=True)
    styles = []
    for wkey, wzh, stroke in WEIGHTS:
        for fkey, fzh, fill in FILLS:
            sid = style_id(wkey, fkey)
            ico_name = f"tray-{sid}.ico"
            prev_name = f"tray-{sid}-preview.png"
            images = [(s, render(s, stroke, fill)) for s in SIZES]
            write_ico(os.path.join(ICON_DIR, ico_name), images)
            gui_preview(stroke, fill, os.path.join(ICON_DIR, prev_name))
            styles.append({
                "id": sid, "weight": wkey, "weight_zh": wzh, "stroke": stroke,
                "fill": fkey, "fill_zh": fzh, "fill_ratio": fill,
                "name": f"{wzh} + {fzh}", "ico": ico_name, "preview": prev_name,
            })
            print(f"  {sid:10s} {ico_name}")

    manifest = {"default": DEFAULT_ID, "styles": styles}
    with open(os.path.join(ICON_DIR, "styles.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 兼容：tray.ico 始终等于默认样式（老配置没写样式时用它）
    dflt = next(s for s in styles if s["id"] == DEFAULT_ID)
    write_ico(os.path.join(HERE, "tray.ico"),
              [(s, render(s, dflt["stroke"], dflt["fill_ratio"])) for s in SIZES])

    sheet = contact_sheet(styles, os.path.join(ICON_DIR, "总览预览.png"))
    print(f"\n共 {len(styles)} 套样式 -> {ICON_DIR}")
    print(f"样式清单 -> {os.path.join(ICON_DIR, 'styles.json')}")
    print(f"总览预览 -> {sheet}")
    if "--open" in sys.argv:
        os.startfile(sheet)
        print("已用系统看图程序打开总览预览")
    return 0


if __name__ == "__main__":
    sys.exit(main())
