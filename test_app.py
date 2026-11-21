"""Автотести: нечіткий висновок, симуляція, API, експорт. Запуск: python -m unittest -v"""
import io
import os
import tempfile
import unittest

import pandas as pd

import storage
# Тести використовують окрему тимчасову базу, щоб не засмічувати історію
storage.DB_PATH = os.path.join(tempfile.mkdtemp(), "test_history.db")

import app as app_module                                   # noqa: E402
from fuzzy_controller import FanFuzzyController, RULES     # noqa: E402
from simulation import run_simulation, validate_params     # noqa: E402


class FuzzyTests(unittest.TestCase):
    def setUp(self):
        self.ctrl = FanFuzzyController()

    def test_rule_base_is_complete(self):
        # 3 x 3 x 3 комбінацій, без дублікатів
        combos = {(t, h, c) for t, h, c, _ in RULES}
        self.assertEqual(len(RULES), 27)
        self.assertEqual(len(combos), 27)

    def test_comfort_gives_low_speed(self):
        self.assertLess(self.ctrl.infer(22, 50, 450), 15)

    def test_worst_case_gives_high_speed(self):
        self.assertGreater(self.ctrl.infer(35, 80, 1800), 85)

    def test_monotonic_in_co2(self):
        values = [self.ctrl.infer(22, 50, c) for c in range(400, 2001, 100)]
        self.assertTrue(all(b >= a - 1e-9 for a, b in zip(values, values[1:])))

    def test_monotonic_in_temperature_and_humidity(self):
        t_vals = [self.ctrl.infer(t, 50, 1000) for t in range(10, 41)]
        h_vals = [self.ctrl.infer(22, h, 1000) for h in range(0, 101, 5)]
        for seq in (t_vals, h_vals):
            self.assertTrue(all(b >= a - 1e-9 for a, b in zip(seq, seq[1:])))

    def test_output_in_range_over_grid(self):
        for t in range(10, 41, 5):
            for h in range(0, 101, 10):
                for c in range(400, 2001, 200):
                    self.assertTrue(0.0 <= self.ctrl.infer(t, h, c) <= 100.0)

    def test_out_of_universe_is_clipped(self):
        self.assertAlmostEqual(self.ctrl.infer(100, 200, 9000), self.ctrl.infer(40, 100, 2000))


class SimulationTests(unittest.TestCase):
    def test_default_reaches_comfort(self):
        res = run_simulation(validate_params({}))
        self.assertTrue(res["metrics"]["all_in_zone"])
        self.assertEqual(len(res["time"]), 181)
        self.assertTrue(all(0 <= u <= 100 for u in res["fan_actual"]))

    def test_strong_disturbance_not_reached(self):
        res = run_simulation(validate_params({"disturbance_gain": 2.0}))
        self.assertFalse(res["metrics"]["all_in_zone"])
        self.assertIsNone(res["metrics"]["settle_time_all"])

    def test_validation(self):
        for bad in ({"duration": 0}, {"temperature0": 99}, {"co2_0": "abc"},
                    {"tau_fan": float("nan")}, {"humidity0": None}):
            with self.assertRaises(ValueError):
                validate_params(bad)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_index_and_membership(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        data = self.client.get("/api/membership").get_json()
        self.assertEqual(len(data["rules"]), 27)
        self.assertIn("fan", data["curves"])

    def test_infer(self):
        r = self.client.post("/api/infer", json={"temperature": 30, "humidity": 70, "co2": 1500})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(0 <= r.get_json()["fan"] <= 100)
        bad = self.client.post("/api/infer", json={"temperature": 300, "humidity": 70, "co2": 1500})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.post("/api/infer", data="x").status_code, 400)

    def test_simulate_errors(self):
        self.assertEqual(self.client.post("/api/simulate", json={"duration": 99999}).status_code, 400)
        self.assertEqual(self.client.post("/api/simulate", json=[1, 2]).status_code, 400)
        self.assertEqual(self.client.post("/api/simulate", json={"co2_0": "abc"}).status_code, 400)

    def test_simulate_history_export(self):
        r = self.client.post("/api/simulate", json={"duration": 60})
        self.assertEqual(r.status_code, 200)
        run_id = r.get_json()["run_id"]
        self.assertTrue(any(x["id"] == run_id for x in self.client.get("/api/history").get_json()))

        csv_resp = self.client.get(f"/api/export/{run_id}.csv")
        self.assertEqual(csv_resp.status_code, 200)
        frame = pd.read_csv(io.BytesIO(csv_resp.data), sep=";", comment="#", encoding="utf-8-sig")
        self.assertEqual(len(frame), 61)
        self.assertIn("Температура, °C", frame.columns)

        xlsx_resp = self.client.get(f"/api/export/{run_id}.xlsx")
        self.assertEqual(xlsx_resp.status_code, 200)
        sheets = pd.read_excel(io.BytesIO(xlsx_resp.data), sheet_name=None)
        self.assertEqual(set(sheets), {"Перехідний процес", "Параметри", "Метрики"})

        self.assertEqual(self.client.get("/api/export/999999.csv").status_code, 404)


if __name__ == "__main__":
    unittest.main()
