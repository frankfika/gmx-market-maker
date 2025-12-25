"""命令行界面"""

import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich import box

from .config import Config
from .data.fetcher import GMXDataFetcher
from .strategy.engine import StrategyEngine
from .execution.executor import TradeExecutor
from .execution.risk import RiskManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

console = Console()


def print_banner():
    """打印启动横幅"""
    banner = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║     ██████╗ ███╗   ███╗██╗  ██╗    ███╗   ███╗███╗   ███╗    ║
║    ██╔════╝ ████╗ ████║╚██╗██╔╝    ████╗ ████║████╗ ████║    ║
║    ██║  ███╗██╔████╔██║ ╚███╔╝     ██╔████╔██║██╔████╔██║    ║
║    ██║   ██║██║╚██╔╝██║ ██╔██╗     ██║╚██╔╝██║██║╚██╔╝██║    ║
║    ╚██████╔╝██║ ╚═╝ ██║██╔╝ ██╗    ██║ ╚═╝ ██║██║ ╚═╝ ██║    ║
║     ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝    ╚═╝     ╚═╝╚═╝     ╚═╝    ║
║                                                               ║
║            GMX v2 Market Making Bot v0.1.0                    ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
    """
    console.print(banner, style="bold cyan")


@click.group()
@click.option("--config", "-c", type=click.Path(), help="配置文件路径")
@click.option("--debug", is_flag=True, help="调试模式")
@click.pass_context
def cli(ctx, config, debug):
    """GMX v2 做市策略机器人"""
    ctx.ensure_object(dict)

    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 加载配置
    ctx.obj["config"] = Config.load(config)


@cli.command()
@click.pass_context
def info(ctx):
    """显示系统信息"""
    print_banner()

    config = ctx.obj["config"]

    info_table = Table(title="系统配置", box=box.ROUNDED)
    info_table.add_column("项目", style="cyan")
    info_table.add_column("值", style="green")

    info_table.add_row("网络", config.network.chain)
    info_table.add_row("RPC", config.network.rpc_url[:50] + "...")
    info_table.add_row("策略", config.strategy.type)
    info_table.add_row("最低 APY", f"{config.strategy.min_apy}%")
    info_table.add_row("最大仓位", f"${config.risk.max_position_usd:,.0f}")
    info_table.add_row("单池上限", f"{config.strategy.max_single_pool_pct}%")

    wallet_status = "✅ 已配置" if config.wallet.private_key else "❌ 未配置"
    info_table.add_row("钱包", wallet_status)

    console.print(info_table)


@cli.command()
@click.pass_context
def pools(ctx):
    """查看池子排名"""
    config = ctx.obj["config"]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description="获取市场数据...", total=None)

        try:
            fetcher = GMXDataFetcher(config)
            markets = fetcher.get_markets()
        except Exception as e:
            console.print(f"[red]错误: {e}[/red]")
            return

    # 创建表格
    table = Table(
        title="🏊 GMX v2 Pool Rankings",
        box=box.DOUBLE_EDGE,
        header_style="bold magenta",
    )

    table.add_column("#", style="dim", width=3)
    table.add_column("Pool", style="cyan", width=12)
    table.add_column("GM Price", justify="right", style="green")
    table.add_column("TVL", justify="right")
    table.add_column("Long", justify="right", style="green")
    table.add_column("Short", justify="right", style="red")
    table.add_column("OI Balance", justify="right")

    for i, market in enumerate(markets[:15], 1):
        stats = fetcher.get_pool_stats(market.market_key)

        # 计算 OI 平衡指示器
        imbalance = market.oi_imbalance
        if imbalance < 0.1:
            balance_indicator = "🟢 均衡"
        elif imbalance < 0.3:
            balance_indicator = "🟡 偏移"
        else:
            balance_indicator = "🔴 失衡"

        table.add_row(
            str(i),
            market.name,
            f"${market.gm_price:.4f}" if market.gm_price else "-",
            f"${market.pool_tvl / 1e6:.1f}M" if market.pool_tvl else "-",
            f"${market.long_oi / 1e6:.1f}M" if market.long_oi else "-",
            f"${market.short_oi / 1e6:.1f}M" if market.short_oi else "-",
            balance_indicator,
        )

    console.print()
    console.print(table)
    console.print()


@cli.command()
@click.pass_context
def positions(ctx):
    """查看当前持仓"""
    config = ctx.obj["config"]

    if not config.wallet.address:
        console.print("[yellow]请先配置钱包地址[/yellow]")
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description="获取持仓数据...", total=None)

        try:
            fetcher = GMXDataFetcher(config)
            pos_list = fetcher.get_positions(config.wallet.address)
        except Exception as e:
            console.print(f"[red]错误: {e}[/red]")
            return

    if not pos_list:
        console.print(Panel("暂无持仓", title="📊 持仓", border_style="yellow"))
        return

    # 创建表格
    table = Table(title="📊 当前持仓", box=box.ROUNDED)
    table.add_column("Pool", style="cyan")
    table.add_column("GM 数量", justify="right")
    table.add_column("价值 (USD)", justify="right", style="green")
    table.add_column("收益", justify="right")

    total_value = 0
    total_pnl = 0

    for pos in pos_list:
        pnl_style = "green" if pos.unrealized_pnl >= 0 else "red"
        pnl_text = f"+${pos.unrealized_pnl:.2f}" if pos.unrealized_pnl >= 0 else f"-${abs(pos.unrealized_pnl):.2f}"

        table.add_row(
            pos.name,
            f"{pos.gm_balance:.4f}",
            f"${pos.value_usd:,.2f}",
            Text(pnl_text, style=pnl_style),
        )
        total_value += pos.value_usd
        total_pnl += pos.unrealized_pnl

    # 汇总行
    table.add_section()
    pnl_style = "green" if total_pnl >= 0 else "red"
    table.add_row(
        "[bold]总计[/bold]",
        "",
        f"[bold]${total_value:,.2f}[/bold]",
        Text(f"{'+' if total_pnl >= 0 else ''}{total_pnl:.2f}", style=f"bold {pnl_style}"),
    )

    console.print()
    console.print(table)
    console.print()


@cli.command()
@click.option("--capital", "-c", type=float, default=0, help="可用资金 (USD)")
@click.option("--execute", is_flag=True, help="执行交易 (默认模拟)")
@click.pass_context
def run(ctx, capital, execute):
    """运行策略"""
    config = ctx.obj["config"]
    dry_run = not execute

    console.print()
    if dry_run:
        console.print(Panel("🔬 模拟模式 - 不会执行真实交易", border_style="yellow"))
    else:
        console.print(Panel("⚡ 执行模式 - 将执行真实交易!", border_style="red"))
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(description="初始化...", total=None)

        try:
            fetcher = GMXDataFetcher(config)
            progress.update(task, description="加载策略...")

            engine = StrategyEngine(config, fetcher)
            progress.update(task, description="运行策略...")

            signals = engine.run(available_capital=capital, dry_run=dry_run)
        except Exception as e:
            console.print(f"[red]错误: {e}[/red]")
            return

    if not signals:
        console.print(Panel("✅ 无需调整", title="策略结果", border_style="green"))
        return

    # 显示信号
    table = Table(title="📝 策略信号", box=box.ROUNDED)
    table.add_column("操作", style="bold")
    table.add_column("池子", style="cyan")
    table.add_column("金额", justify="right", style="green")
    table.add_column("原因")
    table.add_column("置信度", justify="right")

    for signal in signals:
        action_style = "green" if signal.action == "deposit" else "red"
        table.add_row(
            Text(signal.action.upper(), style=action_style),
            signal.market_name,
            f"${signal.amount_usd:,.2f}",
            signal.reason,
            f"{signal.confidence * 100:.0f}%",
        )

    console.print()
    console.print(table)
    console.print()


@cli.command()
@click.pass_context
def alerts(ctx):
    """查看风险告警"""
    config = ctx.obj["config"]

    try:
        fetcher = GMXDataFetcher(config)
        risk_manager = RiskManager(config)

        # 获取持仓
        positions = []
        if config.wallet.address:
            positions = fetcher.get_positions(config.wallet.address)

        # 获取市场数据
        markets = {m.market_key: m for m in fetcher.get_markets()}
        stats = {}
        for market_key in markets:
            s = fetcher.get_pool_stats(market_key)
            if s:
                stats[market_key] = s

        # 检查风险
        new_alerts = risk_manager.check_all(positions, markets, stats)

    except Exception as e:
        console.print(f"[red]错误: {e}[/red]")
        return

    active_alerts = risk_manager.get_active_alerts()

    if not active_alerts:
        console.print(Panel("✅ 无告警", title="🔔 风险告警", border_style="green"))
        return

    table = Table(title="🔔 风险告警", box=box.ROUNDED)
    table.add_column("级别", width=10)
    table.add_column("类型", style="cyan")
    table.add_column("池子")
    table.add_column("详情")
    table.add_column("时间")

    for alert in active_alerts:
        level_style = {
            "info": "blue",
            "warning": "yellow",
            "critical": "red",
        }.get(alert.level, "white")

        table.add_row(
            Text(f"{alert.emoji} {alert.level.upper()}", style=level_style),
            alert.type,
            alert.market_name or "-",
            alert.message,
            alert.timestamp.strftime("%H:%M:%S"),
        )

    console.print()
    console.print(table)
    console.print()


@cli.command()
@click.pass_context
def status(ctx):
    """显示状态仪表盘"""
    config = ctx.obj["config"]

    print_banner()

    try:
        fetcher = GMXDataFetcher(config)
        engine = StrategyEngine(config, fetcher)
        risk_manager = RiskManager(config)

        # 获取数据
        positions = []
        if config.wallet.address:
            positions = fetcher.get_positions(config.wallet.address)

        engine_status = engine.get_status()
        risk_summary = risk_manager.get_risk_summary(positions)

    except Exception as e:
        console.print(f"[red]初始化失败: {e}[/red]")
        return

    # 策略状态
    strategy_panel = Panel(
        f"""
