"""Explicit and auditable agent state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .domain import AgentState


_ALLOWED: dict[AgentState, frozenset[AgentState]] = {
    AgentState.BOOTING: frozenset({AgentState.CONNECTING, AgentState.SYNCING_DATA, AgentState.SHUTDOWN}),
    AgentState.CONNECTING: frozenset({AgentState.SYNCING_DATA, AgentState.DATA_ERROR, AgentState.SHUTDOWN}),
    AgentState.SYNCING_DATA: frozenset({AgentState.OBSERVING, AgentState.DATA_ERROR, AgentState.SHUTDOWN}),
    AgentState.OBSERVING: frozenset({AgentState.BUILDING_CONTEXT, AgentState.SESSION_HALTED, AgentState.DATA_ERROR, AgentState.SHUTDOWN}),
    AgentState.BUILDING_CONTEXT: frozenset({AgentState.RETRIEVING_EXPERIENCE, AgentState.DATA_ERROR, AgentState.SHUTDOWN}),
    AgentState.RETRIEVING_EXPERIENCE: frozenset({AgentState.FORMING_HYPOTHESIS, AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.FORMING_HYPOTHESIS: frozenset({AgentState.BUILDING_EXPECTATION, AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.BUILDING_EXPECTATION: frozenset({AgentState.WAITING_FOR_ZONE, AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.WAITING_FOR_ZONE: frozenset({AgentState.WAITING_FOR_TRIGGER, AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.WAITING_FOR_TRIGGER: frozenset({AgentState.COMPARING_EXPECTED_OBSERVED, AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.COMPARING_EXPECTED_OBSERVED: frozenset({AgentState.HYPOTHESIS_CONFIRMED, AgentState.HYPOTHESIS_WEAKENING, AgentState.HYPOTHESIS_INVALIDATED, AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.HYPOTHESIS_CONFIRMED: frozenset({AgentState.VALIDATING_RISK, AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.HYPOTHESIS_WEAKENING: frozenset({AgentState.OBSERVING, AgentState.WAITING_FOR_ZONE, AgentState.SHUTDOWN}),
    AgentState.HYPOTHESIS_INVALIDATED: frozenset({AgentState.REVIEWING_EXPERIENCE, AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.VALIDATING_RISK: frozenset({AgentState.READY_TO_EXECUTE, AgentState.RISK_LOCK, AgentState.OBSERVING, AgentState.SHUTDOWN}),
    # READY_TO_EXECUTE is a future state. No transition to ORDER_PENDING exists
    # while this project has no execution adapter.
    AgentState.READY_TO_EXECUTE: frozenset({AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.ORDER_PENDING: frozenset({AgentState.POSITION_OPEN, AgentState.DATA_ERROR, AgentState.SHUTDOWN}),
    AgentState.POSITION_OPEN: frozenset({AgentState.MANAGING_POSITION, AgentState.COOLDOWN, AgentState.SHUTDOWN}),
    AgentState.MANAGING_POSITION: frozenset({AgentState.COOLDOWN, AgentState.DATA_ERROR, AgentState.SHUTDOWN}),
    AgentState.REVIEWING_EXPERIENCE: frozenset({AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.COOLDOWN: frozenset({AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.SESSION_HALTED: frozenset({AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.DATA_ERROR: frozenset({AgentState.SYNCING_DATA, AgentState.SHUTDOWN}),
    AgentState.RISK_LOCK: frozenset({AgentState.OBSERVING, AgentState.SHUTDOWN}),
    AgentState.SHUTDOWN: frozenset(),
}


@dataclass(frozen=True, slots=True)
class StateTransition:
    before: AgentState
    after: AgentState
    at: datetime
    reason: str


class AgentStateMachine:
    def __init__(self) -> None:
        self.state = AgentState.BOOTING
        self.transitions: list[StateTransition] = []

    def move(self, after: AgentState, reason: str) -> StateTransition:
        if after not in _ALLOWED[self.state]:
            raise ValueError(f"Transição proibida: {self.state.value} -> {after.value}.")
        transition = StateTransition(self.state, after, datetime.now(timezone.utc), reason)
        self.transitions.append(transition)
        self.state = after
        return transition
