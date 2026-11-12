from copy import deepcopy

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from multi_factor_research.factors import FactorResult
from multi_factor_research.preprocessing import preprocess_factors


def sample(values=(-2., -1., 0., 1., 2.), factor='momentum', day='2025-01-01', window=3):
    frame = pd.DataFrame({'symbol': [f'S{i}' for i in range(len(values))],
        'trade_date': pd.Timestamp(day), 'factor': factor, 'window': window,
        'value': values, 'valid': [not pd.isna(v) for v in values],
        'reason': ['valid' if not pd.isna(v) else 'missing_close_in_window' for v in values]})
    return FactorResult(frame, {'windows': [window]}, 'fixture', 'synthetic/calendar', 'v1')


def test_hand_zscore_no_clip_and_input_unchanged():
    source = sample()
    saved = source.frame.copy(deep=True)
    result = preprocess_factors(source, quantiles=None)
    assert_frame_equal(source.frame, saved)
    np.testing.assert_allclose(result.frame.zscore, np.array([-2, -1, 0, 1, 2]) / np.sqrt(2))
    assert result.frame.preprocess_valid.all()
    assert result.frame.value.iloc[2] == 0
    assert result.audit.iloc[0]['std'] == pytest.approx(np.sqrt(2))
    assert result.audit.unknown_status_count.iloc[0] == 5
    assert result.file_sha256 == 'fixture'


def test_linear_quantile_clipping_exact_values():
    result = preprocess_factors(sample((0., 1., 2., 3., 100.)), quantiles=(0.25, 0.75))
    np.testing.assert_allclose(result.frame.clipped_value, [1, 1, 2, 3, 3])
    assert result.frame.was_clipped.tolist() == [True, False, False, False, True]
    row = result.audit.iloc[0]
    assert row.lower_bound == 1 and row.upper_bound == 3
    assert row['mean'] == 2 and row['std'] == pytest.approx(np.sqrt(0.8))
    assert row.clipped_count == 2
    default = preprocess_factors(sample((0., 1., 2., 3., 100.)))
    assert default.audit.lower_bound.iloc[0] == pytest.approx(0.04)
    assert default.audit.upper_bound.iloc[0] == pytest.approx(96.12)


@pytest.mark.parametrize('factor,direction', [('momentum', 1), ('volatility', -1), ('mean_reversion', -1)])
def test_direction(factor, direction):
    result = preprocess_factors(sample(factor=factor), quantiles=None)
    np.testing.assert_allclose(result.frame.oriented_value, result.frame.zscore * direction)
    assert result.frame.direction.eq(direction).all()


def test_missing_insufficient_and_constant():
    result = preprocess_factors(sample((1., 2., 3., 4., np.nan)))
    assert result.frame.preprocess_reason.iloc[-1] == 'raw_invalid'
    assert result.frame.preprocess_reason.iloc[0] == 'insufficient_cross_section'
    assert result.frame.zscore.isna().all()
    constant = preprocess_factors(sample((2.,) * 5))
    assert constant.frame.preprocess_reason.eq('zero_variance').all()
    assert constant.frame.zscore.isna().all()
    assert constant.frame.clipped_value.eq(2).all()


def test_status_exclusion_unknown_retained_and_tradable_not_filter():
    source = sample(tuple(float(i) for i in range(7)))
    source.frame['is_listed'] = pd.Series([False, True, None, True, True, True, True], dtype='boolean')
    source.frame['is_suspended'] = pd.Series([False, True, None, False, False, False, False], dtype='boolean')
    source.frame['tradable'] = False
    result = preprocess_factors(source)
    assert not result.frame.research_eligible.iloc[:2].any()
    assert result.frame.preprocess_valid.iloc[2:].all()
    assert result.audit.eligible_count.iloc[0] == 5
    assert result.audit.status_excluded_count.iloc[0] == 2
    assert result.audit.unknown_status_count.iloc[0] == 1


def test_date_factor_window_isolation_and_order():
    original = sample()
    extra = [sample((10., 20., 30., 40., 50.), day='2025-01-02'),
             sample((10., 20., 30., 40., 50.), factor='volatility'),
             sample((10., 20., 30., 40., 50.), window=20)]
    expected = preprocess_factors(original, quantiles=None).frame
    extended = deepcopy(original)
    extended.frame = pd.concat([original.frame] + [s.frame for s in extra], ignore_index=True)
    result = preprocess_factors(extended, quantiles=None)
    history = result.frame[(result.frame.trade_date == pd.Timestamp('2025-01-01')) & (result.frame.factor == 'momentum') & (result.frame.window == 3)].reset_index(drop=True)
    assert_frame_equal(expected, history)
    extended.frame = extended.frame.sample(frac=1, random_state=42)
    assert_frame_equal(result.frame, preprocess_factors(extended, quantiles=None).frame)
    assert len(result.audit) == 4
    extended.frame.loc[extended.frame.trade_date > pd.Timestamp('2025-01-01'), 'value'] = 999.
    changed = preprocess_factors(extended, quantiles=None).frame
    assert_frame_equal(result.frame[result.frame.trade_date == pd.Timestamp('2025-01-01')].reset_index(drop=True), changed[changed.trade_date == pd.Timestamp('2025-01-01')].reset_index(drop=True))


@pytest.mark.parametrize('kwargs', [dict(min_samples=1), dict(min_samples=True), dict(quantiles=(0.9, 0.1)), dict(quantiles=(-0.1, 1)), dict(quantiles=(0, np.inf)), dict(quantiles=(True, 1)), dict(directions={'momentum': True}), dict(directions={})])
def test_bad_configuration(kwargs):
    with pytest.raises(ValueError):
        preprocess_factors(sample(), **kwargs)


@pytest.mark.parametrize('kind', ['empty', 'missing', 'duplicate', 'valid_nan', 'inf', 'bool_value', 'bad_value', 'bad_valid', 'bad_status', 'bad_window', 'bad_symbol', 'bad_date', 'processed'])
def test_bad_input(kind):
    source = sample()
    if kind == 'empty': source.frame = source.frame.iloc[:0]
    elif kind == 'missing': source.frame = source.frame.drop(columns='value')
    elif kind == 'duplicate': source.frame = pd.concat([source.frame, source.frame.iloc[:1]])
    elif kind == 'valid_nan': source.frame.loc[0, 'value'] = np.nan
    elif kind == 'inf': source.frame.loc[0, 'value'] = np.inf
    elif kind == 'bool_value': source.frame['value'] = source.frame.value.astype(object); source.frame.loc[0, 'value'] = True
    elif kind == 'bad_value': source.frame['value'] = source.frame.value.astype(object); source.frame.loc[0, 'value'] = 'bad'
    elif kind == 'bad_valid': source.frame['valid'] = 'True'
    elif kind == 'bad_status': source.frame['is_listed'] = 'False'
    elif kind == 'bad_window': source.frame['window'] = 1
    elif kind == 'bad_symbol': source.frame.loc[0, 'symbol'] = ''
    elif kind == 'bad_date': source.frame['trade_date'] = pd.Timestamp('2025-01-01 12:00')
    else: source.frame['zscore'] = 0
    with pytest.raises(ValueError): preprocess_factors(source)


def test_custom_direction_and_small_nonzero_variance():
    source = sample((0., 1e-15, 2e-15, 3e-15, 4e-15))
    result = preprocess_factors(source, quantiles=None, directions={'momentum': -1})
    assert result.frame.preprocess_valid.all()
    np.testing.assert_allclose(result.frame.oriented_value, -result.frame.zscore)
