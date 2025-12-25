"""策略模块测试 (白盒测试)"""

import pytest

from gmx_mm.config import Config
from gmx_mm.data.models import Market, PoolStats, Position
from gmx_mm.strategy.base import BaseStrategy, Signal
from gmx_mm.strategy.balanced import BalancedStrategy
from gmx_mm.strategy.high_yield import HighYieldStrategy


class TestSignal:
    """Signal 测试"""

    def test_create_signal(self):
        """测试创建信号"""
        signal = Signal(
            action="deposit",
            market_key="0x123",
            market_name="ETH-USDC",
            amount_usd=1000.0,
            reason="高 APY",
        )

        assert signal.action == "deposit"
        assert signal.amount_usd == 1000.0
        assert signal.priority == 1
        assert signal.confidence == 0.5

    def test_signal_str(self):
        """测试信号字符串表示"""
        signal = Signal(
            action="withdraw",
            market_key="0x123",
            market_name="ETH-USDC",
            amount_usd=500.0,
            reason="APY 下降",
        )

        assert "WITHDRAW" in str(signal)
        assert "ETH-USDC" in str(signal)
        assert "500.00" in str(signal)


class TestBalancedStrategy:
    """平衡策略测试"""

    @pytest.fixture
    def config(self):
        """创建测试配置"""
        config = Config()
        config.strategy.type = "balanced"
        config.strategy.min_apy = 10.0
        config.strategy.max_single_pool_pct = 30.0
        config.risk.max_position_usd = 10000.0
        config.risk.min_position_usd = 100.0
        config.pools.whitelist = ["ETH-USDC", "BTC-USDC", "ARB-USDC"]
        return config

    @pytest.fixture
    def strategy(self, config):
        """创建策略实例"""
        return BalancedStrategy(config)

    @pytest.fixture
    def sample_markets(self):
        """创建样本市场"""
        return [
            Market(
                market_key="0x001",
                index_token="0xeth",
                long_token="0xeth",
                short_token="0xusdc",
                name="ETH-USDC",
                pool_tvl=50_000_000,
                long_oi=500000,
                short_oi=500000,
            ),
            Market(
                market_key="0x002",
                index_token="0xbtc",
                long_token="0xbtc",
                short_token="0xusdc",
                name="BTC-USDC",
                pool_tvl=40_000_000,
                long_oi=600000,
                short_oi=400000,
            ),
            Market(
                market_key="0x003",
                index_token="0xarb",
                long_token="0xarb",
                short_token="0xusdc",
                name="ARB-USDC",
                pool_tvl=10_000_000,
                long_oi=300000,
                short_oi=700000,
            ),
        ]

    @pytest.fixture
    def sample_stats(self):
        """创建样本统计"""
        return {
            "0x001": PoolStats(market_key="0x001", name="ETH-USDC", apy=18.5),
            "0x002": PoolStats(market_key="0x002", name="BTC-USDC", apy=15.2),
            "0x003": PoolStats(market_key="0x003", name="ARB-USDC", apy=24.3),
        }

    def test_score_pool(self, strategy, sample_markets, sample_stats):
        """测试池子评分"""
        market = sample_markets[0]  # ETH-USDC
        stats = sample_stats["0x001"]

        score = strategy.score_pool(market, stats)

        assert score.market_key == "0x001"
        assert score.name == "ETH-USDC"
        assert score.apy_score > 0
        assert score.liquidity_score > 0
        assert score.balance_score > 0
        assert score.total_score > 0

    def test_filter_pools_whitelist(self, strategy, sample_markets):
        """测试白名单过滤"""
        # 添加一个不在白名单的市场
        sample_markets.append(
            Market(
                market_key="0x999",
                index_token="0xdoge",
                long_token="0xdoge",
                short_token="0xusdc",
                name="DOGE-USDC",
            )
        )

        filtered = strategy.filter_pools(sample_markets)

        assert len(filtered) == 3
        assert all(m.name in ["ETH-USDC", "BTC-USDC", "ARB-USDC"] for m in filtered)

    def test_filter_pools_blacklist(self, config, sample_markets):
        """测试黑名单过滤"""
        config.pools.whitelist = []  # 清空白名单
        config.pools.blacklist = ["ARB-USDC"]

        strategy = BalancedStrategy(config)
        filtered = strategy.filter_pools(sample_markets)

        assert "ARB-USDC" not in [m.name for m in filtered]

    def test_generate_signals_new_investment(
        self, strategy, sample_markets, sample_stats
    ):
        """测试生成信号 - 新投资"""
        positions = []  # 无持仓
        available_capital = 1000.0

        signals = strategy.generate_signals(
            sample_markets, sample_stats, positions, available_capital
        )

        # 应该生成存款信号
        deposit_signals = [s for s in signals if s.action == "deposit"]
        assert len(deposit_signals) > 0

        # 总存款不超过可用资金
        total_deposit = sum(s.amount_usd for s in deposit_signals)
        assert total_deposit <= available_capital

    def test_generate_signals_low_apy_exit(
        self, strategy, sample_markets, sample_stats
    ):
        """测试生成信号 - 低 APY 退出"""
        # 修改 APY 低于阈值
        sample_stats["0x001"].apy = 5.0

        positions = [
            Position(
                market_key="0x001",
                name="ETH-USDC",
                value_usd=1000.0,
            )
        ]

        signals = strategy.generate_signals(sample_markets, sample_stats, positions, 0)

        # 应该生成退出信号
        withdraw_signals = [s for s in signals if s.action == "withdraw"]
        assert len(withdraw_signals) > 0
        assert withdraw_signals[0].market_key == "0x001"

    def test_check_risk_limits_pass(self, strategy):
        """测试风控检查 - 通过"""
        signal = Signal(
            action="deposit",
            market_key="0x001",
            market_name="ETH-USDC",
            amount_usd=1000.0,
            reason="test",
        )

        positions = []  # 无持仓

        result = strategy.check_risk_limits(signal, positions)
        assert result is None  # 通过

    def test_check_risk_limits_exceed_total(self, strategy):
        """测试风控检查 - 超出总仓位"""
        signal = Signal(
            action="deposit",
            market_key="0x001",
            market_name="ETH-USDC",
            amount_usd=5000.0,
            reason="test",
        )

        # 现有仓位已接近上限
        positions = [
            Position(market_key="0x002", name="BTC-USDC", value_usd=6000.0)
        ]

        result = strategy.check_risk_limits(signal, positions)
        assert result is not None
        assert "总仓位限制" in result

    def test_check_risk_limits_exceed_single(self, strategy):
        """测试风控检查 - 超出单池限制"""
        signal = Signal(
            action="deposit",
            market_key="0x001",
            market_name="ETH-USDC",
            amount_usd=2000.0,
            reason="test",
        )

        # 该池已有仓位
        positions = [
            Position(market_key="0x001", name="ETH-USDC", value_usd=2000.0)
        ]

        result = strategy.check_risk_limits(signal, positions)
        assert result is not None
        assert "单池限制" in result

    def test_check_risk_limits_below_min(self, strategy):
        """测试风控检查 - 低于最小仓位"""
        signal = Signal(
            action="deposit",
            market_key="0x001",
            market_name="ETH-USDC",
            amount_usd=50.0,  # 低于 100
            reason="test",
        )

        positions = []

        result = strategy.check_risk_limits(signal, positions)
        assert result is not None
        assert "最小仓位" in result


