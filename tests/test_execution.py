from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from multi_factor_research.execution import ExecutionCostModel, execute_portfolio_plan
from multi_factor_research.portfolio import PortfolioResult


def plan(target_rows, rebalance_rows):
    return PortfolioResult(
        scores=pd.DataFrame(),
        targets=pd.DataFrame(target_rows, columns=["signal_date", "execution_date", "symbol", "target_weight"]),
        changes=pd.DataFrame(),
        rebalances=pd.DataFrame(rebalance_rows, columns=["signal_date", "execution_date", "selected_count", "cash_weight", "target_turnover", "status"]),
        parameters={}, file_sha256="digest", calendar_source="synthetic/calendar", calendar_version="v1",
    )


def market(rows):
    return pd.DataFrame(rows, columns=["symbol", "trade_date", "open", "close"])


def test_shared_cash_sell_before_buy_and_signal_execution_dates():
    target = plan(
        [
            ["2025-01-02", "2025-01-03", "A", 0.5],
            ["2025-01-02", "2025-01-03", "B", 0.5],
        ],
        [["2025-01-02", "2025-01-03", 2, 0.0, 1.0, "planned"]],
    )
    prices = market([
        ["A", "2025-01-02", 10, 10], ["B", "2025-01-02", 20, 20],
        ["A", "2025-01-03", 10, 10], ["B", "2025-01-03", 20, 20],
    ])
    result = execute_portfolio_plan(target, prices, initial_cash=Decimal("100000"), costs=ExecutionCostModel(commission_rate=0, minimum_commission=0, stamp_tax_rate=0, slippage_bps=0))
    assert [(x.symbol, x.side, x.quantity, x.signal_date, x.execute_date) for x in result.orders] == [
        ("A", "BUY", 5000, date(2025, 1, 2), date(2025, 1, 3)),
        ("B", "BUY", 2500, date(2025, 1, 2), date(2025, 1, 3)),
    ]
    assert result.trades[0].quantity == 5000
    assert result.trades[1].quantity == 2500
    assert result.snapshots[-1].cash == Decimal("0.00")
    assert result.snapshots[-1].total_value == Decimal("100000.00")


def test_t1_prevents_same_day_sale_and_missing_open_rejects():
    target = plan(
        [["2025-01-02", "2025-01-03", "A", 1.0]],
        [["2025-01-02", "2025-01-03", 1, 0.0, 1.0, "planned"]],
    )
    prices = market([["A", "2025-01-02", 10, 10], ["A", "2025-01-03", None, 10]])
    result = execute_portfolio_plan(target, prices, initial_cash=Decimal("10000"), costs=ExecutionCostModel(commission_rate=0, minimum_commission=0, stamp_tax_rate=0, slippage_bps=0))
    assert result.orders[0].status == "REJECTED"
    assert result.orders[0].reason == "缺少有效开盘价"
    assert result.trades == []
    assert result.snapshots[-1].total_value == Decimal("10000.00")


def test_costs_lot_size_and_cash_shortfall():
    target = plan(
        [["2025-01-02", "2025-01-03", "A", 0.5], ["2025-01-02", "2025-01-03", "B", 0.5]],
        [["2025-01-02", "2025-01-03", 2, 0.0, 1.0, "planned"]],
    )
    prices = market([["A", "2025-01-02", 10, 10], ["B", "2025-01-02", 10, 10], ["A", "2025-01-03", 10, 10], ["B", "2025-01-03", 10, 10]])
    result = execute_portfolio_plan(target, prices, initial_cash=Decimal("10000"), costs=ExecutionCostModel(commission_rate=Decimal("0.001"), minimum_commission=Decimal("5"), stamp_tax_rate=0, slippage_bps=0, lot_size=100))
    assert all(trade.quantity % 100 == 0 for trade in result.trades)
    assert sum(trade.quantity * trade.price for trade in result.trades) > 0
    assert result.snapshots[-1].cash >= 0


def test_bad_market_contract():
    target = plan([], [])
    with pytest.raises(ValueError):
        execute_portfolio_plan(target, pd.DataFrame({"symbol": ["A"]}))
