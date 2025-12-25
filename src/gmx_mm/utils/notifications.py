"""通知模块"""

import logging
from typing import Optional

import requests

from ..config import Config

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram 通知器"""

    def __init__(self, config: Config):
        self.enabled = config.notifications.telegram.enabled
        self.bot_token = config.notifications.telegram.bot_token
        self.chat_id = config.notifications.telegram.chat_id

        if self.enabled and (not self.bot_token or not self.chat_id):
            logger.warning("Telegram 已启用但未配置 bot_token 或 chat_id")
            self.enabled = False

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """发送消息"""
        if not self.enabled:
            logger.debug(f"[Telegram 禁用] {message}")
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode,
            }

            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()

            logger.info("Telegram 消息已发送")
            return True

        except Exception as e:
            logger.error(f"Telegram 发送失败: {e}")
            return False

    def send_alert(
        self,
        title: str,
        content: str,
        level: str = "info",
    ) -> bool:
        """发送告警"""
        emoji = {
            "info": "ℹ️",
            "warning": "⚠️",
            "critical": "🚨",
            "success": "✅",
        }.get(level, "📢")

        message = f"""
{emoji} <b>{title}</b>

{content}

<i>GMX Market Maker Bot</i>
        """.strip()

        return self.send(message)

    def send_trade_notification(
        self,
        action: str,
        pool: str,
        amount: float,
        tx_hash: Optional[str] = None,
    ) -> bool:
        """发送交易通知"""
        emoji = "📥" if action == "deposit" else "📤"
        action_text = "存入" if action == "deposit" else "提取"

        message = f"""
{emoji} <b>交易执行</b>

<b>操作:</b> {action_text}
<b>池子:</b> {pool}
<b>金额:</b> ${amount:,.2f}
"""

        if tx_hash:
            message += f"\n<b>交易:</b> <a href='https://arbiscan.io/tx/{tx_hash}'>查看</a>"

        return self.send(message.strip())

    def send_daily_report(
        self,
        total_value: float,
        daily_pnl: float,
        positions_count: int,
    ) -> bool:
        """发送日报"""
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
        pnl_sign = "+" if daily_pnl >= 0 else ""

        message = f"""
📊 <b>每日报告</b>

💰 <b>总资产:</b> ${total_value:,.2f}
{pnl_emoji} <b>今日收益:</b> {pnl_sign}${daily_pnl:,.2f}
🏊 <b>持仓池数:</b> {positions_count}

<i>继续加油! 💪</i>
        """.strip()

        return self.send(message)
