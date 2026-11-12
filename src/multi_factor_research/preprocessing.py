"""仅使用同日截面的因子预处理；未知状态不是投资资格。"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from collections.abc import Mapping

import numpy as np
import pandas as pd

from multi_factor_research.factors import FactorResult

LOGGER = logging.getLogger(__name__)
DEFAULT_DIRECTIONS = {"momentum": 1, "volatility": -1, "mean_reversion": -1}
GROUP_KEYS = ["trade_date", "factor", "window"]
ROW_KEYS = ["symbol"] + GROUP_KEYS


@dataclass
class PreprocessingResult:
    frame: pd.DataFrame
    audit: pd.DataFrame
    parameters: dict[str, object]
    file_sha256: str
    calendar_source: str
    calendar_version: str


def preprocess_factors(
    factors: FactorResult,
    *,
    quantiles: tuple[float, float] | None = (0.01, 0.99),
    min_samples: int = 5,
    directions: Mapping[str, int] | None = None,
) -> PreprocessingResult:
    """截尾→总体标准差Z-score→方向统一；保留原始行及无效原因。"""
    if type(min_samples) is not int or min_samples < 2:
        raise ValueError("min_samples必须为至少2的整数")
    if quantiles is not None:
        if len(quantiles) != 2 or any(isinstance(q, (bool, np.bool_)) or not isinstance(q, (int, float)) or not np.isfinite(q) for q in quantiles):
            raise ValueError("quantiles必须为两个有限分位数或None")
        if not 0 <= quantiles[0] < quantiles[1] <= 1:
            raise ValueError("分位数必须满足0≤lower<upper≤1")
    direction_map = dict(DEFAULT_DIRECTIONS if directions is None else directions)
    if any(type(v) is not int or v not in (-1, 1) for v in direction_map.values()):
        raise ValueError("方向必须为整数+1或-1")
    required = ROW_KEYS + ["value", "valid", "reason"]
    if not set(required).issubset(factors.frame.columns) or factors.frame.empty:
        raise ValueError("因子表为空或缺少必要字段")
    frame = factors.frame.copy(deep=True)
    reserved = {"clipped_value", "zscore", "direction", "oriented_value", "was_clipped", "research_eligible", "preprocess_valid", "preprocess_reason"}
    if reserved.intersection(frame.columns):
        raise ValueError("输入已含预处理字段，不允许重复处理")
    if frame[ROW_KEYS].isna().any().any() or frame.duplicated(ROW_KEYS).any():
        raise ValueError("因子键缺失或重复")
    if not frame.symbol.map(lambda x: isinstance(x, str) and bool(x.strip()) and x == x.strip()).all():
        raise ValueError("股票代码必须为非空字符串")
    frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise")
    if frame.trade_date.dt.tz is not None or not frame.trade_date.eq(frame.trade_date.dt.normalize()).all():
        raise ValueError("因子日期必须为无时区的日日期")
    if frame.duplicated(ROW_KEYS).any():
        raise ValueError("日期解析后因子键重复")
    if not frame.window.map(lambda x: isinstance(x, (int, np.integer)) and not isinstance(x, (bool, np.bool_)) and x >= 2).all():
        raise ValueError("窗口必须为至少2的整数")
    if not frame.factor.isin(direction_map).all():
        raise ValueError("每个因子必须明确配置方向")
    if not frame.valid.map(lambda x: isinstance(x, (bool, np.bool_))).all():
        raise ValueError("valid必须为非空布尔值")
    if frame.value.map(lambda x: isinstance(x, (bool, np.bool_))).any():
        raise ValueError("因子值不能为布尔值")
    numeric = pd.to_numeric(frame.value, errors="coerce").astype(float)
    if (frame.value.notna() & numeric.isna()).any() or np.isinf(numeric).any() or (frame.valid & numeric.isna()).any():
        raise ValueError("因子值非法或valid与数值不一致")
    frame["value"] = numeric
    for name in ("is_listed", "is_suspended", "tradable"):
        if name not in frame:
            frame[name] = pd.Series(pd.NA, index=frame.index, dtype="boolean")
        if not frame[name].map(lambda x: pd.isna(x) or isinstance(x, (bool, np.bool_))).all():
            raise ValueError(f"{name}必须为可空布尔值")
        frame[name] = frame[name].astype("boolean")
    frame = frame.sort_values(ROW_KEYS, kind="stable").reset_index(drop=True)
    frame["direction"] = frame.factor.map(direction_map)
    for name in ("clipped_value", "zscore", "oriented_value"):
        frame[name] = np.nan
    frame["was_clipped"] = False
    excluded = frame.is_listed.eq(False).fillna(False) | frame.is_suspended.eq(True).fillna(False)
    frame["research_eligible"] = frame.valid & ~excluded
    frame["preprocess_valid"] = False
    frame["preprocess_reason"] = "raw_invalid"
    frame.loc[frame.valid & excluded, "preprocess_reason"] = "explicit_status_excluded"
    audits: list[dict[str, object]] = []
    for key, group in frame.groupby(GROUP_KEYS, sort=True):
        idx = group.index[group.research_eligible]
        values = frame.loc[idx, "value"]
        n = len(values)
        lower = upper = mean = std = np.nan
        clipped_count = 0
        status = "insufficient_cross_section"
        if n >= min_samples:
            if quantiles is None:
                clipped = values.copy()
            else:
                lower, upper = values.quantile(list(quantiles), interpolation="linear").tolist()
                clipped = values.clip(lower=lower, upper=upper)
            mean, std = float(clipped.mean()), float(clipped.std(ddof=0))
            if not np.isfinite([mean, std]).all():
                raise ValueError("截面统计溢出")
            changed = clipped.ne(values)
            clipped_count = int(changed.sum())
            frame.loc[idx, "clipped_value"] = clipped
            frame.loc[idx, "was_clipped"] = changed
            status = "zero_variance" if std == 0 else "valid"
            if std != 0:
                z = (clipped - mean) / std
                if not np.isfinite(z).all():
                    raise ValueError("标准化结果非有限")
                frame.loc[idx, "zscore"] = z
                frame.loc[idx, "oriented_value"] = z * frame.loc[idx, "direction"]
                frame.loc[idx, "preprocess_valid"] = True
        frame.loc[idx, "preprocess_reason"] = status
        audits.append(dict(zip(GROUP_KEYS, key)) | {
            "input_count": len(group), "eligible_count": n,
            "raw_invalid_count": int((~group.valid).sum()),
            "status_excluded_count": int((group.valid & ~group.research_eligible).sum()),
            "unknown_status_count": int((group.research_eligible & (group.is_listed.isna() | group.is_suspended.isna())).sum()),
            "lower_bound": lower, "upper_bound": upper, "mean": mean, "std": std,
            "clipped_count": clipped_count, "valid_count": n if status == "valid" else 0,
            "status": status,
        })
    params = {
        "quantiles": list(quantiles) if quantiles is not None else None,
        "quantile_interpolation": "linear", "min_samples": min_samples,
        "standardization_ddof": 0, "directions": direction_map,
        "group_keys": GROUP_KEYS.copy(), "input_value": "value (not annualized_value)",
        "eligibility": "exclude explicit not-listed/suspended; unknown retained; not investability",
        "source_factor_parameters": factors.parameters.copy(),
    }
    LOGGER.info("预处理 rows=%s valid=%s", len(frame), int(frame.preprocess_valid.sum()))
    return PreprocessingResult(frame, pd.DataFrame(audits), params, factors.file_sha256, factors.calendar_source, factors.calendar_version)
