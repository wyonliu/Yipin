#!/bin/bash
# 邑品引擎 - 一键启动脚本
# 检查环境 → 初始化 → 启动
set -e

cd "$(dirname "$0")/.."

echo "========================================"
echo "  邑品引擎 - 启动检查"
echo "========================================"

# Check Python
PYTHON=$(command -v python3 || true)
if [ -z "$PYTHON" ]; then
    echo "❌ python3 未安装"
    exit 1
fi
echo "✅ Python: $($PYTHON --version)"

# Check FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "❌ ffmpeg 未安装，正在安装..."
    if command -v brew &> /dev/null; then
        brew install ffmpeg
    else
        echo "  请手动安装: brew install ffmpeg"
        exit 1
    fi
fi
echo "✅ FFmpeg: $(ffmpeg -version 2>&1 | head -1)"

# Check .env
if [ ! -f .env ]; then
    echo "⚠️  .env 文件不存在"
    echo "   运行配置向导: python3 scripts/setup_wizard.py"
    echo "   或复制模板:    cp .env.example .env"
    exit 1
fi
echo "✅ .env 配置文件存在"

# Check OpenRouter key
if grep -q "OPENROUTER_API_KEY=sk-" .env; then
    echo "✅ OpenRouter API Key 已配置"
else
    echo "⚠️  OpenRouter API Key 未配置"
fi

# Check MiniMax key
if grep -q "MINIMAX_API_KEY=sk-" .env; then
    echo "✅ MiniMax TTS Key 已配置"
else
    echo "⚠️  MiniMax TTS Key 未配置"
fi

# Download fonts if needed
bash scripts/download_fonts.sh 2>/dev/null || echo "⚠️  字体下载失败(可选)"

# Install deps
echo ""
echo "📦 安装依赖..."
pip3 install -q -e . 2>/dev/null || pip3 install -q anthropic httpx pydantic pydantic-settings sqlalchemy pyyaml pillow

# Init DB
echo ""
echo "🗄️  初始化数据库..."
$PYTHON main.py init-db

echo ""
echo "========================================"
echo "  ✅ 环境就绪！"
echo ""
echo "  测试素材生成:  python3 scripts/test_pipeline_dry_run.py"
echo "  启动全自动:    python3 main.py run"
echo "  启动看板:      streamlit run dashboard/app.py"
echo "========================================"
