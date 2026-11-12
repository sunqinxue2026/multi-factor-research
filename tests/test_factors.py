from datetime import date

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from multi_factor_research.data import DatasetMetadata, MarketDataset, TradingCalendar, build_calendar_panel
from multi_factor_research.factors import calculate_factors


def fixture(closes=None):
    closes = {'A': [100, 110, 99, 99], 'B': [10, 10, 10, 10]} if closes is None else closes
    # 显式合成日期，仅用于数学测试，不冒充官方日历。
    dates = pd.date_range('2025-01-01', periods=len(next(iter(closes.values()))), freq='D')
    metadata = DatasetMetadata('synthetic/test', 'TEST', '未复权', date(2026, 1, 1), True, '合成股票，不代表历史股票池')
    calendar = TradingCalendar(dates, 'TEST', 'synthetic/calendar', 'v1')
    rows = [[s, d.strftime('%Y-%m-%d'), c, c, c, c, 0, 0] for s, values in closes.items() for d, c in zip(dates, values)]
    frame = pd.DataFrame(rows, columns=['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
    return build_calendar_panel(MarketDataset(frame, metadata, 'fixture', 'fixture.csv'), calendar), calendar


def series(result, factor, symbol='A', window=3):
    f = result.frame
    return f[(f.symbol == symbol) & (f.factor == factor) & (f.window == window)].reset_index(drop=True)


def test_hand_calculated_values_and_raw_direction():
    panel, calendar = fixture()
    result = calculate_factors(panel, calendar, windows=(3,))
    assert series(result, 'momentum').value.iloc[-1] == pytest.approx(-0.01)
    vol = series(result, 'volatility')
    assert vol.value.iloc[-1] == pytest.approx(0.1)
    assert vol.annualized_value.iloc[-1] == pytest.approx(0.1 * np.sqrt(252))
    assert series(result, 'mean_reversion').value.iloc[-1] == pytest.approx(-11 / 308)
    assert len(result.frame) == 24
    assert result.parameters['volatility_ddof'] == 1
    assert result.file_sha256 == 'fixture'


def test_insufficient_history_and_stock_isolation():
    panel, calendar = fixture()
    result = calculate_factors(panel, calendar, windows=(3,))
    assert series(result, 'momentum').valid.tolist() == [False, False, False, True]
    assert series(result, 'volatility').valid.tolist() == [False, False, False, True]
    assert series(result, 'mean_reversion').valid.tolist() == [False, False, True, True]
    for factor in ('momentum', 'volatility', 'mean_reversion'):
        assert series(result, factor, 'B').value.iloc[-1] == pytest.approx(0)
    assert series(result, 'momentum').reason.iloc[0] == 'insufficient_history'


def test_missing_interior_endpoint_and_recovery():
    panel, calendar = fixture({'A': [100, np.nan, 110, 121, 133.1, 146.41]})
    result = calculate_factors(panel, calendar, windows=(2,))
    for factor in ('momentum', 'volatility', 'mean_reversion'):
        f = series(result, factor, window=2)
        assert not f.valid.iloc[2]
        assert f.reason.iloc[2] == 'missing_close_in_window'
        assert f.valid.iloc[-1]
    # t2两端有效但中间缺失，不能算成10%动量；t4窗口已恢复。
    assert series(result, 'momentum', window=2).value.iloc[4] == pytest.approx(0.21)
    assert series(result, 'volatility', window=2).value.iloc[4] == pytest.approx(0, abs=1e-14)


def test_default_20_60_windows():
    panel, calendar = fixture({'A': [100 * 1.01 ** i for i in range(65)]})
    result = calculate_factors(panel, calendar)
    for n in (20, 60):
        mom = series(result, 'momentum', window=n)
        assert mom.valid.sum() == 65 - n
        assert mom.value.iloc[-1] == pytest.approx(1.01 ** n - 1)
        vol = series(result, 'volatility', window=n)
        assert vol.valid.sum() == 65 - n
        assert vol.value.iloc[-1] == pytest.approx(0, abs=1e-14)
        dev = series(result, 'mean_reversion', window=n)
        assert dev.valid.sum() == 66 - n
        expected = 1.01 ** 64 / np.mean([1.01 ** i for i in range(65-n, 65)]) - 1
        assert dev.value.iloc[-1] == pytest.approx(expected)


def test_input_not_mutated_and_unsorted_input():
    panel, calendar = fixture()
    saved = panel.frame.copy(deep=True)
    expected = calculate_factors(panel, calendar, windows=(3,)).frame
    assert_frame_equal(saved, panel.frame)
    panel.frame = panel.frame.sample(frac=1, random_state=7)
    assert_frame_equal(expected, calculate_factors(panel, calendar, windows=(3,)).frame)


def test_append_and_change_future_leave_history_unchanged():
    panel, calendar = fixture()
    baseline = calculate_factors(panel, calendar, windows=(3,)).frame
    extended, extended_calendar = fixture({'A': [100, 110, 99, 99, 500, 1], 'B': [10, 10, 10, 10, 20, 40]})
    actual = calculate_factors(extended, extended_calendar, windows=(3,)).frame
    assert_frame_equal(baseline, actual[actual.trade_date <= calendar.dates[-1]].reset_index(drop=True))
    extended.frame.loc[extended.frame.trade_date > calendar.dates[-1], ['open', 'high', 'low', 'close']] = 7
    changed = calculate_factors(extended, extended_calendar, windows=(3,)).frame
    assert_frame_equal(baseline, changed[changed.trade_date <= calendar.dates[-1]].reset_index(drop=True))


def test_prices_and_eligibility_are_separate():
    panel, calendar = fixture()
    panel.frame.loc[panel.frame.symbol == 'A', 'is_suspended'] = True
    panel.frame.loc[panel.frame.symbol == 'A', 'tradable'] = False
    result = calculate_factors(panel, calendar, windows=(3,))
    f = series(result, 'momentum')
    assert f.is_suspended.all()
    assert f.value.iloc[-1] == pytest.approx(-0.01)
    assert not f.tradable.any()


@pytest.mark.parametrize('windows', [(), (0,), (1,), (-1,), (True,), (2.5,), (2, 2), ('3',)])
def test_invalid_windows(windows):
    panel, calendar = fixture()
    with pytest.raises(ValueError):
        calculate_factors(panel, calendar, windows=windows)


@pytest.mark.parametrize('annualization', [0, -1, True, 252.5])
def test_invalid_annualization(annualization):
    panel, calendar = fixture()
    with pytest.raises(ValueError):
        calculate_factors(panel, calendar, annualization_days=annualization)


@pytest.mark.parametrize('kind', ['missing', 'duplicate', 'market', 'version', 'outside'])
def test_reject_invalid_panel_or_calendar(kind):
    panel, calendar = fixture()
    if kind == 'missing':
        panel.frame = panel.frame.iloc[1:]
    elif kind == 'duplicate':
        panel.frame = pd.concat([panel.frame, panel.frame.iloc[:1]])
    elif kind == 'market':
        calendar.market = 'OTHER'
    elif kind == 'version':
        calendar.version = 'v2'
    else:
        panel.frame.loc[0, 'trade_date'] = pd.Timestamp('2025-02-01')
    with pytest.raises(ValueError):
        calculate_factors(panel, calendar, windows=(3,))
