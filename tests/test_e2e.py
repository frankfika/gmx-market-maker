"""端到端测试 (黑盒测试)

这些测试模拟真实用户场景，不关心内部实现细节。
"""

import os
import tempfile
from unittest.mock import Mock, patch, MagicMock

import pytest

from gmx_mm.config import Config
from gmx_mm.data.models import Market, PoolStats, Position
from gmx_mm.strategy.engine import StrategyEngine
from gmx_mm.execution.risk import RiskManager


class MockDataFetcher:
    """模拟数据获取器"""

    def __init__(self, markets=None, positions=None):
        self._markets = markets or []
        self._positions = positions or []
        self._stats = {}

    def get_markets(self, force_refresh=False):
        return self._markets

    def get_pool_stats(self, market_key):
        return self._stats.get(market_key)

    def get_positions(self, address):
        return self._positions

    def set_stats(self, stats_dict):
        self._stats = stats_dict


class TestUserScenarios:
    """用户场景测试"""

    @pytest.fixture
    def mock_markets(self):
        """模拟市场数据"""
        return [
            Market(
                market_key="0x001",
                index_token="0xeth",
                long_token="0xeth",
                short_token="0xusdc",
                name="ETH-USDC",
                pool_tvl=50_000_000,
                gm_price=1.05,
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
                gm_price=1.03,
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
                gm_price=1.08,
                long_oi=300000,
                short_oi=700000,
            ),
        ]

    @pytest.fixture
    def mock_stats(self):
        """模拟池子统计"""
        return {
            "0x001": PoolStats(market_key="0x001", name="ETH-USDC", apy=18.5),
            "0x002": PoolStats(market_key="0x002", name="BTC-USDC", apy=15.2),
            "0x003": PoolStats(market_key="0x003", name="ARB-USDC", apy=24.3),
        }

    def test_scenario_new_user_first_investment(self, mock_markets, mock_stats):
        """
        场景: 新用户首次投资

        Given: 用户有 $1000 可用资金，无任何持仓
        When: 运行策略
        Then: 应该生成投资建议，分散到多个池子
        """
        # 配置
        config = Config()
        config.strategy.type = "balanced"
        config.strategy.min_apy = 10.0
        config.risk.max_position_usd = 10000.0
        config.pools.whitelist = ["ETH-USDC", "BTC-USDC", "ARB-USDC"]

        # 创建模拟数据获取器
        fetcher = MockDataFetcher(markets=mock_markets)
        fetcher.set_stats(mock_stats)

        # 运行策略
        engine = StrategyEngine(config, fetcher)
        signals = engine.run(available_capital=1000.0, dry_run=True)

        # 验证
        assert len(signals) > 0

        # 应该有存款信号
        deposit_signals = [s for s in signals if s.action == "deposit"]
        assert len(deposit_signals) > 0

        # 总投资不超过可用资金
        total_deposit = sum(s.amount_usd for s in deposit_signals)
        assert total_deposit <= 1000.0

        # 应该分散到多个池子
        pools = set(s.market_name for s in deposit_signals)
        assert len(pools) >= 2

    def test_scenario_exit_low_apy_pool(self, mock_markets, mock_stats):
        """
        场景: 池子 APY 下降，需要退出

        Given: 用户持有 ETH-USDC 池，APY 降到 5%
        When: 运行策略
        Then: 应该生成退出信号
        """
        config = Config()
        config.strategy.type = "balanced"
        config.strategy.min_apy = 10.0
        config.pools.whitelist = ["ETH-USDC", "BTC-USDC", "ARB-USDC"]
        config.wallet.address = "0xtest"  # 设置钱包地址以启用持仓获取

        # 创建低 APY 的统计数据
        low_apy_stats = {
            "0x001": PoolStats(market_key="0x001", name="ETH-USDC", apy=5.0),  # 低于阈值
            "0x002": PoolStats(market_key="0x002", name="BTC-USDC", apy=15.2),
            "0x003": PoolStats(market_key="0x003", name="ARB-USDC", apy=24.3),
        }

        # 用户已有持仓
        positions = [
            Position(market_key="0x001", name="ETH-USDC", value_usd=1000.0)
        ]

        fetcher = MockDataFetcher(markets=mock_markets, positions=positions)
        fetcher.set_stats(low_apy_stats)

        engine = StrategyEngine(config, fetcher)
        signals = engine.run(available_capital=0, dry_run=True)

        # 应该有退出信号
        withdraw_signals = [s for s in signals if s.action == "withdraw"]
        assert len(withdraw_signals) > 0
        assert withdraw_signals[0].market_key == "0x001"

    def test_scenario_risk_alert_triggered(self, mock_markets, mock_stats):
        """
        场景: 持仓亏损触发风险告警

        Given: 用户持仓亏损 12%
        When: 进行风险检查
        Then: 应该生成回撤预警
        """
        config = Config()
        config.risk.max_drawdown_pct = 10.0
        config.risk.stop_loss_pct = 15.0

        # 亏损持仓
        positions = [
            Position(
                market_key="0x001",
                name="ETH-USDC",
                value_usd=880.0,
                cost_basis=1000.0,
                unrealized_pnl=-120.0,  # -12%
            )
        ]

        markets = {m.market_key: m for m in mock_markets}

        risk_manager = RiskManager(config)
        alerts = risk_manager.check_all(positions, markets, mock_stats)

        # 应该有回撤预警
        assert len(alerts) > 0
        drawdown_alerts = [a for a in alerts if a.type == "drawdown"]
        assert len(drawdown_alerts) == 1
        assert drawdown_alerts[0].level == "warning"

    def test_scenario_stop_loss_triggered(self, mock_markets, mock_stats):
        """
        场景: 持仓亏损触发止损

        Given: 用户持仓亏损 18%
        When: 进行风险检查
        Then: 应该触发止损，建议紧急退出
        """
        config = Config()
        config.risk.stop_loss_pct = 15.0

        # 大额亏损
        positions = [
            Position(
                market_key="0x001",
                name="ETH-USDC",
                value_usd=820.0,
                cost_basis=1000.0,
                unrealized_pnl=-180.0,  # -18%
            )
        ]

        markets = {m.market_key: m for m in mock_markets}

        risk_manager = RiskManager(config)

        # 应该触发紧急退出
        should_exit = risk_manager.should_emergency_exit(positions)
        assert should_exit is True

        # 应该有止损告警
        alerts = risk_manager.check_all(positions, markets, mock_stats)
        stop_loss_alerts = [a for a in alerts if a.type == "stop_loss"]
        assert len(stop_loss_alerts) == 1
        assert stop_loss_alerts[0].level == "critical"

    def test_scenario_high_yield_strategy_chase_apy(self, mock_markets, mock_stats):
        """
        场景: 高收益策略追逐最高 APY

        Given: 用户使用高收益策略，有 $1000 可用
        When: 运行策略
        Then: 应该优先投入最高 APY 的池子
        """
        config = Config()
        config.strategy.type = "high_yield"
        config.strategy.min_apy = 10.0
        config.risk.max_position_usd = 10000.0
        config.pools.whitelist = ["ETH-USDC", "BTC-USDC", "ARB-USDC"]

        fetcher = MockDataFetcher(markets=mock_markets)
        fetcher.set_stats(mock_stats)

        engine = StrategyEngine(config, fetcher)
        signals = engine.run(available_capital=1000.0, dry_run=True)

        # 应该有存款信号
        deposit_signals = [s for s in signals if s.action == "deposit"]
        assert len(deposit_signals) > 0

        # 第一个应该是最高 APY 的 ARB-USDC (24.3%)
        assert deposit_signals[0].market_name == "ARB-USDC"

    def test_scenario_rebalance_concentrated_position(self, mock_markets, mock_stats):
        """
        场景: 仓位过于集中需要再平衡

        Given: 用户 70% 仓位在单个池子
        When: 进行风险检查
        Then: 应该产生集中度预警
        """
        config = Config()
        config.strategy.max_single_pool_pct = 30.0

        positions = [
            Position(market_key="0x001", name="ETH-USDC", value_usd=700.0),
            Position(market_key="0x002", name="BTC-USDC", value_usd=300.0),
        ]

        markets = {m.market_key: m for m in mock_markets}

        risk_manager = RiskManager(config)
        alerts = risk_manager.check_all(positions, markets, mock_stats)

        # 应该有集中度告警
        concentration_alerts = [a for a in alerts if a.type == "concentration"]
        assert len(concentration_alerts) == 1

    def test_scenario_oi_imbalance_warning(self, mock_markets, mock_stats):
        """
        场景: 多空严重失衡告警

        Given: 用户持有的池子多空失衡严重 (80%:20%)
        When: 进行风险检查
        Then: 应该产生失衡预警
        """
        config = Config()
        config.risk.max_oi_imbalance = 0.3

        # 修改市场数据为严重失衡
        mock_markets[0].long_oi = 800000
        mock_markets[0].short_oi = 200000

        positions = [
            Position(market_key="0x001", name="ETH-USDC", value_usd=1000.0)
        ]

        markets = {m.market_key: m for m in mock_markets}

        risk_manager = RiskManager(config)
        alerts = risk_manager.check_all(positions, markets, mock_stats)

        # 应该有失衡告警
        imbalance_alerts = [a for a in alerts if a.type == "imbalance"]
        assert len(imbalance_alerts) == 1
        assert "多头" in imbalance_alerts[0].message


