"""风险管理模块测试 (白盒测试)"""

import pytest
from datetime import datetime

from gmx_mm.config import Config
from gmx_mm.data.models import Market, PoolStats, Position
from gmx_mm.execution.risk import RiskManager, RiskAlert


class TestRiskAlert:
    """风险告警测试"""

    def test_create_alert(self):
        """测试创建告警"""
        alert = RiskAlert(
            level="warning",
            type="drawdown",
            market_key="0x123",
            market_name="ETH-USDC",
            message="回撤预警",
            value=-8.0,
            threshold=-10.0,
        )

        assert alert.level == "warning"
        assert alert.type == "drawdown"
        assert alert.acknowledged is False
        assert alert.timestamp is not None

    def test_alert_emoji(self):
        """测试告警 emoji"""
        info_alert = RiskAlert(
            level="info", type="test", market_key=None, market_name=None,
            message="", value=0, threshold=0
        )
        warning_alert = RiskAlert(
            level="warning", type="test", market_key=None, market_name=None,
            message="", value=0, threshold=0
        )
        critical_alert = RiskAlert(
            level="critical", type="test", market_key=None, market_name=None,
            message="", value=0, threshold=0
        )

        assert info_alert.emoji == "ℹ️"
        assert warning_alert.emoji == "⚠️"
        assert critical_alert.emoji == "🚨"


