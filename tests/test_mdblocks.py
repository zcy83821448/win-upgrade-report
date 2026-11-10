# -*- coding: utf-8 -*-
"""mdblocks：报告 Markdown -> WPF 原生阅读器用的结构化块。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mdblocks


class TestMdBlocks(unittest.TestCase):
    def test_heading_and_paragraph(self):
        blocks = mdblocks.to_blocks("# 标题\n\n这是一段文字。\n")
        self.assertEqual(blocks[0]["t"], "h")
        self.assertEqual(blocks[0]["level"], 1)
        self.assertEqual(blocks[1]["t"], "p")
        self.assertEqual(blocks[1]["spans"][0]["v"], "这是一段文字。")
        self.assertEqual(mdblocks.title_of(blocks), "标题")

    def test_inline_spans(self):
        blocks = mdblocks.to_blocks("有 `代码`、**粗体**、*斜体*、~~删除~~ 和 [链接](https://a.b/c)。")
        kinds = [s["t"] for s in blocks[0]["spans"]]
        self.assertIn("code", kinds)
        self.assertIn("b", kinds)
        self.assertIn("i", kinds)
        self.assertIn("s", kinds)
        link = [s for s in blocks[0]["spans"] if s["t"] == "a"][0]
        self.assertEqual(link["href"], "https://a.b/c")

    def test_list_table_code_quote(self):
        md = ("- 一\n- 二\n\n"
              "1. 甲\n2. 乙\n\n"
              "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
              "```py\nprint(1)\n```\n\n"
              "> 引用\n")
        blocks = mdblocks.to_blocks(md)
        types = [b["t"] for b in blocks]
        self.assertIn("ul", types)
        self.assertIn("ol", types)
        self.assertIn("table", types)
        self.assertIn("code", types)
        self.assertIn("quote", types)
        table = [b for b in blocks if b["t"] == "table"][0]
        self.assertEqual(len(table["head"]), 2)
        self.assertEqual(len(table["rows"]), 1)
        code = [b for b in blocks if b["t"] == "code"][0]
        self.assertEqual(code["lang"], "py")
        self.assertEqual(code["text"], "print(1)")

    def test_empty_and_title_fallback(self):
        self.assertEqual(mdblocks.to_blocks(""), [])
        self.assertEqual(mdblocks.title_of([], "兜底"), "兜底")


if __name__ == "__main__":
    unittest.main()
