# -*- coding: utf-8 -*-
"""纯逻辑测试：更新线解析、静默时段、Markdown 渲染、报告命名、通知参数等。"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import channels            # noqa: E402
import checker             # noqa: E402
import reporter            # noqa: E402
import mdlite              # noqa: E402
import notify              # noqa: E402
import deepseek_api        # noqa: E402
import gamesense           # noqa: E402
import datetime as dt      # noqa: E402


class ChannelsTest(unittest.TestCase):
    def test_norm_channel_flighthub(self):
        c = channels.norm_channel({"id": "fh:beta"})
        self.assertEqual(c["id"], "fh:beta")
        self.assertEqual(c["source"], "flighthub")
        self.assertEqual(c["folder"], "beta")
        self.assertFalse(c["enabled"])

    def test_norm_channel_uupdump_from_url(self):
        c = channels.norm_channel({
            "url": "https://uupdump.net/known.php?q=category:w11-26h2"})
        self.assertEqual(c["id"], "uup:w11-26h2")
        self.assertEqual(c["category"], "w11-26h2")

    def test_build_sort_key(self):
        self.assertLess(channels.build_sort_key("26340.9596"),
                        channels.build_sort_key("26340.9882"))
        self.assertGreater(channels.build_sort_key("28120.1000"),
                           channels.build_sort_key("26340.9882"))

    def test_merge_discovered(self):
        configured = [{"id": "fh:experimental", "source": "flighthub",
                       "folder": "experimental", "enabled": True}]
        merged, added = channels.merge_discovered(configured, {
            "experimental": {}, "beta": {}})
        self.assertEqual([c["id"] for c in added], ["fh:beta"])
        self.assertEqual(len(merged), 2)

    def test_parse_flighthub(self):
        html = """
        <table><tr>
          <td>* 26100.1000</td>
          <td><a href="../release-notes/experimental/preview-build-26100-1000">
              10/01/2026 - Windows 11 build 26100.1000</a></td>
        </tr>
        <tr>
          <td>26100.900</td>
          <td><a href="../release-notes/experimental/preview-build-26100-900">
              09/20/2026 - older</a></td>
        </tr>
        <tr>
          <td>26100.1000</td>
          <td><a href="../release-notes/beta/preview-build-26100-1000">
              10/01/2026 - beta</a></td>
        </tr></table>
        """
        data = channels.parse_flighthub(html)
        self.assertIn("experimental", data)
        self.assertIn("beta", data)
        exp = data["experimental"]
        self.assertEqual(exp["latest"]["build"], "26100.1000")
        self.assertEqual(len(exp["history"]), 2)
        self.assertTrue(exp["latest"]["url"].startswith("https://learn.microsoft.com/"))

    def test_rel_notes_url(self):
        self.assertEqual(channels.rel_notes_url("https://x/y"), "https://x/y")
        self.assertEqual(channels.rel_notes_url("/a/b"),
                         "https://learn.microsoft.com/a/b")


class QuietHoursTest(unittest.TestCase):
    def test_same_day(self):
        self.assertTrue(checker.in_quiet_hours(
            "13:00-18:00", dt.datetime(2026, 1, 1, 14, 0)))
        self.assertFalse(checker.in_quiet_hours(
            "13:00-18:00", dt.datetime(2026, 1, 1, 12, 0)))

    def test_cross_midnight(self):
        self.assertTrue(checker.in_quiet_hours(
            "23:00-07:00", dt.datetime(2026, 1, 1, 23, 30)))
        self.assertTrue(checker.in_quiet_hours(
            "23:00-07:00", dt.datetime(2026, 1, 1, 2, 0)))
        self.assertFalse(checker.in_quiet_hours(
            "23:00-07:00", dt.datetime(2026, 1, 1, 12, 0)))

    def test_malformed(self):
        self.assertFalse(checker.in_quiet_hours("", None))
        self.assertFalse(checker.in_quiet_hours("abc", None))
        self.assertFalse(checker.in_quiet_hours("25:00-26:00", None))


class MarkdownTest(unittest.TestCase):
    def test_basic_blocks(self):
        md = ("# 标题\n\n正文 **粗体** 和 `code`。\n\n"
              "## 列表\n- 一\n- 二\n\n"
              "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
              "```\nprint(1)\n```\n")
        html = mdlite.to_html(md)
        self.assertIn("<h1>标题</h1>", html)
        self.assertIn("<strong>粗体</strong>", html)
        self.assertIn("<code>code</code>", html)
        self.assertIn("<ul>", html)
        self.assertIn("<table>", html)
        self.assertIn("<pre><code", html)

    def test_escapes_html(self):
        html = mdlite.to_html("看这个 <script>alert(1)</script> 标签")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_page_embeds_extra_css(self):
        tag = reporter.reader_style_tag()
        self.assertIn('id="winupd-reader"', tag)
        page = mdlite.render_page("# hi", "标题", extra_css=tag)
        self.assertIn('id="winupd-reader"', page)
        self.assertIn("<h1>hi</h1>", page)

    def test_raw_page(self):
        page = mdlite.render_raw("<h1>总览</h1>", "总览")
        self.assertIn("<h1>总览</h1>", page)
        self.assertIn("ul.tl", page)


class ReporterTest(unittest.TestCase):
    def test_one_line_summary(self):
        md = "# t\n\n## 一句话总结\n\n本次更新修复了 **A** 和 B。\n"
        self.assertEqual(reporter.one_line_summary(md), "本次更新修复了 **A** 和 B。")

    def test_one_line_summary_fallback(self):
        md = "# 标题\n\n这是一段普通正文。\n"
        self.assertEqual(reporter.one_line_summary(md), "这是一段普通正文。")

    def test_write_report_and_index(self):
        tmp = tempfile.mkdtemp(prefix="winupd_rep_")
        cfg = {"report_dir": tmp, "keep_reports": 10}
        md_path, html_path = reporter.write(
            cfg, "fh:experimental", "26340.9882",
            "# 报告\n\n## 一句话总结\n\n修复了 X。\n")
        self.assertTrue(os.path.exists(md_path))
        self.assertTrue(os.path.exists(html_path))
        with open(html_path, encoding="utf-8") as f:
            self.assertIn('id="winupd-reader"', f.read())
        names = {"fh:experimental": "测试频道"}
        state = {"channels": {"fh:experimental": {
            "last_version": "26340.9882", "last_check_date": "2026-11-07",
            "last_report": md_path}}}
        idx = reporter.write_index(cfg, state, names)
        self.assertTrue(os.path.exists(idx))
        with open(idx, encoding="utf-8") as f:
            self.assertIn("测试频道", f.read())

    def test_report_arg(self):
        self.assertEqual(checker.report_arg("fh:experimental", "26340.9843"),
                         "r/fh_experimental/26340-9843")


class NotifyTest(unittest.TestCase):
    def test_default_tag_unique_and_safe(self):
        tags = [notify._default_tag("r/fh_experimental/26340-9882", "") for _ in range(4)]
        self.assertEqual(len(set(tags)), 4)
        for t in tags:
            self.assertLessEqual(len(t), 64)
            self.assertRegex(t, r"^[0-9A-Za-z_.-]+$")


class DeepseekTest(unittest.TestCase):
    def test_strip_code_fence(self):
        self.assertEqual(deepseek_api.strip_code_fence("```markdown\n# hi\n```"), "# hi")
        self.assertEqual(deepseek_api.strip_code_fence("```\n# hi\n```"), "# hi")
        self.assertEqual(deepseek_api.strip_code_fence("# hi"), "# hi")
        self.assertEqual(deepseek_api.strip_code_fence(""), "")

    def test_build_prompt(self):
        p = deepseek_api.build_prompt("Windows 11 Beta", "26100.1000", "26100.900",
                                      "https://learn.microsoft.com/x", "官方",
                                      "原文内容", "2026-11-07", detail="详细")
        self.assertIn("26100.1000", p)
        self.assertIn("Windows 11 Beta", p)
        self.assertIn("原文内容", p)
        self.assertIn("覆盖原文每个改动点", p)

    def test_fallback_report(self):
        md = deepseek_api.fallback_report("Beta", "26100.1000", "26100.900",
                                          "2026-11-07", "", "", "HTTP 402")
        self.assertIn("# Beta 更新报告：26100.1000", md)
        self.assertIn("HTTP 402", md)


class GamesenseTest(unittest.TestCase):
    def test_ignored(self):
        self.assertTrue(gamesense._ignored(r"C:\Games\a.exe", ["a.exe"]))
        self.assertTrue(gamesense._ignored(r"C:\Games\a.exe", ["c:\\games\\a.exe"]))
        self.assertTrue(gamesense._ignored(r"C:\Windows\explorer.exe", []))
        self.assertFalse(gamesense._ignored(r"C:\Games\b.exe", ["a.exe"]))


if __name__ == "__main__":
    unittest.main()
