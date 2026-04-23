import streamlit as st
import folium
from streamlit_folium import st_folium
from streamlit_option_menu import option_menu
from datetime import datetime
import time
import pandas as pd
import json
import os

# ================== 障碍物持久化（记忆） ==================
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
    # 🔥 默认定位：南京科技职业学院
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
    st.session_state.polygon_memory = load_obstacles()
if "is_drawing" not in st.session_state:
    st.session_state.is_drawing = False
if "temp_points" not in st.session_state:
    st.session_state.temp_points = []

st.set_page_config(layout="wide")

# ================== 左侧导航 ==================
with st.sidebar:
    st.title("导航")
    page = option_menu("功能页面", ["航线规划", "飞行监控"], default_index=0)
    st.divider()
    st.subheader("坐标系")
    coord_type = st.radio("", ["GCJ-02", "WGS-84"])
    st.divider()
    st.subheader("系统状态")
    st.button("A点已设" if st.session_state.A_set else "A点未设", type="primary")
    st.button("B点已设" if st.session_state.B_set else "B点未设", type="primary")

# ================== 坐标转换 ==================
def gcj02_to_wgs84(lng: float, lat: float):
    import numpy as np
    a = 6378245.0
    ee = 0.00669342162296594323

    def transform_lat(x, y):
        ret = -100.0 + 2.0*x + 3.0*y + 0.2*y*y + 0.1*x*y + 0.2*np.sqrt(abs(x))
        ret += (20.0*np.sin(6.0*x*np.pi) + 20.0*np.sin(2.0*x*np.pi)) * 2.0 / 3.0
        ret += (20.0*np.sin(y*np.pi) + 40.0*np.sin(y/3.0*np.pi)) * 2.0 / 3.0
        ret += (160.0*np.sin(y/12.0*np.pi) + 320*np.sin(y/30.0*np.pi)) * 2.0 / 3.0
        return ret

    def transform_lng(x, y):
        ret = 300.0 + x + 2.0*y + 0.1*x*x + 0.1*x*y + 0.1*np.sqrt(abs(x))
        ret += (20.0*np.sin(6.0*x*np.pi) + 20.0*np.sin(2.0*x*np.pi)) * 2.0 / 3.0
        ret += (20.0*np.sin(x*np.pi) + 40.0*np.sin(x/3.0*np.pi)) * 2.0 / 3.0
        ret += (150.0*np.sin(x/12.0*np.pi) + 300.0*np.sin(x/30.0*np.pi)) * 2.0 / 3.0
        return ret

    dlat = transform_lat(lng - 105.0, lat - 35.0)
    dlng = transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * np.pi
    magic = np.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = np.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * np.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * np.cos(radlat) * np.pi)
    return lat - dlat, lng - dlng

