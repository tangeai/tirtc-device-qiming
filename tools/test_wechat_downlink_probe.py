import contextlib
import io
import unittest

import wechat_downlink_probe as probe


class FakeConsole:
    def __init__(self, missing=None):
        self.calls = []
        self.missing = missing

    def query(self, command, prefix, terminal_ok=True):
        self.calls.append((command, terminal_ok))
        if command == self.missing:
            raise TimeoutError("missing " + command)
        return prefix + "test=1"


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_query_waits_for_complete_multiline_reply(self):
        console = FakeConsole()
        probe.query(console, "AT+MEDIA?", "+MEDIA_DOWN:")
        self.assertEqual(console.calls, [("AT+MEDIA?", True)])

    def test_async_coprocessor_reply_has_no_terminal_ok(self):
        console = FakeConsole()
        probe.query(console, "AT+C61=HEAP", "+C61HEAP:")
        self.assertEqual(console.calls, [("AT+C61=HEAP", False)])

    def test_initial_snapshot_fails_on_missing_evidence(self):
        console = FakeConsole("AT+MEM?")
        with self.assertRaises(TimeoutError):
            probe.snapshot(console, "c61")

    def test_observation_records_timeout_and_continues_without_hangup(self):
        console = FakeConsole("AT+MEM?")
        errors = []
        probe.snapshot(console, "c61", errors)
        self.assertEqual(errors, ["missing AT+MEM?"])
        self.assertEqual(console.calls[-1], ("AT+MEDIA?", True))
        self.assertFalse(any("HANGUP" in cmd for cmd, _ in console.calls))

    def test_c6_does_not_receive_c61_probe_commands(self):
        console = FakeConsole()
        probe.snapshot(console, "c6")
        self.assertFalse(any("C61" in cmd for cmd, _ in console.calls))

    def test_light_snapshot_avoids_hosted_control_queries(self):
        console = FakeConsole()
        probe.snapshot(console, "c61", full=False)
        commands = [command for command, _ in console.calls]
        self.assertEqual(commands, ["AT+WX?", "AT+MEM?", "AT+MEDIA?"])


if __name__ == "__main__":
    unittest.main()
