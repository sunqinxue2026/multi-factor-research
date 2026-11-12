from datetime import date
from decimal import Decimal

import pytest

from multi_factor_research.execution import ExecutionResult, PortfolioSnapshot, ExecutionOrder, ExecutionTrade
from multi_factor_research.performance import analyze_portfolio_performance
import pandas as pd


def execution(values):
    snapshots = [PortfolioSnapshot(date(2025, 1, i + 1), Decimal(str(v)), Decimal(str(v)), 0, 0, None, Decimal("0")) for i, v in enumerate(values)]
    return ExecutionResult([], [], snapshots, pd.DataFrame(), {})


def test_project_one_equity_return_drawdown_and_sharpe_definition():
    metrics, curve = analyze_portfolio_performance(execution([10000, 11000, 9900]), Decimal("10000"))
    assert metrics["total_return"] == pytest.approx(-0.01)
    assert metrics["max_drawdown"] == pytest.approx(-0.1)
    assert curve.normalized_equity.tolist() == pytest.approx([1.0, 1.1, 0.99])
    assert metrics["definitions"]["volatility"].endswith("ddof=1乘sqrt(annualization_days)")


def test_missing_equity_snapshots_are_skipped_and_empty_fails():
    snapshots = [
        PortfolioSnapshot(date(2025, 1, 1), Decimal("10000"), None, 1, 100, None, Decimal("0")),
        PortfolioSnapshot(date(2025, 1, 2), Decimal("10000"), Decimal("10000"), 1, 100, None, Decimal("0")),
    ]
    metrics, curve = analyze_portfolio_performance(ExecutionResult([], [], snapshots, pd.DataFrame(), {}), Decimal("10000"))
    assert len(curve) == 1
    with pytest.raises(ValueError):
        analyze_portfolio_performance(ExecutionResult([], [], [snapshots[0]], pd.DataFrame(), {}), Decimal("10000"))
