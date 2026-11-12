"""研究结果绘图；不填补缺失收益，不重新定义绩效指标。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .analysis import AnalysisResult
from .execution import ExecutionResult
from .factors import FactorResult
from .portfolio import PortfolioResult


@dataclass
class VisualizationResult:
    files: list[Path]
    parameters: dict[str, object]
    series_counts: dict[str, int]


def factor_correlation(factors: FactorResult, window: int) -> tuple[pd.DataFrame, int]:
    """原始因子每日横截面Pearson相关系数的等权时间均值；成对至少3只。"""
    f = factors.frame
    selected = f[f.window.eq(window) & f.valid]
    wide = selected.pivot(index=["trade_date", "symbol"], columns="factor", values="value")
    names = ["momentum", "volatility", "mean_reversion"]
    matrices = [b.reindex(columns=names).corr(min_periods=3) for _, b in wide.groupby(level=0)]
    if not matrices:
        return pd.DataFrame(np.nan, index=names, columns=names), 0
    sums = sum((m.fillna(0) for m in matrices))
    counts = sum((m.notna().astype(int) for m in matrices))
    return sums / counts.replace(0, np.nan), len(matrices)


def plot_research(
    analysis: AnalysisResult, factors: FactorResult, plan: PortfolioResult,
    execution: ExecutionResult, curve: pd.DataFrame, output: Path,
    *, window: int = 20,
) -> VisualizationResult:
    output.mkdir(parents=True, exist_ok=False)
    files: list[Path] = []
    counts: dict[str, int] = {}

    def save(name: str, title: str, draw) -> None:
        fig, ax = plt.subplots(figsize=(10, 4.8))
        try:
            draw(ax)
            ax.set_title(title)
            ax.grid(alpha=.2)
            fig.tight_layout()
            path = output / f"{name}.png"
            fig.savefig(path, dpi=130)
            files.append(path)
        finally:
            plt.close(fig)

    ic = analysis.daily_ic[analysis.daily_ic.value_type.eq("oriented_value")].copy()
    keys = ["factor", "window", "horizon"]
    def ic_lines(ax, column: str) -> None:
        for key, block in ic.groupby(keys, sort=True):
            b = block.sort_values("trade_date")
            values = b[column].where(b.status.eq("valid"))
            ax.plot(pd.to_datetime(b.trade_date), values, label=str(key), linewidth=1)
        ax.axhline(0, color="black", linewidth=.5)
        if len(ic):
            ax.legend(fontsize=6, ncol=2)
        counts[column] = int(ic.status.eq("valid").sum())
    save("ic_series", "Oriented IC | synthetic flag in report", lambda ax: ic_lines(ax, "ic"))
    save("rank_ic_series", "Oriented RankIC", lambda ax: ic_lines(ax, "rank_ic"))

    def histogram(ax) -> None:
        for key, b in ic.groupby(keys, sort=True):
            values = b.loc[b.status.eq("valid"), "ic"].dropna()
            if len(values):
                ax.hist(values, bins=15, alpha=.35, label=str(key))
        if ax.patches:
            ax.legend(fontsize=6, ncol=2)
        ax.set_xlabel("IC (overlapping labels; no independence assumption)")
    save("ic_distribution", "IC distributions by factor/window/horizon", histogram)
    corr, dates = factor_correlation(factors, window)
    def heatmap(ax) -> None:
        image = ax.imshow(corr.to_numpy(), vmin=-1, vmax=1, cmap="coolwarm")
        ax.set_xticks(range(len(corr)), corr.columns, rotation=15)
        ax.set_yticks(range(len(corr)), corr.index)
        for i in range(len(corr)):
            for j in range(len(corr)):
                v = corr.iloc[i, j]
                ax.text(j, i, "NA" if pd.isna(v) else f"{v:.2f}", ha="center", va="center")
        ax.figure.colorbar(image, ax=ax)
    save("factor_correlation", f"Mean daily raw-factor correlation | window={window}", heatmap)

    # 仅画固定锚点非重叠位置；保留其间无效位置的NaN以阻断连线。
    def group_lines(ax) -> None:
        for key, b in analysis.groups.groupby(keys + ["group"], sort=True):
            b = b[b.nonoverlap].sort_values("trade_date")
            ax.plot(pd.to_datetime(b.trade_date), b.cumulative_return, label=str(key))
        if len(analysis.groups):
            ax.legend(fontsize=5, ncol=3)
    save("group_returns", "Non-overlapping group returns | not executable NAV", group_lines)
    def spread_lines(ax) -> None:
        for key, b in analysis.spreads.groupby(keys, sort=True):
            b = b[b.nonoverlap].sort_values("trade_date")
            ax.plot(pd.to_datetime(b.trade_date), b.cumulative_return, label=str(key))
        if len(analysis.spreads):
            ax.legend(fontsize=6)
    save("long_short", "Hypothetical high-minus-low | no borrowing/costs", spread_lines)

    all_dates = pd.DatetimeIndex([s.trade_date for s in execution.snapshots])
    displayed = curve.set_index("trade_date").reindex(all_dates)
    def equity(ax) -> None:
        ax.plot(all_dates, displayed.normalized_equity, label="Portfolio")
        ax.axhline(1, color="black", linewidth=.5)
        for d in pd.to_datetime(plan.rebalances.execution_date):
            ax.axvline(d, color="grey", alpha=.12)
        counts["equity_valid"] = int(displayed.normalized_equity.notna().sum())
    save("portfolio_nav", "Portfolio NAV | initial capital = 1; missing valuations left blank", equity)
    save("drawdown", "Drawdown including initial capital peak", lambda ax: ax.plot(all_dates, displayed.drawdown))
    def turnover(ax) -> None:
        r = plan.rebalances
        ax.plot(pd.to_datetime(r.execution_date), r.target_turnover, "o-", label="Target: half L1 incl cash")
        ax.plot(all_dates, [float(s.actual_turnover) for s in execution.snapshots], label="Actual: gross traded / prior value")
        ax.legend(fontsize=8)
    save("turnover", "Target and actual turnover: different definitions", turnover)
    def orders(ax) -> None:
        rows = pd.DataFrame([{"day": o.execute_date, "status": o.status} for o in execution.orders])
        if not rows.empty:
            table = pd.crosstab(rows.day, rows.status)
            table.index = pd.to_datetime(table.index)
            for col in table:
                ax.plot(table.index, table[col], "o-", label=str(col))
            ax.legend()
        else:
            ax.text(.5, .5, "No orders", transform=ax.transAxes, ha="center")
    save("orders", "Order status counts by execution date", orders)
    return VisualizationResult(files, {"correlation": "mean daily Pearson; pairwise >=3", "window": window, "correlation_dates": dates, "missing_values": "not filled"}, counts)
