"""第七阶段合成演示：多股票共享现金目标执行。"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from multi_factor_research.execution import ExecutionCostModel, execute_portfolio_plan
from multi_factor_research.portfolio import PortfolioResult


def build_demo_plan() -> PortfolioResult:
    targets = pd.DataFrame([
        ["2025-01-03", "2025-01-06", "AAA", 0.5],
        ["2025-01-03", "2025-01-06", "BBB", 0.5],
        ["2025-01-10", "2025-01-13", "BBB", 0.5],
        ["2025-01-10", "2025-01-13", "CCC", 0.5],
    ], columns=["signal_date", "execution_date", "symbol", "target_weight"])
    rebalances = pd.DataFrame([
        ["2025-01-03", "2025-01-06", 2, 0.0, 1.0, "planned"],
        ["2025-01-10", "2025-01-13", 2, 0.0, 0.5, "planned"],
    ], columns=["signal_date", "execution_date", "selected_count", "cash_weight", "target_turnover", "status"])
    return PortfolioResult(
        scores=pd.DataFrame(), targets=targets, changes=pd.DataFrame(), rebalances=rebalances,
        parameters={"demo": True}, file_sha256="synthetic-stage7", calendar_source="synthetic/calendar", calendar_version="v1",
    )


def build_demo_market() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-03", periods=8)
    prices = {"AAA": 10.0, "BBB": 20.0, "CCC": 25.0}
    rows = []
    for i, day in enumerate(dates):
        for symbol, base in prices.items():
            price = base + i * 0.2
            rows.append([symbol, day.strftime("%Y-%m-%d"), price, price])
    return pd.DataFrame(rows, columns=["symbol", "trade_date", "open", "close"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    costs = ExecutionCostModel(
        commission_rate=Decimal("0.001"), minimum_commission=Decimal("5"),
        stamp_tax_rate=Decimal("0.001"), slippage_bps=Decimal("0"), lot_size=100,
    )
    result = execute_portfolio_plan(build_demo_plan(), build_demo_market(), initial_cash=Decimal("100000"), costs=costs)
    pd.DataFrame([x.__dict__ for x in result.orders]).to_csv(args.output / "orders.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([x.__dict__ for x in result.trades]).to_csv(args.output / "trades.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([x.__dict__ for x in result.snapshots]).to_csv(args.output / "snapshots.csv", index=False, encoding="utf-8-sig")
    result.positions.to_csv(args.output / "positions.csv", index=False, encoding="utf-8-sig")
    summary = {
        "status": "completed", "is_synthetic": True, "initial_cash": "100000.00",
        "order_count": len(result.orders), "trade_count": len(result.trades),
        "filled_orders": sum(x.status == "FILLED" for x in result.orders),
        "rejected_orders": sum(x.status == "REJECTED" for x in result.orders),
        "snapshot_count": len(result.snapshots),
        "final_cash": str(result.snapshots[-1].cash),
        "final_value": str(result.snapshots[-1].total_value),
        "parameters": result.parameters,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "limitations": ["合成行情和目标计划，不代表真实策略收益。", "未修改项目一单股票回测引擎。", "缺少开盘价时拒单，成交后按收盘价估值。"],
    }
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
