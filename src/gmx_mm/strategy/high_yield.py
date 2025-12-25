"""高收益策略 - 追求最高 APY"""

from ..config import Config
from ..data.models import Market, PoolStats, PoolScore, Position
from .base import BaseStrategy, Signal


class HighYieldStrategy(BaseStrategy):
    """
    高收益策略

    特点:
    1. 优先追求最高 APY
    2. 接受较高风险
    3. 可能集中在单个高收益池
    4. 频繁调仓追逐热点
    """

    name = "high_yield"
    description = "高收益策略 - 追求最高 APY，接受较高风险"

    def __init__(self, config: Config):
        super().__init__(config)

        # 评分权重 - APY 占主导
        self.weights = {
            "apy": 0.60,
            "risk": 0.15,
            "liquidity": 0.15,
            "balance": 0.10,
        }

    def score_pool(self, market: Market, stats: PoolStats) -> PoolScore:
        """给池子打分"""
        score = PoolScore(
            market_key=market.market_key,
            name=market.name,
            stats=stats,
            market=market,
        )

        # 1. APY 评分 - 对高 APY 更敏感
        # 50% APY 为满分，超过也有加分
        score.apy_score = min(120, (stats.apy / 50) * 100)

        # 2. 风险评分 - 权重较低
        risk_raw = stats.calculate_risk_score(market)
        score.risk_score = (10 - risk_raw) * 10

        # 3. 流动性评分 - 阈值较低
        if market.pool_tvl >= 10_000_000:
            score.liquidity_score = 100
        else:
            score.liquidity_score = (market.pool_tvl / 10_000_000) * 100

        # 4. 多空平衡评分
        score.balance_score = (1 - market.oi_imbalance) * 100

        # 计算综合评分
        score.calculate_total_score(self.weights)

        return score

    def generate_signals(
        self,
        markets: list[Market],
        stats: dict[str, PoolStats],
        positions: list[Position],
        available_capital: float,
    ) -> list[Signal]:
        """生成交易信号"""
        signals = []

        # 过滤池子
        filtered_markets = self.filter_pools(markets)

        # 给所有池子打分
        scores = []
        for market in filtered_markets:
            if market.market_key in stats:
                pool_stats = stats[market.market_key]
                score = self.score_pool(market, pool_stats)
                scores.append(score)

        # 按 APY 排序
        scores.sort(key=lambda x: x.stats.apy if x.stats else 0, reverse=True)

        if not scores:
            return signals

        # 最高 APY 的池子
        best_pool = scores[0]
        best_apy = best_pool.stats.apy if best_pool.stats else 0

        # 当前持仓
        total_position = sum(p.value_usd for p in positions)
        strategy = self.config.strategy
        risk = self.config.risk

        # 1. 检查是否应该切换到更高收益池
        for position in positions:
            current_score = next(
                (s for s in scores if s.market_key == position.market_key),
                None,
            )

            if current_score is None:
                continue

            current_apy = current_score.stats.apy if current_score.stats else 0

            # 如果最高 APY 比当前高出 50%+，考虑切换
            if best_apy > current_apy * 1.5 and position.market_key != best_pool.market_key:
                signals.append(
                    Signal(
                        action="withdraw",
                        market_key=position.market_key,
                        market_name=position.name,
                        amount_usd=position.value_usd,
                        reason=f"切换到更高收益池 ({current_apy:.1f}% → {best_apy:.1f}%)",
                        priority=1,
                        confidence=0.8,
                    )
                )

                signals.append(
                    Signal(
                        action="deposit",
                        market_key=best_pool.market_key,
                        market_name=best_pool.name,
                        amount_usd=position.value_usd,
                        reason=f"最高 APY {best_apy:.1f}%",
                        priority=2,
                        confidence=0.8,
                    )
                )

        # 2. 新资金投入最高 APY 池
        if available_capital >= risk.min_position_usd:
            # 检查是否满足最低 APY 要求
            if best_apy >= strategy.min_apy:
                # 可投入金额
                current_in_best = next(
                    (p.value_usd for p in positions if p.market_key == best_pool.market_key),
                    0,
                )
                max_single = risk.max_position_usd * (strategy.max_single_pool_pct / 100)
                deposit_amount = min(available_capital, max_single - current_in_best)

                if deposit_amount >= risk.min_position_usd:
                    signals.append(
                        Signal(
                            action="deposit",
                            market_key=best_pool.market_key,
                            market_name=best_pool.name,
                            amount_usd=deposit_amount,
                            reason=f"最高 APY {best_apy:.1f}%",
                            priority=3,
                            confidence=best_pool.total_score / 100,
                        )
                    )

        # 3. 退出低于阈值的池子
        for position in positions:
            score = next(
                (s for s in scores if s.market_key == position.market_key),
                None,
            )

            if score and score.stats and score.stats.apy < strategy.min_apy:
                signals.append(
                    Signal(
                        action="withdraw",
                        market_key=position.market_key,
                        market_name=position.name,
                        amount_usd=position.value_usd,
                        reason=f"APY {score.stats.apy:.1f}% 低于阈值 {strategy.min_apy}%",
                        priority=2,
                    )
                )

        # 按优先级排序
        signals.sort(key=lambda x: x.priority)

        return signals
