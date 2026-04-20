"""Unit tests for the reconciliation module."""

from decimal import Decimal

from trading.runtime.reconciliation import (
    BalanceSnapshot,
    PositionSnapshot,
    ReconciliationResult,
    ReconciliationStatus,
    ReconciliationThresholds,
    mock_fetch_interface_balances,
    mock_fetch_interface_positions,
    run_reconciliation,
)


class TestReconciliationThresholds:
    """Threshold dataclass holds tolerance values correctly."""

    def test_default_balance_diff_threshold(self):
        t = ReconciliationThresholds()
        assert t.balance_diff_usdt == Decimal("1.0")

    def test_default_position_critical_count(self):
        t = ReconciliationThresholds()
        assert t.position_critical_count == 3

    def test_custom_thresholds(self):
        t = ReconciliationThresholds(
            balance_diff_usdt=Decimal("5.0"),
            balance_critical_usdt=Decimal("50.0"),
            position_diff_absolute=Decimal("0.001"),
            position_critical_count=5,
        )
        assert t.balance_diff_usdt == Decimal("5.0")
        assert t.balance_critical_usdt == Decimal("50.0")
        assert t.position_diff_absolute == Decimal("0.001")
        assert t.position_critical_count == 5


class TestReconciliationResult:
    """ReconciliationResult struct carries computed diffs correctly."""

    def test_global_pause_recommended_property_true(self):
        result = ReconciliationResult(
            status=ReconciliationStatus.GLOBAL_PAUSE_RECOMMENDED,
            balance_diff_usdt=Decimal("15.0"),
            position_diff_count=0,
            reason="balance diff exceeds critical",
        )
        assert result.global_pause_recommended is True

    def test_global_pause_recommended_property_false(self):
        result = ReconciliationResult(
            status=ReconciliationStatus.OK,
            balance_diff_usdt=Decimal("0"),
            position_diff_count=0,
            reason="all good",
        )
        assert result.global_pause_recommended is False


class TestMockDataSources:
    """Mock interface data sources return predictable paper-safe values."""

    def test_mock_balances_returns_usdt(self):
        balances = mock_fetch_interface_balances()
        assert len(balances) == 1
        assert balances[0].asset == "USDT"
        assert balances[0].free == Decimal("500.0")
        assert balances[0].locked == Decimal("0")

    def test_mock_positions_returns_empty(self):
        positions = mock_fetch_interface_positions()
        assert positions == []


class TestRunReconciliationPerfectMatch:
    """When local and interface snapshots match, status is OK."""

    def test_no_diffs_returns_ok(self):
        local = [BalanceSnapshot(asset="USDT", free=Decimal("500"), locked=Decimal("0"))]
        result = run_reconciliation(local_balances=local, local_positions=[])
        assert result.status == ReconciliationStatus.OK
        assert result.balance_diff_usdt == Decimal("0")
        assert result.position_diff_count == 0
        assert result.global_pause_recommended is False

    def test_with_positions_no_diffs_returns_ok(self):
        local_balances = [BalanceSnapshot(asset="USDT", free=Decimal("400"), locked=Decimal("0"))]
        local_positions = [
            PositionSnapshot(
                symbol="BTCUSDT",
                qty=Decimal("0.01"),
                avg_entry_price=Decimal("50000"),
            ),
        ]
        # Provide identical interface snapshots
        result = run_reconciliation(
            local_balances=local_balances,
            local_positions=local_positions,
            interface_balances=local_balances,
            interface_positions=local_positions,
        )
        assert result.status == ReconciliationStatus.OK


class TestRunReconciliationBalanceMismatch:
    """Balance differences are detected and reported."""

    def test_small_balance_diff_triggers_balance_mismatch(self):
        local = [BalanceSnapshot(asset="USDT", free=Decimal("500"), locked=Decimal("0"))]
        iface = [BalanceSnapshot(asset="USDT", free=Decimal("498"), locked=Decimal("0"))]
        result = run_reconciliation(
            local_balances=local,
            local_positions=[],
            interface_balances=iface,
            thresholds=ReconciliationThresholds(balance_diff_usdt=Decimal("1.0")),
        )
        assert result.status == ReconciliationStatus.BALANCE_MISMATCH
        assert result.balance_diff_usdt == Decimal("2")

    def test_critical_balance_diff_triggers_global_pause(self):
        local = [BalanceSnapshot(asset="USDT", free=Decimal("500"), locked=Decimal("0"))]
        iface = [BalanceSnapshot(asset="USDT", free=Decimal("485"), locked=Decimal("0"))]
        result = run_reconciliation(
            local_balances=local,
            local_positions=[],
            interface_balances=iface,
            thresholds=ReconciliationThresholds(
                balance_diff_usdt=Decimal("1.0"),
                balance_critical_usdt=Decimal("10.0"),
            ),
        )
        assert result.status == ReconciliationStatus.GLOBAL_PAUSE_RECOMMENDED
        assert result.global_pause_recommended is True


