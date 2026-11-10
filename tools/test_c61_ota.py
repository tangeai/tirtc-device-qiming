from collections import deque
import hashlib
import struct
import unittest

from c61_ota import APP_LIMIT, PROJECT, check_image, run_update


ELF = "ab" * 32
DIGEST = "cd" * 32
URL = "http://192.168.1.2:8768/c61-ota.bin"
IDLE = "+STATUS:wifi=1,platform=1,mqtt=1,rtc=1,connected=0,state=waiting,session=0"
MEDIA_IDLE = "+MEDIA:active=0,tx=0"
ACTIVATED = "I cp_ota: C61 OTA activated; restarting P4 after CP activation timer"
BOOTED = "I c61_bootstrap: C61 SPI / Hosted 3.0.7; read-only check passed"


def app_image(chip=20, min_rev=100, max_rev=199):
    data = bytearray(320)
    data[0] = 0xE9
    struct.pack_into("<H", data, 12, chip)
    struct.pack_into("<HH", data, 15, min_rev, max_rev)
    struct.pack_into("<I", data, 32, 0xABCD5432)
    data[80:80 + len(PROJECT)] = PROJECT
    data[176:208] = bytes.fromhex(ELF)
    return bytes(data)


class Transcript:
    def __init__(self, *lines):
        self.lines = deque(lines)
        self.commands = []

    def send(self, command):
        self.commands.append(command)

    def wait_for(self, predicate, seconds):
        while self.lines:
            line = self.lines.popleft()
            if predicate(line):
                return line
        return ""


class C61OtaTest(unittest.TestCase):
    def test_app_image(self):
        data = app_image()
        digest = hashlib.sha256(data).hexdigest()
        self.assertEqual(check_image(data, digest), (digest, ELF))
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            check_image(data, DIGEST)

    def test_rejects_other_chip_revision_and_full_flash(self):
        for data in (app_image(chip=18), app_image(min_rev=101), bytes(APP_LIMIT + 1)):
            with self.subTest(size=len(data)):
                with self.assertRaises(ValueError):
                    check_image(data, hashlib.sha256(data).hexdigest())

    def test_queued_is_not_success(self):
        port = Transcript(IDLE, MEDIA_IDLE, "+CPOTA:QUEUED")
        with self.assertRaisesRegex(RuntimeError, "activation was not confirmed"):
            run_update(port, URL, DIGEST, ELF)
        self.assertEqual(port.commands, ["AT+STATUS?", f"AT+CPOTA={URL},{DIGEST}"])

    def test_ota_verifies_post_restart_identity(self):
        port = Transcript(IDLE, MEDIA_IDLE, ACTIVATED, BOOTED, IDLE, f"+C61:elf={ELF},idf=v5.5.5")
        run_update(port, URL, DIGEST, ELF)
        self.assertEqual(port.commands, [
            "AT+STATUS?", f"AT+CPOTA={URL},{DIGEST}", "AT+STATUS?", "AT+C61=INFO",
        ])

    def test_rejects_busy_device_and_unexpected_identity(self):
        busy = Transcript(IDLE, "+MEDIA:active=1,tx=0")
        with self.assertRaisesRegex(RuntimeError, "online and idle"):
            run_update(busy, URL, DIGEST, ELF)
        self.assertEqual(busy.commands, ["AT+STATUS?"])
        rolled_back = Transcript(IDLE, MEDIA_IDLE, ACTIVATED, BOOTED, IDLE, "+C61:elf=old,idf=v5.5.5")
        with self.assertRaisesRegex(RuntimeError, "expected C61 application is not running"):
            run_update(rolled_back, URL, DIGEST, ELF)
        self.assertEqual(sum(x.startswith("AT+CPOTA=") for x in rolled_back.commands), 1)


if __name__ == "__main__":
    unittest.main()
