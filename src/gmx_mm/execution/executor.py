"""交易执行器"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractLogicError

from ..config import Config
from ..data.fetcher import ARBITRUM_CONTRACTS

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Order:
    """订单"""

    id: str
    order_type: str  # "deposit" / "withdraw"
    market_key: str
    market_name: str
    amount: float  # 代币数量
    amount_usd: float  # USD 价值
    status: OrderStatus = OrderStatus.PENDING
    tx_hash: Optional[str] = None
    gas_used: Optional[int] = None
    error: Optional[str] = None
    created_at: datetime = None
    executed_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


# GMX v2 合约 ABI (简化版)
EXCHANGE_ROUTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "receiver", "type": "address"},
                    {"name": "callbackContract", "type": "address"},
                    {"name": "uiFeeReceiver", "type": "address"},
                    {"name": "market", "type": "address"},
                    {"name": "initialLongToken", "type": "address"},
                    {"name": "initialShortToken", "type": "address"},
                    {"name": "longTokenSwapPath", "type": "address[]"},
                    {"name": "shortTokenSwapPath", "type": "address[]"},
                    {"name": "minMarketTokens", "type": "uint256"},
                    {"name": "shouldUnwrapNativeToken", "type": "bool"},
                    {"name": "executionFee", "type": "uint256"},
                    {"name": "callbackGasLimit", "type": "uint256"},
                ],
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "createDeposit",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [
            {
                "components": [
                    {"name": "receiver", "type": "address"},
                    {"name": "callbackContract", "type": "address"},
                    {"name": "uiFeeReceiver", "type": "address"},
                    {"name": "market", "type": "address"},
                    {"name": "longTokenSwapPath", "type": "address[]"},
                    {"name": "shortTokenSwapPath", "type": "address[]"},
                    {"name": "minLongTokenAmount", "type": "uint256"},
                    {"name": "minShortTokenAmount", "type": "uint256"},
                    {"name": "shouldUnwrapNativeToken", "type": "bool"},
                    {"name": "executionFee", "type": "uint256"},
                    {"name": "callbackGasLimit", "type": "uint256"},
                ],
                "name": "params",
                "type": "tuple",
            },
            {"name": "marketTokenAmount", "type": "uint256"},
        ],
        "name": "createWithdrawal",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [{"name": "token", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "sendTokens",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "sendWnt",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
]

# ERC20 ABI
ERC20_ABI = [
    {
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class TradeExecutor:
    """交易执行器"""

    def __init__(self, config: Config):
        self.config = config
        self.w3 = Web3(Web3.HTTPProvider(config.network.rpc_url))

        if not self.w3.is_connected():
            raise ConnectionError(f"无法连接到 RPC: {config.network.rpc_url}")

        # 初始化账户
        if config.wallet.private_key:
            self.account = Account.from_key(config.wallet.private_key)
            logger.info(f"已加载钱包: {self.account.address}")
        else:
            self.account = None
            logger.warning("未配置私钥，只能进行模拟交易")

        # 初始化合约
        self.exchange_router = self.w3.eth.contract(
            address=Web3.to_checksum_address(ARBITRUM_CONTRACTS["ExchangeRouter"]),
            abi=EXCHANGE_ROUTER_ABI,
        )
        self.deposit_vault = Web3.to_checksum_address(ARBITRUM_CONTRACTS["DepositVault"])
        self.withdrawal_vault = Web3.to_checksum_address(ARBITRUM_CONTRACTS["WithdrawalVault"])

        # 订单历史
        self.orders: list[Order] = []

    def deposit(
        self,
        market_key: str,
        market_name: str,
        long_token: str,
        short_token: str,
        long_amount: float = 0,
        short_amount: float = 0,
        slippage: float = 0.5,
        dry_run: bool = True,
    ) -> Order:
        """
        存入流动性

        Args:
            market_key: 市场地址
            market_name: 市场名称
            long_token: 多头代币地址
            short_token: 空头代币地址
            long_amount: 多头代币数量
            short_amount: 空头代币数量
            slippage: 滑点容忍度 (%)
            dry_run: 是否模拟

        Returns:
            Order: 订单对象
        """
        import uuid

        order = Order(
            id=str(uuid.uuid4())[:8],
            order_type="deposit",
            market_key=market_key,
            market_name=market_name,
            amount=long_amount + short_amount,
            amount_usd=0,  # TODO: 计算 USD 价值
        )

        if dry_run:
            logger.info(f"[模拟] 存入 {market_name}: {long_amount} long + {short_amount} short")
            order.status = OrderStatus.EXECUTED
            self.orders.append(order)
            return order

        if not self.account:
            order.status = OrderStatus.FAILED
            order.error = "未配置私钥"
            return order

        try:
            # 1. 检查并授权代币
            if long_amount > 0:
                self._ensure_allowance(long_token, self.deposit_vault, long_amount)

            if short_amount > 0:
                self._ensure_allowance(short_token, self.deposit_vault, short_amount)

            # 2. 构建交易参数
            execution_fee = self._calculate_execution_fee()

            params = {
                "receiver": self.account.address,
                "callbackContract": "0x0000000000000000000000000000000000000000",
                "uiFeeReceiver": "0x0000000000000000000000000000000000000000",
                "market": Web3.to_checksum_address(market_key),
                "initialLongToken": Web3.to_checksum_address(long_token),
                "initialShortToken": Web3.to_checksum_address(short_token),
                "longTokenSwapPath": [],
                "shortTokenSwapPath": [],
                "minMarketTokens": 0,  # TODO: 计算最小接收量
                "shouldUnwrapNativeToken": False,
                "executionFee": execution_fee,
                "callbackGasLimit": 0,
            }

            # 3. 发送代币到 Vault
            # TODO: 实现 multicall 批量发送

            # 4. 创建存款订单
            tx = self.exchange_router.functions.createDeposit(params).build_transaction(
                {
                    "from": self.account.address,
                    "value": execution_fee,
                    "nonce": self.w3.eth.get_transaction_count(self.account.address),
                    "gas": 500000,
                    "maxFeePerGas": self.w3.eth.gas_price * 2,
                    "maxPriorityFeePerGas": self.w3.to_wei(0.1, "gwei"),
                }
            )

            # 5. 签名并发送
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.config.wallet.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            order.tx_hash = tx_hash.hex()
            order.status = OrderStatus.SUBMITTED

            logger.info(f"存款订单已提交: {order.tx_hash}")

            # 6. 等待确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt["status"] == 1:
                order.status = OrderStatus.EXECUTED
                order.gas_used = receipt["gasUsed"]
                order.executed_at = datetime.utcnow()
                logger.info(f"存款订单已执行: {order.id}")
            else:
                order.status = OrderStatus.FAILED
                order.error = "交易执行失败"

        except ContractLogicError as e:
            order.status = OrderStatus.FAILED
            order.error = f"合约错误: {str(e)}"
            logger.error(f"存款失败: {e}")

        except Exception as e:
            order.status = OrderStatus.FAILED
            order.error = str(e)
            logger.error(f"存款失败: {e}")

        self.orders.append(order)
        return order

    def withdraw(
        self,
        market_key: str,
        market_name: str,
        gm_amount: float,
        long_token: str,
        short_token: str,
        slippage: float = 0.5,
        dry_run: bool = True,
    ) -> Order:
        """
        提取流动性

        Args:
            market_key: 市场地址
            market_name: 市场名称
            gm_amount: GM 代币数量
            long_token: 多头代币地址
            short_token: 空头代币地址
            slippage: 滑点容忍度 (%)
            dry_run: 是否模拟

        Returns:
            Order: 订单对象
        """
        import uuid

        order = Order(
            id=str(uuid.uuid4())[:8],
            order_type="withdraw",
            market_key=market_key,
            market_name=market_name,
            amount=gm_amount,
            amount_usd=0,
        )

        if dry_run:
            logger.info(f"[模拟] 提取 {market_name}: {gm_amount} GM")
            order.status = OrderStatus.EXECUTED
            self.orders.append(order)
            return order

        if not self.account:
            order.status = OrderStatus.FAILED
            order.error = "未配置私钥"
            return order

        try:
            # 1. 授权 GM 代币
            self._ensure_allowance(market_key, self.withdrawal_vault, gm_amount)

            # 2. 构建参数
            execution_fee = self._calculate_execution_fee()
            gm_amount_wei = int(gm_amount * 10**18)

            params = {
                "receiver": self.account.address,
                "callbackContract": "0x0000000000000000000000000000000000000000",
                "uiFeeReceiver": "0x0000000000000000000000000000000000000000",
                "market": Web3.to_checksum_address(market_key),
                "longTokenSwapPath": [],
                "shortTokenSwapPath": [],
                "minLongTokenAmount": 0,
                "minShortTokenAmount": 0,
                "shouldUnwrapNativeToken": False,
                "executionFee": execution_fee,
                "callbackGasLimit": 0,
            }

            # 3. 发送 GM 代币到 Vault
            # TODO: 实现 multicall

            # 4. 创建提款订单
            tx = self.exchange_router.functions.createWithdrawal(
                params, gm_amount_wei
            ).build_transaction(
                {
                    "from": self.account.address,
                    "value": execution_fee,
                    "nonce": self.w3.eth.get_transaction_count(self.account.address),
                    "gas": 500000,
                    "maxFeePerGas": self.w3.eth.gas_price * 2,
                    "maxPriorityFeePerGas": self.w3.to_wei(0.1, "gwei"),
                }
            )

            signed_tx = self.w3.eth.account.sign_transaction(tx, self.config.wallet.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            order.tx_hash = tx_hash.hex()
            order.status = OrderStatus.SUBMITTED

            logger.info(f"提款订单已提交: {order.tx_hash}")

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt["status"] == 1:
                order.status = OrderStatus.EXECUTED
                order.gas_used = receipt["gasUsed"]
                order.executed_at = datetime.utcnow()
            else:
                order.status = OrderStatus.FAILED
                order.error = "交易执行失败"

        except Exception as e:
            order.status = OrderStatus.FAILED
            order.error = str(e)
            logger.error(f"提款失败: {e}")

        self.orders.append(order)
        return order

    def _ensure_allowance(self, token: str, spender: str, amount: float) -> None:
        """确保代币授权足够"""
        token_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token),
            abi=ERC20_ABI,
        )

        decimals = token_contract.functions.decimals().call()
        amount_wei = int(amount * 10**decimals)

        current_allowance = token_contract.functions.allowance(
            self.account.address,
            Web3.to_checksum_address(spender),
        ).call()

        if current_allowance < amount_wei:
            logger.info(f"授权 {token} 到 {spender}")

            tx = token_contract.functions.approve(
                Web3.to_checksum_address(spender),
                amount_wei,
            ).build_transaction(
                {
                    "from": self.account.address,
                    "nonce": self.w3.eth.get_transaction_count(self.account.address),
                    "gas": 100000,
                    "maxFeePerGas": self.w3.eth.gas_price * 2,
                    "maxPriorityFeePerGas": self.w3.to_wei(0.1, "gwei"),
                }
            )

            signed_tx = self.w3.eth.account.sign_transaction(tx, self.config.wallet.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

    def _calculate_execution_fee(self) -> int:
        """计算执行费用"""
        # 估算 keeper 执行需要的 gas
        gas_limit = 1_000_000
        gas_price = self.w3.eth.gas_price
        return gas_limit * gas_price

    def get_order_history(self) -> list[Order]:
        """获取订单历史"""
        return self.orders

    def get_pending_orders(self) -> list[Order]:
        """获取待处理订单"""
        return [o for o in self.orders if o.status in [OrderStatus.PENDING, OrderStatus.SUBMITTED]]