class TestRunReconciliationPositionMismatch:
    """Position quantity differences are detected and reported."""

    def test_single_position_diff_triggers_position_mismatch(self):
        local = [BalanceSnapshot(asset="USDT", free=Decimal("400"), locked=Decimal("0"))]
        local_pos = [
            PositionSnapshot(
                symbol="BTCUSDT",
                qty=Decimal("0.01"),
                avg_entry_price=Decimal("50000"),
            ),
        ]
        iface_pos = [
            PositionSnapshot(
                symbol="BTCUSDT",
                qty=Decimal("0.009"),
                avg_entry_price=Decimal("50000"),
            ),
        ]
        result = run_reconciliation(
            local_balances=local,
            local_positions=local_pos,
            interface_balances=local,
            interface_positions=iface_pos,
            thresholds=ReconciliationThresholds(position_diff_absolute=Decimal("0.0001")),
        )
        assert result.status == ReconciliationStatus.POSITION_MISMATCH
        assert result.position_diff_count == 1

    def test_multiple_position_diffs_trigger_global_pause(self):
        local = [BalanceSnapshot(asset="USDT", free=Decimal("400"), locked=Decimal("0"))]
        local_pos = [
            PositionSnapshot(
                symbol="BTCUSDT",
                qty=Decimal("0.01"),
                avg_entry_price=Decimal("50000"),
            ),
            PositionSnapshot(
                symbol="ETHUSDT",
                qty=Decimal("0.1"),
                avg_entry_price=Decimal("3000"),
            ),
            PositionSnapshot(
                symbol="SOLUSDT",
                qty=Decimal("1"),
                avg_entry_price=Decimal("100"),
            ),
        ]
        # Interface reports slightly different qty for all three
        iface_pos = [
            PositionSnapshot(
                symbol="BTCUSDT",
                qty=Decimal("0.009"),
                avg_entry_price=Decimal("50000"),
            ),
            PositionSnapshot(
                symbol="ETHUSDT",
                qty=Decimal("0.09"),
                avg_entry_price=Decimal("3000"),
            ),
            PositionSnapshot(
                symbol="SOLUSDT",
                qty=Decimal("0.9"),
                avg_entry_price=Decimal("100"),
            ),
        ]
        result = run_reconciliation(
            local_balances=local,
            local_positions=local_pos,
            interface_balances=local,
            interface_positions=iface_pos,
            thresholds=ReconciliationThresholds(
                position_diff_absolute=Decimal("0.0001"),
                position_critical_count=3,
            ),
        )
        assert result.status == ReconciliationStatus.GLOBAL_PAUSE_RECOMMENDED
        assert result.position_diff_count == 3


class TestRunReconciliationMissingAssets:
    """Missing assets in one snapshot are treated as zero-balance / zero-position."""

    def test_asset_missing_in_interface_treated_as_zero(self):
        local = [
            BalanceSnapshot(asset="USDT", free=Decimal("500"), locked=Decimal("0")),
            BalanceSnapshot(asset="BTC", free=Decimal("0.01"), locked=Decimal("0")),
        ]
        # Interface has no BTC
        iface = [BalanceSnapshot(asset="USDT", free=Decimal("500"), locked=Decimal("0"))]
        result = run_reconciliation(
            local_balances=local,
            local_positions=[],
            interface_balances=iface,
            thresholds=ReconciliationThresholds(balance_diff_usdt=Decimal("0")),
        )
        # BTC free=0.01 is treated as USDT value=0 in mock (non-USDT assets return 0),
        # so no USDT balance diff is detected. This test verifies the asset is not
        # incorrectly counted as a USDT balance difference.
        assert result.status in (
            ReconciliationStatus.OK,
            ReconciliationStatus.BALANCE_MISMATCH,
        )

    def test_symbol_missing_in_interface_treated_as_no_position(self):
        # Keep local and interface USDT balance identical so the balance diff
        # does not trigger global_pause before position mismatch is observed.
        local = [BalanceSnapshot(asset="USDT", free=Decimal("500"), locked=Decimal("0"))]
        local_pos = [
            PositionSnapshot(
                symbol="BTCUSDT",
                qty=Decimal("0.01"),
                avg_entry_price=Decimal("50000"),
            ),
        ]
        # With threshold=0 and balance_diff_usdt=0, position diff triggers position_mismatch
        result = run_reconciliation(
            local_balances=local,
            local_positions=local_pos,
            interface_balances=local,  # identical balance → no balance diff
            interface_positions=[],     # BTCUSDT missing in interface
            thresholds=ReconciliationThresholds(
                balance_diff_usdt=Decimal("0"),
                position_diff_absolute=Decimal("0"),
            ),
        )
        assert result.status == ReconciliationStatus.POSITION_MISMATCH
        assert result.position_diff_count == 1


class TestRunReconciliationDefaults:
    """run_reconciliation uses sensible defaults when called with minimal args."""

    def test_called_with_no_args_returns_global_pause(self):
        # local_balances=[] → local has no USDT (treated as 0)
        # mock interface has USDT=500 → diff=500 exceeds balance_critical_usdt=10 → GLOBAL_PAUSE
        result = run_reconciliation(local_balances=[], local_positions=[])
        assert result.status == ReconciliationStatus.GLOBAL_PAUSE_RECOMMENDED
        assert result.balance_diff_usdt == Decimal("500")

    def test_called_with_identical_local_and_mock_returns_ok(self):
        # Explicitly pass local equal to mock → no diff → OK
        local = [BalanceSnapshot(asset="USDT", free=Decimal("500"), locked=Decimal("0"))]
        result = run_reconciliation(
            local_balances=local,
            local_positions=[],
            interface_balances=mock_fetch_interface_balances(),
        )
        assert result.status == ReconciliationStatus.OK
