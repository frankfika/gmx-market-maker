"""策略基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..config import Config
from ..data.models import Market, PoolStats, PoolScore, Position


@dataclass
class Signal:
    """交易信号"""

    action: str  # "deposit" / "withdraw" / "rebalance" / "hold"
    market_key: str
    market_name: str
    amount_usd: float  # 操作金额
    reason: str  # 原因说明
    priority: int = 1  # 优先级 (1最高)
    confidence: float = 0.5  # 置信度 (0-1)

    def __str__(self) -> str:
        return f"[{self.action.upper()}] {self.market_name}: ${self.amount_usd:.2f} ({self.reason})"


class BaseStrategy(ABC):
    """策略基类"""

    name: str = "base"
    description: str = "基础策略"

    def __init__(self, config: Config):
        self.config = config

    @abstractmethod
    def score_pool(self, market: Market, stats: PoolStats) -> PoolScore:
        """
        给池子打分

        Args:
            market: 市场信息
            stats: 池子统计

        Returns:
            PoolScore: 评分结果
        """
        pass

    @abstractmethod
    def generate_signals(
        self,
        markets: list[Market],
        stats: dict[str, PoolStats],
        positions: list[Position],
        available_capital: float,
    ) -> list[Signal]:
        """
        生成交易信号

        Args:
            markets: 所有市场
            stats: 池子统计 (market_key -> stats)
            positions: 当前持仓
            available_capital: 可用资金 (USD)

        Returns:
            list[Signal]: 交易信号列表
        """
        pass

    def filter_pools(self, markets: list[Market]) -> list[Market]:
        """过滤池子 (白名单/黑名单)"""
        pools_config = self.config.pools

        filtered = []
        for market in markets:
            # 检查白名单
            if pools_config.whitelist:
                if market.name not in pools_config.whitelist:
                    continue

            # 检查黑名单
            if market.name in pools_config.blacklist:
                continue

            filtered.append(market)

        return filtered

    def check_risk_limits(self, signal: Signal, positions: list[Position]) -> Optional[str]:
        """
        检查风控限制

        Returns:
            None 如果通过，否则返回拒绝原因
        """
        risk = self.config.risk
        strategy = self.config.strategy

        # 计算当前总仓位
        total_position = sum(p.value_usd for p in positions)

        if signal.action == "deposit":
            # 检查总仓位限制
            if total_position + signal.amount_usd > risk.max_position_usd:
                return f"超出总仓位限制 (${risk.max_position_usd})"

            # 检查单池仓位限制
            current_in_pool = next(
                (p.value_usd for p in positions if p.market_key == signal.market_key),
                0,
            )
            max_single = risk.max_position_usd * (strategy.max_single_pool_pct / 100)
            if current_in_pool + signal.amount_usd > max_single:
                return f"超出单池限制 (${max_single:.0f})"

            # 检查最小仓位
            if signal.amount_usd < risk.min_position_usd:
                return f"低于最小仓位 (${risk.min_position_usd})"

        return None
