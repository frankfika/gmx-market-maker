"""Web 应用"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import Config
from ..data.fetcher import GMXDataFetcher
from ..strategy.engine import StrategyEngine
from ..execution.risk import RiskManager

logger = logging.getLogger(__name__)

# 全局实例
_config: Optional[Config] = None
_fetcher: Optional[GMXDataFetcher] = None
_engine: Optional[StrategyEngine] = None
_risk_manager: Optional[RiskManager] = None


def create_app(config: Config) -> FastAPI:
    """创建 FastAPI 应用"""
    global _config, _fetcher, _engine, _risk_manager

    _config = config

    app = FastAPI(
        title="GMX Market Maker",
        description="GMX v2 做市策略机器人",
        version="0.1.0",
    )

    # 初始化组件
    try:
        _fetcher = GMXDataFetcher(config)
        _engine = StrategyEngine(config, _fetcher)
        _risk_manager = RiskManager(config)
    except Exception as e:
        logger.error(f"初始化失败: {e}")

    # API 路由
    @app.get("/", response_class=HTMLResponse)
    async def index():
        """主页"""
        return get_dashboard_html()

    @app.get("/api/status")
    async def get_status():
        """获取系统状态"""
        try:
            positions = []
            if _config.wallet.address and _fetcher:
                positions = _fetcher.get_positions(_config.wallet.address)

            engine_status = _engine.get_status() if _engine else {}
            risk_summary = _risk_manager.get_risk_summary(positions) if _risk_manager else {}

            return {
                "success": True,
                "data": {
                    "strategy": engine_status,
                    "risk": risk_summary,
                    "positions_count": len(positions),
                    "timestamp": datetime.utcnow().isoformat(),
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/api/pools")
    async def get_pools():
        """获取池子列表"""
        try:
            if not _fetcher:
                raise HTTPException(status_code=500, detail="Fetcher 未初始化")

            markets = _fetcher.get_markets()
            pools_data = []

            for market in markets[:20]:  # 限制数量
                stats = _fetcher.get_pool_stats(market.market_key)

                pools_data.append(
                    {
                        "name": market.name,
                        "market_key": market.market_key,
                        "gm_price": market.gm_price,
                        "tvl": market.pool_tvl,
                        "long_oi": market.long_oi,
                        "short_oi": market.short_oi,
                        "oi_imbalance": market.oi_imbalance,
                        "apy": stats.apy if stats else 0,
                    }
                )

            return {"success": True, "data": pools_data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/api/positions")
    async def get_positions():
        """获取持仓"""
        try:
            if not _fetcher or not _config.wallet.address:
                return {"success": True, "data": []}

            positions = _fetcher.get_positions(_config.wallet.address)

            return {
                "success": True,
                "data": [
                    {
                        "name": p.name,
                        "gm_balance": p.gm_balance,
                        "value_usd": p.value_usd,
                        "pnl": p.unrealized_pnl,
                        "pnl_pct": p.pnl_pct,
                    }
                    for p in positions
                ],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/api/alerts")
    async def get_alerts():
        """获取告警"""
        try:
            if not _risk_manager:
                return {"success": True, "data": []}

            alerts = _risk_manager.get_active_alerts()

            return {
                "success": True,
                "data": [
                    {
                        "level": a.level,
                        "type": a.type,
                        "market": a.market_name,
                        "message": a.message,
                        "timestamp": a.timestamp.isoformat(),
                    }
                    for a in alerts
                ],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    class RunStrategyRequest(BaseModel):
        capital: float = 0
        dry_run: bool = True

    @app.post("/api/run")
    async def run_strategy(request: RunStrategyRequest):
        """运行策略"""
        try:
            if not _engine:
                raise HTTPException(status_code=500, detail="Engine 未初始化")

            signals = _engine.run(
                available_capital=request.capital,
                dry_run=request.dry_run,
            )

            return {
                "success": True,
                "data": [
                    {
                        "action": s.action,
                        "market": s.market_name,
                        "amount_usd": s.amount_usd,
                        "reason": s.reason,
                        "confidence": s.confidence,
                    }
                    for s in signals
                ],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    return app


def get_dashboard_html() -> str:
    """生成仪表盘 HTML"""
    return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GMX Market Maker</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-tertiary: #21262d;
            --border-color: #30363d;
            --text-primary: #f0f6fc;
            --text-secondary: #8b949e;
            --accent-green: #3fb950;
            --accent-red: #f85149;
            --accent-blue: #58a6ff;
            --accent-purple: #a371f7;
            --accent-yellow: #d29922;
            --gradient-1: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --gradient-2: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            --gradient-3: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
        }

        /* Header */
        .header {
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border-color);
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .logo-icon {
            width: 40px;
            height: 40px;
            background: var(--gradient-1);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
        }

        .logo-text {
            font-size: 1.25rem;
            font-weight: 700;
            background: var(--gradient-1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .status-badge {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 1rem;
            background: var(--bg-tertiary);
            border-radius: 20px;
            font-size: 0.875rem;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--accent-green);
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        /* Main Content */
        .main {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }

        /* Stats Cards */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        .stat-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            transition: transform 0.2s, box-shadow 0.2s;
        }

        .stat-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
        }

        .stat-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }

        .stat-card-title {
            color: var(--text-secondary);
            font-size: 0.875rem;
            font-weight: 500;
        }

        .stat-card-icon {
            width: 40px;
            height: 40px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.25rem;
        }

        .stat-card-icon.green { background: rgba(63, 185, 80, 0.15); }
        .stat-card-icon.blue { background: rgba(88, 166, 255, 0.15); }
        .stat-card-icon.purple { background: rgba(163, 113, 247, 0.15); }
        .stat-card-icon.yellow { background: rgba(210, 153, 34, 0.15); }

        .stat-card-value {
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }

        .stat-card-change {
            font-size: 0.875rem;
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }

        .stat-card-change.positive { color: var(--accent-green); }
        .stat-card-change.negative { color: var(--accent-red); }

        /* Panels */
        .panels-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 1.5rem;
        }

        @media (max-width: 1024px) {
            .panels-grid {
                grid-template-columns: 1fr;
            }
        }

        .panel {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            overflow: hidden;
        }

        .panel-header {
            padding: 1.25rem 1.5rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .panel-title {
            font-size: 1rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .panel-body {
            padding: 1rem;
            max-height: 400px;
            overflow-y: auto;
        }

        /* Pool List */
        .pool-item {
            display: flex;
            align-items: center;
            padding: 1rem;
            border-radius: 12px;
            margin-bottom: 0.5rem;
            background: var(--bg-tertiary);
            transition: background 0.2s;
        }

        .pool-item:hover {
            background: rgba(88, 166, 255, 0.1);
        }

        .pool-icon {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: var(--gradient-3);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            margin-right: 1rem;
        }

        .pool-info {
            flex: 1;
        }

        .pool-name {
            font-weight: 600;
            margin-bottom: 0.25rem;
        }

        .pool-meta {
            font-size: 0.75rem;
            color: var(--text-secondary);
        }

        .pool-stats {
            text-align: right;
        }

        .pool-apy {
            font-weight: 600;
            color: var(--accent-green);
            font-size: 1.125rem;
        }

        .pool-tvl {
            font-size: 0.75rem;
            color: var(--text-secondary);
        }

        /* Balance Indicator */
        .balance-bar {
            display: flex;
            height: 6px;
            border-radius: 3px;
            overflow: hidden;
            margin-top: 0.5rem;
        }

        .balance-long {
            background: var(--accent-green);
        }

        .balance-short {
            background: var(--accent-red);
        }

        /* Alerts */
        .alert-item {
            display: flex;
            align-items: flex-start;
            padding: 1rem;
            border-radius: 12px;
            margin-bottom: 0.5rem;
            background: var(--bg-tertiary);
        }

        .alert-item.warning {
            border-left: 3px solid var(--accent-yellow);
        }

        .alert-item.critical {
            border-left: 3px solid var(--accent-red);
        }

        .alert-icon {
            margin-right: 1rem;
            font-size: 1.25rem;
        }

        .alert-content {
            flex: 1;
        }

        .alert-message {
            font-size: 0.875rem;
            margin-bottom: 0.25rem;
        }

        .alert-time {
            font-size: 0.75rem;
            color: var(--text-secondary);
        }

        /* Buttons */
        .btn {
            padding: 0.75rem 1.5rem;
            border-radius: 10px;
            font-weight: 600;
            font-size: 0.875rem;
            cursor: pointer;
            border: none;
            transition: all 0.2s;
        }

        .btn-primary {
            background: var(--gradient-1);
            color: white;
        }

        .btn-primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 20px rgba(102, 126, 234, 0.4);
        }

        .btn-secondary {
            background: var(--bg-tertiary);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
        }

        /* Run Strategy Modal */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }

        .modal.active {
            display: flex;
        }

        .modal-content {
            background: var(--bg-secondary);
            border-radius: 16px;
            padding: 2rem;
            width: 90%;
            max-width: 400px;
            border: 1px solid var(--border-color);
        }

        .modal-title {
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
        }

        .form-group {
            margin-bottom: 1rem;
        }

        .form-label {
            display: block;
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }

        .form-input {
            width: 100%;
            padding: 0.75rem 1rem;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            color: var(--text-primary);
            font-size: 1rem;
        }

        .form-input:focus {
            outline: none;
            border-color: var(--accent-blue);
        }

        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .modal-actions {
            display: flex;
            gap: 1rem;
            margin-top: 1.5rem;
        }

        .modal-actions .btn {
            flex: 1;
        }

        /* Loading */
        .loading {
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 2rem;
        }

        .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid var(--border-color);
            border-top-color: var(--accent-blue);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 2rem;
            color: var(--text-secondary);
        }

        .empty-state-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
        }
    </style>
</head>
<body>
    <!-- Header -->
    <header class="header">
        <div class="logo">
            <div class="logo-icon">🦊</div>
            <span class="logo-text">GMX Market Maker</span>
        </div>
        <div class="status-badge">
            <div class="status-dot"></div>
            <span id="status-text">运行中</span>
        </div>
    </header>

    <!-- Main Content -->
    <main class="main">
        <!-- Stats Cards -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-title">总资产</span>
                    <div class="stat-card-icon green">💰</div>
                </div>
                <div class="stat-card-value" id="total-value">$0.00</div>
                <div class="stat-card-change positive" id="total-change">
                    <span>↑</span>
                    <span>+0.00%</span>
                </div>
            </div>

            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-title">今日收益</span>
                    <div class="stat-card-icon blue">📈</div>
                </div>
                <div class="stat-card-value" id="daily-pnl">$0.00</div>
                <div class="stat-card-change" id="daily-pnl-pct">+0.00%</div>
            </div>

            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-title">持仓池数</span>
                    <div class="stat-card-icon purple">🏊</div>
                </div>
                <div class="stat-card-value" id="positions-count">0</div>
                <div class="stat-card-change" style="color: var(--text-secondary)">个活跃池子</div>
            </div>

            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-title">风险等级</span>
                    <div class="stat-card-icon yellow">🛡️</div>
                </div>
                <div class="stat-card-value" id="risk-level">正常</div>
                <div class="stat-card-change" id="alerts-count" style="color: var(--text-secondary)">0 个告警</div>
            </div>
        </div>

        <!-- Panels -->
        <div class="panels-grid">
            <!-- Pools Panel -->
            <div class="panel">
                <div class="panel-header">
                    <h2 class="panel-title">🏊 池子排名</h2>
                    <button class="btn btn-secondary" onclick="refreshPools()">刷新</button>
                </div>
                <div class="panel-body" id="pools-list">
                    <div class="loading">
                        <div class="spinner"></div>
                    </div>
                </div>
            </div>

            <!-- Alerts Panel -->
            <div class="panel">
                <div class="panel-header">
                    <h2 class="panel-title">🔔 告警</h2>
                </div>
                <div class="panel-body" id="alerts-list">
                    <div class="empty-state">
                        <div class="empty-state-icon">✅</div>
                        <p>暂无告警</p>
                    </div>
                </div>
            </div>
        </div>

        <!-- Action Buttons -->
        <div style="margin-top: 2rem; display: flex; gap: 1rem;">
            <button class="btn btn-primary" onclick="openRunModal()">
                🚀 运行策略
            </button>
            <button class="btn btn-secondary" onclick="refreshAll()">
                🔄 刷新数据
            </button>
        </div>
    </main>

    <!-- Run Strategy Modal -->
    <div class="modal" id="run-modal">
        <div class="modal-content">
            <h3 class="modal-title">🚀 运行策略</h3>
            <div class="form-group">
                <label class="form-label">可用资金 (USD)</label>
                <input type="number" class="form-input" id="capital-input" placeholder="1000" value="0">
            </div>
            <div class="form-group">
                <label class="checkbox-group">
                    <input type="checkbox" id="dry-run-check" checked>
                    <span>模拟模式 (不执行真实交易)</span>
                </label>
            </div>
            <div class="modal-actions">
                <button class="btn btn-secondary" onclick="closeRunModal()">取消</button>
                <button class="btn btn-primary" onclick="runStrategy()">执行</button>
            </div>
        </div>
    </div>

    <script>
        // API 调用函数
        async function fetchAPI(endpoint, options = {}) {
            try {
                const response = await fetch(endpoint, options);
                return await response.json();
            } catch (error) {
                console.error('API Error:', error);
                return { success: false, error: error.message };
            }
        }

        // 刷新状态
        async function refreshStatus() {
            const result = await fetchAPI('/api/status');
            if (result.success) {
                const data = result.data;

                document.getElementById('total-value').textContent =
                    `$${(data.risk?.total_value_usd || 0).toLocaleString('en-US', {minimumFractionDigits: 2})}`;

                const pnl = data.risk?.total_pnl_usd || 0;
                const pnlElement = document.getElementById('daily-pnl');
                pnlElement.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`;
                pnlElement.style.color = pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';

                document.getElementById('positions-count').textContent = data.positions_count || 0;
                document.getElementById('risk-level').textContent = data.risk?.risk_level || '正常';
                document.getElementById('alerts-count').textContent = `${data.risk?.active_alerts || 0} 个告警`;
            }
        }

        // 刷新池子列表
        async function refreshPools() {
            const container = document.getElementById('pools-list');
            container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

            const result = await fetchAPI('/api/pools');
            if (result.success && result.data.length > 0) {
                container.innerHTML = result.data.map(pool => {
                    const longPct = pool.long_oi + pool.short_oi > 0
                        ? (pool.long_oi / (pool.long_oi + pool.short_oi)) * 100
                        : 50;

                    return `
                        <div class="pool-item">
                            <div class="pool-icon">${pool.name.split('-')[0].slice(0, 2)}</div>
                            <div class="pool-info">
                                <div class="pool-name">${pool.name}</div>
                                <div class="pool-meta">
                                    OI: $${(pool.long_oi / 1e6).toFixed(1)}M / $${(pool.short_oi / 1e6).toFixed(1)}M
                                </div>
                                <div class="balance-bar">
                                    <div class="balance-long" style="width: ${longPct}%"></div>
                                    <div class="balance-short" style="width: ${100 - longPct}%"></div>
                                </div>
                            </div>
                            <div class="pool-stats">
                                <div class="pool-apy">${pool.apy.toFixed(1)}%</div>
                                <div class="pool-tvl">TVL: $${(pool.tvl / 1e6).toFixed(1)}M</div>
                            </div>
                        </div>
                    `;
                }).join('');
            } else {
                container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🏊</div><p>暂无池子数据</p></div>';
            }
        }

        // 刷新告警
        async function refreshAlerts() {
            const container = document.getElementById('alerts-list');
            const result = await fetchAPI('/api/alerts');

            if (result.success && result.data.length > 0) {
                container.innerHTML = result.data.map(alert => `
                    <div class="alert-item ${alert.level}">
                        <div class="alert-icon">${alert.level === 'critical' ? '🚨' : '⚠️'}</div>
                        <div class="alert-content">
                            <div class="alert-message">${alert.message}</div>
                            <div class="alert-time">${alert.market || ''} • ${new Date(alert.timestamp).toLocaleTimeString()}</div>
                        </div>
                    </div>
                `).join('');
            } else {
                container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">✅</div><p>暂无告警</p></div>';
            }
        }

        // 刷新所有数据
        async function refreshAll() {
            await Promise.all([
                refreshStatus(),
                refreshPools(),
                refreshAlerts()
            ]);
        }

        // 打开运行策略模态框
        function openRunModal() {
            document.getElementById('run-modal').classList.add('active');
        }

        // 关闭模态框
        function closeRunModal() {
            document.getElementById('run-modal').classList.remove('active');
        }

        // 运行策略
        async function runStrategy() {
            const capital = parseFloat(document.getElementById('capital-input').value) || 0;
            const dryRun = document.getElementById('dry-run-check').checked;

            const result = await fetchAPI('/api/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ capital, dry_run: dryRun })
            });

            closeRunModal();

            if (result.success) {
                if (result.data.length === 0) {
                    alert('✅ 无需调整');
                } else {
                    const signals = result.data.map(s =>
                        `${s.action === 'deposit' ? '📥' : '📤'} ${s.market}: $${s.amount_usd.toFixed(2)}`
                    ).join('\\n');
                    alert(`策略信号:\\n${signals}`);
                }
            } else {
                alert(`❌ 错误: ${result.error}`);
            }

            refreshAll();
        }

        // 初始化
        document.addEventListener('DOMContentLoaded', () => {
            refreshAll();

            // 定时刷新
            setInterval(refreshStatus, 30000);
            setInterval(refreshPools, 60000);
        });

        // 点击模态框外部关闭
        document.getElementById('run-modal').addEventListener('click', (e) => {
            if (e.target.id === 'run-modal') {
                closeRunModal();
            }
        });
    </script>
</body>
</html>
    """
