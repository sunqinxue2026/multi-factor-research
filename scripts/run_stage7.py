"""第七阶段完整演示：数据、因子、预处理、评分、执行和组合绩效。"""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from multi_factor_research.data import DatasetMetadata, MarketDataset, TradingCalendar, build_calendar_panel
from multi_factor_research.factors import calculate_factors
from multi_factor_research.preprocessing import preprocess_factors
from multi_factor_research.portfolio import FACTOR_NAMES, build_portfolio_plan
from multi_factor_research.execution import ExecutionCostModel, execute_portfolio_plan
from multi_factor_research.performance import analyze_portfolio_performance


def build_market() -> tuple[pd.DataFrame, TradingCalendar]:
    dates = pd.bdate_range("2025-01-01", periods=100)
    rows = []
    for s in range(15):
        for i, day in enumerate(dates):
            price = (20 + s) * np.exp((s - 7) * 0.0005 * i + 0.015 * np.sin(i * (s + 1) / 7))
            rows.append([f"TEST{s:03}", day.strftime("%Y-%m-%d"), price, price, price, price, 100.0, price * 100])
    return pd.DataFrame(rows, columns=["symbol", "trade_date", "open", "high", "low", "close", "volume", "amount"]), TradingCalendar(dates, "TEST", "synthetic/stage7-calendar", "v1")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = perf_counter()
    args.output.mkdir(parents=True, exist_ok=False)
    market, calendar = build_market()
    metadata = DatasetMetadata("synthetic/stage7-demo", "TEST", "未复权", calendar.dates[-1].date(), True, "15只虚构证券；不是历史可投资股票池")
    digest = hashlib.sha256(market.to_csv(index=False).encode("utf-8")).hexdigest()
    panel = build_calendar_panel(MarketDataset(market, metadata, digest, "stage7-generated.csv"), calendar)
    factors = calculate_factors(panel, calendar, windows=(20,))
    preprocessed = preprocess_factors(factors)
    plan = build_portfolio_plan(preprocessed, calendar, windows={name: 20 for name in FACTOR_NAMES}, top_n=5, frequency="weekly")
    execution = execute_portfolio_plan(plan, market, initial_cash=Decimal("100000"), costs=ExecutionCostModel())
    metrics, curve = analyze_portfolio_performance(execution, Decimal("100000"))
    plan.scores.to_csv(args.output / "scores.csv", index=False, encoding="utf-8-sig")
    plan.targets.to_csv(args.output / "target_weights.csv", index=False, encoding="utf-8-sig")
    plan.rebalances.to_csv(args.output / "rebalances.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([x.__dict__ for x in execution.orders]).to_csv(args.output / "orders.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([x.__dict__ for x in execution.trades]).to_csv(args.output / "trades.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([x.__dict__ for x in execution.snapshots]).to_csv(args.output / "snapshots.csv", index=False, encoding="utf-8-sig")
    curve.to_csv(args.output / "equity_curve.csv", index=False, encoding="utf-8-sig")
    payload = {
        "status": "completed", "is_synthetic": True, "input_rows": len(market),
        "score_rows": len(plan.scores), "valid_scores": int(plan.scores.score_valid.sum()),
        "rebalance_count": len(plan.rebalances), "order_count": len(execution.orders), "trade_count": len(execution.trades),
        "metrics": metrics, "parameters": {"portfolio": plan.parameters, "execution": execution.parameters},
        "limitations": ["合成行情和教学日历，不代表真实策略收益。", "未接入项目一数据库。", "未建模涨跌停、停牌撮合、公司行动和历史股票池。"],
        "duration_seconds": perf_counter() - started,
    }
    (args.output / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
