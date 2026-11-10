# -*- coding: utf-8 -*-
"""存储层测试：原子写、损坏恢复、跨进程写锁、状态合并。

这些测试只操作临时目录，不会碰真实的 config.json / state.json / logs。
"""
import json
import os
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="winupd_test_")
        self._old = (config.CONFIG_PATH, config.STATE_PATH,
                     config.WATCH_PATH, config.LOG_DIR)
        config.LOG_DIR = os.path.join(self.tmp, "logs")
        config.CONFIG_PATH = os.path.join(self.tmp, "config.json")
        config.STATE_PATH = os.path.join(self.tmp, "state.json")
        config.WATCH_PATH = os.path.join(config.LOG_DIR, "watch.json")
        os.makedirs(config.LOG_DIR, exist_ok=True)
        config._state_cache = None

    def tearDown(self):
        (config.CONFIG_PATH, config.STATE_PATH,
         config.WATCH_PATH, config.LOG_DIR) = self._old
        config._state_cache = None

    # ---------------------------------------------------------- 原子写
    def test_write_read_roundtrip_and_backup(self):
        config.save_config({"api_key": "sk-abcdefghijklmn", "channels": []})
        config.save_config({"api_key": "sk-abcdefghijklmn", "channels": []})
        self.assertTrue(os.path.exists(config.CONFIG_PATH + ".bak"))
        cfg = config.load_config()
        self.assertEqual(cfg["api_key"], "sk-abcdefghijklmn")

    def test_corrupt_main_recovers_from_bak(self):
        config.save_config({"api_key": "sk-good-key-123456", "channels": []})
        config.save_config({"api_key": "sk-good-key-123456", "channels": []})
        with open(config.CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write('{"broken": ')
        cfg = config.load_config()
        self.assertEqual(cfg["api_key"], "sk-good-key-123456")
        with open(config.CONFIG_PATH, encoding="utf-8") as f:
            self.assertIsInstance(json.load(f), dict)

    def test_corrupt_without_backup_kept_as_evidence(self):
        with open(config.CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write("{not json")
        cfg = config.load_config()          # 回落到默认值，但不静默丢弃坏文件
        self.assertIn("channels", cfg)
        names = [n for n in os.listdir(self.tmp) if "corrupt" in n]
        self.assertTrue(names, "损坏的配置文件应被改名留证")

    def test_concurrent_writers_never_produce_broken_json(self):
        errors = []

        def writer(i):
            try:
                for _ in range(12):
                    config._write_json(config.CONFIG_PATH,
                                       {"writer": i, "pad": "x" * 500})
            except Exception as e:                     # noqa: BLE001
                errors.append(e)

        def reader():
            try:
                for _ in range(60):
                    data = config._read_json(config.CONFIG_PATH, {})
                    assert isinstance(data, dict)
            except Exception as e:                     # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)]
        threads.append(threading.Thread(target=reader))
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        with open(config.CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("writer", data)

    # ---------------------------------------------------------- 合并写
    def test_patch_config_keeps_other_keys(self):
        config.save_config({"api_key": "sk-key-123456789", "watch_enabled": True})
        config.patch_config(watch_enabled=False)
        cfg = config.load_config()
        self.assertFalse(cfg["watch_enabled"])
        self.assertEqual(cfg["api_key"], "sk-key-123456789")

    def test_merge_channels_only_adds(self):
        config.save_config({"channels": [{"id": "fh:experimental",
                                          "source": "flighthub",
                                          "folder": "experimental",
                                          "enabled": False}]})
        new, added = config.merge_channels([
            {"id": "fh:experimental", "source": "flighthub",
             "folder": "experimental", "enabled": True, "name": "被改坏的名字"},
            {"id": "fh:beta", "source": "flighthub", "folder": "beta"},
        ])
        ids = [c["id"] for c in new["channels"]]
        self.assertEqual(ids.count("fh:experimental"), 1)
        self.assertIn("fh:beta", ids)
        self.assertEqual([c["id"] for c in added], ["fh:beta"])
        # 已存在频道的用户设置（enabled=False）不能被自动发现覆盖
        exp = next(c for c in new["channels"] if c["id"] == "fh:experimental")
        self.assertFalse(exp["enabled"])

    def test_update_state_reads_latest_disk_state(self):
        config.save_state({"channels": {"fh:experimental": {
            "last_version": "1.0", "ignored": []}}}, merge_disk=False)
        # 模拟后台刚写了更新的状态
        disk = config.load_state(force=True)
        disk["channels"]["fh:experimental"]["last_version"] = "2.0"
        config.save_state(disk, merge_disk=False)

        def mutate(st):
            st["channels"]["fh:experimental"]["ignored"] = ["2.0"]
            return "ok"

        st, ret = config.update_state(mutate)
        self.assertEqual(ret, "ok")
        self.assertEqual(st["channels"]["fh:experimental"]["last_version"], "2.0")
        self.assertEqual(st["channels"]["fh:experimental"]["ignored"], ["2.0"])

    def test_save_state_merges_ignored_from_disk(self):
        config.save_state({"channels": {"fh:experimental": {
            "last_version": "1.0", "ignored": []}}}, merge_disk=False)

        def mutate(st):
            st["channels"]["fh:experimental"]["ignored"] = ["9.9"]

        config.update_state(mutate)
        # 哨兵拿一份「旧内存状态」保存（模拟长任务期间用户点了忽略）
        old = {"schema": 3,
               "channels": {"fh:experimental": {"last_version": "2.0",
                                                "ignored": [], "reports": []}},
               "pending_notify": []}
        config.save_state(old, merge_disk=True)
        st = config.load_state(force=True)
        self.assertEqual(st["channels"]["fh:experimental"]["ignored"], ["9.9"])
        self.assertEqual(st["channels"]["fh:experimental"]["last_version"], "2.0")

    # ---------------------------------------------------------- 心跳
    def test_watch_online_threshold(self):
        import datetime as dt
        now = dt.datetime.now().isoformat(timespec="seconds")
        config.save_watch({"pid": 1, "last_tick": now, "mode": "normal"})
        self.assertTrue(config.load_watch().get("online"))
        old = (dt.datetime.now() - dt.timedelta(seconds=300)).isoformat(
            timespec="seconds")
        config.save_watch({"pid": 1, "last_tick": old, "mode": "normal"})
        self.assertFalse(config.load_watch().get("online"))

    def test_atomic_write_text(self):
        path = os.path.join(self.tmp, "a", "b.html")
        config.atomic_write_text(path, "<h1>hi</h1>")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "<h1>hi</h1>")
        config.atomic_write_text(path, "second")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "second")


if __name__ == "__main__":
    unittest.main()
