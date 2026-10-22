"""Immutable observations and explicit, unvalidated research parameters."""

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class RegimeConfig:
    regime_model_version: str = "0.1.1-expiry"
    transition_expiry_policy: str = "reset_pending_v1"
    window: int = 20
    confirmation_bars: int = 3
    breakout_acceptance_bars: int = 3
    breakout_lifetime_bars: int = 8
    range_lifetime_bars: int = 120
    trend_efficiency_min: float = 0.65
    range_efficiency_max: float = 0.30
    range_overlap_min: float = 0.45
    range_alternation_min: float = 0.40
    trend_extreme_fraction_min: float = 0.50
    boundary_band_fraction: float = 0.10
    boundary_tests_min: int = 2
    location_area_fraction: float = 0.25
    breakout_buffer_fraction: float = 0.02
    minimum_range_width: float = 0.0003
    maximum_age_periods: float = 1.5
    validation_status: str = "needs_review"

    def __post_init__(self):
        for key in (
            "window",
            "confirmation_bars",
            "breakout_acceptance_bars",
            "breakout_lifetime_bars",
            "range_lifetime_bars",
            "boundary_tests_min",
        ):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 2:
                raise ValueError(f"Invalid regime parameter: {key}")
        for key in (
            "trend_efficiency_min",
            "range_efficiency_max",
            "range_overlap_min",
            "range_alternation_min",
            "trend_extreme_fraction_min",
            "boundary_band_fraction",
            "location_area_fraction",
            "breakout_buffer_fraction",
        ):
            if not 0 < getattr(self, key) < 1:
                raise ValueError(f"Invalid regime fraction: {key}")
        if (
            self.range_efficiency_max >= self.trend_efficiency_min
            or not self.minimum_range_width > 0
            or not self.maximum_age_periods >= 1
            or not self.regime_model_version
            or self.validation_status != "needs_review"
            or self.transition_expiry_policy not in {"reset_pending_v1", "legacy_research_v0"}
        ):
            raise ValueError("Inconsistent or unapproved regime configuration")


@dataclass(frozen=True)
class RangeContext:
    range_id: str
    symbol: str
    timeframe: str
    detected_at: str
    upper_boundary: float
    lower_boundary: float
    midpoint: float
    range_width: float
    range_duration: int = 0
    position_inside_range: str = "UNDEFINED"
    internal_structure: str = "two_sided_unvalidated"
    boundary_test_count: dict = field(default_factory=dict)
    upper_break_attempts: int = 0
    lower_break_attempts: int = 0
    failed_breakouts: int = 0
    accepted_breakouts: int = 0
    volatility_state: str = "not_established"
    overlap_state: str = "observed"
    directional_progress: float = 0.0
    evidence_ids: tuple = ()
    status: str = "DEVELOPING"


@dataclass(frozen=True)
class BreakoutObservation:
    breakout_id: str
    range_id: str
    direction: str
    breakout_level: float
    breakout_timestamp: str
    displacement: float
    close_location: str
    follow_through: str = "not_observed"
    retest_status: str = "not_observed"
    return_inside_range: bool = False
    evidence_ids: tuple = ()
    current_status: str = "ATTEMPT"
    acceptance_bars: int = 0


@dataclass(frozen=True)
class RegimeTransition:
    transition_id: str
    from_regime: str
    candidate_regime: str
    started_at: str
    trigger_observation: str
    confirming_evidence: tuple = ()
    conflicting_evidence: tuple = ()
    confirmation_requirements: tuple = ()
    invalidation_requirements: tuple = ()
    status: str = "SUSPECTED"


@dataclass(frozen=True)
class MarketLocation:
    regime: str
    timeframe: str
    relative_location: str = "UNDEFINED"
    nearest_support: float | None = None
    nearest_resistance: float | None = None
    nearest_range_boundary: float | None = None
    nearest_structural_level: float | None = None
    distance_to_boundary: float | None = None
    distance_to_structural_level: float | None = None
    location_quality: str = "insufficient_data"


@dataclass(frozen=True)
class MarketRegimeState:
    regime_id: str
    snapshot_id: str
    timestamp_utc: str
    symbol: str
    timeframe: str
    session: tuple
    regime: str = "UNKNOWN"
    subtype: str = "UNRESOLVED"
    direction: str = "UNDEFINED"
    previous_regime: str = "UNKNOWN"
    transition_status: str = "none"
    maturity: str = "not_established"
    stability: str = "uncertain"
    directional_progress: float | None = None
    overlap_behavior: float | None = None
    breakout_behavior: str = "not_observed"
    follow_through_behavior: str = "not_observed"
    balance_state: str = "undetermined"
    range_state: dict = field(default_factory=dict)
    trend_state: str = "not_established"
    evidence_ids: tuple = ()
    conflicting_evidence_ids: tuple = ()
    invalidating_evidence_ids: tuple = ()
    missing_data: tuple = ()
    classification_quality: str = "descriptive_unvalidated"
    classification_status: str = "INSUFFICIENT_DATA"
    detected_at: str = ""
    last_updated_at: str = ""
    expires_at: str = ""
    regime_model_version: str = "0.1.1-expiry"
    regime_config_hash: str = ""
    transition: dict = field(default_factory=dict)
    breakout: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)
