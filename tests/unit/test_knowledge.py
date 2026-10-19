from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.aurelia_fx.knowledge import KnowledgeEnvironment, KnowledgeRepository


ROOT = Path(__file__).resolve().parents[2]


class KnowledgeRepositoryTests(unittest.TestCase):
    def test_learning_catalog_loads_and_is_not_approved_by_default(self) -> None:
        repository = KnowledgeRepository.load(ROOT / "data" / "knowledge" / "rules.json")

        self.assertEqual(len(repository.rules), 8)
        for environment in KnowledgeEnvironment:
            self.assertEqual(repository.for_environment(environment), ())

    def test_live_requires_explicit_live_approval(self) -> None:
        payload = json.loads((ROOT / "data" / "knowledge" / "rules.json").read_text(encoding="utf-8"))
        rule = payload["rules"][0]
        rule["validation_status"] = "approved_for_demo"
        rule["reviewed_at"] = "2026-10-19"
        repository = _load_payload(payload)

        self.assertEqual(len(repository.for_environment(KnowledgeEnvironment.DEMO)), 1)
        self.assertEqual(repository.for_environment(KnowledgeEnvironment.LIVE), ())

    def test_invalid_status_fails_closed(self) -> None:
        payload = json.loads((ROOT / "data" / "knowledge" / "rules.json").read_text(encoding="utf-8"))
        payload["rules"][0]["validation_status"] = "approved_automatically"

        with self.assertRaises(ValueError):
            _load_payload(payload)

    def test_duplicate_rule_ids_are_rejected(self) -> None:
        payload = json.loads((ROOT / "data" / "knowledge" / "rules.json").read_text(encoding="utf-8"))
        payload["rules"].append(dict(payload["rules"][0]))

        with self.assertRaisesRegex(ValueError, "duplicado"):
            _load_payload(payload)


def _load_payload(payload: dict) -> KnowledgeRepository:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return KnowledgeRepository.load(path)


if __name__ == "__main__":
    unittest.main()
