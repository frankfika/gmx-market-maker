"""配置管理模块"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv


@dataclass
class NetworkConfig:
    chain: str = "arbitrum"
    rpc_url: str = "https://arb1.arbitrum.io/rpc"


@dataclass
class WalletConfig:
    address: str = ""
    private_key: str = ""  # 从环境变量加载


@dataclass
class StrategyConfig:
    type: str = "balanced"
    min_apy: float = 10.0
    target_apy: float = 20.0
    max_single_pool_pct: float = 30.0
    min_pools: int = 2
    max_pools: int = 5
    rebalance_threshold: float = 5.0
    rebalance_interval: int = 86400


@dataclass
class RiskConfig:
    max_position_usd: float = 10000.0
    min_position_usd: float = 100.0
    max_drawdown_pct: float = 10.0
    stop_loss_pct: float = 15.0
    max_oi_imbalance: float = 0.3


@dataclass
class PoolsConfig:
    whitelist: list[str] = field(default_factory=lambda: ["ETH-USDC", "BTC-USDC"])
    blacklist: list[str] = field(default_factory=list)
    min_tvl: float = 1000000.0
    min_volume_24h: float = 100000.0


@dataclass
class ExecutionConfig:
    check_interval: int = 300
    gas_price_max_gwei: int = 50
    slippage_tolerance: float = 0.5


@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


@dataclass
class NotificationsConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    on_trade: bool = True
    on_error: bool = True
    daily_report: bool = True
    apy_change_threshold: float = 5.0


@dataclass
class Config:
    """主配置类"""

    network: NetworkConfig = field(default_factory=NetworkConfig)
    wallet: WalletConfig = field(default_factory=WalletConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    pools: PoolsConfig = field(default_factory=PoolsConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """加载配置"""
        # 加载环境变量
        load_dotenv()

        config = cls()

        # 从环境变量加载敏感信息
        config.wallet.private_key = os.getenv("PRIVATE_KEY", "")
        config.network.rpc_url = os.getenv("ARBITRUM_RPC_URL", config.network.rpc_url)
        config.notifications.telegram.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        config.notifications.telegram.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

        # 从 YAML 文件加载
        if config_path:
            config_file = Path(config_path)
        else:
            config_file = Path("config/config.yaml")

        if config_file.exists():
            with open(config_file) as f:
                yaml_config = yaml.safe_load(f)
                config._load_from_dict(yaml_config)

        return config

    def _load_from_dict(self, data: dict) -> None:
        """从字典加载配置"""
        if not data:
            return

        if "network" in data:
            self.network.chain = data["network"].get("chain", self.network.chain)
            self.network.rpc_url = data["network"].get("rpc_url", self.network.rpc_url)

        if "wallet" in data:
            self.wallet.address = data["wallet"].get("address", self.wallet.address)

        if "strategy" in data:
            s = data["strategy"]
            self.strategy.type = s.get("type", self.strategy.type)
            self.strategy.min_apy = s.get("min_apy", self.strategy.min_apy)
            self.strategy.target_apy = s.get("target_apy", self.strategy.target_apy)
            self.strategy.max_single_pool_pct = s.get(
                "max_single_pool_pct", self.strategy.max_single_pool_pct
            )
            self.strategy.min_pools = s.get("min_pools", self.strategy.min_pools)
            self.strategy.max_pools = s.get("max_pools", self.strategy.max_pools)
            self.strategy.rebalance_threshold = s.get(
                "rebalance_threshold", self.strategy.rebalance_threshold
            )

        if "risk" in data:
            r = data["risk"]
            self.risk.max_position_usd = r.get("max_position_usd", self.risk.max_position_usd)
            self.risk.min_position_usd = r.get("min_position_usd", self.risk.min_position_usd)
            self.risk.max_drawdown_pct = r.get("max_drawdown_pct", self.risk.max_drawdown_pct)
            self.risk.stop_loss_pct = r.get("stop_loss_pct", self.risk.stop_loss_pct)
            self.risk.max_oi_imbalance = r.get("max_oi_imbalance", self.risk.max_oi_imbalance)

        if "pools" in data:
            p = data["pools"]
            self.pools.whitelist = p.get("whitelist", self.pools.whitelist)
            self.pools.blacklist = p.get("blacklist", self.pools.blacklist)
            if "filters" in p:
                self.pools.min_tvl = p["filters"].get("min_tvl", self.pools.min_tvl)
                self.pools.min_volume_24h = p["filters"].get(
                    "min_volume_24h", self.pools.min_volume_24h
                )

        if "execution" in data:
            e = data["execution"]
            self.execution.check_interval = e.get("check_interval", self.execution.check_interval)
            self.execution.gas_price_max_gwei = e.get(
                "gas_price_max_gwei", self.execution.gas_price_max_gwei
            )
            self.execution.slippage_tolerance = e.get(
                "slippage_tolerance", self.execution.slippage_tolerance
            )

    def validate(self) -> list[str]:
        """验证配置，返回错误列表"""
        errors = []

        if not self.wallet.private_key:
            errors.append("PRIVATE_KEY 未设置")

        if self.strategy.min_apy < 0:
            errors.append("min_apy 不能为负数")

        if self.risk.max_position_usd <= 0:
            errors.append("max_position_usd 必须大于 0")

        if not (0 < self.strategy.max_single_pool_pct <= 100):
            errors.append("max_single_pool_pct 必须在 0-100 之间")

        return errors
