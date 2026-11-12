"""多股票组合绩效；口径与项目一保持一致，但不使用单股票交易配对统计。"""
from __future__ import annotations

import math
from decimal import Decimal
import numpy as np
import pandas as pd

from .execution import ExecutionResult


def analyze_portfolio_performance(
    execution: ExecutionResult,
    initial_capital: Decimal,
    *,
    annualization_days: int = 252,
    risk_free_rate: float = 0.0,
) -> tuple[dict[str, object], pd.DataFrame]:
    if isinstance(annualization_days, bool) or not isinstance(annualization_days, int) or annualization_days <= 0:
        raise ValueError("年化交易日数必须为正整数")
    initial = float(initial_capital)
    if not math.isfinite(initial) or initial <= 0 or not math.isfinite(risk_free_rate) or risk_free_rate <= -1:
        raise ValueError("初始资金或无风险利率无效")
    rows = [s for s in execution.snapshots if s.total_value is not None]
    if not rows:
        raise ValueError("没有可用账户估值")
    curve = pd.DataFrame({"trade_date": [s.trade_date for s in rows], "equity": [float(s.total_value) for s in rows]})
    curve["trade_date"] = pd.to_datetime(curve.trade_date)
    if curve.trade_date.duplicated().any() or not np.isfinite(curve.equity).all() or (curve.equity < 0).any():
        raise ValueError("账户曲线无效")
    equity = curve.equity.to_numpy(float)
    previous = np.r_[initial, equity[:-1]]
    if (previous == 0).any():
        raise ValueError("零资产之后的收益率未定义")
    returns = equity / previous - 1
    peak = np.maximum.accumulate(np.r_[initial, equity])[1:]
    curve["daily_return"] = returns
    curve["normalized_equity"] = equity / initial
    curve["drawdown"] = equity / peak - 1
    span = (curve.trade_date.iloc[-1] - curve.trade_date.iloc[0]).days
    total = equity[-1] / initial - 1
    annual = None if not span else (equity[-1] / initial) ** (365.25 / span) - 1
    if annual is not None and not math.isfinite(annual):
        annual = None
    std = float(np.std(returns, ddof=1)) if len(returns) >= 2 else None
    daily_rf = math.expm1(math.log1p(risk_free_rate) / annualization_days)
    sharpe = None if std is None or std <= 1e-15 else float(np.mean(returns - daily_rf) / std * math.sqrt(annualization_days))
    turnover = [float(s.actual_turnover) for s in execution.snapshots if s.actual_turnover]
    metrics = {
        "total_return": float(total),
        "annualized_return": None if annual is None else float(annual),
        "annualized_volatility": None if std is None else float(std * math.sqrt(annualization_days)),
        "max_drawdown": float(curve.drawdown.min()),
        "sharpe_ratio": sharpe,
        "final_equity": float(equity[-1]),
        "trade_count": len(execution.trades),
        "order_count": len(execution.orders),
        "filled_order_count": sum(o.status == "FILLED" for o in execution.orders),
        "rejected_order_count": sum(o.status == "REJECTED" for o in execution.orders),
        "turnover_sum": float(sum(turnover)),
        "average_rebalance_turnover": None if not turnover else float(np.mean(turnover)),
        "notes": ["组合绩效不使用项目一单股票完整交易配对统计。", "短样本年化指标仅用于公式核验。"],
        "definitions": {
            "returns": "首日equity/initial-1；之后equity/previous_equity-1",
            "drawdown": "包含初始资金的历史峰值",
            "annual_return": "(final/initial)^(365.25/calendar_days)-1",
            "volatility": "daily_return样本标准差ddof=1乘sqrt(annualization_days)",
            "turnover": "实际成交金额/调仓前已知账户价值，按调仓日记录",
        },
    }
    return metrics, curve
