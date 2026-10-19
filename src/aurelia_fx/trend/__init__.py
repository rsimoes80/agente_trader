"""Causal trend hierarchy; no strategy or execution dependencies."""

from .trend_hierarchy_engine import (
    ClosedBarAggregator,
    HierarchyConfig,
    TrendHierarchyEngine,
    timeframe_seconds,
)

__all__ = [
    "HierarchyConfig",
    "TrendHierarchyEngine",
    "ClosedBarAggregator",
    "timeframe_seconds",
]
