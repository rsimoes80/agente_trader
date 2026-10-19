import ast
import unittest
from pathlib import Path

from aurelia_fx.hypothesis_lab import v3_cohort_report

ROOT = Path(__file__).resolve().parents[2]


class V3BoundaryTests(unittest.TestCase):
    def test_perception_has_no_execution_or_network_imports(self):
        package = ROOT / "src/aurelia_fx"
        paths = [package / "observer.py", package / "market_intelligence.py"]
        for folder in ("trend", "price_action", "levels", "evidence", "observation"):
            paths.extend((package / folder).glob("*.py"))
        forbidden = {
            "execution_simulator",
            "mt5_provider",
            "MetaTrader5",
            "risk",
            "socket",
            "subprocess",
        }
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                for module in modules:
                    self.assertFalse(set(module.split(".")) & forbidden, str(path))

    def test_offline_cohorts_deduplicate_outcomes_and_suppress_small_sample(self):
        outcome = {
            "decision_id": "d",
            "trade_direction_class": "WITH_TREND",
            "evidence_state": "SUPPORTIVE",
            "financial_result": {"result_in_r": -1},
        }
        result = v3_cohort_report((outcome, outcome), minimum_samples=30)
        self.assertEqual(result["unique_outcomes"], 1)
        self.assertEqual(result["status"], "needs_review")
        self.assertTrue(all(cohort["mean_r"] is None for cohort in result["cohorts"]))
        self.assertIn("no_promotion", result["interpretation"])


if __name__ == "__main__":
    unittest.main()
