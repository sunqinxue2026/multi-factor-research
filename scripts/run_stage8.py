"""最终研究入口：默认合成数据；外部CSV必须提供元数据与显式日历。"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import logging
from pathlib import Path
import platform
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))

import matplotlib
import numpy as np
import pandas as pd
from run_stage7 import build_market
from multi_factor_research.data import DatasetMetadata, MarketDataset, TradingCalendar, read_market_csv, build_calendar_panel
from multi_factor_research.factors import calculate_factors
from multi_factor_research.preprocessing import preprocess_factors
from multi_factor_research.analysis import build_forward_returns, analyze_factors
from multi_factor_research.portfolio import FACTOR_NAMES, build_portfolio_plan
from multi_factor_research.execution import ExecutionCostModel, execute_portfolio_plan
from multi_factor_research.performance import analyze_portfolio_performance
from multi_factor_research.report import generate_research_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--csv', type=Path)
    parser.add_argument('--metadata', type=Path)
    parser.add_argument('--calendar', type=Path)
    parser.add_argument('--calendar-source')
    parser.add_argument('--calendar-version')
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--horizons', type=int, nargs='+', default=[5, 20])
    parser.add_argument('--groups', type=int, choices=[5, 10], default=5)
    parser.add_argument('--top-n', type=int, default=5)
    parser.add_argument('--frequency', choices=['weekly', 'monthly'], default='weekly')
    parser.add_argument('--initial-cash', type=Decimal, default=Decimal('100000'))
    args = parser.parse_args()
    if args.output.exists():
        parser.error('输出目录已存在，拒绝覆盖')
    external = [args.csv, args.metadata, args.calendar, args.calendar_source, args.calendar_version]
    if any(x is not None for x in external) and not all(x is not None for x in external):
        parser.error('外部数据必须同时提供csv、metadata、calendar、calendar-source、calendar-version')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    started = perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    if args.csv:
        values = json.loads(args.metadata.read_text(encoding='utf-8-sig'))
        values['data_as_of'] = date.fromisoformat(values['data_as_of'])
        metadata = DatasetMetadata(**values)
        calendar = TradingCalendar.from_csv(args.calendar, market=metadata.market, source=args.calendar_source, version=args.calendar_version)
        dataset = read_market_csv(args.csv, metadata)
    else:
        market, calendar = build_market()
        metadata = DatasetMetadata('synthetic/stage8-demo', 'TEST', '未复权', calendar.dates[-1].date(), True, '15只虚构证券；不是历史可投资股票池')
        dataset = MarketDataset(market, metadata, sha256(market.to_csv(index=False).encode('utf-8')).hexdigest(), 'stage8-generated.csv')
    panel = build_calendar_panel(dataset, calendar)
    factors = calculate_factors(panel, calendar, windows=(args.window,))
    preprocessed = preprocess_factors(factors)
    labels = build_forward_returns(panel, calendar, horizons=tuple(args.horizons))
    analysis = analyze_factors(preprocessed, labels, n_groups=args.groups)
    plan = build_portfolio_plan(preprocessed, calendar, windows={n: args.window for n in FACTOR_NAMES}, top_n=args.top_n, frequency=args.frequency)
    execution = execute_portfolio_plan(plan, panel.frame, initial_cash=args.initial_cash, costs=ExecutionCostModel())
    metrics, curve = analyze_portfolio_performance(execution, args.initial_cash)
    result = generate_research_report(args.output, market=panel.frame, factors=factors, preprocessed=preprocessed,
        labels=labels, analysis=analysis, plan=plan, execution=execution, metrics=metrics, curve=curve,
        initial=args.initial_cash, metadata=asdict(metadata), run_info={
            'started_at_utc': started_at, 'compute_seconds': perf_counter() - started,
            'python': platform.python_version(), 'pandas': pd.__version__, 'numpy': np.__version__,
            'matplotlib': matplotlib.__version__, 'calendar_sha256': sha256('\n'.join(str(d.date()) for d in calendar.dates).encode()).hexdigest(),
            'calendar_is_exchange_verified': False, 'initial_cash': str(args.initial_cash),
            'timing_scope': 'compute_seconds不含图表与报告写入；total_seconds见命令行输出'})
    print(json.dumps({'status': 'completed', 'files': len(result.files), 'counts': result.summary['counts'],
                      'metrics': metrics, 'total_seconds': perf_counter() - started}, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
