"""Account reconciliation module for paper-safe pre-live verification.

This module compares a local snapshot (e.g. paper portfolio state) against
an external interface response (e.g. exchange account info) to detect
discrepancies before they compound.  It is designed to run in-process
during a trading cycle or as a standalone health-check.

Only paper-safe / readonly interfaces are consulted — no live trading is
performed or implied by this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trading.storage.repositories import EventsRepository


class ReconciliationStatus(StrEnum):
    """Overall reconciliation health."""

    OK = "ok"
    """Balances and positions match within tolerance."""

    BALANCE_MISMATCH = "balance_mismatch"
    """Cash balance differs beyond the configured threshold."""

    POSITION_MISMATCH = "position_mismatch"
    """One or more position quantities differ beyond the configured threshold."""

    GLOBAL_PAUSE_RECOMMENDED = "global_pause_recommended"
    """Discrepancy exceeds critical threshold; a full pause is recommended."""


@dataclass(frozen=True)
class ReconciliationThresholds:
    """Tunable tolerance parameters for reconciliation checks."""

    balance_diff_usdt: Decimal = field(default_factory=lambda: Decimal("1.0"))
    position_diff_absolute: Decimal = field(default_factory=lambda: Decimal("0.0001"))
    position_diff_count: int = 0  # number of positions that differ
    balance_critical_usdt: Decimal = field(default_factory=lambda: Decimal("10.0"))
    position_critical_count: int = 3  # trigger global_pause_recommended after this many mismatches


@dataclass(frozen=True)
class ReconciliationResult:
    """Structured result of a reconciliation run."""

    status: ReconciliationStatus
    balance_diff_usdt: Decimal
    position_diff_count: int
    reason: str

    @property
    def global_pause_recommended(self) -> bool:
        return self.status == ReconciliationStatus.GLOBAL_PAUSE_RECOMMENDED


@dataclass(frozen=True)
class BalanceSnapshot:
    """Simple snapshot of a single asset's cash balance."""

    asset: str          # e.g. "USDT"
    free: Decimal       # available balance
    locked: Decimal     # reserved / open-order locked

    @property
    def total_usdt(self) -> Decimal:
        # For non-USDT assets this would need a price lookup; we store as-is.
        if self.asset == "USDT":
            return self.free + self.locked
        return Decimal("0")


@dataclass(frozen=True)
class PositionSnapshot:
    """Simple snapshot of a single symbol's position."""

    symbol: str         # e.g. "BTCUSDT"
    qty: Decimal         # absolute quantity held
    avg_entry_price: Decimal


# ── Mock data sources ──────────────────────────────────────────────────────────
# These exist so the reconciliation framework can be exercised without a live
# exchange connection.  Replace with real interface adapters (e.g. Binance
# account-info API) when available.


def mock_fetch_interface_balances() -> list[BalanceSnapshot]:
    """Return mock interface balance data for paper-safe testing."""
    return [
        BalanceSnapshot(asset="USDT", free=Decimal("500.0"), locked=Decimal("0")),
    ]


def mock_fetch_interface_positions() -> list[PositionSnapshot]:
    """Return mock interface position data for paper-safe testing."""
    return []


# ── Core reconciliation logic ───────────────────────────────────────────────────


