import unittest

from c61_udp_regression import (
    extract_prefixed_line,
    echo_unrecovered,
    fields,
    media_is_idle,
    missing_count,
    profile_failures,
)


class UdpMeasurementTests(unittest.TestCase):
    def test_fields_preserve_values_with_equals(self):
        self.assertEqual(fields("+C61:cmd=SINK=1,ret=0"), {"cmd": "SINK=1", "ret": "0"})

    def test_async_log_prefix_does_not_hide_at_response(self):
        line = "W hosted: pressure i+WX:state=0,ready=1"
        self.assertEqual(extract_prefixed_line(line, "+WX:"), "+WX:state=0,ready=1")

    def test_unrelated_log_has_no_at_response(self):
        self.assertIsNone(extract_prefixed_line("W hosted: pressure", "+WX:"))

    def test_missing_includes_prefix_and_tail(self):
        stats = {"unique": "5", "overflow": "0", "seq": "2-6", "missing": "0"}
        self.assertEqual(missing_count(10, stats), 5)

    def test_all_packets_lost(self):
        self.assertEqual(missing_count(100, {"unique": "0", "overflow": "0"}), 100)

    def test_no_loss(self):
        self.assertEqual(missing_count(100, {"unique": "100", "overflow": "0"}), 0)

    def test_echo_retries_are_not_final_failures(self):
        self.assertEqual(echo_unrecovered({"echo_fail": "0", "echo_retry": "12",
                                           "echo_recover": "5",
                                           "echo_unrecovered": "0"}), 0)

    def test_echo_failure_falls_back_to_legacy_field(self):
        self.assertEqual(echo_unrecovered({"echo_fail": "2"}), 2)

    def test_idle_media_allows_enabled_next_call_preference(self):
        media = "+MEDIA:call=0,send=1,camera=0,0x0@0"
        media_down = "+MEDIA_DOWN:run=0,wait_key=0,rx=10"
        self.assertTrue(media_is_idle(media, media_down))

    def test_active_media_is_rejected(self):
        self.assertFalse(media_is_idle(
            "+MEDIA:call=1,send=1,camera=1,480x320@15",
            "+MEDIA_DOWN:run=1,wait_key=0,rx=10"))

    def test_overflow_is_not_a_valid_result(self):
        with self.assertRaises(ValueError):
            missing_count(100, {"unique": "90", "overflow": "1"})

    def test_impossible_count_is_rejected(self):
        with self.assertRaises(ValueError):
            missing_count(100, {"unique": "101", "overflow": "0"})

    def sample(self):
        return {"zero_loss": True, "measurement_endpoint": "P4",
                "receiver": {"unique": "100", "invalid": "0", "overflow": "0",
                             "rxerr": "0", "longgap": "0"},
                "c61": {"unique": "100", "overflow": "0", "maxgap_us": "70000"},
                "c61_heap_before": {"fail": "5"}, "c61_heap_after": {"fail": "5"}}

    def test_profile_passes_only_without_new_errors(self):
        self.assertEqual(profile_failures(self.sample()), [])

    def test_heap_failure_cannot_pass_with_zero_packet_loss(self):
        sample = self.sample()
        sample["c61_heap_after"]["fail"] = "6"
        self.assertIn("c61_heap_failure_delta", profile_failures(sample))

    def test_forwarding_disagreement_is_not_ignored(self):
        sample = self.sample()
        sample["receiver"]["unique"] = "99"
        self.assertIn("c61_p4_count_mismatch", profile_failures(sample))

    def test_sequence_window_overrun_invalidates_profile(self):
        sample = self.sample()
        sample["c61"]["overflow"] = "1"
        self.assertIn("c61_sequence_outside_window", profile_failures(sample))


if __name__ == "__main__":
    unittest.main()
