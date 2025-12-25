#!/usr/bin/env python3
"""运行做市机器人 (定时任务版)"""

import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# 添加 src 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from apscheduler.schedulers.blocking import BlockingScheduler

from gmx_mm.config import Config
from gmx_mm.data.fetcher import GMXDataFetcher
from gmx_mm.strategy.engine import StrategyEngine
from gmx_mm.execution.risk import RiskManager
from gmx_mm.utils.notifications import TelegramNotifier

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bot.log"),
    ],
)
logger = logging.getLogger(__name__)

# 全局实例
config: Config = None
fetcher: GMXDataFetcher = None
engine: StrategyEngine = None
risk_manager: RiskManager = None
notifier: TelegramNotifier = None


def init():
    """初始化"""
    global config, fetcher, engine, risk_manager, notifier

    logger.info("初始化 GMX Market Maker Bot...")

    config = Config.load()

    # 验证配置
    errors = config.validate()
    if errors:
        logger.error(f"配置错误: {errors}")
        sys.exit(1)

    fetcher = GMXDataFetcher(config)
    engine = StrategyEngine(config, fetcher)
    risk_manager = RiskManager(config)
    notifier = TelegramNotifier(config)

    logger.info("初始化完成")


def run_strategy_job():
    """策略执行任务"""
    logger.info("=== 运行策略检查 ===")

    try:
        # 获取持仓
        positions = []
        if config.wallet.address:
            positions = fetcher.get_positions(config.wallet.address)

        # 计算可用资金 (这里简化处理，实际需要查询钱包余额)
        available_capital = 0

        # 运行策略
        signals = engine.run(
            available_capital=available_capital,
            dry_run=True,  # 默认模拟模式
        )

        if signals:
            logger.info(f"生成 {len(signals)} 个信号")
            for signal in signals:
                logger.info(f"  - {signal}")
        else:
            logger.info("无需调整")

    except Exception as e:
        logger.error(f"策略执行失败: {e}")
        notifier.send_alert("策略执行失败", str(e), level="critical")


def run_risk_check_job():
    """风险检查任务"""
    logger.info("=== 运行风险检查 ===")

    try:
        # 获取数据
        positions = []
        if config.wallet.address:
            positions = fetcher.get_positions(config.wallet.address)

        markets = {m.market_key: m for m in fetcher.get_markets()}
        stats = {}
        for market_key in markets:
            s = fetcher.get_pool_stats(market_key)
            if s:
                stats[market_key] = s

        # 检查风险
        alerts = risk_manager.check_all(positions, markets, stats)

        if alerts:
            logger.warning(f"发现 {len(alerts)} 个风险告警")
            for alert in alerts:
                logger.warning(f"  {alert.emoji} [{alert.level}] {alert.message}")
                notifier.send_alert(
                    f"风险告警 - {alert.type}",
                    alert.message,
                    level=alert.level,
                )
        else:
            logger.info("风险状态正常")

        # 检查是否需要紧急退出
        if risk_manager.should_emergency_exit(positions):
            logger.critical("触发紧急退出!")
            notifier.send_alert(
                "紧急退出触发",
                "止损线已触发，请立即检查持仓",
                level="critical",
            )

    except Exception as e:
        logger.error(f"风险检查失败: {e}")


def send_daily_report_job():
    """发送日报任务"""
    logger.info("=== 发送日报 ===")

    try:
        positions = []
        if config.wallet.address:
            positions = fetcher.get_positions(config.wallet.address)

        total_value = sum(p.value_usd for p in positions)
        daily_pnl = sum(p.unrealized_pnl for p in positions)

        notifier.send_daily_report(
            total_value=total_value,
            daily_pnl=daily_pnl,
            positions_count=len(positions),
        )

        logger.info("日报已发送")

    except Exception as e:
        logger.error(f"发送日报失败: {e}")


def main():
    """主函数"""
    init()

    # 创建调度器
    scheduler = BlockingScheduler()

    # 策略检查 - 每 5 分钟
    scheduler.add_job(
        run_strategy_job,
        "interval",
        minutes=config.execution.check_interval // 60 or 5,
        id="strategy_check",
    )

    # 风险检查 - 每 1 分钟
    scheduler.add_job(
        run_risk_check_job,
        "interval",
        minutes=1,
        id="risk_check",
    )

    # 日报 - 每天 UTC 0:00
    scheduler.add_job(
        send_daily_report_job,
        "cron",
        hour=0,
        minute=0,
        id="daily_report",
    )

    # 处理退出信号
    def signal_handler(signum, frame):
        logger.info("收到退出信号，正在关闭...")
        scheduler.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("🚀 GMX Market Maker Bot 已启动")
    logger.info(f"策略: {config.strategy.type}")
    logger.info(f"检查间隔: {config.execution.check_interval}s")

    # 立即运行一次
    run_strategy_job()
    run_risk_check_job()

    # 开始调度
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
