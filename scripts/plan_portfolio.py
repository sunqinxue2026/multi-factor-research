"""第六阶段合成目标计划演示；不是实际成交或策略收益。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from pathlib import Path
import platform
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
import pandas as pd
from multi_factor_research.data import DatasetMetadata, MarketDataset, TradingCalendar, build_calendar_panel
from multi_factor_research.factors import calculate_factors
from multi_factor_research.preprocessing import preprocess_factors
from multi_factor_research.portfolio import build_portfolio_plan, FACTOR_NAMES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--weights', nargs=3, type=float, default=[1/3, 1/3, 1/3], metavar=('MOM', 'VOL', 'REV'))
    parser.add_argument('--top-n', type=int, default=5)
    parser.add_argument('--frequency', choices=['weekly', 'monthly'], default='weekly')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    started, started_at = perf_counter(), datetime.now(timezone.utc).isoformat()
    dates = pd.bdate_range('2025-01-01', periods=100)
    rows = []
    for s in range(15):
        for i, day in enumerate(dates):
            p = (20+s) * np.exp((s-7)*.0005*i + .015*np.sin(i*(s+1)/7))
            rows.append([f'TEST{s:03}', day.strftime('%Y-%m-%d'), p, p, p, p, 100., 100*p])
    frame = pd.DataFrame(rows, columns=['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
    meta = DatasetMetadata('synthetic/stage6-demo', 'TEST', '未复权', dates[-1].date(), True, '15只虚构证券，无历史股票池含义')
    cal = TradingCalendar(dates, 'TEST', 'synthetic/weekday-calendar-not-exchange', 'v1')
    digest = sha256(frame.to_csv(index=False).encode('utf-8')).hexdigest()
    panel = build_calendar_panel(MarketDataset(frame, meta, digest, 'in-memory'), cal)
    factors = preprocess_factors(calculate_factors(panel, cal, windows=(args.window,)))
    result = build_portfolio_plan(factors, cal, windows={name: args.window for name in FACTOR_NAMES},
        weights=dict(zip(FACTOR_NAMES, args.weights)), top_n=args.top_n, frequency=args.frequency)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, table in [('scores', result.scores), ('target_weights', result.targets), ('target_changes', result.changes), ('rebalances', result.rebalances)]:
        table.to_csv(args.output / f'{name}.csv', index=False, encoding='utf-8-sig')
    summary = {'status': 'completed', 'is_synthetic': True, 'input_rows': len(frame),
        'score_rows': len(result.scores), 'valid_scores': int(result.scores.score_valid.sum()),
        'rebalance_count': len(result.rebalances), 'all_cash_count': int(result.rebalances.status.eq('all_cash').sum()),
        'parameters': result.parameters, 'input_sha256': digest, 'calendar_source': cal.source, 'calendar_version': cal.version,
        'started_at_utc': started_at, 'duration_seconds': perf_counter()-started,
        'python_version': platform.python_version(), 'pandas_version': pd.__version__, 'numpy_version': np.__version__,
        'limitations': ['合成行情及工作日教学日历，未核验交易所假期。', '目标权重不是实际持仓，未计算费用、滑点或收益。',
            '目标换手包含现金，初始全现金，不含持仓价格漂移。', '未知市场状态参与研究，不保证可成交；未消除幸存者偏差。',
            '输出非原子提交，失败可能保留部分文件；目录禁止覆盖。']}
    text = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)
    (args.output / 'summary.json').write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
