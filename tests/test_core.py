import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from core import priority, validate_reading, device_id
from main import Spool
from storage import Store


def sample():
    return {"device_id": "plant01", "ts": 1800000000,
            "soil": {"moisture": 42.5, "temperature": 27, "ec": 850,
                     "ph": 6.4, "n": 40, "p": 18, "k": 95},
            "air": {"temperature": 30, "humidity": 72}}


class CoreTests(unittest.TestCase):
    def test_missing_sensors_are_not_zero(self):
        p = sample()
        p["soil"] = {}
        result = validate_reading(p, "plant01")
        self.assertIsNone(result["soil"]["moisture"])
        self.assertEqual(priority(result, now=p["ts"])[0], "unknown")

    def test_priority_boundaries(self):
        p = sample()
        for value, expected in [(19.9, "high"), (20, "medium"), (34.9, "medium"), (35, "low")]:
            p["soil"]["moisture"] = value
            self.assertEqual(priority(p, now=p["ts"])[0], expected)

    def test_bad_values_are_flagged(self):
        p = sample()
        for value in [float("nan"), float("inf"), -1, 101, True, "42"]:
            p["soil"]["moisture"] = value
            result = validate_reading(p, "plant01")
            self.assertIsNone(result["soil"]["moisture"])
            self.assertIn("soil.moisture", result["invalid_fields"])

    def test_stale_and_future_never_green(self):
        p = sample()
        for now in [p["ts"] + 121, p["ts"] - 61]:
            self.assertEqual(priority(p, now=now)[0], "unknown")

    def test_reject_wrong_device_and_timestamp(self):
        with self.assertRaises(ValueError): validate_reading(sample(), "other")
        for ts in [0, True, "1800000000", 1800000000000.0, 1800000000000]:
            p = sample(); p["ts"] = ts
            with self.assertRaises(ValueError): validate_reading(p, "plant01")
        with self.assertRaises(ValueError): device_id("plant/+/other")

    def test_spool_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "jobs.db")
            spool = Spool(path)
            spool.add(sample())
            event = spool.first()[0]
            spool.db.close()
            restarted = Spool(path)
            self.assertEqual(restarted.first()[0], event)
            self.assertEqual(json.loads(restarted.first()[2]), sample())
            restarted.done(event)
            self.assertIsNone(restarted.first())
            restarted.db.close()

    def test_dynamodb_float_conversion(self):
        from decimal import Decimal
        class FakeTable:
            def put_item(self, **kw): self.item = kw["Item"]
        store = Store.__new__(Store)
        store.table = FakeTable()
        store.put("plant01", "event", "SENSOR", 1800000000, sample())
        self.assertIsInstance(store.table.item["payload"]["soil"]["moisture"], Decimal)
        self.assertEqual(store.table.item["pk"], "DEVICE#plant01")


if __name__ == "__main__": unittest.main()
