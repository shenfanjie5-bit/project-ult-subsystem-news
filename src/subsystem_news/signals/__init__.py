"""Ex-2 signal generation and local constraint checks."""

from subsystem_news.signals.aggregator import (
    aggregate_cluster_signals,
    build_signal_candidate,
    generate_signals,
)
from subsystem_news.signals.direction_judge import SignalJudgement, judge_direction
from subsystem_news.signals.magnitude import (
    derive_impact_scope,
    derive_time_horizon,
    estimate_magnitude,
)
from subsystem_news.signals.promotion_rules import (
    PromotionDecision,
    should_promote_fact,
)
from subsystem_news.signals.schema_pin import SIGNAL_SCHEMA_PIN

__all__ = [
    "SIGNAL_SCHEMA_PIN",
    "PromotionDecision",
    "SignalJudgement",
    "aggregate_cluster_signals",
    "build_signal_candidate",
    "derive_impact_scope",
    "derive_time_horizon",
    "estimate_magnitude",
    "generate_signals",
    "judge_direction",
    "should_promote_fact",
]
