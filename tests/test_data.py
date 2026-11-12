from datetime import date

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from multi_factor_research.data import (
    DatasetMetadata, MarketDataset, TradingCalendar, build_calendar_panel,
    read_market_csv, validate_market_frame,
)


def metadata(**kwargs):
    values = dict(source='synthetic/test', market='TEST', price_type='未复权',
                  data_as_of=date(2025, 1, 10), is_synthetic=True,
                  universe_description='两只合成证券，不代表历史成分股')
    values.update(kwargs)
    return DatasetMetadata(**values)


def prices():
    return pd.DataFrame([
        ['000002', '2025-01-03', 20, 22, 19, 21, 100, 2100],
        ['000001', '2025-01-02', 10, 12, 9, 11, 0, 0],
        ['000002', '2025-01-02', 20, 21, 19, 20, None, None],
        ['000001', '2025-01-06', 12, 14, 11, 13, 100, 1300],
    ], columns=['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount'])


def calendar(dates=('2025-01-02', '2025-01-03', '2025-01-06'), **kwargs):
    values = dict(market='TEST', source='synthetic/calendar', version='v1')
    values.update(kwargs)
    return TradingCalendar(pd.DatetimeIndex(dates), **values)


def dataset(frame=None):
    return MarketDataset(prices() if frame is None else frame, metadata(), 'test-digest', 'fixture.csv')


def test_csv_preserves_symbol_digest_and_sorting(tmp_path):
    path = tmp_path / 'prices.csv'
    prices().to_csv(path, index=False, encoding='utf-8-sig')
    result = read_market_csv(path, metadata())
    assert result.frame.symbol.tolist() == ['000001', '000001', '000002', '000002']
    assert len(result.file_sha256) == 64
    assert result.source_file == 'prices.csv'
    assert result.frame.iloc[0].volume == 0
    assert np.isnan(result.frame.iloc[2].volume)


def test_alignment_exact_values_and_no_fill():
    original = prices()
    saved = original.copy(deep=True)
    result = build_calendar_panel(dataset(original), calendar())
    panel = result.frame
    assert len(panel) == 6
    assert panel.observed.sum() == 4
    a = panel[panel.symbol == '000001']
    assert a.close.iloc[0] == 11
    assert np.isnan(a.close.iloc[1])
    assert a.close.iloc[2] == 13
    assert not a.observed.iloc[1]
    assert a.volume.iloc[0] == 0
    assert a.status_reason.iloc[1] == 'missing_record'
    assert a.tradable.iloc[1] == False
    assert pd.isna(a.tradable.iloc[0])
    assert panel.is_listed.isna().all()
    assert panel.is_suspended.isna().all()
    assert_frame_equal(original, saved)
    cross = result.cross_section('2025-01-03')
    assert len(cross) == 2
    cross.loc[:, 'close'] = 999
    assert not result.frame.close.eq(999).any()


def test_explicit_status_only_applies_to_given_date():
    statuses = pd.DataFrame({'symbol': ['000001', '000002'],
        'trade_date': ['2025-01-02', '2025-01-06'],
        'is_suspended': [True, None], 'is_listed': [True, False]})
    panel = build_calendar_panel(dataset(), calendar(), statuses=statuses).frame
    assert panel.iloc[0].status_reason == 'explicit_suspension'
    assert panel.iloc[0].tradable == False
    assert pd.isna(panel.iloc[1].is_suspended)
    assert panel.iloc[-1].status_reason == 'explicit_not_listed'


def test_partial_price_keeps_missing_and_blocks_execution():
    frame = prices()
    frame.loc[0, 'open'] = np.nan
    panel = build_calendar_panel(dataset(frame), calendar()).frame
    row = panel[(panel.symbol == '000002') & (panel.trade_date == pd.Timestamp('2025-01-03'))].iloc[0]
    assert row.observed and not row.price_complete
    assert pd.isna(row.open)
    assert row.status_reason == 'missing_price'
    assert row.tradable == False


