"""研究评分与目标组合计划；不模拟实际成交、现金漂移或交易成本。"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging

import numpy as np
import pandas as pd

from multi_factor_research.data import TradingCalendar
from multi_factor_research.preprocessing import PreprocessingResult

LOGGER = logging.getLogger(__name__)
FACTOR_NAMES = ("momentum", "volatility", "mean_reversion")


@dataclass
class PortfolioResult:
    scores: pd.DataFrame
    targets: pd.DataFrame
    changes: pd.DataFrame
    rebalances: pd.DataFrame
    parameters: dict[str, object]
    file_sha256: str
    calendar_source: str
    calendar_version: str


def build_portfolio_plan(
    factors: PreprocessingResult,
    calendar: TradingCalendar,
    *,
    windows: Mapping[str, int] | None = None,
    weights: Mapping[str, float] | None = None,
    top_n: int = 5,
    frequency: str = "weekly",
) -> PortfolioResult:
    """全部指定因子有效才评分；周期末信号、下一日历位置计划执行。

    相邻目标单边换手包含现金，不等于真实持仓漂移后的实际换手。
    日历必须覆盖下一周期，尾部不猜测周期结束。无截面也输出现金目标。
    """
    window_map = dict(windows) if windows is not None else {name: 20 for name in FACTOR_NAMES}
    weight_map = dict(weights) if weights is not None else {name: 1 / 3 for name in FACTOR_NAMES}
    if set(window_map) != set(FACTOR_NAMES) or set(weight_map) != set(FACTOR_NAMES):
        raise ValueError("必须为三个因子明确配置窗口和权重")
    if any(type(v) is not int or v < 2 for v in window_map.values()):
        raise ValueError("窗口必须为至少2的整数")
    if any(isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, float)) or not np.isfinite(v) or v < 0 for v in weight_map.values()):
        raise ValueError("权重必须为有限非负数")
    if not np.isclose(sum(weight_map.values()), 1., rtol=0, atol=1e-12):
        raise ValueError("权重之和必须为1，不隐式归一化")
    if type(top_n) is not int or top_n <= 0:
        raise ValueError("top_n必须为正整数")
    if frequency not in ("weekly", "monthly"):
        raise ValueError("frequency仅支持weekly/monthly")
    if (factors.calendar_source, factors.calendar_version) != (calendar.source, calendar.version):
        raise ValueError("日历身份不一致")
    keys = ["symbol", "trade_date", "factor", "window"]
    frame = factors.frame.copy(deep=True)
    if frame.empty or not set(keys + ["oriented_value", "preprocess_valid"]).issubset(frame.columns):
        raise ValueError("输入为空或缺少因子字段")
    frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise")
    if frame.trade_date.dt.tz is not None or not frame.trade_date.eq(frame.trade_date.dt.normalize()).all():
        raise ValueError("日期必须无时区且无日内时间")
    if frame[keys].isna().any().any() or frame.duplicated(keys).any():
        raise ValueError("联合键缺失或重复")
    if not frame.symbol.map(lambda x: isinstance(x, str) and bool(x.strip()) and x == x.strip() and x != "CASH").all():
        raise ValueError("股票代码非法或使用保留字CASH")
    if not frame.trade_date.isin(calendar.dates).all():
        raise ValueError("因子存在日历外日期")
    if not frame.window.map(lambda x: isinstance(x, (int, np.integer)) and not isinstance(x, (bool, np.bool_)) and x >= 2).all():
        raise ValueError("因子窗口非法")
    if not frame.preprocess_valid.map(lambda x: isinstance(x, (bool, np.bool_))).all():
        raise ValueError("preprocess_valid必须为布尔值")
    raw = frame.oriented_value
    numeric = pd.to_numeric(raw, errors="coerce").astype(float)
    if raw.map(lambda x: isinstance(x, (bool, np.bool_))).any() or (raw.notna() & numeric.isna()).any() or np.isinf(numeric).any() or (frame.preprocess_valid & numeric.isna()).any():
        raise ValueError("定向因子数值非法")
    frame["oriented_value"] = numeric
    # 保留每个已观察股票日期；指定窗口缺失时也不能静默丢行。
    base = frame[["symbol", "trade_date"]].drop_duplicates().sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    for name in FACTOR_NAMES:
        part = frame[frame.factor.eq(name) & frame.window.eq(window_map[name])]
        part = part[["symbol", "trade_date", "oriented_value", "preprocess_valid"]].rename(columns={"oriented_value": name, "preprocess_valid": f"{name}_valid"})
        base = base.merge(part, on=["symbol", "trade_date"], how="left", validate="one_to_one")
    flag_cols = [f"{name}_valid" for name in FACTOR_NAMES]
    base["score_valid"] = base[flag_cols].eq(True).all(axis=1) & base[list(FACTOR_NAMES)].notna().all(axis=1)
    base["score"] = sum(base[name] * weight_map[name] for name in FACTOR_NAMES).where(base.score_valid)
    if not np.isfinite(base.loc[base.score_valid, "score"]).all():
        raise ValueError("综合评分溢出")
    base["score_reason"] = np.where(base.score_valid, "valid", "missing_or_invalid_factor")
    base = base.sort_values(["trade_date", "score", "symbol"], ascending=[True, False, True], na_position="last", kind="stable").reset_index(drop=True)
    base["rank"] = pd.Series(pd.NA, index=base.index, dtype="Int64")
    valid = base[base.score_valid]
    base.loc[valid.index, "rank"] = valid.groupby("trade_date").cumcount().to_numpy() + 1
    dates = calendar.dates
    periods = dates.to_period("W-SUN" if frequency == "weekly" else "M")
    target_rows, change_rows, rebalance_rows = [], [], []
    previous = {"CASH": 1.}
    by_date = {day: block for day, block in base.groupby("trade_date", sort=False)}
    for i in range(len(dates) - 1):
        if periods[i] == periods[i + 1]:
            continue
        signal, execution = dates[i], dates[i + 1]
        block = by_date.get(signal)
        selected = base.iloc[:0] if block is None else block[block.score_valid & block["rank"].le(top_n).fillna(False)]
        current = {symbol: 1 / top_n for symbol in selected.symbol}
        current["CASH"] = max(0., 1 - len(selected) / top_n)
        common = {"signal_date": signal, "execution_date": execution}
        for symbol, weight in sorted(current.items()):
            target_rows.append(common | {"symbol": symbol, "target_weight": weight})
        total_change = 0.
        for symbol in sorted(set(previous) | set(current)):
            old, new = previous.get(symbol, 0.), current.get(symbol, 0.)
            delta = new - old
            total_change += abs(delta)
            change_rows.append(common | {"symbol": symbol, "previous_target_weight": old, "target_weight": new,
                "weight_change": delta, "action": "increase" if delta > 0 else "decrease" if delta < 0 else "unchanged"})
        rebalance_rows.append(common | {"selected_count": len(selected), "cash_weight": current["CASH"],
            "target_turnover": .5 * total_change, "status": "all_cash" if selected.empty else "planned"})
        previous = current
    LOGGER.info("评分 rows=%s valid=%s rebalances=%s", len(base), int(base.score_valid.sum()), len(rebalance_rows))
    return PortfolioResult(base,
        pd.DataFrame(target_rows, columns=["signal_date", "execution_date", "symbol", "target_weight"]),
        pd.DataFrame(change_rows, columns=["signal_date", "execution_date", "symbol", "previous_target_weight", "target_weight", "weight_change", "action"]),
        pd.DataFrame(rebalance_rows, columns=["signal_date", "execution_date", "selected_count", "cash_weight", "target_turnover", "status"]),
        {"windows": window_map, "weights": weight_map, "top_n": top_n, "frequency": frequency,
         "ranking": "score descending, symbol ascending", "incomplete_factors": "exclude without weight redistribution",
         "turnover": "0.5*sum(abs(target-new minus target-old)), including CASH; initial all cash",
         "execution": "next supplied market date; plan only", "tail": "skip unconfirmed final period",
         "costs_included": False, "preprocessing": factors.parameters},
        factors.file_sha256, calendar.source, calendar.version)
