from dataclasses import asdict, replace
from decimal import Decimal
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from multi_factor_research.data import DatasetMetadata, MarketDataset, TradingCalendar, build_calendar_panel
from multi_factor_research.factors import calculate_factors
from multi_factor_research.preprocessing import preprocess_factors
from multi_factor_research.analysis import build_forward_returns, analyze_factors
from multi_factor_research.portfolio import build_portfolio_plan, FACTOR_NAMES
from multi_factor_research.execution import execute_portfolio_plan
from multi_factor_research.performance import analyze_portfolio_performance
from multi_factor_research.report import generate_research_report, validate_results, json_safe
from multi_factor_research.visualization import factor_correlation, plot_research


@pytest.fixture(scope='module')
def bundle():
    days = pd.bdate_range('2025-01-01', periods=30)
    rows = []
    for s in range(6):
        for i, day in enumerate(days):
            price = (20+s)*np.exp(.001*s*i + .02*np.sin(i*(s+1)/7))
            rows.append([f'TEST{s}', str(day.date()), price, price, price, price, 100, price*100])
    market = pd.DataFrame(rows, columns=['symbol','trade_date','open','high','low','close','volume','amount'])
    cal = TradingCalendar(days, 'TEST', 'synthetic/test', 'v1')
    meta = DatasetMetadata('<script>bad</script>', 'TEST', '未复权', days[-1].date(), True, '虚构股票')
    panel = build_calendar_panel(MarketDataset(market, meta, 'digest', 'memory'), cal)
    factors = calculate_factors(panel, cal, windows=(3,))
    pre = preprocess_factors(factors)
    labels = build_forward_returns(panel, cal, horizons=(2,))
    analysis = analyze_factors(pre, labels)
    plan = build_portfolio_plan(pre, cal, windows={n:3 for n in FACTOR_NAMES})
    execution = execute_portfolio_plan(plan, panel.frame)
    metrics, curve = analyze_portfolio_performance(execution, Decimal('100000'))
    return dict(market=panel.frame, factors=factors, preprocessed=pre, labels=labels, analysis=analysis,
                plan=plan, execution=execution, metrics=metrics, curve=curve, initial=Decimal('100000'),
                metadata=asdict(meta), run_info={'python':'test'})


@pytest.mark.parametrize('key', ['final_equity','total_return','max_drawdown','order_count','trade_count'])
def test_reject_metric_drift(bundle, key):
    metrics = bundle['metrics'] | {key: 987654321}
    with pytest.raises(ValueError, match='指标'):
        validate_results(bundle['plan'], bundle['execution'], metrics, bundle['curve'], bundle['initial'])


def test_reject_curve_and_identity_drift(bundle, tmp_path):
    curve = bundle['curve'].copy()
    curve.loc[0,'equity'] += 100
    with pytest.raises(ValueError, match='资产'):
        validate_results(bundle['plan'], bundle['execution'], bundle['metrics'], curve, bundle['initial'])
    with pytest.raises(ValueError, match='来源'):
        generate_research_report(tmp_path/'bad', **(bundle | {'labels':replace(bundle['labels'], file_sha256='other')}))
    assert not (tmp_path/'bad').exists()


def test_report_exports_and_html_escape(bundle, tmp_path):
    result = generate_research_report(tmp_path/'report', **bundle)
    assert len(result.files) == 31
    assert all(p.is_file() for p in result.files)
    text = result.report_path.read_text(encoding='utf-8')
    assert '<script>bad</script>' not in text
    assert '&lt;script&gt;bad&lt;/script&gt;' in text
    for word in ['合成数据','幸存者偏差','目标换手','风险与局限']:
        assert word in text
    summary = json.loads((tmp_path/'report'/'summary.json').read_text(encoding='utf-8'))
    assert summary['counts']['trades'] == len(bundle['execution'].trades)
    assert summary['metrics'] == json_safe(bundle['metrics'])
    assert summary['chart_series_counts']['equity_valid'] == len(bundle['curve'])
    for path in (tmp_path/'report'/'charts').glob('*.png'):
        import matplotlib.image as mpimg
        pixels = mpimg.imread(path)
        assert pixels.shape[0] > 100 and pixels.shape[1] > 100
        assert pixels.std() > .01
    with pytest.raises(FileExistsError):
        generate_research_report(tmp_path/'report', **bundle)


def test_correlation_is_mean_daily_not_pooled(bundle):
    factors = bundle['factors']
    matrix, count = factor_correlation(factors, 3)
    wide = factors.frame.query('window == 3 and valid').pivot(index=['trade_date','symbol'], columns='factor', values='value')
    expected = pd.concat([b.corr(min_periods=3) for _, b in wide.groupby(level=0)]).groupby(level=0).mean()
    pd.testing.assert_frame_equal(matrix.sort_index().sort_index(axis=1), expected.sort_index().sort_index(axis=1))
    assert count > 0


def test_missing_valuation_is_not_interpolated(bundle, tmp_path):
    execution = bundle['execution']
    snapshots = list(execution.snapshots)
    snapshots[10] = replace(snapshots[10], total_value=None)
    execution = replace(execution, snapshots=snapshots)
    metrics, curve = analyze_portfolio_performance(execution, bundle['initial'])
    charts = plot_research(bundle['analysis'], bundle['factors'], bundle['plan'], execution, curve, tmp_path/'charts', window=3)
    assert charts.series_counts['equity_valid'] == len(snapshots)-1


@pytest.mark.parametrize('value,expected', [(float('nan'),None),(np.float64('inf'),None),(Decimal('1.2'),'1.2')])
def test_json_safe(value, expected):
    assert json_safe(value) == expected