@pytest.mark.parametrize('column,value', [
    ('close', 0), ('open', -1), ('high', 1), ('low', 99),
    ('volume', -1), ('amount', -1), ('close', np.inf),
    ('amount', 'bad'), ('symbol', ''), ('symbol', 1),
    ('trade_date', '2025-02-30'), ('trade_date', 20250102),
    ('trade_date', None), ('close', True),
])
def test_invalid_market_rejected(column, value):
    frame = prices().astype(object)
    frame.loc[0, column] = value
    with pytest.raises(ValueError):
        validate_market_frame(frame)


def test_duplicate_key_rejected_even_identical():
    frame = prices()
    with pytest.raises(ValueError, match='重复'):
        validate_market_frame(pd.concat([frame, frame.iloc[:1]]))


@pytest.mark.parametrize('frame', [pd.DataFrame(), prices().drop(columns='amount'), prices().iloc[:0]])
def test_missing_schema_or_empty_rejected(frame):
    with pytest.raises(ValueError):
        validate_market_frame(frame)


@pytest.mark.parametrize('kind', ['none', 'market', 'outside', 'future'])
def test_calendar_contract(kind):
    cal = calendar()
    if kind == 'none':
        cal = None
    elif kind == 'market':
        cal = calendar(market='OTHER')
    elif kind == 'outside':
        cal = calendar(('2025-01-02', '2025-01-03'))
    else:
        cal = calendar(('2025-01-02', '2025-01-03', '2025-01-06', '2025-01-13'))
    with pytest.raises(ValueError):
        build_calendar_panel(dataset(), cal)


@pytest.mark.parametrize('dates', [[], ['2025-01-02', '2025-01-02']])
def test_empty_or_duplicate_calendar(dates):
    with pytest.raises(ValueError):
        calendar(dates)


@pytest.mark.parametrize('changes', [dict(price_type='unknown'), dict(volume_unit='手'),
    dict(source=''), dict(is_synthetic=None), dict(data_as_of='2025-01-10'),
    dict(includes_delisted=1)])
def test_metadata_contract(changes):
    with pytest.raises(ValueError):
        metadata(**changes)


def test_data_as_of_rejects_future_csv(tmp_path):
    path = tmp_path / 'market.csv'
    prices().to_csv(path, index=False)
    with pytest.raises(ValueError, match='data_as_of'):
        read_market_csv(path, metadata(data_as_of=date(2025, 1, 2)))


@pytest.mark.parametrize('kind', ['duplicate', 'outside', 'not_bool', 'extra'])
def test_status_contract(kind):
    state = pd.DataFrame({'symbol': ['000001'], 'trade_date': ['2025-01-02'], 'is_suspended': [True]})
    if kind == 'duplicate':
        state = pd.concat([state, state])
    elif kind == 'outside':
        state['symbol'] = 'OTHER'
    elif kind == 'not_bool':
        state['is_suspended'] = 'False'
    else:
        state['future_signal'] = 1
    with pytest.raises(ValueError):
        build_calendar_panel(dataset(), calendar(), statuses=state)


def test_append_future_keeps_historical_panel_unchanged():
    earlier = build_calendar_panel(dataset(), calendar()).frame
    extra = pd.DataFrame([['000001', '2025-01-07', 30, 31, 29, 30, 0, 0]], columns=prices().columns)
    extended = build_calendar_panel(dataset(pd.concat([prices(), extra])),
        calendar(('2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07'))).frame
    history = extended[extended.trade_date <= pd.Timestamp('2025-01-06')].reset_index(drop=True)
    assert_frame_equal(earlier, history)


def test_calendar_csv_only_uses_supplied_open_dates(tmp_path):
    path = tmp_path / 'calendar.csv'
    pd.DataFrame({'trade_date': ['2025-01-06', '2025-01-02']}).to_csv(path, index=False)
    cal = TradingCalendar.from_csv(path, market='TEST', source='synthetic/calendar', version='v1')
    assert cal.dates.tolist() == [pd.Timestamp('2025-01-02'), pd.Timestamp('2025-01-06')]
    pd.DataFrame({'date': ['2025-01-02']}).to_csv(path, index=False)
    with pytest.raises(ValueError):
        TradingCalendar.from_csv(path, market='TEST', source='synthetic/calendar', version='v1')