class TestRiskManager:
    """风险管理器测试"""

    @pytest.fixture
    def config(self):
        """创建测试配置"""
        config = Config()
        config.risk.max_drawdown_pct = 10.0
        config.risk.stop_loss_pct = 15.0
        config.risk.max_oi_imbalance = 0.3
        config.strategy.max_single_pool_pct = 30.0
        config.notifications.apy_change_threshold = 5.0
        return config

    @pytest.fixture
    def risk_manager(self, config):
        """创建风险管理器"""
        return RiskManager(config)

    def test_check_drawdown_normal(self, risk_manager):
        """测试回撤检查 - 正常"""
        positions = [
            Position(
                market_key="0x001",
                name="ETH-USDC",
                value_usd=1000.0,
                cost_basis=1000.0,
                unrealized_pnl=0.0,
            )
        ]

        alerts = risk_manager._check_drawdown(positions)
        assert len(alerts) == 0

    def test_check_drawdown_warning(self, risk_manager):
        """测试回撤检查 - 预警"""
        positions = [
            Position(
                market_key="0x001",
                name="ETH-USDC",
                value_usd=890.0,
                cost_basis=1000.0,
                unrealized_pnl=-110.0,  # -11%
            )
        ]

        alerts = risk_manager._check_drawdown(positions)
        assert len(alerts) == 1
        assert alerts[0].level == "warning"
        assert alerts[0].type == "drawdown"

    def test_check_drawdown_stop_loss(self, risk_manager):
        """测试回撤检查 - 止损"""
        positions = [
            Position(
                market_key="0x001",
                name="ETH-USDC",
                value_usd=840.0,
                cost_basis=1000.0,
                unrealized_pnl=-160.0,  # -16%
            )
        ]

        alerts = risk_manager._check_drawdown(positions)
        assert len(alerts) == 1
        assert alerts[0].level == "critical"
        assert alerts[0].type == "stop_loss"

    def test_check_oi_imbalance_normal(self, risk_manager):
        """测试多空失衡检查 - 正常"""
        positions = [
            Position(market_key="0x001", name="ETH-USDC")
        ]
        markets = {
            "0x001": Market(
                market_key="0x001",
                index_token="0x",
                long_token="0x",
                short_token="0x",
                name="ETH-USDC",
                long_oi=500000,
                short_oi=500000,  # 平衡
            )
        }

        alerts = risk_manager._check_oi_imbalance(positions, markets)
        assert len(alerts) == 0

    def test_check_oi_imbalance_warning(self, risk_manager):
        """测试多空失衡检查 - 预警"""
        positions = [
            Position(market_key="0x001", name="ETH-USDC")
        ]
        markets = {
            "0x001": Market(
                market_key="0x001",
                index_token="0x",
                long_token="0x",
                short_token="0x",
                name="ETH-USDC",
                long_oi=800000,
                short_oi=200000,  # 多头偏重
            )
        }

        alerts = risk_manager._check_oi_imbalance(positions, markets)
        assert len(alerts) == 1
        assert alerts[0].type == "imbalance"
        assert "多头" in alerts[0].message

    def test_check_concentration_normal(self, risk_manager):
        """测试仓位集中度检查 - 正常"""
        # 最高占比 35%，低于 30%*1.2=36%
        positions = [
            Position(market_key="0x001", name="ETH-USDC", value_usd=350.0),
            Position(market_key="0x002", name="BTC-USDC", value_usd=350.0),
            Position(market_key="0x003", name="ARB-USDC", value_usd=300.0),
        ]

        alerts = risk_manager._check_concentration(positions)
        assert len(alerts) == 0  # 最高 35%，低于 30%*1.2=36%

    def test_check_concentration_warning(self, risk_manager):
        """测试仓位集中度检查 - 预警"""
        positions = [
            Position(market_key="0x001", name="ETH-USDC", value_usd=100.0),
            Position(market_key="0x002", name="BTC-USDC", value_usd=900.0),  # 90%
        ]

        alerts = risk_manager._check_concentration(positions)
        assert len(alerts) == 1
        assert alerts[0].type == "concentration"

    def test_check_all_multiple_alerts(self, risk_manager):
        """测试全面检查 - 多个告警"""
        positions = [
            Position(
                market_key="0x001",
                name="ETH-USDC",
                value_usd=840.0,
                cost_basis=1000.0,
                unrealized_pnl=-160.0,  # 止损触发
            )
        ]
        markets = {
            "0x001": Market(
                market_key="0x001",
                index_token="0x",
                long_token="0x",
                short_token="0x",
                name="ETH-USDC",
                long_oi=900000,
                short_oi=100000,  # 失衡
            )
        }
        stats = {
            "0x001": PoolStats(market_key="0x001", name="ETH-USDC", apy=5.0)  # 低于阈值
        }

        alerts = risk_manager.check_all(positions, markets, stats)

        # 应该有多个告警
        assert len(alerts) >= 2

    def test_should_emergency_exit_no(self, risk_manager):
        """测试紧急退出判断 - 否"""
        positions = [
            Position(
                market_key="0x001",
                name="ETH-USDC",
                value_usd=950.0,
                cost_basis=1000.0,
                unrealized_pnl=-50.0,  # -5%, 未触发止损
            )
        ]

        assert risk_manager.should_emergency_exit(positions) is False

    def test_should_emergency_exit_yes(self, risk_manager):
        """测试紧急退出判断 - 是"""
        positions = [
            Position(
                market_key="0x001",
                name="ETH-USDC",
                value_usd=840.0,
                cost_basis=1000.0,
                unrealized_pnl=-160.0,  # -16%, 超过止损线
            )
        ]

        assert risk_manager.should_emergency_exit(positions) is True

    def test_acknowledge_alert(self, risk_manager):
        """测试确认告警"""
        # 添加告警
        risk_manager.alerts.append(
            RiskAlert(
                level="warning",
                type="test",
                market_key=None,
                market_name=None,
                message="Test",
                value=0,
                threshold=0,
            )
        )

        assert len(risk_manager.get_active_alerts()) == 1

        # 确认
        result = risk_manager.acknowledge_alert(0)
        assert result is True
        assert len(risk_manager.get_active_alerts()) == 0

    def test_risk_summary(self, risk_manager):
        """测试风险摘要"""
        positions = [
            Position(
                market_key="0x001",
                name="ETH-USDC",
                value_usd=600.0,
                cost_basis=500.0,
                unrealized_pnl=100.0,
            ),
            Position(
                market_key="0x002",
                name="BTC-USDC",
                value_usd=400.0,
                cost_basis=450.0,
                unrealized_pnl=-50.0,
            ),
        ]

        summary = risk_manager.get_risk_summary(positions)

        assert summary["total_value_usd"] == 1000.0
        assert summary["total_pnl_usd"] == 50.0  # 100 - 50
        assert summary["max_concentration_pct"] == 60.0  # 600/1000
        assert summary["risk_level"] == "正常"

    def test_calculate_risk_level(self, risk_manager):
        """测试风险等级计算"""
        positions = []

        # 无告警
        assert risk_manager._calculate_risk_level(positions) == "正常"

        # 添加警告
        for i in range(3):
            risk_manager.alerts.append(
                RiskAlert(
                    level="warning", type="test", market_key=None, market_name=None,
                    message="", value=0, threshold=0
                )
            )

        assert risk_manager._calculate_risk_level(positions) == "较高"

        # 添加危险
        risk_manager.alerts.append(
            RiskAlert(
                level="critical", type="test", market_key=None, market_name=None,
                message="", value=0, threshold=0
            )
        )

        assert risk_manager._calculate_risk_level(positions) == "危险"
