# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["THEME_HEAT_CACHE_DB"] = os.path.join(
    tempfile.gettempdir(), "theme_heat_service_test_%s.sqlite3" % os.getpid()
)
import theme_heat_service as svc


class ThemeHeatOptimizationTests(unittest.TestCase):
    def setUp(self):
        svc._clear_all_caches()
        svc._stats_reset()

    def test_limit_reuses_cached_full_result(self):
        calls = []

        def fake_compute(theme, limit):
            calls.append(limit)
            return {
                "success": True,
                "theme": theme,
                "rows": [{"display_rank": i, "current_rank": None} for i in range(1, limit + 1)],
                "ranked_count": limit,
            }

        with mock.patch.object(svc, "_compute_theme_heat", side_effect=fake_compute):
            first = svc.query_theme_heat("房地产", 20)
            second = svc.query_theme_heat("房地产", 10)
            third = svc.query_theme_heat("房地产", 30)

        self.assertEqual(calls, [20, 30])
        self.assertEqual(len(first["rows"]), 20)
        self.assertEqual(len(second["rows"]), 10)
        self.assertTrue(second["cached"])
        self.assertEqual(len(third["rows"]), 30)

    def test_same_theme_requests_are_single_flight(self):
        calls = []
        barrier = threading.Barrier(8)

        def fake_compute(theme, limit):
            calls.append(limit)
            time.sleep(0.15)
            return {"success": True, "theme": theme, "rows": [{"display_rank": 1}]}

        results = []
        errors = []
        with mock.patch.object(svc, "_compute_theme_heat", side_effect=fake_compute):
            def worker():
                try:
                    barrier.wait()
                    results.append(svc.query_theme_heat("房地产", 20))
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 8)
        self.assertEqual(calls, [20])

    def test_cli_gate_caps_parallel_processes(self):
        class FakeProc:
            next_pid = 1000

            def __init__(self, *args, **kwargs):
                FakeProc.next_pid += 1
                self.pid = FakeProc.next_pid
                self.returncode = 0

            def communicate(self, timeout=None):
                time.sleep(0.05)
                return '{"ok":true,"data":{}}', ""

            def poll(self):
                return self.returncode

            def kill(self):
                self.returncode = -9

            def wait(self, timeout=None):
                return self.returncode

        errors = []
        with mock.patch.object(svc.subprocess, "Popen", side_effect=FakeProc):
            def worker():
                try:
                    svc._run_json(["fake"])
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)

        stats = svc._stats_snapshot()
        self.assertEqual(errors, [])
        self.assertEqual(stats["calls"], 8)
        self.assertLessEqual(stats["max_active"], svc._CLI_CONCURRENCY)
        self.assertGreater(stats["max_active"], 0)

    def test_non_transient_error_is_not_retried(self):
        calls = []

        class FakeProc:
            pid = 2000
            returncode = 1

            def __init__(self, *args, **kwargs):
                calls.append(args)

            def communicate(self, timeout=None):
                return "", "authentication failed"

            def poll(self):
                return self.returncode

            def kill(self):
                pass

            def wait(self, timeout=None):
                return self.returncode

        with mock.patch.object(svc.subprocess, "Popen", side_effect=FakeProc):
            with self.assertRaises(RuntimeError):
                svc._run_json(["special", "hot-stock"])

        self.assertEqual(len(calls), 1)
        self.assertEqual(svc._stats_snapshot()["retries"], 0)

    def test_disk_cache_survives_memory_clear(self):
        svc._cache_set("persistence-test", {"ok": True})
        with svc._CACHE_LOCK:
            svc._CACHE.clear()
        self.assertEqual(svc._cache_get("persistence-test", 60), {"ok": True})

    def test_stale_result_is_returned_when_refresh_fails(self):
        first_result = {
            "success": True,
            "theme": "房地产",
            "rows": [{"display_rank": i, "current_rank": None} for i in range(1, 21)],
            "ranked_count": 20,
        }
        with mock.patch.object(
            svc,
            "_compute_theme_heat",
            side_effect=[first_result, RuntimeError("upstream unavailable")],
        ):
            first = svc.query_theme_heat("房地产", 10)
            second = svc.query_theme_heat("房地产", 20)

        self.assertEqual(len(first["rows"]), 10)
        self.assertTrue(second["cached"])
        self.assertTrue(second["stale"])
        self.assertEqual(len(second["rows"]), 20)

    def test_transient_error_is_retried_once(self):
        calls = []

        class FakeProc:
            next_pid = 3000

            def __init__(self, *args, **kwargs):
                calls.append(args)
                self.pid = FakeProc.next_pid
                FakeProc.next_pid += 1
                self.returncode = 1 if len(calls) == 1 else 0

            def communicate(self, timeout=None):
                if self.returncode:
                    return "", "network timeout"
                return '{"ok":true,"data":{}}', ""

            def poll(self):
                return self.returncode

            def kill(self):
                pass

            def wait(self, timeout=None):
                return self.returncode

        with mock.patch.object(svc.subprocess, "Popen", side_effect=FakeProc):
            result = svc._run_json(["fake"])

        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(svc._stats_snapshot()["retries"], 1)

    def test_trend_budget_prefers_boundary_then_fillers(self):
        indices = [{"name": "测试板块", "thscode": "IDX", "tag": "cn_concept"}]
        members = [
            {"thscode": "A", "name": "A股", "ticker": "A"},
            {"thscode": "B", "name": "B股", "ticker": "B"},
            {"thscode": "C", "name": "C股", "ticker": "C"},
            {"thscode": "D", "name": "D股", "ticker": "D"},
        ]
        snapshot = {
            "A": {"turnover": 100},
            "B": {"turnover": 90},
            "C": {"turnover": 80},
            "D": {"turnover": 70},
        }
        trend_calls = []

        def fake_trends(codes, start_date, end_date):
            trend_calls.append((list(codes), start_date, end_date))
            return {code: {start_date: 4, end_date: 2} for code in codes}

        with mock.patch.object(svc, "resolve_indices", return_value=indices), \
             mock.patch.object(svc, "_constituents", return_value=members), \
             mock.patch.object(svc, "_market_snapshot", return_value=snapshot), \
             mock.patch.object(svc, "_hot_list", return_value={
                 "items": [
                     {"thscode": "A", "rank": 1},
                     {"thscode": "B", "rank": 2},
                 ],
                 "as_of": "2026-10-04",
             }), \
             mock.patch.object(svc, "_hot_history", return_value={
                 "items": [{"thscode": "A", "rank": 3}],
                 "as_of": "2026-10-01",
             }), \
             mock.patch.object(svc, "_load_trends", side_effect=fake_trends), \
             mock.patch.object(svc, "_latest_lhb", return_value={}), \
             mock.patch.object(svc, "_TREND_LOOKUP_LIMIT", 2):
            result = svc._compute_theme_heat("测试", 20)

        self.assertEqual([call[0] for call in trend_calls], [["B", "C"]])
        rows = {row["thscode"]: row for row in result["rows"]}
        self.assertEqual(rows["A"]["current_rank"], 1)
        self.assertEqual(rows["A"]["rank_3d_ago"], 3)
        self.assertEqual(rows["B"]["current_rank"], 2)
        self.assertEqual(rows["B"]["rank_3d_ago"], 4)
        self.assertEqual(rows["C"]["current_rank"], 2)
        self.assertIsNone(rows["D"]["current_rank"])
        self.assertEqual(rows["D"]["state"], "未上榜")


if __name__ == "__main__":
    unittest.main(verbosity=2)
