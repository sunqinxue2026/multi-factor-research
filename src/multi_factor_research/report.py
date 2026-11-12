"""静态中文研究报告、结果导出与一致性检查。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from html import escape
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import AnalysisResult, LabelResult
from .execution import ExecutionResult
from .factors import FactorResult
from .portfolio import PortfolioResult
from .preprocessing import PreprocessingResult
from .visualization import plot_research


@dataclass
class ResearchReportResult:
    report_path: Path
    files: list[Path]
    summary: dict[str, object]


def json_safe(value):
    """不可定义统计量转null；不将NaN写入非标准JSON。"""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (date, datetime, pd.Timestamp, Path, Decimal)):
        return str(value)
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def validate_results(plan: PortfolioResult, execution: ExecutionResult, metrics: dict,
                     curve: pd.DataFrame, initial: Decimal) -> None:
    if curve.empty or curve.trade_date.duplicated().any():
        raise ValueError("绩效曲线为空或日期重复")
    usable = [s for s in execution.snapshots if s.total_value is not None]
    if list(pd.to_datetime(curve.trade_date).dt.date) != [s.trade_date for s in usable]:
        raise ValueError("曲线日期与有效估值不一致")
    if not np.allclose(curve.equity, [float(s.total_value) for s in usable], rtol=0, atol=1e-8):
        raise ValueError("曲线与快照资产不一致")
    equity = curve.equity.to_numpy(float)
    normalized = equity / float(initial)
    drawdown = equity / np.maximum.accumulate(np.r_[float(initial), equity])[1:] - 1
    checks = [np.allclose(curve.normalized_equity, normalized), np.allclose(curve.drawdown, drawdown),
              np.isclose(metrics['final_equity'], equity[-1]),
              np.isclose(metrics['total_return'], normalized[-1] - 1),
              np.isclose(metrics['max_drawdown'], drawdown.min()),
              metrics['order_count'] == len(execution.orders), metrics['trade_count'] == len(execution.trades)]
    if not all(checks):
        raise ValueError("报告指标与正式结果不一致")
    if len(plan.rebalances) and not (pd.to_datetime(plan.rebalances.execution_date) > pd.to_datetime(plan.rebalances.signal_date)).all():
        raise ValueError("执行日必须晚于信号日")
    order_ids = {o.order_id for o in execution.orders}
    if any(t.order_id not in order_ids for t in execution.trades):
        raise ValueError("成交缺少对应订单")


def generate_research_report(
    output: Path, *, market: pd.DataFrame, factors: FactorResult,
    preprocessed: PreprocessingResult, labels: LabelResult, analysis: AnalysisResult,
    plan: PortfolioResult, execution: ExecutionResult, metrics: dict, curve: pd.DataFrame,
    initial: Decimal, metadata: dict, run_info: dict,
) -> ResearchReportResult:
    validate_results(plan, execution, metrics, curve, initial)
    identities = [factors.file_sha256, preprocessed.file_sha256, labels.file_sha256, analysis.file_sha256, plan.file_sha256]
    if len(set(identities)) != 1:
        raise ValueError("不同来源结果不能合并报告")
    output.mkdir(parents=True, exist_ok=False)
    tables = {
        'market': market, 'factors': factors.frame, 'preprocessed_factors': preprocessed.frame,
        'cross_section_audit': preprocessed.audit, 'forward_returns': labels.frame,
        'daily_ic': analysis.daily_ic, 'ic_summary': analysis.ic_summary,
        'group_returns': analysis.groups, 'long_short_returns': analysis.spreads,
        'group_summary': analysis.group_summary, 'scores': plan.scores,
        'target_weights': plan.targets, 'target_changes': plan.changes, 'rebalances': plan.rebalances,
        'orders': pd.DataFrame([asdict(o) for o in execution.orders]),
        'trades': pd.DataFrame([asdict(t) for t in execution.trades]),
        'snapshots': pd.DataFrame([asdict(s) for s in execution.snapshots]),
        'positions': execution.positions, 'equity_curve': curve,
    }
    files = []
    for name, table in tables.items():
        path = output / f'{name}.csv'
        table.to_csv(path, index=False, encoding='utf-8-sig')
        files.append(path)
    charts = plot_research(analysis, factors, plan, execution, curve, output / 'charts')
    files.extend(charts.files)
    limitations = [
        '合成数据仅用于工程验证，不证明因子有效或策略可盈利。' if metadata['is_synthetic'] else '外部行情由用户提供，文件摘要不证明数据真实性。',
        '没有历史成分股与完整退市样本，未消除幸存者偏差；未知上市和停牌状态不等于可投资。',
        '未完整建模涨跌停、停牌撮合、成交量约束、公司行动和融券；未连接数据库。',
        '分组收益为固定锚点非重叠研究统计，不是含成本的可执行组合；多空收益差不是自融资净值。',
        'ICIR不年化，重叠标签存在序列相关；没有独立样本显著性结论。',
        '缺失估值不填充，绩效沿用第七阶段跳过缺失估值的口径；跨缺口收益不是严格单日收益。',
        '目标换手为含现金半L1距离，实际换手为双边成交金额/调仓前已知资产，两者不可直接等同。',
        '输出非原子提交；失败可能留下部分文件，不会覆盖既有目录。',
    ]
    summary = json_safe({'status': 'completed', 'metadata': metadata, 'run': run_info,
        'input_sha256': factors.file_sha256, 'calendar': {'source': factors.calendar_source, 'version': factors.calendar_version},
        'counts': {k: len(v) for k, v in tables.items()}, 'metrics': metrics,
        'parameters': {'factors': factors.parameters, 'preprocessing': preprocessed.parameters,
                       'labels': labels.parameters, 'analysis': analysis.parameters,
                       'portfolio': plan.parameters, 'execution': execution.parameters},
        'visualization': charts.parameters, 'chart_series_counts': charts.series_counts,
        'limitations': limitations})
    report_path = output / '研究报告.html'
    sections = [('<h1>多因子选股与组合研究报告</h1>'),
        '<p><strong>' + ('合成数据工程演示，非真实投资结论' if metadata['is_synthetic'] else '用户提供的外部数据研究') + '</strong></p>']
    def section(title: str, content: str) -> None:
        sections.append(f'<section><h2>{escape(title)}</h2>{content}</section>')
    section('研究概览与数据说明', '<pre>' + escape(json.dumps(json_safe(metadata), ensure_ascii=False, indent=2)) + '</pre>')
    section('因子定义与预处理', '<p>动量=C[t]/C[t-N]−1；波动率=最近N个日收益样本标准差；均线偏离=C[t]/MA[N]−1。横截面截尾、ddof=0标准化并统一方向。</p>')
    section('IC与RankIC', analysis.ic_summary.to_html(index=False, escape=True, na_rep='不可计算'))
    section('分组收益', analysis.group_summary.to_html(index=False, escape=True, na_rep='不可计算'))
    section('组合执行与绩效', pd.DataFrame([{'指标': k, '值': v} for k,v in metrics.items() if not isinstance(v, (dict,list))]).to_html(index=False, escape=True, na_rep='不可计算'))
    section('研究图表', ''.join(f'<figure><img src="{escape(p.relative_to(output).as_posix())}" alt="{escape(p.stem)}"><figcaption>{escape(p.stem)}</figcaption></figure>' for p in charts.files))
    section('风险与局限', '<ul>' + ''.join('<li>' + escape(x) + '</li>' for x in limitations) + '</ul>')
    section('参数、环境与运行信息', '<pre>' + escape(json.dumps(summary, ensure_ascii=False, indent=2)) + '</pre>')
    section('输出文件索引', '<ul>' + ''.join(f'<li><a href="{escape(p.relative_to(output).as_posix())}">{escape(p.name)}</a></li>' for p in files) + '<li><a href="summary.json">summary.json</a></li></ul>')
    report_path.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>多因子研究报告</title><style>body{max-width:1120px;margin:32px auto;padding:0 24px;font-family:system-ui;line-height:1.7;color:#203040}h1,h2{color:#16436b}section{margin:32px 0}table{border-collapse:collapse;font-size:13px;display:block;overflow:auto}th,td{padding:8px;border:1px solid #dde3eb}pre{background:#f2f5f9;padding:16px;overflow:auto}img{max-width:100%}figure{margin:24px 0}</style>' + ''.join(sections) + '</html>', encoding='utf-8')
    summary['files'] = [p.relative_to(output).as_posix() for p in files] + ['研究报告.html', 'summary.json']
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return ResearchReportResult(report_path, files + [report_path, output / 'summary.json'], summary)
