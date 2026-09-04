import unittest

from summarize_wechat_probe import summarize


def media(second, run, rx, show):
    return (f"2026-09-03T12:00:{second:02d}.000 +MEDIA_DOWN:run={run},rx={rx},"
            f"decode={rx},convert={show},show={show},q=0/0,drop=0/0,fail=0/0")


class SummaryTests(unittest.TestCase):
    def test_setup_and_idle_counts_do_not_inflate_fps(self):
        result = summarize([media(0, 0, 999, 999), media(10, 1, 0, 0),
                            media(20, 1, 10, 9), media(30, 1, 90, 89),
                            media(50, 0, 120, 120)])
        self.assertEqual(len(result["periods"]), 1)
        self.assertEqual(result["periods"][0]["rx_fps"], 8)
        self.assertEqual(result["periods"][0]["handoff_fps"], 8)
        self.assertEqual(result["periods"][0]["observed_media_seconds"], 10)

    def test_missing_evidence_is_not_zero(self):
        result = summarize([media(10, 1, 10, 10)])
        self.assertIsNone(result["periods"][0]["rx_fps"])
        self.assertIsNone(result["periods"][0]["vrx"])
        self.assertIsNone(result["counters"]["C61HEAP"]["failure_delta"])

    def test_new_renderer_epoch_separates_counters(self):
        result = summarize([media(10, 1, 20, 20), media(20, 1, 100, 100),
                            media(30, 1, 1, 1), media(40, 1, 81, 81)])
        self.assertEqual([p["rx_fps"] for p in result["periods"]], [8, 8])

    def test_only_active_transaction_owns_vrx(self):
        result = summarize([media(10, 1, 20, 20),
                            "2026-09-03T12:00:10.000 +VRX:gap_us=100/200",
                            media(20, 0, 20, 20),
                            "2026-09-03T12:00:20.000 +VRX:gap_us=999/999"])
        self.assertEqual(result["periods"][0]["vrx"]["gap_us"], "100/200")


if __name__ == "__main__":
    unittest.main()
