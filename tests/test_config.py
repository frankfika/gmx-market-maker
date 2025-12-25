"""配置模块测试 (白盒测试)"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from gmx_mm.config import (
    Config,
    NetworkConfig,
    WalletConfig,
    StrategyConfig,
    RiskConfig,
    PoolsConfig,
)


class TestNetworkConfig:
    """网络配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = NetworkConfig()
        assert config.chain == "arbitrum"
        assert config.rpc_url == "https://arb1.arbitrum.io/rpc"

    def test_custom_values(self):
        """测试自定义值"""
        config = NetworkConfig(chain="avalanche", rpc_url="https://custom.rpc")
        assert config.chain == "avalanche"
        assert config.rpc_url == "https://custom.rpc"


class TestStrategyConfig:
    """策略配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = StrategyConfig()
        assert config.type == "balanced"
        assert config.min_apy == 10.0
        assert config.max_single_pool_pct == 30.0
        assert config.min_pools == 2
        assert config.max_pools == 5

    def test_custom_values(self):
        """测试自定义值"""
        config = StrategyConfig(
            type="high_yield",
            min_apy=20.0,
            target_apy=40.0,
            max_single_pool_pct=50.0,
        )
        assert config.type == "high_yield"
        assert config.min_apy == 20.0
        assert config.max_single_pool_pct == 50.0


class TestRiskConfig:
    """风险配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = RiskConfig()
        assert config.max_position_usd == 10000.0
        assert config.min_position_usd == 100.0
        assert config.max_drawdown_pct == 10.0
        assert config.stop_loss_pct == 15.0

    def test_custom_values(self):
        """测试自定义值"""
        config = RiskConfig(
            max_position_usd=50000.0,
            stop_loss_pct=20.0,
        )
        assert config.max_position_usd == 50000.0
        assert config.stop_loss_pct == 20.0


class TestPoolsConfig:
    """池子配置测试"""

    def test_default_whitelist(self):
        """测试默认白名单"""
        config = PoolsConfig()
        assert "ETH-USDC" in config.whitelist
        assert "BTC-USDC" in config.whitelist

    def test_custom_whitelist(self):
        """测试自定义白名单"""
        config = PoolsConfig(whitelist=["ARB-USDC", "LINK-USDC"])
        assert "ARB-USDC" in config.whitelist
        assert "ETH-USDC" not in config.whitelist

    def test_blacklist(self):
        """测试黑名单"""
        config = PoolsConfig(blacklist=["DOGE-USDC"])
        assert "DOGE-USDC" in config.blacklist


class TestConfig:
    """主配置类测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = Config()
        assert config.network.chain == "arbitrum"
        assert config.strategy.type == "balanced"
        assert config.risk.max_position_usd == 10000.0

    def test_load_from_yaml(self):
        """测试从 YAML 文件加载"""
        yaml_content = """
network:
  chain: avalanche
  rpc_url: https://custom.rpc

strategy:
  type: high_yield
  min_apy: 15.0

risk:
  max_position_usd: 50000
  stop_loss_pct: 20.0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            config = Config.load(f.name)

            assert config.network.chain == "avalanche"
            assert config.strategy.type == "high_yield"
            assert config.strategy.min_apy == 15.0
            assert config.risk.max_position_usd == 50000.0

            os.unlink(f.name)

    def test_load_from_env(self):
        """测试从环境变量加载"""
        os.environ["PRIVATE_KEY"] = "test_private_key"
        os.environ["ARBITRUM_RPC_URL"] = "https://env.rpc"

        config = Config.load()

        assert config.wallet.private_key == "test_private_key"
        assert config.network.rpc_url == "https://env.rpc"

        # 清理
        del os.environ["PRIVATE_KEY"]
        del os.environ["ARBITRUM_RPC_URL"]

    def test_validate_missing_private_key(self):
        """测试验证 - 缺少私钥"""
        config = Config()
        config.wallet.private_key = ""

        errors = config.validate()
        assert "PRIVATE_KEY 未设置" in errors

    def test_validate_invalid_apy(self):
        """测试验证 - 无效 APY"""
        config = Config()
        config.wallet.private_key = "test"
        config.strategy.min_apy = -5.0

        errors = config.validate()
        assert "min_apy 不能为负数" in errors

    def test_validate_invalid_position(self):
        """测试验证 - 无效仓位"""
        config = Config()
        config.wallet.private_key = "test"
        config.risk.max_position_usd = 0

        errors = config.validate()
        assert "max_position_usd 必须大于 0" in errors

    def test_validate_invalid_pool_pct(self):
        """测试验证 - 无效单池占比"""
        config = Config()
        config.wallet.private_key = "test"
        config.strategy.max_single_pool_pct = 150

        errors = config.validate()
        assert "max_single_pool_pct 必须在 0-100 之间" in errors

    def test_validate_success(self):
        """测试验证 - 成功"""
        config = Config()
        config.wallet.private_key = "test_key"

        errors = config.validate()
        assert len(errors) == 0
