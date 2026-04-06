import json
import random
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from streamlit_folium import st_folium
import folium
from folium.plugins import Draw

# ================== GCJ-02 转 WGS84 ==================
def gcj02_to_wgs84(lng: float, lat: float):
    a = 6378245.0
    ee = 0.006693421622965943

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

# ================== 心跳模拟 ==================
def generate_heartbeat():
    hb = []
    now = datetime.now()
    seq = 1
    drop_start = random.randint(10, 30)
    drop_dur = random.randint(3, 6)
    for i in range(60):
        if drop_start <= i < drop_start + drop_dur:
            continue
        ts = now + timedelta(seconds=i)
        hb.append({
            "seq": seq,
            "timestamp": ts,
            "time_str": ts.strftime("%H:%M:%S"),
            "idx": i
        })
        seq += 1
    df = pd.DataFrame(hb)
    df["gap"] = df["timestamp"].diff().dt.total_seconds().fillna(1)
    df["dropout"] = df["gap"] > 3
    return df

# ================== 主界面 ==================
st.set_page_config(page_title="无人机监测", layout="wide")
st.title("🚁 无人机心跳 + 地图 + 障碍物圈选")

if "hb" not in st.session_state:
    st.session_state.hb = generate_heartbeat()
if "obs" not in st.session_state:
    st.session_state.obs = []

# ================== 侧边栏 ==================
with st.sidebar:
    st.subheader("📡 心跳控制")
    if st.button("重新生成心跳"):
        st.session_state.hb = generate_heartbeat()
        st.rerun()

    drop_cnt = st.session_state.hb["dropout"].sum()
    st.metric("掉线次数", int(drop_cnt))

    st.divider()
    st.subheader("🗺️ 坐标 A/B")
    a_lat = st.number_input("A纬度", 32.2332, format="%.6f")
    a_lng = st.number_input("A经度", 118.7490, format="%.6f")
    b_lat = st.number_input("B纬度", 32.2340, format="%.6f")
    b_lng = st.number_input("B经度", 118.7500, format="%.6f")

    st.divider()
    st.subheader("🧩 障碍物")
    if st.button("清空障碍物"):
        st.session_state.obs = []
        st.rerun()

# ================== 地图 ==================
tab1, tab2 = st.tabs(["地图", "心跳监测"])

with tab1:
    a_lat_wgs, a_lng_wgs = gcj02_to_wgs84(a_lng, a_lat)
    b_lat_wgs, b_lng_wgs = gcj02_to_wgs84(b_lng, b_lat)

    m = folium.Map(location=[a_lat_wgs, a_lng_wgs], zoom_start=17)
    folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google').add_to(m)
    folium.TileLayer('OpenStreetMap').add_to(m)

    folium.Marker([a_lat_wgs, a_lng_wgs], icon=folium.Icon(color="green"), tooltip="A").add_to(m)
    folium.Marker([b_lat_wgs, b_lng_wgs], icon=folium.Icon(color="red"), tooltip="B").add_to(m)
    folium.PolyLine([[a_lat_wgs,a_lng_wgs],[b_lat_wgs,b_lng_wgs]], color="blue").add_to(m)

    for p in st.session_state.obs:
        coords = [[c[1], c[0]] for c in p["coords"]]
        folium.Polygon(locations=coords, color="red", fill=True, fill_opacity=0.4).add_to(m)

    draw = Draw(draw_options={"polygon": True}, edit_options={"edit": True})
    draw.add_to(m)
    out = st_folium(m, key="map", width=900, height=550)

    if out and "last_active_drawing" in out and out["last_active_drawing"]:
        geom = out["last_active_drawing"]["geometry"]
        if geom["type"] == "Polygon":
            coords = geom["coordinates"][0]
            exist = any(p["coords"] == coords for p in st.session_state.obs)
            if not exist:
                st.session_state.obs.append({"coords": coords})
                st.success("已添加障碍物")
                st.rerun()

with tab2:
    df = st.session_state.hb
    fig = px.line(df, x="seq", y="gap", markers=True, title="心跳间隔")
    fig.add_hline(y=3, line_dash="dash", line_color="red")
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("心跳记录"):
        st.dataframe(df[["seq","time_str","gap","dropout"]])

st.info("✅ 已支持 GitHub 部署 + Streamlit Cloud 在线运行")
