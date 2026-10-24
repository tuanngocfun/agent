import unittest
from download_candles import closed_candles


def candle(opened, closed=3_599_999, close="102", amount="1234"):
    return [opened, "100", "110", "90", close, "12", closed, amount, 5, "1", "100", "0"]


class CandleTests(unittest.TestCase):
    def test_omits_open_candle_and_keeps_quote_volume(self):
        rows = closed_candles([candle(0), candle(3_600_000, 7_199_999)], 4_000_000, "1h")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], "1234")
        self.assertEqual(rows[0]["timestamps"], "1970-01-01T00:00:00+00:00")

    def test_rejects_duplicates_and_gaps(self):
        for other in (candle(0), candle(7_200_000, 10_799_999)):
            with self.subTest(other=other[0]), self.assertRaises(ValueError):
                closed_candles([candle(0), other], 12_000_000, "1h")

    def test_rejects_bad_bounds_and_nonfinite(self):
        for close in ("111", "NaN", "Infinity", "-1"):
            with self.subTest(close=close), self.assertRaises(ValueError):
                closed_candles([candle(0, close=close)], 4_000_000, "1h")

    def test_rejects_wrong_interval_and_no_closed_candles(self):
        for payload in ([candle(0, closed=10)], [candle(0)]):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                closed_candles(payload, 0 if payload[0][6] > 10 else 100, "1h")


if __name__ == "__main__":
    unittest.main()
