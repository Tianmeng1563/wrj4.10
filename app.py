import streamlit as st
import folium
import json
import os
from streamlit_folium import st_folium
from streamlit_option_menu import option_menu
from datetime import datetime
import time
import pandas as pd

# ================== 障碍物记忆（永久保存）==================
OBSTACLE_FILE = "obstacles.json"

def load_obstacles():
    if os.path.exists(OBSTACLE_FILE):
        with open(OBSTACLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_obstacles(polygons):
    with open(OBSTACLE_FILE, "w", encoding="utf-8") as f:
        json.dump(polygons, f, ensure_ascii=False, indent=2)

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
    st.session_state.polygon_memory = load_obstacles()  # 开机自动加载
if "is_drawing" not in st.session_state:
    st.session_state.is_drawing = False
if "temp_points" not in st.session_state:
    st.session_state.temp_points = []

st.set_page_config(layout="wide")

# ================== 左侧导航 ==================
with st.sidebar:
    st.title("导航")
    option_menu("功能页面", ["航线规划", "飞行监控"], default_index=0)
    st.divider()
    st.subheader("坐标系")
    st.radio("", ["GCJ-02", "WGS-84"])
    st.divider()
    st.subheader("系统状态")
    st.button("A点已设" if st.session_state.A_set else "A点未设", type="primary")
    st.button("B点已设" if st.session_state.B_set else "B点未设", type="primary")

# ================== 主页面 ==================
st.title("航线规划（3D地图）")
col_map, col_ctrl = st.columns([3, 1])

with col_ctrl:
    st.subheader("控制面板")
    a_lat = st.number_input("起点A纬度", value=st.session_state.A[0], format="%.6f")
    a_lon = st.number_input("起点A经度", value=st.session_state.A[1], format="%.6f")
    b_lat = st.number_input("终点B纬度", value=st.session_state.B[0], format="%.6f")
    b_lon = st.number_input("终点B经度", value=st.session_state.B[1], format="%.6f")
    st.session_state.height = st.slider("飞行高度(m)", 0, 200, value=st.session_state.height)

    if st.button("设置A点"):
        st.session_state.A = (a_lat, a_lon)
        st.session_state.A_set = True
    if st.button("设置B点"):
        st.session_state.B = (b_lat, b_lon)
        st.session_state.B_set = True

    st.divider()
    st.subheader("障碍物设置")

    if st.button("开始圈选障碍物"):
        st.session_state.is_drawing = True
        st.session_state.temp_points = []

    if st.button("清除障碍物（含记忆）"):
        st.session_state.polygon_memory = []
        st.session_state.temp_points = []
        save_obstacles([])
        st.rerun()

    st.info(f"已记忆障碍物：{len(st.session_state.polygon_memory)} 个")

    st.divider()
    st.subheader("心跳状态")
    now = datetime.now().strftime("%H:%M:%S")
    st.metric("当前时间", now)

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
    center_lat = (st.session_state.A[0] + st.session_state.B[0]) / 2
    center_lon = (st.session_state.A[1] + st.session_state.B[1]) / 2
    m = folium.Map(location=[center_lat, center_lon], zoom_start=18, tiles="Cartodb dark_matter")

    if st.session_state.A_set:
        folium.CircleMarker(st.session_state.A, radius=10, color="red", fill=True).add_to(m)
    if st.session_state.B_set:
        folium.CircleMarker(st.session_state.B, radius=10, color="green", fill=True).add_to(m)
    if st.session_state.A_set and st.session_state.B_set:
        folium.PolyLine([st.session_state.A, st.session_state.B], color="blue", weight=3).add_to(m)

    # 画出所有记忆的障碍物
    for poly in st.session_state.polygon_memory:
        folium.Polygon(locations=poly, color="red", fill=True, fill_opacity=0.5).add_to(m)

    # 临时画线
    if st.session_state.temp_points:
        folium.PolyLine(locations=st.session_state.temp_points, color="red").add_to(m)

    output = st_folium(m, width=1000, height=600)

    # 圈选逻辑
    if st.session_state.is_drawing and output.get("last_clicked"):
        lat = output["last_clicked"]["lat"]
        lon = output["last_clicked"]["lng"]
        st.session_state.temp_points.append([lat, lon])

    # 够3个点自动闭合并保存记忆
    if len(st.session_state.temp_points) >= 3:
        st.session_state.polygon_memory.append(st.session_state.temp_points)
        save_obstacles(st.session_state.polygon_memory)  # 永久保存
        st.session_state.is_drawing = False
        st.session_state.temp_points = []
        st.rerun()
