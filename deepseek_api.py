# -*- coding: utf-8 -*-
"""DeepSeek 调用（关闭思考模式）与报告模板。"""
import json
import urllib.error
import urllib.request

SYSTEM_PROMPT = (
    "你是一名 Windows 内测版本更新分析师，服务对象是中文用户。用户会给你某个 Windows "
    "构建号的官方发布说明原文，你要把它整理成简洁、准确的中文更新报告。要求：\n"
    "1. 只依据给定原文，绝不编造官方没写的内容；原文没提到就说“官方说明中未提及”。\n"
    "2. 说人话：讲清楚“这次更新改变了什么、对用户有什么用”，不要逐句翻译，专有名词保留英文。\n"
    "3. 严格按用户给的模板输出 Markdown，不要加寒暄、解释或代码块包裹。\n"
    "4. 官方原文里的已知问题（Known issues）要如实列出；那是用户最关心的部分。\n"
    "5. 不要输出“原文开始/结束”这类字样，直接给报告。"
)

DETAIL_SPEC = {
    "简短": "篇幅尽量短：一句话总结不超过 40 字，更新概述 2 句，主要变更 3-4 条。",
    "标准": "篇幅适中：一句话总结一两句，更新概述 2-4 句，主要变更 4-7 条。",
    "详细": "篇幅可以长一些：更新概述 4-6 句，主要变更尽量覆盖原文每个改动点（可到 12 条），"
            "已知问题逐条列出，并给出对普通用户/内测用户的升级建议。",
}


def build_prompt(channel_name, build, prev_build, notes_url, notes_kind, notes_text,
                 date_str, detail="标准"):
    prev = prev_build or "（首次记录，无上一版本）"
    spec = DETAIL_SPEC.get(detail, DETAIL_SPEC["标准"])
    lines = [
        f"更新线（频道）：{channel_name}",
        f"构建号：{build}",
        f"上一版本：{prev}",
        f"检测日期：{date_str}",
        f"官方说明来源：{notes_url or '未能取到官方页面'}",
        "",
        f"整理要求：{spec}",
        "",
        "下面是微软官方发布说明原文（已去网页噪音，可能被截断）：",
        "----- 原文开始 -----",
        notes_text or ("（没有取到官方原文。请仅根据构建号和频道说明这是该频道的新构建，"
                       "并提醒用户查看微软官方发布说明，不要编造具体改动。）"),
        "----- 原文结束 -----",
        "",
        "请严格按以下模板输出（Markdown，标题层级和字段名保持不变）：",
        "",
        f"# {channel_name} 更新报告：{build}",
        "",
        f"- **更新线**：{channel_name}",
        f"- **构建号**：{build}",
        f"- **上一版本**：{prev}",
        f"- **检测时间**：{date_str}",
        f"- **官方来源**：{notes_url or '未获取到'}",
        "",
        "## 一句话总结",
        "（一句话说清这次更新最关键的变化）",
        "",
        "## 更新概述",
        "（普通用户视角，说人话）",
        "",
        "## 主要变更",
        "- **分类名**：这条改了什么、对用户有什么影响",
        "- **分类名**：……",
        "",
        "## 已知问题",
        "（官方列出的 known issues；没有就写“官方说明中未提及”）",
        "",
        "## 需要注意",
        "（兼容性 / 升级建议 / 该频道性质提醒；没有就写“官方说明中未提及”）",
    ]
    return "\n".join(lines)


def summarize(cfg, api_key, prompt, timeout=None):
    url = (cfg.get("api_base") or "https://api.deepseek.com").rstrip("/") + "/chat/completions"
    body = {
        "model": cfg.get("model") or "deepseek-flash",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": int(cfg.get("max_tokens") or 1600),
        "temperature": float(cfg.get("temperature") or 0.3),
        "stream": False,
    }
    if cfg.get("disable_thinking", True):
        body["thinking"] = {"type": "disabled"}

    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api_key})
    try:
        with urllib.request.urlopen(req, timeout=timeout or 180) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"DeepSeek HTTP {e.code}: {detail}") from e
    except Exception as e:
        raise RuntimeError(f"DeepSeek 请求失败: {type(e).__name__}: {e}") from e

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        raise RuntimeError("DeepSeek 返回格式异常: " +
                           json.dumps(data, ensure_ascii=False)[:400])


FALLBACK = """# {channel} 更新报告：{build}

- **更新线**：{channel}
- **构建号**：{build}
- **上一版本**：{prev}
- **检测时间**：{date}
- **官方来源**：{url}

## 一句话总结

检测到 {channel} 出现新构建 {build}（AI 概述未生成，以下为原始信息）。

## 更新概述

{overview}

## 主要变更

- 详见下方官方原文摘录；本次未能生成 AI 概述，原因：{err}

## 已知问题

官方说明中未提及。

## 需要注意

本条为兜底报告。修好 API 后，可以删掉 `state.json` 里该频道的 `last_version`
再手动跑一次 `python checker.py --force`，重生成正式报告。
"""


def fallback_report(channel_name, build, prev, date_str, url, notes_text, err):
    return FALLBACK.format(
        channel=channel_name, build=build, prev=prev or "（无）", date=date_str,
        url=url or "未获取到",
        overview=(notes_text or "未能获取官方发布说明原文。")[:900], err=err)
