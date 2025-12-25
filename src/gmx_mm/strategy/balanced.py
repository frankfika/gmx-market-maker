"""平衡策略 - 综合考虑收益和风险"""

from ..config import Config
from ..data.models import Market, PoolStats, PoolScore, Position
from .base import BaseStrategy, Signal


class BalancedStrategy(BaseStrategy):
    """
    平衡策略

    特点:
    1. 综合考虑 APY、风险、流动性
    2. 优先选择多空平衡的池子
    3. 分散投资到多个池子
    4. 避免极端波动的标的
    """

    name = "balanced"
    description = "平衡策略 - 综合考虑收益和风险，分散投资"

    def __init__(self, config: Config):
        super().__init__(config)

        # 评分权重
        self.weights = {
            "apy": 0.30,  # APY 权重
            "risk": 0.25,  # 风险权重 (越低越好)
            "liquidity": 0.25,  # 流动性权重
            "balance": 0.20,  # 多空平衡权重
        }

    def score_pool(self, market: Market, stats: PoolStats) -> PoolScore:
        """给池子打分"""
        score = PoolScore(
            market_key=market.market_key,
            name=market.name,
            stats=stats,
            market=market,
        )

        # 1. APY 评分 (0-100)
        # 假设 30% APY 为满分
        score.apy_score = min(100, (stats.apy / 30) * 100)

        # 2. 风险评分 (转换为正向, 风险低=分数高)
        # risk_score 1-10, 转换为 0-100
        risk_raw = stats.calculate_risk_score(market)
        score.risk_score = (10 - risk_raw) * 10

        # 3. 流动性评分
        # TVL $50M 为满分
        if market.pool_tvl >= 50_000_000:
            score.liquidity_score = 100
        else:
            score.liquidity_score = (market.pool_tvl / 50_000_000) * 100

        # 4. 多空平衡评分
        # imbalance 0 为满分
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

        # 按综合评分排序
        scores.sort(key=lambda x: x.total_score, reverse=True)

        # 当前持仓的市场
        position_markets = {p.market_key for p in positions}
        total_position = sum(p.value_usd for p in positions)

        # 策略参数
        strategy = self.config.strategy
        risk = self.config.risk
        min_apy = strategy.min_apy
        max_pools = strategy.max_pools
        rebalance_threshold = strategy.rebalance_threshold

        # 1. 检查是否需要退出低评分池
        for position in positions:
            score = next(
                (s for s in scores if s.market_key == position.market_key),
                None,
            )

            if score is None:
                # 池子不在候选列表，可能被加入黑名单
                signals.append(
                    Signal(
                        action="withdraw",
                        market_key=position.market_key,
                        market_name=position.name,
                        amount_usd=position.value_usd,
                        reason="池子被过滤",
                        priority=1,
                    )
                )
                continue

            # APY 低于阈值
            if score.stats and score.stats.apy < min_apy:
                signals.append(
                    Signal(
                        action="withdraw",
                        market_key=position.market_key,
                        market_name=position.name,
                        amount_usd=position.value_usd,
                        reason=f"APY {score.stats.apy:.1f}% < {min_apy}%",
                        priority=2,
                    )
                )

        # 2. 计算目标分配
        if available_capital > 0:
            # 取前 N 个高分池
            top_pools = [s for s in scores if s.stats and s.stats.apy >= min_apy][:max_pools]

            if top_pools:
                # 按评分加权分配
                total_score = sum(s.total_score for s in top_pools)

                for score in top_pools:
                    # 计算目标仓位
                    weight = score.total_score / total_score
                    target_amount = available_capital * weight

                    # 限制单池仓位
                    max_single = risk.max_position_usd * (strategy.max_single_pool_pct / 100)
                    current_in_pool = next(
                        (p.value_usd for p in positions if p.market_key == score.market_key),
                        0,
                    )
                    target_amount = min(target_amount, max_single - current_in_pool)

                    if target_amount >= risk.min_position_usd:
                        signals.append(
                            Signal(
                                action="deposit",
                                market_key=score.market_key,
                                market_name=score.name,
                                amount_usd=target_amount,
                                reason=f"评分 {score.total_score:.1f}, APY {score.stats.apy:.1f}%",
                                priority=3,
                                confidence=score.total_score / 100,
                            )
                        )

        # 3. 检查再平衡需求
        if len(positions) >= 2 and not signals:
            # 计算当前分配偏差
            position_scores = []
            for pos in positions:
                score = next((s for s in scores if s.market_key == pos.market_key), None)
                if score:
                    position_scores.append((pos, score))

            if position_scores:
                # 计算目标分配
                total_current = sum(p.value_usd for p, _ in position_scores)
                total_score = sum(s.total_score for _, s in position_scores)

                for pos, score in position_scores:
                    target_pct = score.total_score / total_score
                    current_pct = pos.value_usd / total_current
                    deviation = abs(current_pct - target_pct) * 100

                    if deviation > rebalance_threshold:
                        if current_pct > target_pct:
                            # 需要减仓
                            reduce_amount = (current_pct - target_pct) * total_current
                            signals.append(
                                Signal(
                                    action="withdraw",
                                    market_key=pos.market_key,
                                    market_name=pos.name,
                                    amount_usd=reduce_amount,
                                    reason=f"再平衡: 偏差 {deviation:.1f}%",
                                    priority=4,
                                )
                            )

        # 按优先级排序
        signals.sort(key=lambda x: x.priority)

        return signals