[bold cyan]策略:[/bold cyan] {engine_status['strategy']}
[bold cyan]检查间隔:[/bold cyan] {engine_status['config']['check_interval']}s
[bold cyan]最低 APY:[/bold cyan] {engine_status['config']['min_apy']}%
[bold cyan]最大仓位:[/bold cyan] ${engine_status['config']['max_position']}
        """,
        title="⚙️ 策略配置",
        border_style="cyan",
    )

    # 持仓状态
    total_value = risk_summary["total_value_usd"]
    pnl = risk_summary["total_pnl_usd"]
    pnl_pct = risk_summary["overall_pnl_pct"]
    pnl_color = "green" if pnl >= 0 else "red"

    position_panel = Panel(
        f"""
[bold]总资产:[/bold] ${total_value:,.2f}
[bold]未实现收益:[/bold] [{pnl_color}]{'+' if pnl >= 0 else ''}{pnl:.2f} ({pnl_pct:+.1f}%)[/{pnl_color}]
[bold]持仓数:[/bold] {len(positions)} 个池子
[bold]最大集中度:[/bold] {risk_summary['max_concentration_pct']:.1f}%
        """,
        title="💰 持仓概览",
        border_style="green",
    )

    # 风险状态
    risk_level = risk_summary["risk_level"]
    risk_color = {
        "正常": "green",
        "中等": "yellow",
        "较高": "orange1",
        "危险": "red",
    }.get(risk_level, "white")

    risk_panel = Panel(
        f"""
