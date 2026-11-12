"""事后因子评价；未来标签不得回流评分或交易信号。"""
from __future__ import annotations

from dataclasses import dataclass
import logging

import numpy as np
import pandas as pd

from multi_factor_research.data import PanelResult, TradingCalendar, validate_market_frame
from multi_factor_research.preprocessing import PreprocessingResult

LOGGER = logging.getLogger(__name__)


@dataclass
class LabelResult:
    frame: pd.DataFrame
    parameters: dict[str, object]
    file_sha256: str
    calendar_source: str
    calendar_version: str


@dataclass
class AnalysisResult:
    daily_ic: pd.DataFrame
    ic_summary: pd.DataFrame
    groups: pd.DataFrame
    spreads: pd.DataFrame
    group_summary: pd.DataFrame
    parameters: dict[str, object]
    file_sha256: str


def build_forward_returns(
    panel: PanelResult, calendar: TradingCalendar, *, horizons: tuple[int, ...] = (5, 20),
) -> LabelResult:
    """t收盘因子对应open[t+1+H]/open[t+1]-1；缺价不推迟执行日期。"""
    horizons = tuple(horizons)
    if not horizons or any(type(h) is not int or h <= 0 for h in horizons) or len(set(horizons)) != len(horizons):
        raise ValueError("horizons必须为不重复的正整数")
    if (calendar.market, calendar.source, calendar.version) != (panel.metadata.market, panel.calendar_source, panel.calendar_version):
        raise ValueError("面板与日历身份不一致")
    frame = validate_market_frame(panel.frame)
    expected = pd.MultiIndex.from_product([sorted(frame.symbol.unique()), calendar.dates], names=['symbol', 'trade_date'])
    keys = pd.MultiIndex.from_frame(frame[['symbol', 'trade_date']])
    if len(keys) != len(expected) or not keys.isin(expected).all():
        raise ValueError("标签必须使用完整显式日历面板")
    dates = pd.Series(calendar.dates)
    outputs = []
    for symbol, stock in frame.groupby('symbol', sort=True):
        prices = stock.set_index('trade_date').reindex(calendar.dates).open.reset_index(drop=True)
        for h in horizons:
            entry, exit_ = prices.shift(-1), prices.shift(-(h + 1))
            entry_dates, exit_dates = dates.shift(-1), dates.shift(-(h + 1))
            valid = exit_dates.notna() & entry.notna() & exit_.notna()
            values = (exit_ / entry - 1).where(valid)
            if not np.isfinite(values.dropna()).all():
                raise ValueError("标签收益溢出")
            reason = np.where(exit_dates.isna(), 'insufficient_future', np.where(valid, 'valid', 'missing_endpoint_open'))
            outputs.append(pd.DataFrame({'symbol': symbol, 'trade_date': dates, 'horizon': h,
                'entry_date': entry_dates, 'exit_date': exit_dates, 'forward_return': values,
                'label_valid': valid, 'label_reason': reason,
                'nonoverlap': np.arange(len(dates)) % h == 0}))
    result = pd.concat(outputs, ignore_index=True).sort_values(['symbol', 'trade_date', 'horizon']).reset_index(drop=True)
    LOGGER.info('标签 rows=%s valid=%s', len(result), int(result.label_valid.sum()))
    return LabelResult(result, {'horizons': list(horizons), 'formula': 'open[t+1+H]/open[t+1]-1',
        'nonoverlap_anchor': str(calendar.dates[0].date()), 'calendar_dates': [str(d.date()) for d in calendar.dates],
        'endpoint_only': True, 'costs_included': False}, panel.file_sha256, calendar.source, calendar.version)


