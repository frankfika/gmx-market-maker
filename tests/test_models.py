"""数据模型测试 (白盒测试)"""

from datetime import datetime

import pytest

from gmx_mm.data.models import Market, PoolStats, Position, PoolScore


class TestMarket:
    """Market 模型测试"""

    def test_create_market(self):
        """测试创建市场"""
        market = Market(
            market_key="0x123",
            index_token="0xeth",
            long_token="0xeth",
            short_token="0xusdc",
            name="ETH-USDC",
        )

        assert market.market_key == "0x123"
        assert market.name == "ETH-USDC"
        assert market.pool_tvl == 0.0

    def test_oi_imbalance_zero(self):
        """测试 OI 失衡 - 零持仓"""
        market = Market(
            market_key="0x123",
            index_token="0xeth",
            long_token="0xeth",
            short_token="0xusdc",
            name="ETH-USDC",
            long_oi=0,
            short_oi=0,
        )

        assert market.oi_imbalance == 0

    def test_oi_imbalance_balanced(self):
        """测试 OI 失衡 - 平衡"""
        market = Market(
            market_key="0x123",
            index_token="0xeth",
            long_token="0xeth",
            short_token="0xusdc",
            name="ETH-USDC",
            long_oi=1000000,
            short_oi=1000000,
        )

        assert market.oi_imbalance == 0

    def test_oi_imbalance_long_heavy(self):
        """测试 OI 失衡 - 多头偏重"""
        market = Market(
            market_key="0x123",
            index_token="0xeth",
            long_token="0xeth",
            short_token="0xusdc",
            name="ETH-USDC",
            long_oi=800000,
            short_oi=200000,
        )

        # (800000 - 200000) / 1000000 = 0.6
        assert market.oi_imbalance == 0.6

    def test_oi_imbalance_short_heavy(self):
        """测试 OI 失衡 - 空头偏重"""
        market = Market(
            market_key="0x123",
            index_token="0xeth",
            long_token="0xeth",
            short_token="0xusdc",
            name="ETH-USDC",
            long_oi=300000,
            short_oi=700000,
        )

        # abs(300000 - 700000) / 1000000 = 0.4
        assert market.oi_imbalance == 0.4


class TestPoolStats:
    """PoolStats 模型测试"""

    def test_create_stats(self):
        """测试创建统计"""
        stats = PoolStats(
            market_key="0x123",
            name="ETH-USDC",
            apy=18.5,
            utilization=0.6,
        )

        assert stats.apy == 18.5
        assert stats.utilization == 0.6
        assert stats.updated_at is not None

    def test_risk_score_low_risk(self):
        """测试风险评分 - 低风险"""
        market = Market(
            market_key="0x123",
            index_token="0xeth",
            long_token="0xeth",
            short_token="0xusdc",
            name="ETH-USDC",
            pool_tvl=50_000_000,
            long_oi=500000,
            short_oi=500000,
        )

        stats = PoolStats(
            market_key="0x123",
            name="ETH-USDC",
            apy=15.0,
            utilization=0.5,
        )

        score = stats.calculate_risk_score(market)

        # 基础分 5 + 失衡 0 + TVL 充足 0 + 利用率正常 0 + APY 正常 0
        assert score == 5.0

    def test_risk_score_high_risk(self):
        """测试风险评分 - 高风险"""
        market = Market(
            market_key="0x123",
            index_token="0xeth",
            long_token="0xeth",
            short_token="0xusdc",
            name="ETH-USDC",
            pool_tvl=500_000,  # 低 TVL
            long_oi=900000,  # 高失衡
            short_oi=100000,
        )

        stats = PoolStats(
            market_key="0x123",
            name="ETH-USDC",
            apy=60.0,  # 超高 APY
            utilization=0.9,  # 高利用率
        )

        score = stats.calculate_risk_score(market)

        # 应该接近上限
        assert score > 8


class TestPosition:
    """Position 模型测试"""

    def test_create_position(self):
        """测试创建持仓"""
        pos = Position(
            market_key="0x123",
            name="ETH-USDC",
            gm_balance=100.0,
            value_usd=1500.0,
            cost_basis=1400.0,
        )

        assert pos.gm_balance == 100.0
        assert pos.value_usd == 1500.0

    def test_pnl_pct_profit(self):
        """测试收益率 - 盈利"""
        pos = Position(
            market_key="0x123",
            name="ETH-USDC",
            gm_balance=100.0,
            value_usd=1500.0,
            cost_basis=1000.0,
            unrealized_pnl=500.0,
        )

        assert pos.pnl_pct == 50.0  # 50% 收益

    def test_pnl_pct_loss(self):
        """测试收益率 - 亏损"""
        pos = Position(
            market_key="0x123",
            name="ETH-USDC",
            gm_balance=100.0,
            value_usd=800.0,
            cost_basis=1000.0,
            unrealized_pnl=-200.0,
        )

        assert pos.pnl_pct == -20.0  # 20% 亏损

    def test_pnl_pct_zero_cost(self):
        """测试收益率 - 零成本"""
        pos = Position(
            market_key="0x123",
            name="ETH-USDC",
            cost_basis=0,
        )

        assert pos.pnl_pct == 0

    def test_total_pnl(self):
        """测试总收益"""
        pos = Position(
            market_key="0x123",
            name="ETH-USDC",
            unrealized_pnl=100.0,
            realized_pnl=50.0,
            fees_earned=20.0,
        )

        assert pos.total_pnl == 170.0


class TestPoolScore:
    """PoolScore 模型测试"""

    def test_create_score(self):
        """测试创建评分"""
        score = PoolScore(
            market_key="0x123",
            name="ETH-USDC",
            apy_score=80.0,
            risk_score=70.0,
            liquidity_score=90.0,
            balance_score=85.0,
        )

        assert score.apy_score == 80.0
        assert score.total_score == 0  # 未计算

    def test_calculate_total_score_default_weights(self):
        """测试计算综合评分 - 默认权重"""
        score = PoolScore(
            market_key="0x123",
            name="ETH-USDC",
            apy_score=80.0,
            risk_score=70.0,
            liquidity_score=90.0,
            balance_score=85.0,
        )

        total = score.calculate_total_score()

        # 80*0.3 + 70*0.25 + 90*0.25 + 85*0.2 = 24 + 17.5 + 22.5 + 17 = 81
        assert total == 81.0

    def test_calculate_total_score_custom_weights(self):
        """测试计算综合评分 - 自定义权重"""
        score = PoolScore(
            market_key="0x123",
            name="ETH-USDC",
            apy_score=100.0,
            risk_score=50.0,
            liquidity_score=50.0,
            balance_score=50.0,
        )

        # APY 权重 60%
        custom_weights = {
            "apy": 0.6,
            "risk": 0.2,
            "liquidity": 0.1,
            "balance": 0.1,
        }

        total = score.calculate_total_score(custom_weights)

        # 100*0.6 + 50*0.2 + 50*0.1 + 50*0.1 = 60 + 10 + 5 + 5 = 80
        assert total == 80.0
