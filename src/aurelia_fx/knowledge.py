"""Typed, fail-closed access to versioned strategy knowledge.

This module only loads and filters knowledge records. It never promotes a rule,
changes a strategy, or talks to a broker.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any


class ValidationStatus(str, Enum):
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"
    APPROVED_FOR_RESEARCH = "approved_for_research"
    BACKTESTED = "backtested"
    WALK_FORWARD_VALIDATED = "walk_forward_validated"
    APPROVED_FOR_DEMO = "approved_for_demo"
    APPROVED_FOR_LIVE = "approved_for_live"


class KnowledgeEnvironment(str, Enum):
    RESEARCH = "research"
    BACKTEST = "backtest"
    REPLAY = "replay"
    PAPER = "paper"
    DEMO = "demo"
    LIVE = "live"


_ELIGIBLE: dict[KnowledgeEnvironment, frozenset[ValidationStatus]] = {
    KnowledgeEnvironment.RESEARCH: frozenset({
        ValidationStatus.APPROVED_FOR_RESEARCH,
        ValidationStatus.BACKTESTED,
        ValidationStatus.WALK_FORWARD_VALIDATED,
        ValidationStatus.APPROVED_FOR_DEMO,
        ValidationStatus.APPROVED_FOR_LIVE,
    }),
    KnowledgeEnvironment.BACKTEST: frozenset({
        ValidationStatus.APPROVED_FOR_RESEARCH,
        ValidationStatus.BACKTESTED,
        ValidationStatus.WALK_FORWARD_VALIDATED,
        ValidationStatus.APPROVED_FOR_DEMO,
        ValidationStatus.APPROVED_FOR_LIVE,
    }),
    KnowledgeEnvironment.REPLAY: frozenset({
        ValidationStatus.APPROVED_FOR_RESEARCH,
        ValidationStatus.BACKTESTED,
        ValidationStatus.WALK_FORWARD_VALIDATED,
        ValidationStatus.APPROVED_FOR_DEMO,
        ValidationStatus.APPROVED_FOR_LIVE,
    }),
    KnowledgeEnvironment.PAPER: frozenset({
        ValidationStatus.APPROVED_FOR_RESEARCH,
        ValidationStatus.BACKTESTED,
        ValidationStatus.WALK_FORWARD_VALIDATED,
        ValidationStatus.APPROVED_FOR_DEMO,
        ValidationStatus.APPROVED_FOR_LIVE,
    }),
    KnowledgeEnvironment.DEMO: frozenset({
        ValidationStatus.APPROVED_FOR_DEMO,
        ValidationStatus.APPROVED_FOR_LIVE,
    }),
    KnowledgeEnvironment.LIVE: frozenset({ValidationStatus.APPROVED_FOR_LIVE}),
}


@dataclass(frozen=True, slots=True)
class KnowledgeRule:
    rule_id: str
    title: str
    category: str
    description: str
    source_document: str
    source_location: str
    conditions: tuple[str, ...]
    expected_observation: str
    invalidation: str
    confidence_status: str
    validation_status: ValidationStatus
    applicable_symbols: tuple[str, ...]
    applicable_sessions: tuple[str, ...]
    applicable_timeframes: tuple[str, ...]
    version: int
    created_at: date
    reviewed_at: date | None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "KnowledgeRule":
        required_text = (
            "rule_id", "title", "category", "description", "source_document",
            "source_location", "expected_observation", "invalidation", "confidence_status",
        )
        for key in required_text:
            if not isinstance(value.get(key), str) or not value[key].strip():
                raise ValueError(f"KnowledgeRule.{key} precisa ser texto não vazio.")
        for key in ("conditions", "applicable_symbols", "applicable_sessions", "applicable_timeframes"):
            items = value.get(key)
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise ValueError(f"KnowledgeRule.{key} precisa ser uma lista de textos.")
        version = value.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("KnowledgeRule.version precisa ser inteiro positivo.")
        try:
            status = ValidationStatus(value["validation_status"])
            created = date.fromisoformat(value["created_at"])
            reviewed_raw = value.get("reviewed_at")
            reviewed = date.fromisoformat(reviewed_raw) if reviewed_raw else None
        except (KeyError, ValueError, TypeError):
            raise ValueError("KnowledgeRule contém status ou data inválidos.") from None
        if status in {ValidationStatus.APPROVED_FOR_DEMO, ValidationStatus.APPROVED_FOR_LIVE} and reviewed is None:
            raise ValueError("Aprovação para demo/live exige reviewed_at.")
        return cls(
            rule_id=value["rule_id"], title=value["title"], category=value["category"],
            description=value["description"], source_document=value["source_document"],
            source_location=value["source_location"], conditions=tuple(value["conditions"]),
            expected_observation=value["expected_observation"], invalidation=value["invalidation"],
            confidence_status=value["confidence_status"], validation_status=status,
            applicable_symbols=tuple(value["applicable_symbols"]),
            applicable_sessions=tuple(value["applicable_sessions"]),
            applicable_timeframes=tuple(value["applicable_timeframes"]), version=version,
            created_at=created, reviewed_at=reviewed,
        )


@dataclass(frozen=True, slots=True)
class KnowledgeRepository:
    rules: tuple[KnowledgeRule, ...]

    @classmethod
    def load(cls, path: Path) -> "KnowledgeRepository":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("Versão do catálogo de conhecimento ausente ou incompatível.")
        raw_rules = payload.get("rules")
        if not isinstance(raw_rules, list):
            raise ValueError("O catálogo precisa conter uma lista rules.")
        rules = tuple(KnowledgeRule.from_mapping(item) for item in raw_rules if isinstance(item, dict))
        if len(rules) != len(raw_rules):
            raise ValueError("Cada regra do catálogo precisa ser um objeto.")
        identifiers = [rule.rule_id for rule in rules]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("rule_id duplicado no catálogo de conhecimento.")
        return cls(rules)

    def for_environment(self, environment: KnowledgeEnvironment) -> tuple[KnowledgeRule, ...]:
        """Return only rules explicitly cleared for this environment."""
        eligible = _ELIGIBLE[environment]
        return tuple(rule for rule in self.rules if rule.validation_status in eligible)