[bold]风险等级:[/bold] [{risk_color}]{risk_level}[/{risk_color}]
[bold]活跃告警:[/bold] {risk_summary['active_alerts']} 个
        """,
        title="🛡️ 风险状态",
        border_style=risk_color,
    )

    console.print()
    console.print(strategy_panel)
    console.print(position_panel)
    console.print(risk_panel)
    console.print()


@cli.command()
@click.pass_context
def init(ctx):
    """初始化配置向导"""
    console.print()
    console.print(Panel("🚀 GMX Market Maker 初始化向导", border_style="cyan"))
    console.print()

    # 创建配置目录
    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)

    # 询问基本配置
    console.print("[bold]1. 选择风险偏好:[/bold]")
    console.print("  1) 稳健型 (balanced) - 综合考虑收益和风险")
    console.print("  2) 激进型 (high_yield) - 追求最高收益")

    choice = click.prompt("请选择", type=int, default=1)
    strategy_type = "balanced" if choice == 1 else "high_yield"

    console.print()
    console.print("[bold]2. 设置投资参数:[/bold]")
    max_position = click.prompt("最大总仓位 (USD)", type=float, default=10000)
    min_apy = click.prompt("最低 APY 阈值 (%)", type=float, default=10.0)

    # 生成配置文件
    config_content = f"""# GMX Market Maker 配置文件
# 生成时间: {__import__('datetime').datetime.now().isoformat()}

network:
  chain: "arbitrum"
  rpc_url: "https://arb1.arbitrum.io/rpc"

strategy:
  type: "{strategy_type}"
  min_apy: {min_apy}
  max_single_pool_pct: 30.0

risk:
  max_position_usd: {max_position}
  max_drawdown_pct: 10.0
  stop_loss_pct: 15.0

pools:
  whitelist:
    - "ETH-USDC"
    - "BTC-USDC"
    - "ARB-USDC"
  blacklist: []

execution:
  check_interval: 300
  slippage_tolerance: 0.5

notifications:
  telegram:
    enabled: false
"""

    config_path = config_dir / "config.yaml"
    with open(config_path, "w") as f:
        f.write(config_content)

    console.print()
    console.print(f"[green]✅ 配置文件已生成: {config_path}[/green]")
    console.print()
    console.print("[yellow]⚠️ 请设置环境变量 PRIVATE_KEY 为你的钱包私钥[/yellow]")
    console.print("   export PRIVATE_KEY=your_private_key_here")
    console.print()


def main():
    """主入口"""
    cli(obj={})


if __name__ == "__main__":
    main()
