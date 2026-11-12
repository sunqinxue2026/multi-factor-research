"""第七阶段：多股票目标计划的共享现金执行适配层。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_EVEN
from typing import Mapping

import numpy as np
import pandas as pd

from .portfolio import PortfolioResult

MONEY = Decimal("0.01")
PRICE = Decimal("0.000001")


@dataclass(frozen=True)
class ExecutionCostModel:
    commission_rate: Decimal = Decimal("0.0003")
    minimum_commission: Decimal = Decimal("5")
    stamp_tax_rate: Decimal = Decimal("0.0005")
    slippage_bps: Decimal = Decimal("5")
    lot_size: int = 100

    def __post_init__(self) -> None:
        for name in ("commission_rate", "minimum_commission", "stamp_tax_rate", "slippage_bps"):
            value = Decimal(str(getattr(self, name)))
            if not value.is_finite() or value < 0:
                raise ValueError("交易成本参数必须是有限非负数")
            object.__setattr__(self, name, value)
        if self.slippage_bps >= 10000:
            raise ValueError("滑点必须小于10000基点")
        if isinstance(self.lot_size, bool) or not isinstance(self.lot_size, int) or self.lot_size <= 0:
            raise ValueError("交易单位必须为正整数")


@dataclass(frozen=True)
class ExecutionOrder:
    order_id: int
    signal_date: date
    execute_date: date
    symbol: str
    side: str
    requested_quantity: int
    quantity: int
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class ExecutionTrade:
    trade_id: int
    order_id: int
    trade_date: date
    symbol: str
    side: str
    quantity: int
    price: Decimal
    commission: Decimal
    tax: Decimal
    slippage: Decimal


@dataclass(frozen=True)
class PortfolioSnapshot:
    trade_date: date
    cash: Decimal
    total_value: Decimal | None
    position_count: int
    position_quantity: int
    daily_return: Decimal | None
    actual_turnover: Decimal


@dataclass
class ExecutionResult:
    orders: list[ExecutionOrder]
    trades: list[ExecutionTrade]
    snapshots: list[PortfolioSnapshot]
    positions: pd.DataFrame
    parameters: dict[str, object]


def _as_decimal(value: object, name: str) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{name}必须是有限正数")
    return result


def _floor_lot(quantity: Decimal, lot_size: int) -> int:
    if quantity <= 0:
        return 0
    return int(quantity.to_integral_value(rounding=ROUND_FLOOR)) // lot_size * lot_size


def _fill(costs: ExecutionCostModel, side: str, quantity: int, open_price: Decimal) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    rate = costs.slippage_bps / Decimal("10000")
    slippage = (open_price * rate).quantize(PRICE, rounding=ROUND_HALF_EVEN)
    execution_price = open_price + slippage if side == "BUY" else open_price - slippage
    turnover = (execution_price * quantity).quantize(MONEY, rounding=ROUND_HALF_EVEN)
    commission = max((turnover * costs.commission_rate).quantize(MONEY, rounding=ROUND_HALF_EVEN), costs.minimum_commission)
    tax = (turnover * costs.stamp_tax_rate).quantize(MONEY, rounding=ROUND_HALF_EVEN) if side == "SELL" else Decimal("0")
    cash_change = -(turnover + commission + tax) if side == "BUY" else turnover - commission - tax
    return execution_price, commission, tax, cash_change


def _validate_inputs(target: PortfolioResult, market: pd.DataFrame, initial_cash: Decimal) -> pd.DataFrame:
    required_market = {"symbol", "trade_date", "open", "close"}
    if not required_market.issubset(market.columns):
        raise ValueError("行情缺少symbol、trade_date、open或close")
    frame = market[list(required_market)].copy(deep=True)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    if frame["trade_date"].dt.tz is not None or not frame["trade_date"].eq(frame["trade_date"].dt.normalize()).all():
        raise ValueError("行情日期必须无时区且无日内时间")
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise ValueError("行情同股票同日重复")
    for col in ("open", "close"):
        raw = frame[col]
        numeric = pd.to_numeric(raw, errors="coerce")
        if (raw.notna() & numeric.isna()).any() or np.isinf(numeric).any():
            raise ValueError(f"{col}包含非法数值")
        frame[col] = numeric
    if (frame["open"].notna() & (frame["open"] <= 0)).any() or (frame["close"].notna() & (frame["close"] <= 0)).any():
        raise ValueError("行情价格必须为正数")
    if not target.rebalances.empty:
        if not {"signal_date", "execution_date"}.issubset(target.rebalances.columns):
            raise ValueError("调仓计划缺少日期")
    if target.targets.empty and not target.rebalances.empty:
        raise ValueError("存在调仓但目标表为空")
    initial_cash = _as_decimal(initial_cash, "初始资金")
    if initial_cash <= 0:
        raise ValueError("初始资金必须大于零")
    return frame.sort_values(["trade_date", "symbol"], kind="mergesort").reset_index(drop=True)


def execute_portfolio_plan(
    target: PortfolioResult,
    market: pd.DataFrame,
    *,
    initial_cash: Decimal = Decimal("100000"),
    costs: ExecutionCostModel | None = None,
) -> ExecutionResult:
    """执行第六阶段目标计划；执行日开盘成交，账户按收盘估值。

    本实现使用独立的多股票共享现金账户，不改变项目一的单股票引擎。
    先卖后买；买入数量按目标权重和可用现金向下取整到交易单位。
    """
    costs = costs or ExecutionCostModel()
    initial_cash = _as_decimal(initial_cash, "初始资金").quantize(MONEY)
    frame = _validate_inputs(target, market, initial_cash)
    prices = {(row.trade_date, str(row.symbol)): row for row in frame.itertuples(index=False)}
    all_dates = sorted(frame.trade_date.unique())
    plans = target.targets.copy(deep=True)
    if not plans.empty:
        plans["signal_date"] = pd.to_datetime(plans["signal_date"], errors="raise")
        plans["execution_date"] = pd.to_datetime(plans["execution_date"], errors="raise")
        if plans["execution_date"].le(plans["signal_date"]).any():
            raise ValueError("执行日必须晚于信号日")
    rebalance_by_date = {}
    for row in target.rebalances.itertuples(index=False):
        rebalance_by_date.setdefault(pd.Timestamp(row.execution_date), row)
    target_by_execution: dict[pd.Timestamp, dict[str, Decimal]] = {}
    signal_by_execution: dict[pd.Timestamp, pd.Timestamp] = {}
    for execution_date, block in plans.groupby("execution_date", sort=True):
        execution_ts = pd.Timestamp(execution_date)
        signal_dates = block["signal_date"].drop_duplicates().tolist()
        if len(signal_dates) != 1:
            raise ValueError("同一执行日必须对应唯一信号日")
        signal_by_execution[execution_ts] = pd.Timestamp(signal_dates[0])
        target_by_execution[execution_ts] = {str(row.symbol): Decimal(str(row.target_weight)) for row in block.itertuples(index=False)}
    cash = initial_cash
    holdings: dict[str, dict[str, object]] = {}
    orders: list[ExecutionOrder] = []
    trades: list[ExecutionTrade] = []
    snapshots: list[PortfolioSnapshot] = []
    order_id = trade_id = 0
    previous_value: Decimal | None = None
    last_turnover = Decimal("0")

    for day in all_dates:
        day_ts = pd.Timestamp(day)
        for position in holdings.values():
            if position["buy_date"] < day:
                position["sellable"] = int(position["quantity"])
        if day_ts in rebalance_by_date:
            signal_date = signal_by_execution.get(day_ts, day_ts).date()
            desired = target_by_execution.get(day_ts, {})
            desired = {symbol: weight for symbol, weight in desired.items() if symbol != "CASH" and weight > 0}
            close_for_value = {symbol: _as_decimal(prices[(day, symbol)].close, "收盘价") for symbol in holdings if (day, symbol) in prices and pd.notna(prices[(day, symbol)].close)}
            known_value = cash + sum(Decimal(str(pos["quantity"])) * close_for_value[symbol] for symbol, pos in holdings.items() if symbol in close_for_value)
            actual_turnover_money = Decimal("0")
            # 先卖出目标中降低或退出的持仓；缺开盘价时拒单，不修改持仓。
            for symbol in sorted(list(holdings)):
                pos = holdings[symbol]
                row = prices.get((day, symbol))
                open_value = None if row is None or pd.isna(row.open) else _as_decimal(row.open, "开盘价")
                desired_weight = desired.get(symbol, Decimal("0"))
                target_qty = 0 if known_value <= 0 or open_value is None else _floor_lot(known_value * desired_weight / open_value, costs.lot_size)
                sell_qty = max(0, int(pos["sellable"]) - target_qty)
                if sell_qty <= 0:
                    continue
                order_id += 1
                if open_value is None:
                    orders.append(ExecutionOrder(order_id, signal_date, pd.Timestamp(day).date(), symbol, "SELL", sell_qty, 0, "REJECTED", "缺少有效开盘价"))
                    continue
                execution_price, commission, tax, cash_change = _fill(costs, "SELL", sell_qty, open_value)
                cash = (cash + cash_change).quantize(MONEY)
                pos["quantity"] = int(pos["quantity"]) - sell_qty
                pos["sellable"] = int(pos["sellable"]) - sell_qty
                if pos["quantity"] == 0:
                    del holdings[symbol]
                orders.append(ExecutionOrder(order_id, signal_date, pd.Timestamp(day).date(), symbol, "SELL", sell_qty, sell_qty, "FILLED"))
                trade_id += 1
                trades.append(ExecutionTrade(trade_id, order_id, pd.Timestamp(day).date(), symbol, "SELL", sell_qty, execution_price, commission, tax, execution_price - open_value))
                actual_turnover_money += execution_price * sell_qty
            # 再按股票代码顺序买入，现金不足则减少数量。
            for symbol, weight in sorted(desired.items()):
                row = prices.get((day, symbol))
                open_value = None if row is None or pd.isna(row.open) else _as_decimal(row.open, "开盘价")
                current_qty = int(holdings.get(symbol, {}).get("quantity", 0))
                if open_value is None:
                    order_id += 1
                    orders.append(ExecutionOrder(order_id, signal_date, pd.Timestamp(day).date(), symbol, "BUY", 0, 0, "REJECTED", "缺少有效开盘价"))
                    continue
                target_qty = _floor_lot(known_value * weight / open_value, costs.lot_size)
                buy_qty = max(0, target_qty - current_qty)
                if buy_qty == 0:
                    continue
                affordable = 0
                high = buy_qty // costs.lot_size
                low = 0
                while low <= high:
                    mid = (low + high) // 2
                    qty = mid * costs.lot_size
                    if qty == 0 or cash + _fill(costs, "BUY", qty, open_value)[3] >= 0:
                        affordable = qty
                        low = mid + 1
                    else:
                        high = mid - 1
                order_id += 1
                if affordable == 0:
                    orders.append(ExecutionOrder(order_id, signal_date, pd.Timestamp(day).date(), symbol, "BUY", buy_qty, 0, "REJECTED", "资金不足以买入一手"))
                    continue
                execution_price, commission, tax, cash_change = _fill(costs, "BUY", affordable, open_value)
                cash = (cash + cash_change).quantize(MONEY)
                holdings.setdefault(symbol, {"quantity": 0, "sellable": 0, "buy_date": day, "average_cost": Decimal("0")})
                pos = holdings[symbol]
                pos["quantity"] = int(pos["quantity"]) + affordable
                pos["buy_date"] = day
                pos["sellable"] = int(pos["sellable"])
                orders.append(ExecutionOrder(order_id, signal_date, pd.Timestamp(day).date(), symbol, "BUY", buy_qty, affordable, "FILLED"))
                trade_id += 1
                trades.append(ExecutionTrade(trade_id, order_id, pd.Timestamp(day).date(), symbol, "BUY", affordable, execution_price, commission, tax, execution_price - open_value))
                actual_turnover_money += execution_price * affordable
            last_turnover = Decimal("0") if known_value <= 0 else (actual_turnover_money / known_value)
        close_values = {}
        total_value: Decimal | None = cash
        for symbol, pos in holdings.items():
            row = prices.get((day, symbol))
            if row is None or pd.isna(row.close):
                total_value = None
                continue
            close = _as_decimal(row.close, "收盘价")
            close_values[symbol] = close
            if total_value is not None:
                total_value += Decimal(str(pos["quantity"])) * close
        total_value = None if total_value is None else total_value.quantize(MONEY)
        daily_return = None if total_value is None or previous_value in (None, Decimal("0")) else total_value / previous_value - Decimal("1")
        snapshots.append(PortfolioSnapshot(pd.Timestamp(day).date(), cash.quantize(MONEY), total_value, len(holdings), sum(int(p["quantity"]) for p in holdings.values()), daily_return, last_turnover))
        if total_value is not None:
            previous_value = total_value
        last_turnover = Decimal("0")
    position_rows = [{"symbol": symbol, "quantity": int(pos["quantity"]), "sellable_quantity": int(pos["sellable"]), "buy_date": pos["buy_date"]} for symbol, pos in sorted(holdings.items())]
    return ExecutionResult(orders, trades, snapshots, pd.DataFrame(position_rows, columns=["symbol", "quantity", "sellable_quantity", "buy_date"]), {"initial_cash": str(initial_cash), "costs": {name: str(getattr(costs, name)) for name in ("commission_rate", "minimum_commission", "stamp_tax_rate", "slippage_bps", "lot_size")}, "execution": "next supplied market date open; sell before buy; shared cash; T+1", "actual_turnover": "executed turnover / pre-rebalance known account value"})
