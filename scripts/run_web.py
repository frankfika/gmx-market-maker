#!/usr/bin/env python3
"""启动 Web 服务器"""

import sys
from pathlib import Path

# 添加 src 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import uvicorn

from gmx_mm.config import Config
from gmx_mm.web.app import create_app


def main():
    """启动 Web 服务器"""
    config = Config.load()
    app = create_app(config)

    print("🚀 启动 GMX Market Maker Web UI...")
    print("📡 访问地址: http://localhost:8000")

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
