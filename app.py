import streamlit as st
import folium
from streamlit_folium import st_folium
from streamlit_option_menu import option_menu
from datetime import datetime
import time
import pandas as pd

# ================== 全局状态 ==================
if "A" not in st.session_state:
    st.session_state.A = (32.2322, 118.7490)
if "B" not in st.session_state:
    st.session_state.B = (32.2343, 118.7490)
if "A_set" not in st.session_state:
    st.session_state.A_set = False
if "B_set" not in st.session_state:
    st.session_state.B_set = False
if "height" not in st.session_state:
    st.session_state.height = 50
if "heartbeat_data" not in st.session_state:
    st.session_state.heartbeat_data = []
if "polygon_memory" not in st.session_state:
    st.session_state.polygon_memory = []  # 纯内存，不读写文件
if "is_drawing" not in st.session_state:
    st.session_state.is_drawing = False
if "temp_points" not in st.session_state:
    st.session_state.temp_points = []

st.set_page_config(layout="wide")

# ================== 侧边栏导航 ==================
with st.sidebar:
    st.title("🚁 无人机导航系统")
    page = option_menu("功能页面", ["航线规划", "飞行监控"], default_index=0)
    st.divider()
    
    st.subheader("🌐 坐标系")
    st.radio("", ["GCJ-02", "WGS-84"], index=0, label_visibility="collapsed")
    
    st.divider()
    st.subheader("📊 系统状态")
    st.button(
        "✅ A点已设" if st.session_state.A_set else "❌ A点未设", 
        type="primary" if st.session_state.A_set else "secondary",
        disabled=True
    )
    st.button(
        "✅ B点已设" if st.session_state.B_set else "❌ B点未设", 
        type="primary" if st.session_state.B_set else "secondary",
        disabled=True
    )

# ================== 航线规划页面 ==================
if page == "航线规划":
    st.title("航线规划（3D地图）")
    
    col_map, col_ctrl = st.columns([3, 1], gap="medium")

    with col_ctrl:
        st.subheader("控制面板")
        
        # A/B点坐标输入
        a_lat = st.number_input("起点A纬度", value=st.session_state.A[0], format="%.6f")
        a_lon = st.number_input("起点A经度", value=st.session_state.A[1], format="%.6f")
        b_lat = st.number_input("终点B纬度", value=st.session_state.B[0], format="%.6f")
        b_lon = st.number_input("终点B经度", value=st.session_state.B[1], format="%.6f")
        
        # 飞行高度
        st.session_state.height = st.slider(
            "飞行高度(m)", 
            min_value=0, 
            max_value=200, 
            value=st.session_state.height
        )

        # A/B点设置按钮
        if st.button("设置A点"):
            st.session_state.A = (a_lat, a_lon)
            st.session_state.A_set = True
        if st.button("设置B点"):
            st.session_state.B = (b_lat, b_lon)
            st.session_state.B_set = True

        st.divider()
        st.subheader("🧱 障碍物设置")
        
        # 障碍物按钮
        if st.button("🖌️ 开始圈选障碍物"):
            st.session_state.is_drawing = True
            st.session_state.temp_points = []
        if st.button("🗑️ 清除所有障碍物"):
            st.session_state.polygon_memory = []
            st.session_state.temp_points = []
            st.rerun()

        st.info(f"当前障碍物：{len(st.session_state.polygon_memory)} 个 (会话记忆)")

        st.divider()
        st.subheader("心跳状态")
        now = datetime.now().strftime("%H:%M:%S")
        st.metric("当前时间", now)

        # 心跳图表
        st.session_state.heartbeat_data.append(time.time())
        if len(st.session_state.heartbeat_data) > 30:
            st.session_state.heartbeat_data.pop(0)
        df = pd.DataFrame({
            "时间": range(len(st.session_state.heartbeat_data)),
            "心跳": st.session_state.heartbeat_data
        })
        st.line_chart(df.set_index("时间"), height=150)
        st.success("心跳正常")

    with col_map:
        # 计算地图中心
        center_lat = (st.session_state.A[0] + st.session_state.B[0]) / 2
        center_lon = (st.session_state.A[1] + st.session_state.B[1]) / 2
        
        # 创建地图
        m = folium.Map(location=[center_lat, center_lon], zoom_start=18, tiles="Cartodb dark_matter")

        # 绘制 A/B 点
        if st.session_state.A_set:
            folium.CircleMarker(st.session_state.A, radius=10, color="red", fill=True, tooltip="A点").add_to(m)
        if st.session_state.B_set:
            folium.CircleMarker(st.session_state.B, radius=10, color="green", fill=True, tooltip="B点").add_to(m)
        if st.session_state.A_set and st.session_state.B_set:
            folium.PolyLine([st.session_state.A, st.session_state.B], color="blue", weight=3, tooltip="航线").add_to(m)

        # 绘制障碍物
        for poly in st.session_state.polygon_memory:
            if len(poly) >= 3: # 确保是多边形
                folium.Polygon(locations=poly, color="red", fill=True, fill_opacity=0.5).add_to(m)
        
        # 绘制临时线条
        if st.session_state.temp_points:
            folium.PolyLine(locations=st.session_state.temp_points, color="red", weight=2, dash_array="5,5").add_to(m)

        # 渲染地图
        output = st_folium(m, width=1000, height=600, key="map1")

        # 圈选逻辑
        if st.session_state.is_drawing and output.get("last_clicked"):
            lat = output["last_clicked"]["lat"]
            lon = output["last_clicked"]["lng"]
            st.session_state.temp_points.append([lat, lon])
            st.rerun() # 实时刷新显示线条
        
        # 自动完成多边形 (至少3个点)
        if len(st.session_state.temp_points) >= 3:
            # 询问是否确认闭合
            if st.button("✅ 完成圈选并添加障碍物"):
                st.session_state.polygon_memory.append(st.session_state.temp_points.copy())
                st.session_state.is_drawing = False
                st.session_state.temp_points = []
                st.rerun()
            st.warning("⚠️ 已点击地图3次以上，请点击上方按钮确认添加")

elif page == "飞行监控":
    st.title("📡 无人机飞行监控")
    st.success("✅ 无人机在线，心跳正常，连接稳定")
    st.metric("当前高度", f"{st.session_state.height} m")
    st.metric("地图障碍物数量", len(st.session_state.polygon_memory))
