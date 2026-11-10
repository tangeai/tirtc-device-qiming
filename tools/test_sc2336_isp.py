import copy
import json
import unittest

from generate_sc2336_isp import CHANNELS, OUTPUT, SOURCE, derive, interpolate, validate_grid


class GammaTuningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads(SOURCE.read_text(encoding="utf-8"))
        cls.result = derive(cls.source)

    def test_original_error_matches_driver_rejection(self):
        curve = self.source["SC2336"]["aen"]["gamma"]["table"][2]["red"]
        with self.assertRaisesRegex(ValueError, "point 15.*127"):
            validate_grid(curve["x"])

    def test_all_luma_interpolations_keep_valid_x(self):
        units = self.result["SC2336"]["aen"]["gamma"]["table"]
        for left, right in zip(units, units[1:]):
            for channel in CHANNELS:
                for step in range(1001):
                    x = [int(a + (b - a) * step / 1000) for a, b in
                         zip(left[channel]["x"], right[channel]["x"])]
                    validate_grid(x)

    def test_curves_are_resampled_not_disabled(self):
        before = self.source["SC2336"]["aen"]["gamma"]["table"]
        after = self.result["SC2336"]["aen"]["gamma"]["table"]
        for old, new in zip(before, after):
            for channel in CHANNELS:
                curve = old.get(channel, old)
                actual = new[channel]
                expected = [int(interpolate(curve["x"], curve["y"], x) + 0.5) for x in actual["x"]]
                self.assertEqual(actual["y"], expected)
                self.assertEqual(actual["y"][-1], 255)
                self.assertEqual(actual["y"], sorted(actual["y"]))

    def test_other_isp_settings_and_source_unchanged(self):
        source, result = copy.deepcopy(self.source), copy.deepcopy(self.result)
        source["SC2336"]["aen"].pop("gamma")
        result["SC2336"]["aen"].pop("gamma")
        self.assertEqual(source, result)
        self.assertEqual(self.source, json.loads(SOURCE.read_text(encoding="utf-8")))

    def test_resampling_error_is_bounded(self):
        before = self.source["SC2336"]["aen"]["gamma"]["table"]
        after = self.result["SC2336"]["aen"]["gamma"]["table"]
        for old, new in zip(before, after):
            for channel in CHANNELS:
                curve = old.get(channel, old)
                for value in range(256):
                    error = abs(interpolate(curve["x"], curve["y"], value) -
                                interpolate(new[channel]["x"], new[channel]["y"], value))
                    self.assertLessEqual(error, 7.0)

    def test_committed_asset_is_reproducible(self):
        self.assertEqual(self.result, json.loads(OUTPUT.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