class TestConfigurationScenarios:
    """配置场景测试"""

    def test_scenario_load_config_from_file(self):
        """
        场景: 从配置文件加载设置

        Given: 用户创建了配置文件
        When: 加载配置
        Then: 应该正确读取所有设置
        """
        yaml_content = """
network:
  chain: arbitrum
  rpc_url: https://arb1.arbitrum.io/rpc

strategy:
  type: balanced
  min_apy: 15.0
  max_single_pool_pct: 25.0

risk:
  max_position_usd: 50000
  stop_loss_pct: 20.0

pools:
  whitelist:
    - ETH-USDC
    - BTC-USDC
  blacklist:
    - DOGE-USDC
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            config = Config.load(f.name)

            assert config.network.chain == "arbitrum"
            assert config.strategy.min_apy == 15.0
            assert config.strategy.max_single_pool_pct == 25.0
            assert config.risk.max_position_usd == 50000
            assert "ETH-USDC" in config.pools.whitelist
            assert "DOGE-USDC" in config.pools.blacklist

            os.unlink(f.name)

    def test_scenario_validate_invalid_config(self):
        """
        场景: 验证无效配置

        Given: 用户配置了无效参数
        When: 验证配置
        Then: 应该返回错误列表
        """
        config = Config()
        config.wallet.private_key = ""  # 缺失
        config.strategy.min_apy = -10.0  # 负数
        config.risk.max_position_usd = 0  # 无效

        errors = config.validate()

        assert len(errors) >= 3
        assert any("PRIVATE_KEY" in e for e in errors)
        assert any("min_apy" in e for e in errors)
        assert any("max_position_usd" in e for e in errors)


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_markets(self):
        """测试空市场列表"""
        config = Config()
        config.strategy.type = "balanced"

        fetcher = MockDataFetcher(markets=[])
        engine = StrategyEngine(config, fetcher)

        signals = engine.run(available_capital=1000.0, dry_run=True)
        assert signals == []

    def test_zero_capital(self, ):
        """测试零可用资金"""
        config = Config()
        config.strategy.type = "balanced"
        config.pools.whitelist = ["ETH-USDC"]

        markets = [
            Market(
                market_key="0x001",
                index_token="0x",
                long_token="0x",
                short_token="0x",
                name="ETH-USDC",
                pool_tvl=50_000_000,
            )
        ]
        stats = {"0x001": PoolStats(market_key="0x001", name="ETH-USDC", apy=20.0)}

        fetcher = MockDataFetcher(markets=markets)
        fetcher.set_stats(stats)

        engine = StrategyEngine(config, fetcher)
        signals = engine.run(available_capital=0, dry_run=True)

        # 零资金不应生成存款信号
        deposit_signals = [s for s in signals if s.action == "deposit"]
        assert len(deposit_signals) == 0

    def test_all_pools_below_min_apy(self):
        """测试所有池子 APY 低于阈值"""
        config = Config()
        config.strategy.type = "balanced"
        config.strategy.min_apy = 30.0  # 高阈值
        config.pools.whitelist = ["ETH-USDC"]

        markets = [
            Market(
                market_key="0x001",
                index_token="0x",
                long_token="0x",
                short_token="0x",
                name="ETH-USDC",
                pool_tvl=50_000_000,
            )
        ]
        stats = {"0x001": PoolStats(market_key="0x001", name="ETH-USDC", apy=10.0)}

        fetcher = MockDataFetcher(markets=markets)
        fetcher.set_stats(stats)

        engine = StrategyEngine(config, fetcher)
        signals = engine.run(available_capital=1000.0, dry_run=True)

        # 不应生成存款信号
        deposit_signals = [s for s in signals if s.action == "deposit"]
        assert len(deposit_signals) == 0
