"""第二阶段入口：读取多股票CSV并按显式交易日历对齐。"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
import platform
import sys
from time import perf_counter
from hashlib import sha256

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import pandas as pd
from multi_factor_research.data import DatasetMetadata, TradingCalendar, read_market_csv, build_calendar_panel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--calendar', type=Path, required=True)
    parser.add_argument('--calendar-source', required=True)
    parser.add_argument('--calendar-version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    started_at = datetime.now(timezone.utc).isoformat()
    started = perf_counter()
    values = json.loads(args.metadata.read_text(encoding='utf-8-sig'))
    values['data_as_of'] = date.fromisoformat(values['data_as_of'])
    metadata = DatasetMetadata(**values)
    calendar = TradingCalendar.from_csv(args.calendar, market=metadata.market,
        source=args.calendar_source, version=args.calendar_version)
    result = build_calendar_panel(read_market_csv(args.csv, metadata), calendar)
    # 拒绝覆盖已有输出；失败时可能留下部分文件，不宣称原子提交。
    args.output.mkdir(parents=True, exist_ok=False)
    result.frame.to_csv(args.output / 'panel.csv', index=False, encoding='utf-8-sig')
    summary = {
        'status': 'completed', 'input_rows': int(result.frame.observed.sum()),
        'panel_rows': len(result.frame), 'symbols': result.frame.symbol.nunique(),
        'calendar_days': len(calendar.dates),
        'missing_records': int((~result.frame.observed).sum()),
        'incomplete_price_rows': int((~result.frame.price_complete).sum()),
        'unknown_tradability_rows': int(result.frame.tradable.isna().sum()),
        'metadata': asdict(metadata), 'file_sha256': result.file_sha256,
        'calendar_source': result.calendar_source, 'calendar_version': result.calendar_version,
        'calendar_sha256': sha256(args.calendar.read_bytes()).hexdigest(),
        'started_at_utc': started_at, 'duration_seconds': perf_counter() - started,
        'python_version': platform.python_version(), 'pandas_version': pd.__version__,
        'limitations': [
            '交易日历真实性由提供者保证；不以工作日自动生成。',
            '只包含输入中观察到的股票，不能消除幸存者偏差。',
            '未提供历史上市、停牌和公司行动资料；未知状态不等于可交易。',
            '前复权历史可能修订；文件摘要不证明历史时点可获得。',
        ],
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2, default=str)
    (args.output / 'summary.json').write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