class TestHighYieldStrategy:
    """高收益策略测试"""

    @pytest.fixture
    def config(self):
        """创建测试配置"""
        config = Config()
        config.strategy.type = "high_yield"
        config.strategy.min_apy = 10.0
        config.risk.max_position_usd = 10000.0
        config.risk.min_position_usd = 100.0
        config.pools.whitelist = ["ETH-USDC", "BTC-USDC", "ARB-USDC"]
        return config

    @pytest.fixture
    def strategy(self, config):
        """创建策略实例"""
        return HighYieldStrategy(config)

    def test_apy_weight_high(self, strategy):
        """测试 APY 权重较高"""
        assert strategy.weights["apy"] == 0.60  # APY 占 60%

    def test_score_pool_high_apy(self, strategy):
        """测试评分 - 高 APY 得分更高"""
        market = Market(
            market_key="0x001",
            index_token="0xeth",
            long_token="0xeth",
            short_token="0xusdc",
            name="ETH-USDC",
            pool_tvl=10_000_000,
        )

        low_apy_stats = PoolStats(market_key="0x001", name="ETH-USDC", apy=10.0)
        high_apy_stats = PoolStats(market_key="0x001", name="ETH-USDC", apy=40.0)

        low_score = strategy.score_pool(market, low_apy_stats)
        high_score = strategy.score_pool(market, high_apy_stats)

        assert high_score.total_score > low_score.total_score

    def test_generate_signals_chase_high_apy(self, strategy):
        """测试信号生成 - 追逐高收益"""
        markets = [
            Market(
                market_key="0x001",
                index_token="0xeth",
                long_token="0xeth",
                short_token="0xusdc",
                name="ETH-USDC",
                pool_tvl=50_000_000,
            ),
            Market(
                market_key="0x002",
                index_token="0xarb",
                long_token="0xarb",
                short_token="0xusdc",
                name="ARB-USDC",
                pool_tvl=10_000_000,
            ),
        ]

        stats = {
            "0x001": PoolStats(market_key="0x001", name="ETH-USDC", apy=15.0),
            "0x002": PoolStats(market_key="0x002", name="ARB-USDC", apy=35.0),  # 更高
        }

        positions = []
        available_capital = 1000.0

        signals = strategy.generate_signals(markets, stats, positions, available_capital)

        deposit_signals = [s for s in signals if s.action == "deposit"]
        assert len(deposit_signals) > 0

        # 应该优先投入高 APY 池
        top_signal = deposit_signals[0]
        assert top_signal.market_name == "ARB-USDC"

    def test_generate_signals_switch_pools(self, strategy):
        """测试信号生成 - 切换到更高收益池"""
        markets = [
            Market(
                market_key="0x001",
                index_token="0xeth",
                long_token="0xeth",
                short_token="0xusdc",
                name="ETH-USDC",
                pool_tvl=50_000_000,
            ),
            Market(
                market_key="0x002",
                index_token="0xarb",
                long_token="0xarb",
                short_token="0xusdc",
                name="ARB-USDC",
                pool_tvl=10_000_000,
            ),
        ]

        stats = {
            "0x001": PoolStats(market_key="0x001", name="ETH-USDC", apy=10.0),  # 当前持仓
            "0x002": PoolStats(market_key="0x002", name="ARB-USDC", apy=40.0),  # 超过 1.5x
        }

        positions = [
            Position(market_key="0x001", name="ETH-USDC", value_usd=1000.0)
        ]

        signals = strategy.generate_signals(markets, stats, positions, 0)

        # 应该有退出当前池和进入新池的信号
        withdraw_signals = [s for s in signals if s.action == "withdraw"]
        deposit_signals = [s for s in signals if s.action == "deposit"]

        assert len(withdraw_signals) > 0
        assert len(deposit_signals) > 0