def analyze_factors(
    factors: PreprocessingResult, labels: LabelResult, *, min_samples: int = 5, n_groups: int = 5,
) -> AnalysisResult:
    """成对完整样本IC；按定向值分组。研究分组收益并非可执行组合收益。"""
    if type(min_samples) is not int or min_samples < 3:
        raise ValueError('IC最少样本必须为至少3的整数')
    if type(n_groups) is not int or n_groups not in (5, 10):
        raise ValueError('仅支持五组或十组')
    if (factors.file_sha256, factors.calendar_source, factors.calendar_version) != (labels.file_sha256, labels.calendar_source, labels.calendar_version):
        raise ValueError('因子与标签来源不一致')
    f, lab = factors.frame.copy(deep=True), labels.frame.copy(deep=True)
    fkeys = ['symbol', 'trade_date', 'factor', 'window']
    lkeys = ['symbol', 'trade_date', 'horizon']
    for table, keys, required in ((f, fkeys, ['value', 'oriented_value', 'preprocess_valid']),
                                  (lab, lkeys, ['forward_return', 'label_valid', 'entry_date', 'exit_date', 'nonoverlap'])):
        if table.empty or not set(keys + required).issubset(table.columns):
            raise ValueError('分析输入为空或缺列')
        table['trade_date'] = pd.to_datetime(table.trade_date, errors='raise')
        if table[keys].isna().any().any() or table.duplicated(keys).any():
            raise ValueError('分析联合键缺失或重复')
    for table, flags in ((f, ['preprocess_valid']), (lab, ['label_valid', 'nonoverlap'])):
        for flag in flags:
            if not table[flag].map(lambda v: isinstance(v, (bool, np.bool_))).all():
                raise ValueError('有效标记必须为非空布尔值')
    for table, col, flag in ((f, 'value', 'preprocess_valid'), (f, 'oriented_value', 'preprocess_valid'), (lab, 'forward_return', 'label_valid')):
        raw = table[col]
        numeric = pd.to_numeric(raw, errors='coerce').astype(float)
        if raw.map(lambda v: isinstance(v, (bool, np.bool_))).any() or (raw.notna() & numeric.isna()).any() or np.isinf(numeric).any() or (table[flag] & numeric.isna()).any():
            raise ValueError('分析数值非法')
        table[col] = numeric
    if (lab.loc[lab.label_valid, 'forward_return'] < -1).any():
        raise ValueError('价格收益不能小于-100%')
    # 每个股票日期必须有每个H的标签，包括无效标签；拒绝内连接静默丢行。
    base = f[['symbol', 'trade_date']].drop_duplicates()
    for _, part in lab.groupby('horizon'):
        probe = base.merge(part[['symbol', 'trade_date']], on=['symbol', 'trade_date'], how='left', indicator=True)
        if probe._merge.ne('both').any():
            raise ValueError('因子缺少对应标签键')
    joined = f.merge(lab, on=['symbol', 'trade_date'], how='left', validate='many_to_many')
    daily, group_rows, spread_rows = [], [], []
    gkeys = ['trade_date', 'factor', 'window', 'horizon']
    for key, block in joined.groupby(gkeys, sort=True):
        common = dict(zip(gkeys, key))
        eligible = block[block.preprocess_valid]
        paired = eligible[eligible.label_valid]
        for value_col in ('value', 'oriented_value'):
            x, y = paired[value_col], paired.forward_return
            status = 'insufficient_samples' if len(paired) < min_samples else 'constant' if x.nunique() < 2 or y.nunique() < 2 else 'valid'
            ic = x.corr(y) if status == 'valid' else np.nan
            rankic = x.rank(method='average').corr(y.rank(method='average')) if status == 'valid' else np.nan
            if status == 'valid' and not np.isfinite([ic, rankic]).all():
                raise ValueError('相关系数非有限')
            daily.append(common | {'value_type': value_col, 'sample_count': len(paired), 'ic': ic, 'rank_ic': rankic, 'status': status})
        # 先按当时可获得的因子分组，再观察标签；不以未来是否缺价决定分组边界。
        assignments = eligible.copy()
        enough = len(assignments) >= n_groups
        if enough:
            assignments['group'] = np.ceil(assignments.oriented_value.rank(method='average') / len(assignments) * n_groups).astype(int)
        returns = {}
        for number in range(1, n_groups + 1):
            members = assignments[assignments['group'].eq(number)] if enough else assignments.iloc[:0]
            observed = members[members.label_valid]
            status = 'insufficient_stocks' if not enough else 'empty_group' if members.empty else 'missing_labels' if len(observed) != len(members) else 'valid'
            ret = float(observed.forward_return.mean()) if status == 'valid' else np.nan
            returns[number] = ret
            group_rows.append(common | {'group': number, 'stock_count': len(members), 'label_count': len(observed),
                'mean_return': ret, 'status': status, 'entry_date': block.entry_date.iloc[0],
                'exit_date': block.exit_date.iloc[0], 'nonoverlap': bool(block.nonoverlap.iloc[0])})
        spread_rows.append(common | {'long_short_return': returns[n_groups] - returns[1],
            'nonoverlap': bool(block.nonoverlap.iloc[0])})
    daily_frame = pd.DataFrame(daily)
    summaries = []
    for key, block in daily_frame.groupby(['factor', 'window', 'horizon', 'value_type'], sort=True):
        good = block[block.status.eq('valid')]
        ic, ric = good.ic, good.rank_ic
        std = float(ic.std(ddof=1)) if len(ic) > 1 else np.nan
        summaries.append(dict(zip(['factor', 'window', 'horizon', 'value_type'], key)) | {
            'date_count': len(block), 'valid_dates': len(good), 'ic_mean': ic.mean(), 'rank_ic_mean': ric.mean(),
            'ic_std': std, 'icir': ic.mean() / std if std > 0 else np.nan,
            'ic_positive_ratio': float(ic.gt(0).mean()) if len(ic) else np.nan})
    groups = pd.DataFrame(group_rows)
    spreads = pd.DataFrame(spread_rows)
    for table, keys, value in ((groups, ['factor', 'window', 'horizon', 'group'], 'mean_return'),
                               (spreads, ['factor', 'window', 'horizon'], 'long_short_return')):
        table['cumulative_return'] = np.nan
        table['curve_status'] = 'not_selected'
        for _, block in table.groupby(keys, sort=True):
            wealth, broken = 1., False
            for idx, row in block.sort_values('trade_date').iterrows():
                if not row.nonoverlap:
                    continue
                if pd.isna(row[value]) or broken:
                    # 首次有效区间前属于预热；启动后的缺口阻断累计。
                    broken = broken or wealth != 1. or bool(table.loc[block.index, 'curve_status'].eq('valid').any())
                    table.loc[idx, 'curve_status'] = 'gap' if broken else 'warmup'
                    continue
                wealth *= 1 + row[value]
                table.loc[idx, 'cumulative_return'] = wealth - 1
                table.loc[idx, 'curve_status'] = 'valid'
    risk_rows = []
    for key, block in groups.groupby(['factor', 'window', 'horizon', 'group'], sort=True):
        selected = block[block.curve_status.eq('valid')].sort_values('trade_date')
        returns = selected.mean_return
        wealth = np.r_[1., 1 + selected.cumulative_return.to_numpy()]
        drawdown = wealth / np.maximum.accumulate(wealth) - 1
        risk_rows.append(dict(zip(['factor', 'window', 'horizon', 'group'], key)) | {
            'period_count': len(selected), 'period_mean_return': returns.mean(),
            'period_return_std': returns.std(ddof=1),
            'max_drawdown': float(drawdown.min()) if len(selected) else np.nan,
            'cumulative_return': float(wealth[-1] - 1) if len(selected) else np.nan})
    LOGGER.info('分析 IC=%s groups=%s', len(daily_frame), len(groups))
    return AnalysisResult(daily_frame, pd.DataFrame(summaries), groups, spreads, pd.DataFrame(risk_rows),
        {'min_samples': min_samples, 'n_groups': n_groups, 'rank_method': 'average', 'icir_ddof': 1,
         'icir_annualized': False, 'group_value': 'oriented_value', 'group_rule': 'ceil(average_rank/n*G)',
         'missing_group_labels': 'invalidate entire group', 'curve': 'fixed anchor nonoverlap; stop at first gap',
         'spread_curve': 'hypothetical compounded return spread; not self-financing portfolio',
         'labels': labels.parameters, 'preprocessing': factors.parameters}, factors.file_sha256)
