from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from multi_factor_research.data import TradingCalendar
from multi_factor_research.preprocessing import PreprocessingResult
from multi_factor_research.portfolio import build_portfolio_plan, FACTOR_NAMES


def sample(dates=None):
    dates = pd.bdate_range('2025-01-01', '2025-02-04') if dates is None else pd.DatetimeIndex(dates)
    calendar = TradingCalendar(dates, 'TEST', 'synthetic/calendar', 'v1')
    rows = [dict(symbol=s, trade_date=d, factor=f, window=20,
                 oriented_value=float(i), preprocess_valid=True)
            for d in dates for i, s in enumerate(['A', 'B', 'C']) for f in FACTOR_NAMES]
    pre = PreprocessingResult(pd.DataFrame(rows), pd.DataFrame(), {}, 'digest', calendar.source, calendar.version)
    return pre, calendar


def test_weighted_score_ranking_and_no_input_mutation():
    pre, cal = sample()
    before = pre.frame.copy(deep=True)
    pre.frame.loc[pre.frame.symbol.eq('A') & pre.frame.factor.eq('momentum'), 'oriented_value'] = 10.
    before = pre.frame.copy(deep=True)
    out = build_portfolio_plan(pre, cal, weights=dict(momentum=.5, volatility=.25, mean_reversion=.25), top_n=2)
    day = out.scores[out.scores.trade_date.eq(cal.dates[0])]
    assert day.symbol.tolist() == ['A', 'C', 'B']
    assert day.score.tolist() == pytest.approx([5., 2., 1.])
    assert day['rank'].tolist() == [1, 2, 3]
    assert_frame_equal(pre.frame, before)
    assert out.rebalances.iloc[0].target_turnover == pytest.approx(1.)
    assert out.targets[out.targets.signal_date.eq(out.rebalances.iloc[0].signal_date)].target_weight.sum() == pytest.approx(1.)


def test_ties_shuffle_and_zero_weight_still_requires_factor():
    pre, cal = sample()
    pre.frame['oriented_value'] = 1.
    out = build_portfolio_plan(pre, cal, top_n=2)
    assert out.scores.iloc[:3].symbol.tolist() == ['A', 'B', 'C']
    shuffled = replace(pre, frame=pre.frame.sample(frac=1, random_state=7))
    assert_frame_equal(out.scores, build_portfolio_plan(shuffled, cal, top_n=2).scores)
    pre.frame.loc[pre.frame.symbol.eq('A') & pre.frame.factor.eq('volatility'), 'preprocess_valid'] = False
    out = build_portfolio_plan(pre, cal, weights=dict(momentum=1., volatility=0., mean_reversion=0.))
    assert not out.scores[out.scores.symbol.eq('A')].score_valid.any()


def test_missing_factor_and_cash_no_renormalization():
    pre, cal = sample()
    pre.frame = pre.frame[~(pre.frame.symbol.eq('C') & pre.frame.factor.eq('volatility'))]
    out = build_portfolio_plan(pre, cal, top_n=5)
    assert not out.scores[out.scores.symbol.eq('C')].score_valid.any()
    assert out.rebalances.selected_count.eq(2).all()
    assert out.rebalances.cash_weight.tolist() == pytest.approx([.6] * len(out.rebalances))
    stocks = out.targets[out.targets.symbol.ne('CASH')]
    assert stocks.target_weight.tolist() == pytest.approx([.2] * len(stocks))


def test_exit_all_cash_and_turnover_hand():
    pre, cal = sample()
    # 第一周仅A有效，第二周仅B有效，后续全无效。Top2每股50%。
    pre.frame['preprocess_valid'] = False
    for day, symbol in [('2025-01-03', 'A'), ('2025-01-10', 'B')]:
        pre.frame.loc[pre.frame.trade_date.eq(pd.Timestamp(day)) & pre.frame.symbol.eq(symbol), 'preprocess_valid'] = True
    out = build_portfolio_plan(pre, cal, top_n=2)
    assert out.rebalances.target_turnover.tolist() == pytest.approx([.5, .5, .5, 0., 0.])
    exits = out.changes[out.changes.signal_date.eq(pd.Timestamp('2025-01-10')) & out.changes.symbol.eq('A')].iloc[0]
    assert exits.previous_target_weight == .5 and exits.target_weight == 0 and exits.action == 'decrease'
    assert out.rebalances.iloc[2].status == 'all_cash'
    assert out.rebalances.iloc[2].cash_weight == 1.


