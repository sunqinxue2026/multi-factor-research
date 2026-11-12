"""第三阶段合成演示：显式教学日历，不代表真实市场表现。"""
from __future__ import annotations

import argparse
from dataclasses import asdict
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows', nargs='+', type=int, default=[20, 60])
    parser.add_argument('--annualization-days', type=int, default=252)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    started_at = datetime.now(timezone.utc).isoformat()
    started = perf_counter()
    # 80个逐日教学位置，不以工作日冒充官方交易日历。
    dates = pd.date_range('2025-01-01', periods=80, freq='D')
    closes = {'A': [100., 110., 99., 99.] + [99. * 1.01 ** i for i in range(1, 77)],
              'B': [20.] * 80}
    rows = [[s, d.strftime('%Y-%m-%d'), c, c, c, c, 100., c * 100] for s, values in closes.items() for d, c in zip(dates, values)]
    frame = pd.DataFrame(rows, columns=['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
    metadata = DatasetMetadata('synthetic/stage3-demo', 'TEST', '未复权', date(2025, 3, 21), True, '两只虚构证券，无历史股票池含义')
    calendar = TradingCalendar(dates, 'TEST', 'synthetic/calendar', 'v1')
    digest = sha256(frame.to_csv(index=False).encode('utf-8')).hexdigest()
    panel = build_calendar_panel(MarketDataset(frame, metadata, digest, 'generated-in-memory.csv'), calendar)
    result = calculate_factors(panel, calendar, windows=args.windows, annualization_days=args.annualization_days)
    args.output.mkdir(parents=True, exist_ok=False)
    result.frame.to_csv(args.output / 'factors.csv', index=False, encoding='utf-8-sig')
    summary = {
        'status': 'completed', 'is_synthetic': True, 'input_rows': len(frame),
        'factor_rows': len(result.frame), 'valid_factor_rows': int(result.frame.valid.sum()),
        'parameters': result.parameters, 'metadata': asdict(metadata),
        'input_sha256': digest, 'calendar_source': calendar.source, 'calendar_version': calendar.version,
        'started_at_utc': started_at, 'duration_seconds': perf_counter() - started,
        'python_version': platform.python_version(), 'pandas_version': pd.__version__, 'numpy_version': np.__version__,
        'limitations': ['合成行情与日历仅用于公式演示，不证明因子有效。', 'valid仅代表价格窗口有效，不代表股票可投资。', '未实现标准化、IC、组合或执行。', '导出非原子提交，失败可能保留部分文件。'],
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2, default=str, allow_nan=False)
    (args.output / 'summary.json').write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
