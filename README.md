# GMX v2 Market Maker Bot

<div align="center">

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Tests](https://img.shields.io/badge/Tests-75%20passed-success.svg)

**自动化的 GMX v2 做市策略机器人**

*智能管理流动性仓位，最大化收益并控制风险*

[功能特性](#功能特性) · [快速开始](#快速开始) · [策略说明](#策略说明) · [API 参考](#api-参考)

</div>

---

## 功能特性

| 功能 | 描述 |
|------|------|
| 🏊 **池子监控** | 实时获取所有 GMX v2 池子数据，包括 APY、TVL、多空比例 |
| 📊 **智能评分** | 综合考虑收益、风险、流动性、多空平衡等因素 |
| 🤖 **自动策略** | 支持平衡策略和高收益策略 |
| 🛡️ **风险控制** | 回撤预警、止损机制、仓位限制 |
| 📱 **多种界面** | CLI 命令行 + Web 仪表盘 |
| 🔔 **告警通知** | Telegram 推送 |

## 截图预览

### Web 仪表盘
- 现代化深色主题设计
- 实时数据刷新
- 多空平衡可视化
- 一键运行策略

### CLI 界面
```
╔═══════════════════════════════════════════════════════════════╗
║     ██████╗ ███╗   ███╗██╗  ██╗    ███╗   ███╗███╗   ███╗    ║
║    ██╔════╝ ████╗ ████║╚██╗██╔╝    ████╗ ████║████╗ ████║    ║
║    ██║  ███╗██╔████╔██║ ╚███╔╝     ██╔████╔██║██╔████╔██║    ║
║    ██║   ██║██║╚██╔╝██║ ██╔██╗     ██║╚██╔╝██║██║╚██╔╝██║    ║
║    ╚██████╔╝██║ ╚═╝ ██║██╔╝ ██╗    ██║ ╚═╝ ██║██║ ╚═╝ ██║    ║
║     ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝    ╚═╝     ╚═╝╚═╝     ╚═╝    ║
║            GMX v2 Market Making Bot v0.1.0                    ║
╚═══════════════════════════════════════════════════════════════╝
```

## 快速开始

### 1. 安装

```bash
# 克隆项目
git clone https://github.com/frankfika/gmx-market-maker.git
cd gmx-market-maker

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -e ".[dev]"
```

### 2. 配置

```bash
# 复制配置模板
cp config/config.example.yaml config/config.yaml
cp .env.example .env

# 编辑配置
# 设置你的钱包私钥和 RPC URL
```

### 3. 运行

#### CLI 模式

```bash
# 查看系统信息
gmx-mm info

# 查看池子排名
gmx-mm pools

# 查看持仓
gmx-mm positions

# 运行策略 (模拟)
gmx-mm run --capital 1000

# 查看告警
gmx-mm alerts

# 初始化向导
gmx-mm init
```

#### Web 界面

```bash
python scripts/run_web.py
# 访问 http://localhost:8000
```

#### 后台运行

```bash
python scripts/run_bot.py
```

## 策略说明

### 平衡策略 (balanced)

综合考虑收益和风险，分散投资到多个池子：

- APY 权重: 30%
- 风险权重: 25%
- 流动性权重: 25%
- 多空平衡权重: 20%

### 高收益策略 (high_yield)

追求最高 APY，接受较高风险：

- APY 权重: 60%
- 风险权重: 15%
- 流动性权重: 15%
- 多空平衡权重: 10%

## 配置参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `strategy.type` | 策略类型 | balanced |
| `strategy.min_apy` | 最低 APY 阈值 | 10% |
| `strategy.max_single_pool_pct` | 单池最大占比 | 30% |
| `risk.max_position_usd` | 总仓位上限 | $10,000 |
| `risk.max_drawdown_pct` | 最大回撤预警 | 10% |
| `risk.stop_loss_pct` | 止损线 | 15% |

## 项目结构

```
trader/
├── docs/                    # 文档
│   ├── PRD.md              # 产品需求文档
│   └── USE_CASES.md        # 用例文档
├── src/gmx_mm/             # 源代码
│   ├── data/               # 数据模块
│   │   ├── fetcher.py      # 数据获取
│   │   └── models.py       # 数据模型
│   ├── strategy/           # 策略模块
│   │   ├── base.py         # 策略基类
│   │   ├── balanced.py     # 平衡策略
│   │   ├── high_yield.py   # 高收益策略
│   │   └── engine.py       # 策略引擎
│   ├── execution/          # 执行模块
│   │   ├── executor.py     # 交易执行器
│   │   └── risk.py         # 风险管理
│   ├── web/                # Web 界面
│   │   └── app.py          # FastAPI 应用
│   ├── utils/              # 工具模块
│   │   └── notifications.py # 通知
│   ├── cli.py              # CLI 入口
│   └── config.py           # 配置管理
├── tests/                  # 测试
│   ├── test_config.py      # 配置测试
│   ├── test_models.py      # 模型测试
│   ├── test_strategy.py    # 策略测试
│   ├── test_risk.py        # 风险测试
│   └── test_e2e.py         # 端到端测试
├── scripts/                # 脚本
│   ├── run_web.py          # 启动 Web
│   └── run_bot.py          # 启动机器人
├── config/                 # 配置文件
│   └── config.example.yaml # 配置模板
├── pyproject.toml          # 项目配置
└── README.md               # 说明文档
```

## 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试文件
pytest tests/test_strategy.py

# 运行带覆盖率
pytest --cov=gmx_mm --cov-report=html
```

## API 参考

### GMXDataFetcher

```python
from gmx_mm.data.fetcher import GMXDataFetcher
from gmx_mm.config import Config

config = Config.load()
fetcher = GMXDataFetcher(config)

# 获取所有市场
markets = fetcher.get_markets()

# 获取池子统计
stats = fetcher.get_pool_stats(market_key)

# 获取持仓
positions = fetcher.get_positions(address)
```

### StrategyEngine

```python
from gmx_mm.strategy.engine import StrategyEngine

engine = StrategyEngine(config, fetcher)

# 运行策略
signals = engine.run(available_capital=1000, dry_run=True)

# 获取池子排名
rankings = engine.get_pool_rankings()
```

### RiskManager

```python
from gmx_mm.execution.risk import RiskManager

risk_manager = RiskManager(config)

# 检查风险
alerts = risk_manager.check_all(positions, markets, stats)

# 是否需要紧急退出
if risk_manager.should_emergency_exit(positions):
    print("触发止损!")
```

## 风险提示

⚠️ **重要警告**:

1. 本项目仅供学习和研究使用
2. DeFi 投资存在智能合约风险、市场风险等
3. 请勿投入超过承受能力的资金
4. 使用前请充分了解 GMX 协议机制

## 许可证

MIT License

## 资源链接

- [GMX v2 官方文档](https://docs.gmx.io/docs/providing-liquidity/v2/)
- [GMX Python SDK](https://github.com/snipermonke01/gmx_python_sdk)
- [GMX 合约](https://github.com/gmx-io/gmx-contracts)
