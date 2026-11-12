"""第四阶段合成演示：多股票历史因子与同日截面处理。"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows', nargs='+', type=int, default=[20, 60])
    parser.add_argument('--min-samples', type=int, default=5)
    parser.add_argument('--lower', type=float, default=0.01)
    parser.add_argument('--upper', type=float, default=0.99)
    parser.add_argument('--no-clip', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    started_at = datetime.now(timezone.utc).isoformat()
    started = perf_counter()
    dates = pd.date_range('2025-01-01', periods=80, freq='D')
    rows = []
    for s in range(8):
        for i, day in enumerate(dates):
            close = (20 + s) * np.exp((s - 3) * 0.001 * i + 0.015 * np.sin(i * (s + 1) / 7))
            rows.append([f'TEST{s:03}', day.strftime('%Y-%m-%d'), close, close, close, close, 100., close * 100])
    frame = pd.DataFrame(rows, columns=['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
    metadata = DatasetMetadata('synthetic/stage4-demo', 'TEST', '未复权', date(2025, 3, 21), True, '8只虚构证券；不是历史可投资股票池')
    calendar = TradingCalendar(dates, 'TEST', 'synthetic/calendar', 'v1')
    digest = sha256(frame.to_csv(index=False).encode('utf-8')).hexdigest()
    panel = build_calendar_panel(MarketDataset(frame, metadata, digest, 'generated-in-memory.csv'), calendar)
    factors = calculate_factors(panel, calendar, windows=args.windows)
    result = preprocess_factors(factors, quantiles=None if args.no_clip else (args.lower, args.upper), min_samples=args.min_samples)
    args.output.mkdir(parents=True, exist_ok=False)
    result.frame.to_csv(args.output / 'preprocessed_factors.csv', index=False, encoding='utf-8-sig')
    result.audit.to_csv(args.output / 'cross_section_audit.csv', index=False, encoding='utf-8-sig')
    summary = {
        'status': 'completed', 'is_synthetic': True, 'input_rows': len(frame),
        'factor_rows': len(result.frame), 'valid_preprocessed_rows': int(result.frame.preprocess_valid.sum()),
        'cross_sections': len(result.audit), 'cross_section_statuses': result.audit.status.value_counts().to_dict(),
        'parameters': result.parameters, 'input_sha256': digest,
        'calendar_source': result.calendar_source, 'calendar_version': result.calendar_version,
        'started_at_utc': started_at, 'duration_seconds': perf_counter() - started,
        'python_version': platform.python_version(), 'pandas_version': pd.__version__, 'numpy_version': np.__version__,
        'limitations': ['合成行情及教学日历，不证明因子有效。', '未知市场状态参与研究，不代表可投资；未消除幸存者偏差。', '未实现IC、评分、组合或回测。', '文件导出非原子提交，失败可能保留部分文件。'],
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)
    (args.output / 'summary.json').write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
