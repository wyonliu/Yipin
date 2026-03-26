#!/bin/bash
# 下载中文字幕字体 (Noto Sans SC) 到 assets/fonts/
set -e

FONT_DIR="$(dirname "$0")/../assets/fonts"
mkdir -p "$FONT_DIR"

if [ -f "$FONT_DIR/NotoSansSC-Bold.ttf" ]; then
    echo "✅ 字体已存在: $FONT_DIR/NotoSansSC-Bold.ttf"
    exit 0
fi

echo "📥 下载 Noto Sans SC Bold..."
curl -L -o "$FONT_DIR/NotoSansSC-Bold.ttf" \
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansSC-Bold.otf"

echo "✅ 字体下载完成: $FONT_DIR/NotoSansSC-Bold.ttf"
