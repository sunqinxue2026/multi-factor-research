"""多股票行情契约及显式交易日历对齐；不填充行情或推断停牌。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import logging
from pathlib import Path

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
KEYS = ["symbol", "trade_date"]
VALUES = ["open", "high", "low", "close", "volume", "amount"]
REQUIRED = KEYS + VALUES


def _dates(values: pd.Series, name: str) -> pd.Series:
    """日期只接受YYYY-MM-DD；避免将整数错误解析为纳秒。"""
    text = values.astype("string")
    if text.isna().any() or not text.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise ValueError(f"{name}必须是YYYY-MM-DD日期")
    return pd.to_datetime(text, format="%Y-%m-%d", errors="raise")


@dataclass(frozen=True)
class DatasetMetadata:
    source: str
    market: str
    price_type: str
    data_as_of: date
    is_synthetic: bool
    universe_description: str
    includes_delisted: bool | None = None
    price_unit: str = "CNY"
    volume_unit: str = "股"
    amount_unit: str = "CNY"

    def __post_init__(self) -> None:
        for name in ("source", "market", "universe_description"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name}不能为空")
        if self.price_type not in {"未复权", "前复权", "后复权"}:
            raise ValueError("必须明确价格复权口径")
        if type(self.data_as_of) is not date:
            raise ValueError("data_as_of必须为date")
        if type(self.is_synthetic) is not bool:
            raise ValueError("is_synthetic必须明确为布尔值")
        if self.includes_delisted is not None and type(self.includes_delisted) is not bool:
            raise ValueError("includes_delisted必须为布尔值或None")
        if (self.price_unit, self.volume_unit, self.amount_unit) != ("CNY", "股", "CNY"):
            raise ValueError("本阶段仅接受CNY/股/CNY，不自动换算单位")


@dataclass
class MarketDataset:
    frame: pd.DataFrame
    metadata: DatasetMetadata
    file_sha256: str
    source_file: str


@dataclass
class TradingCalendar:
    dates: pd.DatetimeIndex
    market: str
    source: str
    version: str

    def __post_init__(self) -> None:
        if not all(isinstance(v, str) and v.strip() for v in (self.market, self.source, self.version)):
            raise ValueError("日历market/source/version不能为空")
        parsed = _dates(pd.Series(self.dates), "日历日期")
        if parsed.empty or parsed.duplicated().any():
            raise ValueError("日历为空或存在重复日期")
        self.dates = pd.DatetimeIndex(parsed.sort_values(), name="trade_date")

    @classmethod
    def from_csv(cls, path: str | Path, *, market: str, source: str, version: str) -> TradingCalendar:
        frame = pd.read_csv(path, dtype="string", encoding="utf-8-sig")
        if list(frame.columns) != ["trade_date"]:
            raise ValueError("日历CSV应仅包含trade_date列，且仅列开放交易日")
        return cls(pd.DatetimeIndex(_dates(frame.trade_date, "日历日期")), market, source, version)


def validate_market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(REQUIRED) - set(frame.columns))
    if missing:
        raise ValueError(f"缺少字段: {missing}")
    if frame.empty:
        raise ValueError("行情不能为空")
    result = frame[REQUIRED].copy(deep=True)
    if result.symbol.isna().any() or not result.symbol.map(lambda v: isinstance(v, str) and bool(v.strip()) and v == v.strip()).all():
        raise ValueError("symbol必须是非空字符串且不含首尾空格")
    result["symbol"] = result.symbol.astype("string")
    result["trade_date"] = _dates(result.trade_date, "trade_date")
    if result.duplicated(KEYS).any():
        raise ValueError("存在重复symbol/trade_date；必须先显式解决冲突")
    for col in VALUES:
        original = result[col]
        if original.map(lambda v: isinstance(v, (bool, np.bool_))).any():
            raise ValueError(f"{col}不接受布尔值")
        numeric = pd.to_numeric(original, errors="coerce").astype(float)
        if (original.notna() & numeric.isna()).any() or np.isinf(numeric).any():
            raise ValueError(f"{col}包含非法数值")
        if (numeric.dropna() <= 0).any() if col in VALUES[:4] else (numeric.dropna() < 0).any():
            raise ValueError(f"{col}价格须为正，成交量额不得为负")
        result[col] = numeric
    for lower, upper in (("low", "high"), ("open", "high"), ("close", "high"), ("low", "open"), ("low", "close")):
        if (result[lower] > result[upper]).any():
            raise ValueError("OHLC价格关系错误")
    return result.sort_values(KEYS, kind="stable").reset_index(drop=True)


def read_market_csv(path: str | Path, metadata: DatasetMetadata) -> MarketDataset:
    path = Path(path)
    # 同一字节快照用于摘要和解析，避免两次读取期间输入改变。
    from io import BytesIO
    content = path.read_bytes()
    raw = pd.read_csv(BytesIO(content), dtype={"symbol": "string"}, encoding="utf-8-sig")
    frame = validate_market_frame(raw)
    if frame.trade_date.max().date() > metadata.data_as_of:
        raise ValueError("行情日期晚于data_as_of")
    LOGGER.info("读取行情 rows=%s symbols=%s", len(frame), frame.symbol.nunique())
    return MarketDataset(frame, metadata, sha256(content).hexdigest(), path.name)


@dataclass
class PanelResult:
    frame: pd.DataFrame
    metadata: DatasetMetadata
    calendar_source: str
    calendar_version: str
    file_sha256: str

    def cross_section(self, trade_date: str) -> pd.DataFrame:
        selected = _dates(pd.Series([trade_date]), "横截面日期").iloc[0]
        return self.frame.loc[self.frame.trade_date == selected].copy(deep=True)


def build_calendar_panel(
    dataset: MarketDataset,
    calendar: TradingCalendar | None,
    *,
    statuses: pd.DataFrame | None = None,
) -> PanelResult:
    """构造日历×已观察股票面板。状态必须是逐日显式事实，不传播到其他日期。

    未提供历史股票池/上市资料时，面板的边缘缺失仍标unknown，
    不据首末记录推断上市退市。tradable只标False或未知，不保证真实成交。
    """
    if calendar is None:
        raise ValueError("正式面板需要显式交易日历")
    if calendar.market != dataset.metadata.market:
        raise ValueError("行情与日历市场不一致")
    frame = validate_market_frame(dataset.frame)
    if frame.trade_date.max().date() > dataset.metadata.data_as_of:
        raise ValueError("行情日期晚于data_as_of")
    if not frame.trade_date.isin(calendar.dates).all():
        raise ValueError("存在日历外行情，不静默丢弃")
    if calendar.dates.max().date() > dataset.metadata.data_as_of:
        raise ValueError("日历范围晚于data_as_of，请显式选择研究区间")
    index = pd.MultiIndex.from_product([sorted(frame.symbol.unique()), calendar.dates], names=KEYS)
    observed = frame.set_index(KEYS)
    panel = observed.reindex(index)
    panel["observed"] = index.isin(observed.index)
    for name in ("is_listed", "is_suspended"):
        panel[name] = pd.Series(pd.NA, index=index, dtype="boolean")
    if statuses is not None:
        if not set(KEYS).issubset(statuses.columns) or set(statuses.columns) - set(KEYS + ["is_listed", "is_suspended"]):
            raise ValueError("状态表仅允许symbol/trade_date/is_listed/is_suspended")
        state = statuses.copy(deep=True)
        state["trade_date"] = _dates(state.trade_date, "状态日期")
        if state.duplicated(KEYS).any():
            raise ValueError("状态表键重复")
        state = state.set_index(KEYS)
        if not state.index.isin(index).all():
            raise ValueError("状态表包含面板外日期或股票")
        for name in ("is_listed", "is_suspended"):
            if name in state:
                if not state[name].dropna().map(lambda v: isinstance(v, (bool, np.bool_))).all():
                    raise ValueError("状态须为布尔值或缺失值")
                panel[name] = state[name].astype("boolean").reindex(index)
    panel["price_complete"] = panel[VALUES[:4]].notna().all(axis=1)
    panel["tradable"] = pd.Series(pd.NA, index=index, dtype="boolean")
    blocked = (~panel.price_complete) | panel.is_suspended.fillna(False) | panel.is_listed.eq(False).fillna(False)
    panel.loc[blocked, "tradable"] = False
    panel["status_reason"] = "unknown_execution_constraints"
    panel.loc[~panel.price_complete, "status_reason"] = "missing_price"
    panel.loc[~panel.observed, "status_reason"] = "missing_record"
    panel.loc[panel.is_suspended.fillna(False), "status_reason"] = "explicit_suspension"
    panel.loc[panel.is_listed.eq(False).fillna(False), "status_reason"] = "explicit_not_listed"
    LOGGER.info("对齐面板 rows=%s observed=%s", len(panel), int(panel.observed.sum()))
    return PanelResult(panel.reset_index(), dataset.metadata, calendar.source, calendar.version, dataset.file_sha256)