def run_reconciliation(
    local_balances: list[BalanceSnapshot],
    local_positions: list[PositionSnapshot],
    interface_balances: list[BalanceSnapshot] | None = None,
    interface_positions: list[PositionSnapshot] | None = None,
    thresholds: ReconciliationThresholds | None = None,
) -> ReconciliationResult:
    """Compare local snapshots against interface data and return a result.

    Args:
        local_balances:  balances tracked by the local portfolio/accounting layer.
        local_positions: positions tracked by the local portfolio/accounting layer.
        interface_balances: balances reported by the external interface
            (exchange account-info).  When None the mock is used.
        interface_positions: positions reported by the external interface.
            When None the mock is used.
        thresholds: tolerance configuration.  When None defaults are used.

    Returns:
        ReconciliationResult describing the comparison outcome.
    """
    if thresholds is None:
        thresholds = ReconciliationThresholds()

    if interface_balances is None:
        interface_balances = mock_fetch_interface_balances()
    if interface_positions is None:
        interface_positions = mock_fetch_interface_positions()

    # ── Balance comparison ─────────────────────────────────────────────────────
    local_by_asset = {b.asset: b for b in local_balances}
    iface_by_asset = {b.asset: b for b in interface_balances}

    balance_diff_usdt = Decimal("0")
    balance_mismatch = False

    all_assets = set(local_by_asset.keys()) | set(iface_by_asset.keys())
    for asset in all_assets:
        local_b = local_by_asset.get(asset)
        iface_b = iface_by_asset.get(asset)

        local_total = local_b.total_usdt if local_b else Decimal("0")
        iface_total = iface_b.total_usdt if iface_b else Decimal("0")

        diff = abs(local_total - iface_total)
        if diff > thresholds.balance_diff_usdt:
            balance_mismatch = True
            balance_diff_usdt = max(balance_diff_usdt, diff)

    # ── Position comparison ─────────────────────────────────────────────────────
    local_by_symbol = {p.symbol: p for p in local_positions}
    iface_by_symbol = {p.symbol: p for p in interface_positions}

    position_diff_count = 0
    position_mismatch = False

    all_symbols = set(local_by_symbol.keys()) | set(iface_by_symbol.keys())
    for symbol in all_symbols:
        local_p = local_by_symbol.get(symbol)
        iface_p = iface_by_symbol.get(symbol)

        local_qty = local_p.qty if local_p else Decimal("0")
        iface_qty = iface_p.qty if iface_p else Decimal("0")

        diff = abs(local_qty - iface_qty)
        if diff > thresholds.position_diff_absolute:
            position_mismatch = True
            position_diff_count += 1

    # ── Determine overall status ───────────────────────────────────────────────
    if balance_mismatch and balance_diff_usdt > thresholds.balance_critical_usdt:
        status = ReconciliationStatus.GLOBAL_PAUSE_RECOMMENDED
        reason = (
            f"balance diff {balance_diff_usdt} USDT exceeds critical threshold "
            f"{thresholds.balance_critical_usdt} USDT"
        )
    elif position_diff_count >= thresholds.position_critical_count:
        status = ReconciliationStatus.GLOBAL_PAUSE_RECOMMENDED
        reason = (
            f"{position_diff_count} positions differ (threshold: "
            f"{thresholds.position_critical_count}); global pause recommended"
        )
    elif balance_mismatch:
        status = ReconciliationStatus.BALANCE_MISMATCH
        reason = f"balance diff {balance_diff_usdt} USDT"
    elif position_mismatch:
        status = ReconciliationStatus.POSITION_MISMATCH
        reason = f"{position_diff_count} position(s) differ"
    else:
        status = ReconciliationStatus.OK
        reason = "balances and positions match within tolerance"

    return ReconciliationResult(
        status=status,
        balance_diff_usdt=balance_diff_usdt,
        position_diff_count=position_diff_count,
        reason=reason,
    )


# ── Event recording helpers ────────────────────────────────────────────────────


def record_reconciliation_event(
    events_repo: EventsRepository,
    result: ReconciliationResult,
) -> None:
    """Write a reconciliation result to the event log.

    This is called by the runtime after each reconciliation check so the
    outcome is auditable from the dashboard events feed.
    """
    try:
        if result.status == ReconciliationStatus.OK:
            events_repo.record_event(
                event_type="reconciliation_ok",
                severity="info",
                component="reconciliation",
                message="Reconciliation passed",
                context={
                    "status": result.status.value,
                    "balance_diff_usdt": str(result.balance_diff_usdt),
                    "position_diff_count": result.position_diff_count,
                    "reason": result.reason,
                },
            )
        else:
            events_repo.record_event(
                event_type="reconciliation_mismatch",
                severity=(
                    "warning"
                    if result.status != ReconciliationStatus.GLOBAL_PAUSE_RECOMMENDED
                    else "error"
                ),
                component="reconciliation",
                message=f"Reconciliation mismatch: {result.reason}",
                context={
                    "status": result.status.value,
                    "balance_diff_usdt": str(result.balance_diff_usdt),
                    "position_diff_count": result.position_diff_count,
                    "global_pause_recommended": result.global_pause_recommended,
                    "reason": result.reason,
                },
            )
    except Exception:
        # Fail closed: if event recording fails, still don't let it crash the runtime.
        logging.getLogger(__name__).exception(
            "Failed to record reconciliation event: status=%s", result.status
        )
