import csv
from pathlib import Path
import tempfile
import unittest
from first_forecast import FEATURES, read_window


class WindowTests(unittest.TestCase):
    def write_csv(self, directory, stamps):
        path = Path(directory) / "candles.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamps", *FEATURES])
            writer.writeheader()
            for stamp in stamps:
                writer.writerow(dict(zip(["timestamps", *FEATURES],
                    [stamp, 100, 110, 90, 102, 12, 1234])))
        return path

    def test_normalizes_timezone_before_chronological_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_csv(directory, ["2026-01-01T07:00:00+07:00",
                "2026-01-01T01:00:00+00:00", "2026-01-01T02:00:00+00:00"])
            history, stamps = read_window(path, 2, 1)
            self.assertEqual(len(history), 3)
            self.assertEqual(stamps[0].hour, 0)

    def test_rejects_insufficient_or_duplicate_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_csv(directory, ["2026-01-01T00:00:00"] * 3)
            for lookback, horizon in ((3, 1), (2, 1)):
                with self.subTest(lookback=lookback), self.assertRaises(ValueError):
                    read_window(path, lookback, horizon)

    def test_rejects_missing_timestamp_and_history_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_csv(directory, ["2026-01-01T00:00:00",
                "2026-01-01T01:00:00", "2026-01-01T02:00:00"])
            original = path.read_text()
            for damaged in (original.replace("2026-01-01T00:00:00", "", 1),
                            original.replace(",100,110,90,102,12,1234", ",100", 1)):
                path.write_text(damaged)
                with self.subTest(damaged=damaged[:60]), self.assertRaises(ValueError):
                    read_window(path, 2, 1)


if __name__ == "__main__":
    unittest.main()