def test_weekly_monthly_and_holiday_gap():
    pre, cal = sample(['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-30', '2025-02-03'])
    weekly = build_portfolio_plan(pre, cal)
    assert weekly.rebalances.signal_date.tolist() == list(pd.to_datetime(['2025-01-03', '2025-01-06', '2025-01-30']))
    assert (weekly.rebalances.execution_date > weekly.rebalances.signal_date).all()
    monthly = build_portfolio_plan(pre, cal, frequency='monthly')
    assert monthly.rebalances.signal_date.tolist() == [pd.Timestamp('2025-01-30')]
    assert monthly.rebalances.execution_date.iloc[0] == pd.Timestamp('2025-02-03')


def test_unconfirmed_tail_empty_and_missing_signal_cross_section():
    pre, cal = sample(['2025-01-01', '2025-01-02', '2025-01-03'])
    out = build_portfolio_plan(pre, cal)
    assert out.rebalances.empty and list(out.targets.columns) == ['signal_date', 'execution_date', 'symbol', 'target_weight']
    pre, cal = sample()
    pre.frame = pre.frame[~pre.frame.trade_date.eq(pd.Timestamp('2025-01-03'))]
    out = build_portfolio_plan(pre, cal)
    assert out.rebalances.iloc[0].status == 'all_cash'


def test_append_and_modify_future_preserve_confirmed_history():
    pre, cal = sample(pd.bdate_range('2025-01-01', '2025-01-21'))
    early = build_portfolio_plan(pre, cal)
    bigger, newcal = sample()
    bigger.frame.loc[bigger.frame.trade_date.gt(cal.dates[-1]), 'oriented_value'] *= -100
    later = build_portfolio_plan(bigger, newcal)
    for name in ('scores', 'targets', 'changes', 'rebalances'):
        a, b = getattr(early, name), getattr(later, name)
        key = 'trade_date' if name == 'scores' else 'execution_date'
        assert_frame_equal(a.reset_index(drop=True), b[b[key].le(cal.dates[-1])].reset_index(drop=True))


@pytest.mark.parametrize('kwargs', [
    {'top_n': 0}, {'top_n': True}, {'frequency': 'daily'},
    {'weights': dict(momentum=.5, volatility=.5, mean_reversion=.5)},
    {'weights': dict(momentum=-1., volatility=1., mean_reversion=1.)},
    {'weights': dict(momentum=True, volatility=0., mean_reversion=0.)},
    {'weights': dict(momentum=np.nan, volatility=0., mean_reversion=0.)},
    {'weights': {'momentum': 1.}}, {'windows': {'momentum': 20}},
    {'windows': dict(momentum=True, volatility=20, mean_reversion=20)},
])
def test_bad_parameters(kwargs):
    pre, cal = sample()
    with pytest.raises(ValueError):
        build_portfolio_plan(pre, cal, **kwargs)


@pytest.mark.parametrize('kind', ['duplicate', 'date', 'flag', 'nan', 'infinity', 'bool_value', 'symbol', 'source', 'empty', 'missing'])
def test_bad_contract(kind):
    pre, cal = sample()
    if kind == 'duplicate': pre.frame = pd.concat([pre.frame, pre.frame.iloc[:1]])
    elif kind == 'date': pre.frame.loc[0, 'trade_date'] = pd.Timestamp('2026-01-01')
    elif kind == 'flag': pre.frame['preprocess_valid'] = 'True'
    elif kind == 'nan': pre.frame.loc[0, 'oriented_value'] = np.nan
    elif kind == 'infinity': pre.frame.loc[0, 'oriented_value'] = np.inf
    elif kind == 'bool_value': pre.frame['oriented_value'] = True
    elif kind == 'symbol': pre.frame.loc[0, 'symbol'] = 'CASH'
    elif kind == 'source': pre.calendar_version = 'other'
    elif kind == 'empty': pre.frame = pre.frame.iloc[:0]
    else: pre.frame = pre.frame.drop(columns='window')
    with pytest.raises(ValueError): build_portfolio_plan(pre, cal)


def test_configurable_window_and_unknown_state_not_execution():
    pre, cal = sample()
    pre.frame['window'] = 60
    pre.frame['tradable'] = pd.NA
    out = build_portfolio_plan(pre, cal, windows={name: 60 for name in FACTOR_NAMES})
    assert out.scores.score_valid.all()
    assert not out.parameters['costs_included']
    assert out.parameters['windows']['momentum'] == 60
