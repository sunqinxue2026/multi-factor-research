"""历史价格因子；连续性按显式市场日历验证，不代表投资资格。"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from collections.abc import Sequence

import numpy as np
import pandas as pd

from multi_factor_research.data import KEYS, PanelResult, TradingCalendar, validate_market_frame

LOGGER = logging.getLogger(__name__)


@dataclass
class FactorResult:
    frame: pd.DataFrame
    parameters: dict[str, object]
    file_sha256: str
    calendar_source: str
    calendar_version: str


def calculate_factors(
    panel: PanelResult,
    calendar: TradingCalendar,
    *,
    windows: Sequence[int] = (20, 60),
    annualization_days: int = 252,
) -> FactorResult:
    """返回每个股票/日期/窗口的三类原始因子长表。

    momentum需要N+1个有效收盘价；volatility使用N个日收益，ddof=1；
    mean_reversion保存close/rolling_mean-1，尚未反转符号。
    状态列随输出保留，不以tradable未知推断样本不可研究或可以投资。
    """
    windows = tuple(windows)
    if not windows or any(type(n) is not int or n < 2 for n in windows):
        raise ValueError("windows必须包含至少一个大于等于2的整数，不接受布尔值")
    if len(set(windows)) != len(windows):
        raise ValueError("windows不得重复")
    if type(annualization_days) is not int or annualization_days <= 0:
        raise ValueError("annualization_days必须为正整数")
    if calendar.market != panel.metadata.market:
        raise ValueError("面板与日历市场不一致")
    if (calendar.source, calendar.version) != (panel.calendar_source, panel.calendar_version):
        raise ValueError("面板与日历来源或版本不一致")
    if calendar.dates.max().date() > panel.metadata.data_as_of:
        raise ValueError("日历晚于data_as_of")
    frame = validate_market_frame(panel.frame)
    expected = pd.MultiIndex.from_product(
        [sorted(frame.symbol.unique()), calendar.dates], names=KEYS
    )
    actual = pd.MultiIndex.from_frame(frame[KEYS])
    if len(actual) != len(expected) or not actual.isin(expected).all():
        raise ValueError("必须提供完整日历面板，不得删去缺失日期或混入日历外行")
    # 验证后价格为浮点数；状态及观测标记取副本并按键对齐。
    state_columns = [c for c in ("observed", "price_complete", "is_listed", "is_suspended", "tradable", "status_reason") if c in panel.frame]
    states = panel.frame.set_index(KEYS)[state_columns].reindex(expected).reset_index()
    states["symbol"] = states.symbol.astype("string")
    states["trade_date"] = pd.to_datetime(states.trade_date)
    output: list[pd.DataFrame] = []
    for symbol, stock in frame.groupby("symbol", sort=False):
        stock = stock.reset_index(drop=True)
        close = stock.close
        daily_return = close.pct_change(fill_method=None)
        base = states.loc[states.symbol == symbol].reset_index(drop=True)
        for window in windows:
            continuous = close.rolling(window + 1, min_periods=window + 1).count().eq(window + 1)
            momentum = (close / close.shift(window) - 1).where(continuous)
            volatility = daily_return.rolling(window, min_periods=window).std(ddof=1)
            deviation = close / close.rolling(window, min_periods=window).mean() - 1
            for name, value, needed in (
                ("momentum", momentum, window + 1),
                ("volatility", volatility, window + 1),
                ("mean_reversion", deviation, window),
            ):
                if np.isinf(value).any():
                    raise ValueError("因子计算溢出，请检查价格尺度")
                result = base.copy(deep=True)
                result["factor"] = name
                result["window"] = window
                result["value"] = value
                result["valid"] = value.notna()
                result["reason"] = np.where(value.notna(), "valid", np.where(np.arange(len(stock)) < needed - 1, "insufficient_history", "missing_close_in_window"))
                result["annualized_value"] = value * np.sqrt(annualization_days) if name == "volatility" else np.nan
                output.append(result)
    combined = pd.concat(output, ignore_index=True).sort_values(KEYS + ["factor", "window"], kind="stable").reset_index(drop=True)
    params: dict[str, object] = {
        "windows": list(windows), "annualization_days": annualization_days,
        "volatility_ddof": 1, "as_of": "trade_date收盘后",
        "momentum": "close[t]/close[t-N]-1; requires N+1 consecutive valid closes",
        "volatility": "std(last N simple daily returns, ddof=1)",
        "mean_reversion": "close[t]/mean(close[t-N+1:t])-1; raw deviation",
        "eligibility": "price statistic only; states retained, not an investable universe",
    }
    LOGGER.info("因子计算 rows=%s valid=%s", len(combined), int(combined.valid.sum()))
    return FactorResult(combined, params, panel.file_sha256, calendar.source, calendar.version)
