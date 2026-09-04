"""CI-only, time-boxed acknowledgement of a known upstream freshness freeze.

Why this module exists
----------------------
``quality/freshness.py`` answers one question and answers it for everybody:
*is this observation inside the policy window?* The dashboard shows that answer
to a human, so it must stay brutally literal — an eight-month-old CPI reading is
``error``, permanently, no exceptions.

But CI asks a different question: *is this a NEW problem?* When an upstream
series is frozen and the freeze has already been investigated, documented and
accepted, failing the scheduled run every single week produces a red that
carries no information. A check that can only ever be red has stopped being a
check.

So this module adds a second, CI-only decision layer on top of the shared
policy. It never relaxes the policy; it classifies the policy's ``error`` into
"the known freeze, still within its review window" versus "everything else".

Three properties keep this from decaying into a permanent bypass:

1. **Exact match.** The waiver applies only when the series code matches
   exactly AND the newest observation month equals the recorded ``frozen_at``
   month exactly. If upstream publishes even one more month, the waiver stops
   matching and the gate fails again.
2. **Hard expiry.** ``review_by`` is *exclusive*. On that date the waiver stops
   applying and the gate goes red on its own, with no human action required.
   A waiver cannot silently outlive its justification.
3. **Fail-closed.** Every parse error, missing field, unknown field, wildcard,
   duplicate or contradictory record raises at import time. A malformed waiver
   never degrades into a permissive one.

This module deliberately lives under ``ingest/`` and is imported only by the CI
gate. ``dashboard/`` imports ``quality.freshness`` and must never import this.
``tests/test_freshness.py`` asserts that separation.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quality.freshness import (  # noqa: E402
    MAX_LAG_MONTHS,
    freshness_state,
    normalize_observation_date,
)

# Decision states returned by evaluate_ci_freshness.
FRESH = "fresh"
ACKNOWLEDGED_STALE = "acknowledged_stale"
STALE = "stale"

_MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_SERIES_PATTERN = re.compile(r"^[A-Za-z0-9._]+$")


class WaiverConfigError(ValueError):
    """Raised when a waiver record is malformed, ambiguous or contradictory.

    This is intentionally fatal at import time. A waiver whose meaning is
    unclear must never be interpreted generously.
    """


@dataclass(frozen=True)
class FreshnessWaiver:
    """One acknowledged upstream freeze, valid for a bounded period.

    Attributes
    ----------
    series_code:
        Exact upstream series identifier. Wildcards are rejected.
    frozen_at:
        The ``YYYY-MM`` month of the newest observation at acknowledgement
        time. The waiver matches only this exact month.
    accepted_on:
        Date the freeze was investigated and accepted. Runs dated before this
        do not match.
    review_by:
        **Exclusive** expiry. The waiver applies while
        ``accepted_on <= as_of < review_by``.
    owner:
        Who is accountable for revisiting this before ``review_by``.
    evidence:
        Where the investigation is recorded.
    issue:
        The tracking issue for this incident.
    """

    series_code: str
    frozen_at: str
    accepted_on: date
    review_by: date
    owner: str
    evidence: str
    issue: str

    def __post_init__(self) -> None:
        for field_name in ("series_code", "frozen_at", "owner", "evidence", "issue"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise WaiverConfigError(
                    f"waiver field {field_name!r} must be a non-empty string"
                )

        if not _SERIES_PATTERN.match(self.series_code):
            raise WaiverConfigError(
                f"waiver series_code {self.series_code!r} is not a literal series "
                "identifier; wildcards and patterns are not allowed"
            )

        if not _MONTH_PATTERN.match(self.frozen_at):
            raise WaiverConfigError(
                f"waiver frozen_at {self.frozen_at!r} must be an exact YYYY-MM month"
            )

        for field_name in ("accepted_on", "review_by"):
            value = getattr(self, field_name)
            if not isinstance(value, date):
                raise WaiverConfigError(
                    f"waiver field {field_name!r} must be a datetime.date"
                )

        if self.review_by <= self.accepted_on:
            raise WaiverConfigError(
                f"waiver review_by ({self.review_by.isoformat()}) must be strictly "
                f"after accepted_on ({self.accepted_on.isoformat()})"
            )

    def covers(self, series_code: str, observed_month: str, as_of: date) -> bool:
        """True only on an exact series + exact month match inside the window."""
        return (
            series_code == self.series_code
            and observed_month == self.frozen_at
            and self.accepted_on <= as_of < self.review_by
        )

    def days_remaining(self, as_of: date) -> int:
        """Whole days until this waiver stops applying. Never negative."""
        return max(0, (self.review_by - as_of).days)


# ---------------------------------------------------------------------------
# The register.
#
# Adding an entry here weakens a production gate for a bounded period, so it is
# a reviewed change, not a configuration tweak. Each record must cite evidence
# and name an owner.
#
# TP.FG.J0 froze upstream at 2026-01, verified 2026-08-22. Fourteen candidate
# replacement series were swept and the decision set came back empty: every
# YoY-compatible candidate was itself stale, and every current candidate was
# materially incompatible (TP.TUFE1YI.T1 diverges from TP.FG.J0 by a mean of
# 15.1540 and a maximum of 72.1737 percentage points across 121 overlapping YoY
# months — far too large to be a rebasing artifact, since a constant base factor
# cancels in a YoY ratio). Substituting a series was therefore rejected on the
# evidence, which is exactly why this freeze needs acknowledging rather than
# fixing.
# ---------------------------------------------------------------------------
WAIVERS: tuple[FreshnessWaiver, ...] = (
    FreshnessWaiver(
        series_code="TP.FG.J0",
        frozen_at="2026-01",
        accepted_on=date(2026, 9, 4),
        review_by=date(2026, 10, 5),
        owner="umutseve4",
        evidence="docs/data-freshness.md",
        issue="https://github.com/umutseve4/econ-lakehouse/issues/32",
    ),
)


def _validate_register(waivers: tuple[FreshnessWaiver, ...]) -> None:
    """Reject duplicate or contradictory records. Fail-closed."""
    seen: dict[str, FreshnessWaiver] = {}
    for waiver in waivers:
        if not isinstance(waiver, FreshnessWaiver):
            raise WaiverConfigError(
                f"waiver register contains a non-waiver entry: {waiver!r}"
            )
        existing = seen.get(waiver.series_code)
        if existing is not None:
            raise WaiverConfigError(
                f"duplicate waiver for series {waiver.series_code!r}; a series may "
                "have at most one acknowledged freeze"
            )
        seen[waiver.series_code] = waiver


_validate_register(WAIVERS)


def observation_month(value: Any) -> str:
    """Render any supported date-like value as an exact ``YYYY-MM`` string."""
    observed = normalize_observation_date(value)
    return f"{observed.year:04d}-{observed.month:02d}"


def find_waiver(
    series_code: str | None,
    observed_month: str,
    as_of: date,
    waivers: tuple[FreshnessWaiver, ...] = WAIVERS,
) -> FreshnessWaiver | None:
    """Return the single waiver covering this exact situation, if any.

    ``series_code`` of ``None`` — the caller did not tell us which series it
    fetched — can never match. Not knowing the series is not a reason to be
    lenient.
    """
    if not series_code:
        return None
    matches = [w for w in waivers if w.covers(series_code, observed_month, as_of)]
    if len(matches) > 1:  # pragma: no cover - _validate_register prevents this
        raise WaiverConfigError(
            f"multiple waivers match series {series_code!r} at {observed_month}"
        )
    return matches[0] if matches else None


def evaluate_ci_freshness(
    observed_on: Any,
    series_code: str | None = None,
    as_of: date | None = None,
    max_lag_months: int = MAX_LAG_MONTHS,
    waivers: tuple[FreshnessWaiver, ...] = WAIVERS,
) -> tuple[str, int, str]:
    """Classify freshness for CI into fresh / acknowledged_stale / stale.

    The shared policy in ``quality.freshness`` decides freshness; this function
    only decides whether an already-stale result is the *known* stale one. It
    never overrides ``success`` and never invents a passing lag.

    Returns ``(state, lag_months, message)``. The acknowledgement message never
    contains the word "fresh" at all — not even negated — because the data is
    stale and the wording must not be skim-readable as a pass. A test enforces
    this literally so no future rewording can soften it.
    """
    effective_as_of = as_of if as_of is not None else date.today()
    severity, lag, message = freshness_state(
        observed_on, effective_as_of, max_lag_months
    )

    if severity == "success":
        return (FRESH, lag, message)

    month = observation_month(observed_on)
    waiver = find_waiver(series_code, month, effective_as_of, waivers)
    if waiver is None:
        return (STALE, lag, message)

    remaining = waiver.days_remaining(effective_as_of)
    acknowledged = (
        f"Data is STALE and acknowledged, NOT current: series {waiver.series_code} "
        f"is frozen upstream at {waiver.frozen_at} ({lag} months old; policy "
        f"limit: {max_lag_months}). This is a known, investigated freeze accepted "
        f"on {waiver.accepted_on.isoformat()}, so CI does not treat it as a new "
        f"failure. The acknowledgement EXPIRES on {waiver.review_by.isoformat()} "
        f"({remaining} days remaining), after which this gate fails again. "
        f"Owner: {waiver.owner}. Evidence: {waiver.evidence}. Tracking: "
        f"{waiver.issue}"
    )
    return (ACKNOWLEDGED_STALE, lag, acknowledged)