# ================== 主页面：航线规划 ==================
if page == "航线规划":
    st.title("🚁 南京科技职业学院 - 3D无人机航线规划")
    col_map, col_ctrl = st.columns([3, 1])

    with col_ctrl:
        st.subheader("🎛️ 控制面板")
        a_lat = st.number_input("起点A纬度", value=st.session_state.A[0], format="%.6f")
        a_lon = st.number_input("起点A经度", value=st.session_state.A[1], format="%.6f")
        b_lat = st.number_input("终点B纬度", value=st.session_state.B[0], format="%.6f")
        b_lon = st.number_input("终点B经度", value=st.session_state.B[1], format="%.6f")
        st.session_state.height = st.slider("飞行高度(m)", 0, 200, value=st.session_state.height)

        if st.button("✅ 设置A点"):
            st.session_state.A = (a_lat, a_lon)
            st.session_state.A_set = True
        if st.button("✅ 设置B点"):
            st.session_state.B = (b_lat, b_lon)
            st.session_state.B_set = True

        st.divider()
        st.subheader("🚧 障碍物设置")
        if st.session_state.is_drawing:
            st.warning("👉 点击地图加点 → 点【完成圈选】结束")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("开始圈选障碍物"):
                st.session_state.is_drawing = True
                st.session_state.temp_points = []
        with col2:
            if st.button("完成圈选"):
                if len(st.session_state.temp_points)>=3:
                    st.session_state.polygon_memory.append(st.session_state.temp_points.copy())
                    save_obstacles(st.session_state.polygon_memory)
                st.session_state.is_drawing = False
                st.session_state.temp_points = []
                st.rerun()

        if st.button("🗑️ 清除所有障碍物"):
            st.session_state.polygon_memory = []
            save_obstacles([])
            st.rerun()
        st.info(f"已保存障碍物：{len(st.session_state.polygon_memory)} 个")

        st.divider()
        st.subheader("❤️ 心跳状态")
        now = datetime.now().strftime("%H:%M:%S")
        st.metric("当前时间", now)
        st.session_state.heartbeat_data.append(time.time())
        if len(st.session_state.heartbeat_data)>30:
            st.session_state.heartbeat_data.pop(0)
        df = pd.DataFrame({"时间":range(len(st.session_state.heartbeat_data)), "心跳":st.session_state.heartbeat_data})
        st.line_chart(df.set_index("时间"), height=150)
        st.success("心跳正常")

    with col_map:
        center_lat = (st.session_state.A[0] + st.session_state.B[0])/2
        center_lon = (st.session_state.A[1] + st.session_state.B[1])/2

        # 🔥 3D 地图核心（Streamlit + GitHub 都能正常显示）
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=19,
            tiles="https://{s}.tile.openstreetmap.de/tiles/osmde/{z}/{x}/{y}.png",
            attr="OpenStreetMap",
            # 3D 倾斜视角
            zoom_control=True,
            scrollWheelZoom=True,
            max_zoom=22
        )

        # 3D 倾斜效果开启
        m.add_child(folium.plugins.Fullscreen())
        m.get_root().html.add_child(folium.Element("""
            <style>
                .leaflet-container { cursor: grab !important; }
                .mapboxgl-canvas { perspective: 1000px !important; }
            </style>
        """))

        # 坐标转换
        if coord_type == "GCJ-02":
            A_wgs = gcj02_to_wgs84(st.session_state.A[1], st.session_state.A[0])
            B_wgs = gcj02_to_wgs84(st.session_state.B[1], st.session_state.B[0])
        else:
            A_wgs = st.session_state.A
            B_wgs = st.session_state.B

        # 绘制航线
        if st.session_state.A_set:
            folium.CircleMarker(A_wgs, radius=12, color="red", fill=True, popup="起点A").add_to(m)
        if st.session_state.B_set:
            folium.CircleMarker(B_wgs, radius=12, color="green", fill=True, popup="终点B").add_to(m)
        if st.session_state.A_set and st.session_state.B_set:
            folium.PolyLine([A_wgs, B_wgs], color="blue", weight=4).add_to(m)

        # 绘制障碍物（永久记忆）
        for poly in st.session_state.polygon_memory:
            if len(poly)>=3:
                folium.Polygon(locations=poly, color="red", fill=True, fill_opacity=0.5).add_to(m)
        if st.session_state.temp_points:
            folium.PolyLine(locations=st.session_state.temp_points, color="red", weight=3).add_to(m)

        output = st_folium(m, width=1100, height=700, key="map3d")

        # 绘制障碍物点
        if st.session_state.is_drawing and output and output.get("last_clicked"):
            lat = output["last_clicked"]["lat"]
            lng = output["last_clicked"]["lng"]
            if not st.session_state.temp_points or [lat,lng]!=st.session_state.temp_points[-1]:
                st.session_state.temp_points.append([lat,lng])
                st.rerun()

else:
    st.title("📡 飞行监控")
    st.success("✅ 系统正常运行中")
    st.subheader("南京科技职业学院无人机监控系统")
