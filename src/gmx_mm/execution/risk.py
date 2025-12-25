"""风险管理模块"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from ..config import Config
from ..data.models import Market, PoolStats, Position

logger = logging.getLogger(__name__)


@dataclass
class RiskAlert:
    """风险告警"""

    level: str  # "info" / "warning" / "critical"
    type: str  # "drawdown" / "imbalance" / "volatility" / "apy_drop"
    market_key: Optional[str]
    market_name: Optional[str]
    message: str
    value: float  # 触发值
    threshold: float  # 阈值
    timestamp: datetime = None
    acknowledged: bool = False

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

    @property
    def emoji(self) -> str:
        emojis = {
            "info": "ℹ️",
            "warning": "⚠️",
            "critical": "🚨",
        }
        return emojis.get(self.level, "📢")


class RiskManager:
    """
    风险管理器

    负责:
    1. 监控持仓风险
    2. 检测异常情况
    3. 触发告警
    4. 执行保护措施
    """

    def __init__(self, config: Config):
        self.config = config
        self.alerts: list[RiskAlert] = []
        self.position_history: dict[str, list[float]] = {}  # market_key -> [values]
        self.last_check: Optional[datetime] = None

    def check_all(
        self,
        positions: list[Position],
        markets: dict[str, Market],
        stats: dict[str, PoolStats],
    ) -> list[RiskAlert]:
        """
        执行全面风险检查

        Args:
            positions: 当前持仓列表
            markets: 市场信息 (market_key -> Market)
            stats: 池子统计 (market_key -> PoolStats)

        Returns:
            新产生的告警列表
        """
        new_alerts = []

        # 1. 检查回撤
        alerts = self._check_drawdown(positions)
        new_alerts.extend(alerts)

        # 2. 检查多空失衡
        alerts = self._check_oi_imbalance(positions, markets)
        new_alerts.extend(alerts)

        # 3. 检查 APY 变化
        alerts = self._check_apy_changes(positions, stats)
        new_alerts.extend(alerts)

        # 4. 检查仓位集中度
        alerts = self._check_concentration(positions)
        new_alerts.extend(alerts)

        # 记录检查时间
        self.last_check = datetime.utcnow()

        # 保存告警
        self.alerts.extend(new_alerts)

        # 记录持仓历史
        for pos in positions:
            if pos.market_key not in self.position_history:
                self.position_history[pos.market_key] = []
            self.position_history[pos.market_key].append(pos.value_usd)
            # 只保留最近 100 个数据点
            if len(self.position_history[pos.market_key]) > 100:
                self.position_history[pos.market_key] = self.position_history[pos.market_key][-100:]

        return new_alerts

    def _check_drawdown(self, positions: list[Position]) -> list[RiskAlert]:
        """检查回撤"""
        alerts = []
        max_drawdown = self.config.risk.max_drawdown_pct
        stop_loss = self.config.risk.stop_loss_pct

        for pos in positions:
            if pos.cost_basis > 0:
                pnl_pct = pos.pnl_pct

                if pnl_pct <= -stop_loss:
                    alerts.append(
                        RiskAlert(
                            level="critical",
                            type="stop_loss",
                            market_key=pos.market_key,
                            market_name=pos.name,
                            message=f"触发止损! 亏损 {abs(pnl_pct):.1f}%",
                            value=pnl_pct,
                            threshold=-stop_loss,
                        )
                    )
                elif pnl_pct <= -max_drawdown:
                    alerts.append(
                        RiskAlert(
                            level="warning",
                            type="drawdown",
                            market_key=pos.market_key,
                            market_name=pos.name,
                            message=f"回撤预警: 亏损 {abs(pnl_pct):.1f}%",
                            value=pnl_pct,
                            threshold=-max_drawdown,
                        )
                    )

        return alerts

    def _check_oi_imbalance(
        self, positions: list[Position], markets: dict[str, Market]
    ) -> list[RiskAlert]:
        """检查多空失衡"""
        alerts = []
        max_imbalance = self.config.risk.max_oi_imbalance

        for pos in positions:
            if pos.market_key in markets:
                market = markets[pos.market_key]
                imbalance = market.oi_imbalance

                if imbalance > max_imbalance:
                    # 判断哪边更多
                    side = "多头" if market.long_oi > market.short_oi else "空头"

                    alerts.append(
                        RiskAlert(
                            level="warning",
                            type="imbalance",
                            market_key=pos.market_key,
                            market_name=pos.name,
                            message=f"{side}偏重: 失衡比 {imbalance:.2f}",
                            value=imbalance,
                            threshold=max_imbalance,
                        )
                    )

        return alerts

    def _check_apy_changes(
        self, positions: list[Position], stats: dict[str, PoolStats]
    ) -> list[RiskAlert]:
        """检查 APY 大幅变化"""
        alerts = []
        apy_threshold = self.config.notifications.apy_change_threshold

        for pos in positions:
            if pos.market_key in stats:
                pool_stats = stats[pos.market_key]
                current_apy = pool_stats.apy
                min_apy = self.config.strategy.min_apy

                # APY 低于最低阈值
                if current_apy < min_apy:
                    alerts.append(
                        RiskAlert(
                            level="info",
                            type="apy_low",
                            market_key=pos.market_key,
                            market_name=pos.name,
                            message=f"APY 低于阈值: {current_apy:.1f}% < {min_apy}%",
                            value=current_apy,
                            threshold=min_apy,
                        )
                    )

        return alerts

    def _check_concentration(self, positions: list[Position]) -> list[RiskAlert]:
        """检查仓位集中度"""
        alerts = []
        max_single_pct = self.config.strategy.max_single_pool_pct

        total_value = sum(p.value_usd for p in positions)
        if total_value == 0:
            return alerts

        for pos in positions:
            pct = (pos.value_usd / total_value) * 100

            if pct > max_single_pct * 1.2:  # 超出 20% 告警
                alerts.append(
                    RiskAlert(
                        level="warning",
                        type="concentration",
                        market_key=pos.market_key,
                        market_name=pos.name,
                        message=f"仓位过于集中: {pct:.1f}% > {max_single_pct}%",
                        value=pct,
                        threshold=max_single_pct,
                    )
                )

        return alerts

    def should_emergency_exit(self, positions: list[Position]) -> bool:
        """判断是否需要紧急退出"""
        # 检查是否有触发止损的持仓
        stop_loss = self.config.risk.stop_loss_pct

        for pos in positions:
            if pos.cost_basis > 0 and pos.pnl_pct <= -stop_loss:
                logger.warning(f"紧急退出触发: {pos.name} 亏损 {abs(pos.pnl_pct):.1f}%")
                return True

        return False

    def get_active_alerts(self) -> list[RiskAlert]:
        """获取未确认的告警"""
        return [a for a in self.alerts if not a.acknowledged]

    def acknowledge_alert(self, index: int) -> bool:
        """确认告警"""
        if 0 <= index < len(self.alerts):
            self.alerts[index].acknowledged = True
            return True
        return False

    def get_risk_summary(self, positions: list[Position]) -> dict:
        """获取风险摘要"""
        total_value = sum(p.value_usd for p in positions)
        total_pnl = sum(p.unrealized_pnl for p in positions)

        # 计算整体回撤
        overall_pnl_pct = 0
        if total_value > 0:
            total_cost = sum(p.cost_basis for p in positions if p.cost_basis > 0)
            if total_cost > 0:
                overall_pnl_pct = (total_pnl / total_cost) * 100

        # 最大单仓位占比
        max_concentration = 0
        if total_value > 0:
            max_concentration = max((p.value_usd / total_value) * 100 for p in positions)

        return {
            "total_value_usd": total_value,
            "total_pnl_usd": total_pnl,
            "overall_pnl_pct": overall_pnl_pct,
            "max_concentration_pct": max_concentration,
            "active_alerts": len(self.get_active_alerts()),
            "risk_level": self._calculate_risk_level(positions),
        }

    def _calculate_risk_level(self, positions: list[Position]) -> str:
        """计算整体风险等级"""
        active_alerts = self.get_active_alerts()

        critical_count = len([a for a in active_alerts if a.level == "critical"])
        warning_count = len([a for a in active_alerts if a.level == "warning"])

        if critical_count > 0:
            return "危险"
        elif warning_count >= 3:
            return "较高"
        elif warning_count >= 1:
            return "中等"
        else:
            return "正常"
