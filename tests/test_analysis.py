from datetime import date

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from multi_factor_research.data import DatasetMetadata, MarketDataset, TradingCalendar, build_calendar_panel
from multi_factor_research.preprocessing import PreprocessingResult
from multi_factor_research.analysis import build_forward_returns, analyze_factors


def sample(n=5, periods=9):
    dates = pd.date_range('2025-01-01', periods=periods)
    rows = []
    for i in range(n):
        for j, d in enumerate(dates):
            p = 100 * (1 + (i + 1) / 100) ** j
            rows.append([f'S{i}', d.strftime('%Y-%m-%d'), p, p, p, p, 100, p * 100])
    frame = pd.DataFrame(rows, columns=['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
    meta = DatasetMetadata('synthetic/test', 'TEST', '未复权', date(2025, 12, 31), True, '虚构样本')
    cal = TradingCalendar(dates, 'TEST', 'test', 'v1')
    panel = build_calendar_panel(MarketDataset(frame, meta, 'digest', 'memory'), cal)
    factors = pd.DataFrame([{'symbol': f'S{i}', 'trade_date': d, 'factor': 'momentum', 'window': 2,
        'value': float(i), 'oriented_value': float(i), 'preprocess_valid': True} for i in range(n) for d in dates])
    pre = PreprocessingResult(factors, pd.DataFrame(), {}, 'digest', 'test', 'v1')
    return panel, cal, pre


def test_label_hand_timing_and_tail():
    panel, cal, _ = sample()
    result = build_forward_returns(panel, cal, horizons=(2,))
    a = result.frame[result.frame.symbol.eq('S0')]
    assert a.iloc[0].forward_return == pytest.approx(1.01 ** 2 - 1)
    assert a.iloc[0].entry_date == cal.dates[1]
    assert a.iloc[0].exit_date == cal.dates[3]
    assert a.label_valid.sum() == 6
    assert a.iloc[-1].label_reason == 'insufficient_future'
    assert a.nonoverlap.tolist() == [True, False, True, False, True, False, True, False, True]


def test_missing_endpoint_no_delay_and_interior_not_used():
    panel, cal, _ = sample()
    panel.frame.loc[(panel.frame.symbol.eq('S0')) & panel.frame.trade_date.eq(cal.dates[2]), 'open'] = np.nan
    labels = build_forward_returns(panel, cal, horizons=(2,)).frame
    a = labels[labels.symbol.eq('S0')]
    assert a.iloc[0].label_valid  # 内部缺价不是端点；统计标签不表示期间可执行。
    assert not a.iloc[1].label_valid
    assert a.iloc[1].label_reason == 'missing_endpoint_open'
    assert a.iloc[1].entry_date == cal.dates[2]


def test_ic_and_groups_hand_and_input_unchanged():
    panel, cal, pre = sample()
    labels = build_forward_returns(panel, cal, horizons=(1,))
    saved = pre.frame.copy(deep=True)
    result = analyze_factors(pre, labels)
    first = result.daily_ic.iloc[0]
    assert first.ic == pytest.approx(1)
    assert first.rank_ic == pytest.approx(1)
    assert first.sample_count == 5
    group = result.groups[result.groups.trade_date.eq(cal.dates[0])]
    assert group.stock_count.tolist() == [1] * 5
    assert group.mean_return.tolist() == pytest.approx([.01, .02, .03, .04, .05])
    assert result.spreads.iloc[0].long_short_return == pytest.approx(.04)
    assert result.groups[result.groups.group.eq(1)].iloc[1].cumulative_return == pytest.approx(1.01 ** 2 - 1)
    assert_frame_equal(pre.frame, saved)


def test_tied_ranks_and_raw_direction():
    panel, cal, pre = sample()
    pre.frame['value'] = pre.frame.symbol.map({'S0': 0., 'S1': 0., 'S2': 1., 'S3': 2., 'S4': 2.})
    pre.frame['oriented_value'] = -pre.frame.value
    result = analyze_factors(pre, build_forward_returns(panel, cal, horizons=(1,)))
    block = result.daily_ic[result.daily_ic.trade_date.eq(cal.dates[0])].set_index('value_type')
    assert block.loc['value', 'rank_ic'] == pytest.approx(np.sqrt(.9))
    assert block.loc['oriented_value', 'rank_ic'] == pytest.approx(-np.sqrt(.9))
    groups = result.groups[result.groups.trade_date.eq(cal.dates[0])]
    assert groups.stock_count.tolist() == [0, 2, 1, 0, 2]
    assert groups.iloc[0].status == 'empty_group'


def test_constant_insufficient_and_icir():
    panel, cal, pre = sample()
    pre.frame['value'] = pre.frame['oriented_value'] = 0.
    out = analyze_factors(pre, build_forward_returns(panel, cal, horizons=(1,)))
    assert out.daily_ic.iloc[0].status == 'constant'
    assert out.ic_summary.icir.isna().all()
    panel, cal, pre = sample(n=4)
    out = analyze_factors(pre, build_forward_returns(panel, cal, horizons=(1,)))
    assert out.daily_ic.iloc[0].status == 'insufficient_samples'
    assert out.groups.iloc[0].status == 'insufficient_stocks'


def test_group_missing_label_keeps_members_and_breaks_curve():
    panel, cal, pre = sample()
    labels = build_forward_returns(panel, cal, horizons=(1,))
    idx = labels.frame.index[labels.frame.symbol.eq('S0') & labels.frame.trade_date.eq(cal.dates[2])][0]
    labels.frame.loc[idx, ['label_valid', 'forward_return']] = [False, np.nan]
    out = analyze_factors(pre, labels)
    a = out.groups[out.groups.group.eq(1)]
    assert a.iloc[2].stock_count == 1 and a.iloc[2].label_count == 0
    assert a.iloc[2].status == 'missing_labels'
    assert a.iloc[3].curve_status == 'gap'
    assert pd.isna(a.iloc[3].cumulative_return)


def test_fixed_anchor_nonoverlap_and_history():
    panel, cal, pre = sample()
    labels = build_forward_returns(panel, cal, horizons=(2,))
    result = analyze_factors(pre, labels)
    a = result.groups[result.groups.group.eq(1)]
    assert a.iloc[1].curve_status == 'not_selected'
    assert a.iloc[2].cumulative_return == pytest.approx(1.01 ** 4 - 1)
    # 只评价标签已完整实现的早期日期；新增未来不会改变它们。
    bigger, newcal, newpre = sample(periods=12)
    later = analyze_factors(newpre, build_forward_returns(bigger, newcal, horizons=(2,)))
    cutoff = cal.dates[4]
    assert_frame_equal(result.daily_ic[result.daily_ic.trade_date <= cutoff].reset_index(drop=True),
                       later.daily_ic[later.daily_ic.trade_date <= cutoff].reset_index(drop=True))
    shuffled = PreprocessingResult(pre.frame.sample(frac=1, random_state=3), pre.audit, {}, 'digest', 'test', 'v1')
    assert_frame_equal(result.groups, analyze_factors(shuffled, labels).groups)


@pytest.mark.parametrize('horizons', [(), (0,), (True,), (2, 2), (-1,)])
def test_bad_horizons(horizons):
    panel, cal, _ = sample()
    with pytest.raises(ValueError):
        build_forward_returns(panel, cal, horizons=horizons)


@pytest.mark.parametrize('kind', ['source', 'duplicate', 'missing_key', 'number', 'flag', 'groups', 'minimum', 'sparse', 'calendar'])
def test_bad_contract(kind):
    panel, cal, pre = sample()
    labels = build_forward_returns(panel, cal, horizons=(1,))
    kwargs = {}
    if kind == 'source': labels.file_sha256 = 'wrong'
    elif kind == 'duplicate': pre.frame = pd.concat([pre.frame, pre.frame.iloc[:1]])
    elif kind == 'missing_key': labels.frame = labels.frame.iloc[1:]
    elif kind == 'number': pre.frame.loc[0, 'value'] = np.inf
    elif kind == 'flag': pre.frame['preprocess_valid'] = 'True'
    elif kind == 'groups': kwargs['n_groups'] = 3
    elif kind == 'minimum': kwargs['min_samples'] = 2
    elif kind == 'sparse':
        panel.frame = panel.frame.iloc[1:]
        with pytest.raises(ValueError): build_forward_returns(panel, cal)
        return
    else:
        cal.version = 'different'
        with pytest.raises(ValueError): build_forward_returns(panel, cal)
        return
    with pytest.raises(ValueError): analyze_factors(pre, labels, **kwargs)


def test_ic_summary_sample_std_and_positive_ratio():
    panel, cal, pre = sample()
    # H=1有7个可评价日期，依次构造4次正相关、3次负相关。
    for j, d in enumerate(cal.dates):
        if j % 2:
            mask = pre.frame.trade_date.eq(d)
            pre.frame.loc[mask, 'value'] *= -1
            pre.frame.loc[mask, 'oriented_value'] *= -1
    result = analyze_factors(pre, build_forward_returns(panel, cal, horizons=(1,)))
    summary = result.ic_summary.iloc[0]
    expected = np.array([1., -1., 1., -1., 1., -1., 1.])
    assert summary.ic_mean == pytest.approx(1 / 7)
    assert summary.ic_std == pytest.approx(expected.std(ddof=1))
    assert summary.icir == pytest.approx(expected.mean() / expected.std(ddof=1))
    assert summary.ic_positive_ratio == pytest.approx(4 / 7)
    risk = result.group_summary.iloc[0]
    assert risk.period_count == 7
    assert risk.max_drawdown <= 0


def test_ten_groups_and_warmup():
    panel, cal, pre = sample(n=10)
    pre.frame.loc[pre.frame.trade_date.eq(cal.dates[0]), 'preprocess_valid'] = False
    result = analyze_factors(pre, build_forward_returns(panel, cal, horizons=(1,)), n_groups=10)
    first = result.groups[result.groups.group.eq(1)]
    assert first.iloc[0].curve_status == 'warmup'
    assert first.iloc[1].curve_status == 'valid'
    assert first.iloc[1].cumulative_return == pytest.approx(.01)
