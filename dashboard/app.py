"""邑品引擎 Dashboard - Streamlit 实时数据看板.

Usage:
    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import streamlit as st

st.set_page_config(page_title="邑品引擎", page_icon="🚀", layout="wide")

st.title("🚀 邑品引擎 - AI 自动投流控制台")

# --- Sidebar ---
st.sidebar.header("控制面板")
if st.sidebar.button("🎬 立即生成素材"):
    st.sidebar.info("素材生成任务已触发...")

if st.sidebar.button("🔄 立即优化巡检"):
    st.sidebar.info("优化巡检已触发...")

if st.sidebar.button("📦 处理待发订单"):
    st.sidebar.info("订单处理已触发...")

# --- Main metrics ---
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("今日消耗", "¥0", help="千川广告总消耗")
with col2:
    st.metric("今日GMV", "¥0", help="成交总额")
with col3:
    st.metric("今日订单", "0", help="成交订单数")
with col4:
    st.metric("整体ROI", "0.00", help="GMV / 广告消耗")
with col5:
    st.metric("平均CPA", "¥0", help="平均获客成本")

st.divider()

# --- Campaign status ---
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("📊 在投计划")
    st.info("连接千川 API 后显示实时数据")
    # Placeholder table
    st.dataframe(
        {
            "计划名称": ["等待配置..."],
            "状态": ["--"],
            "消耗": ["--"],
            "转化": ["--"],
            "CPA": ["--"],
            "ROI": ["--"],
        },
        use_container_width=True,
    )

with col_right:
    st.subheader("🎬 今日素材")
    st.info("生成素材后显示")
    st.dataframe(
        {
            "素材ID": ["等待生成..."],
            "产品": ["--"],
            "角度": ["--"],
            "钩子": ["--"],
            "状态": ["--"],
        },
        use_container_width=True,
    )

st.divider()

# --- Orders ---
st.subheader("📦 订单状态")
ord_col1, ord_col2, ord_col3 = st.columns(3)
with ord_col1:
    st.metric("待发货", "0")
with ord_col2:
    st.metric("已发货", "0")
with ord_col3:
    st.metric("已完成", "0")

st.divider()

# --- System status ---
st.subheader("⚙️ 系统状态")
status_cols = st.columns(4)
with status_cols[0]:
    st.caption("素材引擎")
    st.success("就绪")
with status_cols[1]:
    st.caption("投放引擎")
    st.warning("待配置 API")
with status_cols[2]:
    st.caption("订单引擎")
    st.warning("待配置 API")
with status_cols[3]:
    st.caption("飞书通知")
    st.warning("待配置 Webhook")

# --- Quick start guide ---
with st.expander("🚀 快速开始指南"):
    st.markdown("""
    ### 第一步：配置环境变量
    ```bash
    cp .env.example .env
    # 编辑 .env 文件，填入各平台 API 密钥
    ```

    ### 第二步：准备产品素材
    - 在 `assets/products/` 下按产品建文件夹
    - 放入产品图片（建议 5-8 张高清图）
    - 在 `assets/bgm/` 放入背景音乐 MP3

    ### 第三步：安装依赖
    ```bash
    pip install -e ".[dev]"
    # 确保 ffmpeg 已安装
    brew install ffmpeg  # macOS
    ```

    ### 第四步：测试素材生成
    ```bash
    python main.py creatives
    ```

    ### 第五步：启动全自动引擎
    ```bash
    python main.py run
    ```
    """)
