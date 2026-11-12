"""第五阶段合成完整链路演示；不证明因子有效或可实现投资收益。"""
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
from multi_factor_research.analysis import build_forward_returns, analyze_factors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows', nargs='+', type=int, default=[20, 60])
    parser.add_argument('--horizons', nargs='+', type=int, default=[5, 20])
    parser.add_argument('--groups', type=int, default=5)
    parser.add_argument('--min-samples', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    started = perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    dates = pd.date_range('2025-01-01', periods=100, freq='D')
    rows = []
    for s in range(15):
        for i, day in enumerate(dates):
            close = (20 + s) * np.exp((s - 7) * .0005 * i + .015 * np.sin(i * (s + 1) / 7))
            opening = close * (1 + .002 * np.cos(i + s))
            rows.append([f'TEST{s:03}', day.strftime('%Y-%m-%d'), opening, max(opening, close), min(opening, close), close, 100., close * 100])
    frame = pd.DataFrame(rows, columns=['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
    meta = DatasetMetadata('synthetic/stage5-demo', 'TEST', '未复权', dates[-1].date(), True, '15只虚构证券；没有真实股票池含义')
    cal = TradingCalendar(dates, 'TEST', 'synthetic/calendar', 'v1')
    digest = sha256(frame.to_csv(index=False).encode('utf-8')).hexdigest()
    panel = build_calendar_panel(MarketDataset(frame, meta, digest, 'in-memory'), cal)
    factors = preprocess_factors(calculate_factors(panel, cal, windows=args.windows))
    labels = build_forward_returns(panel, cal, horizons=tuple(args.horizons))
    result = analyze_factors(factors, labels, min_samples=args.min_samples, n_groups=args.groups)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, table in [('forward_returns', labels.frame), ('daily_ic', result.daily_ic), ('ic_summary', result.ic_summary), ('group_returns', result.groups), ('long_short_returns', result.spreads), ('group_summary', result.group_summary)]:
        table.to_csv(args.output / f'{name}.csv', index=False, encoding='utf-8-sig')
    summary = {'status': 'completed', 'is_synthetic': True, 'input_rows': len(frame),
        'label_rows': len(labels.frame), 'valid_labels': int(labels.frame.label_valid.sum()),
        'ic_rows': len(result.daily_ic), 'valid_ic_rows': int(result.daily_ic.status.eq('valid').sum()),
        'group_rows': len(result.groups), 'valid_group_rows': int(result.groups.status.eq('valid').sum()),
        'parameters': result.parameters, 'input_sha256': digest, 'started_at_utc': started_at,
        'duration_seconds': perf_counter() - started, 'python_version': platform.python_version(),
        'pandas_version': pd.__version__, 'numpy_version': np.__version__,
        'limitations': ['合成行情和教学日历；无真实因子有效性结论。', '标签仅检查入口出口价格，不保证中间可交易。',
            '无费用、融券和成交约束；分组收益不是共享现金组合。', '多空复利曲线为假设收益差，不是自融资净值；可能小于-100%。',
            'ICIR不年化；重叠标签有序列相关，不提供独立样本显著性结论。', '无历史股票池，未消除幸存者偏差。', '输出非原子提交，失败可能残留部分文件。']}
    text = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)
    (args.output / 'summary.json').write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
