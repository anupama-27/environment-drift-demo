"""Unit and integration verification tests for the 8 Table 10 backend prototype components.

Run with:
    python -m unittest tests.test_demo_backend -v
"""
import os
import unittest

from drift import config
from drift.analysis import POLICIES, RunView, candidate_truth, pair, pair_measure, simulate
from drift.envs import ENVS, env_at, map_schedule
from drift.extract import extract_v1, extract_v2, gold_answer, is_correct
from drift.model import Cache, generation_key
from drift.pipeline import Runner, get_runs
from drift.report import write_table


class TestDemoBackendPrototype(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = get_runs(seeds=[1])
        assert len(cls.runs) == 1, "Expected Seed 1 saved run JSON"
        cls.seed1_run = cls.runs[0]
        cls.view = RunView(cls.seed1_run)

    def test_01_reference_manager(self):
        """Component 1: Reference manager (drift.pipeline:Runner.run & drift.analysis:RunView.stored)."""
        snaps = self.seed1_run["snapshots"]
        self.assertEqual(len(snaps), config.ROUNDS)
        self.assertEqual(snaps[0]["round"], 0)
        self.assertEqual(snaps[0]["env"], "E1")
        h0 = snaps[0]["prompt"]
        stored_labels = self.view.stored(h0, "E1", "E4")
        self.assertEqual(len(stored_labels), config.N_EVAL)
        self.assertAlmostEqual(sum(stored_labels) / len(stored_labels), 0.68, places=4)

    def test_02_environment_version_tracker(self):
        """Component 2: Environment version tracker (drift.envs:ENVS, env_at, map_schedule)."""
        self.assertEqual(set(ENVS.keys()), {"E1", "E2", "E3", "E4"})
        self.assertEqual(env_at(0, config.ENV_SCHEDULE), "E1")
        self.assertEqual(env_at(4, config.ENV_SCHEDULE), "E2")
        self.assertEqual(env_at(8, config.ENV_SCHEDULE), "E4")
        no_dec = map_schedule(config.ENV_SCHEDULE, {"E2": "E1", "E4": "E3"})
        self.assertEqual(no_dec, {0: "E1", 4: "E1", 8: "E3"})

    def test_03_reference_rerun_mechanism(self):
        """Component 3: Reference rerun mechanism (drift.pipeline:Runner.outputs & drift.analysis:RunView.rerun)."""
        h0 = self.seed1_run["snapshots"][0]["prompt"]
        for env_id in ("E1", "E2", "E3", "E4"):
            cur = self.view.labels(h0, env_id, tag="current")
            rer = self.view.rerun(h0, env_id)
            self.assertEqual(len(cur), config.N_EVAL)
            self.assertEqual(len(rer), config.N_EVAL)
        # Under E4, h0 stored under E1 is 68.0% while fresh E4 rerun is 69.0%
        self.assertAlmostEqual(sum(self.view.stored(h0, "E1", "E4")) / config.N_EVAL, 0.68, places=4)
        self.assertAlmostEqual(sum(self.view.rerun(h0, "E4")) / config.N_EVAL, 0.69, places=4)

    def test_04_candidate_comparison_view(self):
        """Component 4: Candidate comparison view (drift.analysis:pair, win_rate, pair_measure)."""
        h0 = self.seed1_run["snapshots"][0]["prompt"]
        c11 = self.seed1_run["candidates"][10]  # Round 10 (C11 under E4)
        inc10 = self.seed1_run["snapshots"][10]["prompt"]
        m = pair_measure(self.view, c11["prompt"], h0, "E1", "E4", inc10)
        w, l, br, bw = pair(self.view.labels(c11["prompt"], "E4"), self.view.stored(h0, "E1", "E4"))
        self.assertEqual((w, l, br + bw), (24, 22, 200 - 46))
        self.assertTrue(m["promote"])
        self.assertTrue(m["false_accept"])
        self.assertAlmostEqual(100 * m["inflation"], 1.50, places=2)

    def test_05_ground_truth_evaluation_panel(self):
        """Component 5: Ground-truth evaluation panel (drift.extract:extract_v1, extract_v2, is_correct & RunView.gt_acc)."""
        self.assertEqual(extract_v1(r"Therefore the answer is \boxed{42}."), 42.0)
        self.assertIsNone(extract_v1(r"Total is \boxed{$1,250}."))
        self.assertEqual(extract_v2(r"Total is \boxed{$1,250}."), 1250.0)
        self.assertTrue(is_correct(extract_v2(r"Total is \boxed{$1,250}."), gold_answer("#### 1,250")))
        rows = candidate_truth(self.view)
        self.assertEqual(len(rows), config.ROUNDS)
        self.assertEqual(rows[1]["cid"], "C2")
        self.assertEqual(rows[1]["outcome"], "improved")

    def test_06_false_accept_and_drift_dashboard(self):
        """Component 6: False-accept and drift dashboard (drift.analysis:simulate(with_records=True))."""
        r_p1 = simulate(self.view, "P1", with_records=True)
        self.assertEqual(r_p1["evaluated"], 11)
        self.assertEqual(r_p1["accepted"], 7)
        self.assertEqual(r_p1["false_accepts"], 4)
        self.assertEqual(len(r_p1["records"]), 11)
        fa_cids = [rec["cid"] for rec in r_p1["records"] if rec["false_accept"]]
        self.assertEqual(fa_cids, ["C4", "C7", "C10", "C11"])

    def test_07_refresh_policy_comparison(self):
        """Component 7: Refresh-policy comparison (drift.analysis:simulate across P1, P2, P3)."""
        res = {p: simulate(self.view, p, with_records=True) for p in POLICIES}
        self.assertEqual(res["P1"]["total_calls"], 4411)
        self.assertEqual(res["P2"]["total_calls"], 6611)
        self.assertEqual(res["P3"]["total_calls"], 4811)
        self.assertAlmostEqual(100 * res["P2"]["inflation"], 0.0, places=4)
        self.assertGreater(res["P3"]["final_gt_acc"], res["P1"]["final_gt_acc"])
        self.assertLess(res["P3"]["false_accept_rate"], res["P1"]["false_accept_rate"])

    def test_08_reproducibility_and_experiment_logs(self):
        """Component 8: Reproducibility & experiment logs (drift.model:Cache, generation_key & drift.report:write_table)."""
        import tempfile
        k1 = generation_key(config.INITIAL_PROMPT, 0, ENVS["E1"], 1, "current")
        k2 = generation_key(config.INITIAL_PROMPT, 0, ENVS["E1"], 1, "rerun")
        k3 = generation_key(config.INITIAL_PROMPT, 0, ENVS["E2"], 1, "current")
        self.assertEqual(len(k1), 40)
        self.assertNotEqual(k1, k2)
        self.assertNotEqual(k1, k3)
        with tempfile.TemporaryDirectory() as tmpdir:
            cpath = os.path.join(tmpdir, "test_cache.jsonl")
            cache = Cache(cpath)
            cache.put_many([(k1, r"\boxed{42}")])
            reloaded = Cache(cpath)
            self.assertEqual(reloaded.get(k1), r"\boxed{42}")
        self.assertTrue(callable(write_table))
        self.assertTrue(callable(Runner.outputs))
        self.assertEqual(self.seed1_run["seed"], 1)
        self.assertIn("correct", self.seed1_run)
        for t in (3, 4, 5, 6, 8, 9):
            self.assertTrue(os.path.exists(os.path.join(config.LOGS_DIR, f"table{t}.log")))

    def test_09_end_to_end_reproducible_demo_run(self):
        """End-to-end integration test across all 5 seeds verifying cross-table consistency."""
        views = [RunView(r) for r in get_runs(seeds=[1, 2, 3, 4, 5])]
        self.assertEqual(len(views), 5)
        p1 = [simulate(v, "P1") for v in views]
        p3 = [simulate(v, "P3") for v in views]
        self.assertEqual(sum(r["accepted"] for r in p1), 34)
        self.assertEqual(sum(r["false_accepts"] for r in p1), 13)
        self.assertEqual(sum(r["accepted"] for r in p3), 16)
        self.assertEqual(sum(r["false_accepts"] for r in p3), 2)


if __name__ == "__main__":
    unittest.main()

