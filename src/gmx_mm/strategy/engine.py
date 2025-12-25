"""策略执行引擎"""

import logging
from datetime import datetime
from typing import Optional

from ..config import Config
from ..data.fetcher import GMXDataFetcher
from ..data.models import Position
from .base import BaseStrategy, Signal
from .balanced import BalancedStrategy
from .high_yield import HighYieldStrategy

logger = logging.getLogger(__name__)


class StrategyEngine:
    """
    策略执行引擎

    负责:
    1. 加载和管理策略
    2. 定期运行策略逻辑
    3. 生成和过滤信号
    4. 调用执行器执行交易
    """

    def __init__(self, config: Config, fetcher: GMXDataFetcher):
        self.config = config
        self.fetcher = fetcher
        self.strategy: Optional[BaseStrategy] = None
        self.last_run: Optional[datetime] = None
        self.signals_history: list[Signal] = []

        # 加载策略
        self._load_strategy()

    def _load_strategy(self) -> None:
        """加载策略"""
        strategy_type = self.config.strategy.type

        strategies = {
            "balanced": BalancedStrategy,
            "high_yield": HighYieldStrategy,
        }

        if strategy_type not in strategies:
            raise ValueError(f"未知策略类型: {strategy_type}")

        self.strategy = strategies[strategy_type](self.config)
        logger.info(f"已加载策略: {self.strategy.name} - {self.strategy.description}")

    def run(self, available_capital: float = 0.0, dry_run: bool = True) -> list[Signal]:
        """
        运行策略

        Args:
            available_capital: 可用资金 (USD)
            dry_run: 是否模拟运行 (不执行交易)

        Returns:
            生成的信号列表
        """
        logger.info(f"开始运行策略 (dry_run={dry_run}, 可用资金=${available_capital:.2f})")

        # 1. 获取市场数据
        markets = self.fetcher.get_markets()
        logger.info(f"获取到 {len(markets)} 个市场")

        # 2. 获取池子统计
        stats = {}
        for market in markets:
            pool_stats = self.fetcher.get_pool_stats(market.market_key)
            if pool_stats:
                stats[market.market_key] = pool_stats

        logger.info(f"获取到 {len(stats)} 个池子的统计数据")

        # 3. 获取当前持仓
        positions = []
        if self.config.wallet.address:
            positions = self.fetcher.get_positions(self.config.wallet.address)
            logger.info(f"当前持仓: {len(positions)} 个池子")
            for pos in positions:
                logger.info(f"  - {pos.name}: {pos.gm_balance:.4f} GM (${pos.value_usd:.2f})")

        # 4. 生成信号
        signals = self.strategy.generate_signals(markets, stats, positions, available_capital)
        logger.info(f"生成 {len(signals)} 个信号")

        # 5. 风控过滤
        filtered_signals = []
        for signal in signals:
            rejection = self.strategy.check_risk_limits(signal, positions)
            if rejection:
                logger.warning(f"信号被拒绝: {signal} - {rejection}")
            else:
                filtered_signals.append(signal)
                logger.info(f"信号通过: {signal}")

        # 6. 执行 (如果不是模拟)
        if not dry_run and filtered_signals:
            self._execute_signals(filtered_signals)

        # 记录
        self.last_run = datetime.utcnow()
        self.signals_history.extend(filtered_signals)

        return filtered_signals

    def _execute_signals(self, signals: list[Signal]) -> None:
        """执行信号"""
        # TODO: 集成执行器
        for signal in signals:
            logger.info(f"执行信号: {signal}")

    def get_pool_rankings(self) -> list[dict]:
        """获取池子排名"""
        markets = self.fetcher.get_markets()
        filtered = self.strategy.filter_pools(markets)

        rankings = []
        for market in filtered:
            stats = self.fetcher.get_pool_stats(market.market_key)
            if stats:
                score = self.strategy.score_pool(market, stats)
                rankings.append(
                    {
                        "name": market.name,
                        "market_key": market.market_key,
                        "apy": stats.apy,
                        "tvl": market.pool_tvl,
                        "oi_imbalance": market.oi_imbalance,
                        "score": score.total_score,
                        "apy_score": score.apy_score,
                        "risk_score": score.risk_score,
                        "liquidity_score": score.liquidity_score,
                        "balance_score": score.balance_score,
                    }
                )

        rankings.sort(key=lambda x: x["score"], reverse=True)
        return rankings

    def get_status(self) -> dict:
        """获取引擎状态"""
        return {
            "strategy": self.strategy.name if self.strategy else None,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "signals_count": len(self.signals_history),
            "config": {
                "min_apy": self.config.strategy.min_apy,
                "max_position": self.config.risk.max_position_usd,
                "check_interval": self.config.execution.check_interval,
            },
        }
