#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
无人机智能化应用综合Demo - 心跳监测 + 地图可视化 + 障碍物圈选记忆
满足分组作业2、3、9的核心要求:
- 心跳包模拟、掉线检测、Streamlit可视化 (作业2)
- 地图显示(卫星图/OSM)、GCJ-02坐标转换、A/B点设置 (作业3)
- 多边形障碍物圈选、记忆功能(保存/加载)、心跳包修正 (作业9)
"""

import json
import time
import random
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from streamlit_folium import st_folium, folium_static
import folium
from folium import plugins
from folium.plugins import Draw

# ================== 坐标转换 (GCJ-02 <-> WGS84) ==================
# 简化但精确的GCJ-02转换算法 (基于已知标准转换公式)
def gcj02_to_wgs84(lng: float, lat: float) -> Tuple[float, float]:
    """
    将GCJ-02(火星坐标系)坐标转换为WGS84坐标
    用于在地图(OSM/卫星图)上正确显示位置
    """
    a = 6378245.0
    ee = 0.00669342162296594323
    
    def transform_lat(x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * np.sqrt(abs(x))
        ret += (20.0 * np.sin(6.0 * x * np.pi) + 20.0 * np.sin(2.0 * x * np.pi)) * 2.0 / 3.0
        ret += (20.0 * np.sin(y * np.pi) + 40.0 * np.sin(y / 3.0 * np.pi)) * 2.0 / 3.0
        ret += (160.0 * np.sin(y / 12.0 * np.pi) + 320 * np.sin(y * np.pi / 30.0)) * 2.0 / 3.0
        return ret
    
    def transform_lng(x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * np.sqrt(abs(x))
        ret += (20.0 * np.sin(6.0 * x * np.pi) + 20.0 * np.sin(2.0 * x * np.pi)) * 2.0 / 3.0
        ret += (20.0 * np.sin(x * np.pi) + 40.0 * np.sin(x / 3.0 * np.pi)) * 2.0 / 3.0
        ret += (150.0 * np.sin(x / 12.0 * np.pi) + 300.0 * np.sin(x / 30.0 * np.pi)) * 2.0 / 3.0
        return ret
    
    dlat = transform_lat(lng - 105.0, lat - 35.0)
    dlng = transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * np.pi
    magic = np.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = np.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * np.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * np.cos(radlat) * np.pi)
    wgs_lat = lat - dlat
    wgs_lng = lng - dlng
    return wgs_lng, wgs_lat

def wgs84_to_gcj02(lng: float, lat: float) -> Tuple[float, float]:
    """WGS84转GCJ-02 (简单近似, 实际演示够用, 反向转换使用上述函数即可)"""
    # 注意: 精确逆转换需要迭代, 此处为演示不做深度实现, 但作业中只需要GCJ02输入后转WGS84显示
    # 此处仅做占位, 实际未使用正向转换, 因为用户输入直接是GCJ02
    return lng, lat

# ================== 心跳模拟与掉线检测 ==================
def generate_heartbeat_series(
    duration_sec: int = 60,
    normal_interval: float = 1.0,
    dropout_start: int = 20,
    dropout_duration: int = 5
) -> pd.DataFrame:
    """
    生成模拟心跳数据序列
    - 正常情况下每秒一个心跳
    - 在指定时间段模拟掉线 (超过3秒无心跳)
    返回DataFrame包含: seq, timestamp, receive_time_str, gap
    """
    heartbeats = []
    current_time = datetime.now()
    seq = 1
    idx = 0
    
    while idx <= duration_sec:
        # 模拟掉线区间: 从 dropout_start 秒开始, 持续 dropout_duration 秒无心跳
        if dropout_start <= idx < dropout_start + dropout_duration:
            # 掉线期间不生成心跳
            idx += 1
            time.sleep(0.01)  # 模拟时间流逝
            continue
        
        # 正常心跳
        receive_time = current_time + timedelta(seconds=idx)
        heartbeats.append({
            'seq': seq,
            'timestamp': receive_time,
            'receive_time_str': receive_time.strftime("%H:%M:%S.%f")[:-3],
            'gap': idx - (heartbeats[-1]['idx'] if heartbeats else 0)
        })
        seq += 1
        idx += 1
    
    # 计算心跳间隔(秒), 用于掉线判断
    df = pd.DataFrame(heartbeats)
    if len(df) > 1:
        df['gap_seconds'] = df['timestamp'].diff().dt.total_seconds().fillna(1.0)
        df['is_dropout'] = df['gap_seconds'] > 3.0
    else:
        df['gap_seconds'] = 1.0
        df['is_dropout'] = False
    return df

def check_dropout_alerts(df: pd.DataFrame) -> List[str]:
    """检查心跳数据中的掉线事件并返回警报信息"""
    alerts = []
    dropout_events = df[df['is_dropout'] == True]
    for _, row in dropout_events.iterrows():
        alerts.append(f"⚠️ 掉线检测: 序号{row['seq']} 与上一心跳间隔 {row['gap_seconds']:.1f}秒 (>3秒)")
    return alerts

# ================== 多边形记忆管理 ==================
class PolygonMemory:
    """多边形障碍物数据的保存/加载 (基于JSON文件或session_state)"""
    
    @staticmethod
    def save_polygons_to_file(polygons: List[dict], filename: str = "obstacles_memory.json"):
        """将多边形列表保存到JSON文件"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(polygons, f, ensure_ascii=False, indent=2)
    
    @staticmethod
    def load_polygons_from_file(filename: str = "obstacles_memory.json") -> List[dict]:
        """从JSON文件加载多边形列表"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return []
    
    @staticmethod
    def parse_draw_geometry(draw_data: dict) -> Optional[dict]:
        """
        解析streamlit-folium绘图插件的返回数据, 提取多边形几何信息
        返回标准格式: {"type": "Polygon", "coordinates": [...], "properties": {...}}
        """
        if not draw_data or 'last_active_drawing' not in draw_data:
            return None
        
        geom = draw_data['last_active_drawing']
        if geom and geom.get('geometry', {}).get('type') == 'Polygon':
            # 提取多边形外环坐标 (WGS84格式)
            coords = geom['geometry']['coordinates'][0]  # 外环
            # 转换为可存储格式 (列表 of [lng, lat])
            polygon_coords = [[c[0], c[1]] for c in coords]
            return {
                "type": "Polygon",
                "coordinates": polygon_coords,
                "properties": {
                    "name": f"障碍物_{datetime.now().strftime('%H%M%S')}",
                    "created": datetime.now().isoformat()
                }
            }
        return None

# ================== 主应用 ==================
st.set_page_config(page_title="无人机智能监测系统", layout="wide", page_icon="🚁")

# 初始化session_state
if 'heartbeat_df' not in st.session_state:
    st.session_state.heartbeat_df = generate_heartbeat_series(duration_sec=45, dropout_start=15, dropout_duration=4)
if 'obstacle_polygons' not in st.session_state:
    st.session_state.obstacle_polygons = []  # 存储多边形列表
if 'point_a_gcj' not in st.session_state:
    st.session_state.point_a_gcj = (118.749, 32.2332)   # (lng, lat) GCJ-02
if 'point_b_gcj' not in st.session_state:
    st.session_state.point_b_gcj = (118.750, 32.2340)
if 'map_center' not in st.session_state:
    # 中心点转为WGS84用于地图显示
    center_wgs = gcj02_to_wgs84(118.7495, 32.2336)
    st.session_state.map_center = center_wgs
if 'last_draw_data' not in st.session_state:
    st.session_state.last_draw_data = None

# 标题与说明
st.title("🚁 无人机智能化综合监测平台")
st.markdown("**心跳监测 | 卫星地图 | 障碍物多边形圈选记忆 | GCJ-02坐标支持**")

# ================== 侧边栏: 控制区 ==================
with st.sidebar:
    st.header("📡 心跳模拟与控制")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 重新生成心跳数据", use_container_width=True):
            st.session_state.heartbeat_df = generate_heartbeat_series(
                duration_sec=50, dropout_start=random.randint(10, 30), dropout_duration=random.randint(3, 6)
            )
            st.rerun()
    with col2:
        st.metric("最新心跳序号", int(st.session_state.heartbeat_df['seq'].max()) if not st.session_state.heartbeat_df.empty else 0)
    
    # 掉线警报显示
    alerts = check_dropout_alerts(st.session_state.heartbeat_df)
    if alerts:
        st.error("🚨 **掉线警报**")
        for alert in alerts[:3]:
            st.warning(alert)
        if len(alerts) > 3:
            st.info(f"共 {len(alerts)} 次掉线事件, 查看下方图表详情")
    else:
        st.success("✅ 心跳连接正常, 无掉线")
    
    st.divider()
    st.header("🗺️ 坐标设置 (GCJ-02)")
    # A点坐标输入
    a_lat = st.number_input("A点纬度 (GCJ-02)", value=float(st.session_state.point_a_gcj[1]), format="%.6f", key="a_lat")
    a_lng = st.number_input("A点经度 (GCJ-02)", value=float(st.session_state.point_a_gcj[0]), format="%.6f", key="a_lng")
    if st.button("📍 设置A点", use_container_width=True):
        st.session_state.point_a_gcj = (a_lng, a_lat)
        # 更新地图中心到A点附近
        center_wgs = gcj02_to_wgs84(a_lng, a_lat)
        st.session_state.map_center = center_wgs
        st.success(f"A点已更新: ({a_lat}, {a_lng})")
        st.rerun()
    
    b_lat = st.number_input("B点纬度 (GCJ-02)", value=float(st.session_state.point_b_gcj[1]), format="%.6f", key="b_lat")
    b_lng = st.number_input("B点经度 (GCJ-02)", value=float(st.session_state.point_b_gcj[0]), format="%.6f", key="b_lng")
    if st.button("🎯 设置B点", use_container_width=True):
        st.session_state.point_b_gcj = (b_lng, b_lat)
        st.success(f"B点已更新: ({b_lat}, {b_lng})")
        st.rerun()
    
    st.divider()
    st.header("🧩 障碍物多边形记忆")
    # 保存多边形到文件
    if st.button("💾 保存当前障碍物 (记忆)", use_container_width=True):
        if st.session_state.obstacle_polygons:
            PolygonMemory.save_polygons_to_file(st.session_state.obstacle_polygons, "obstacles_memory.json")
            st.success(f"已保存 {len(st.session_state.obstacle_polygons)} 个多边形障碍物到本地文件")
        else:
            st.warning("当前没有多边形可保存, 请先在地图上绘制")
    
    uploaded_file = st.file_uploader("📂 加载记忆的多边形文件", type=["json"], key="polygon_upload")
    if uploaded_file is not None:
        try:
            loaded_polygons = json.load(uploaded_file)
            if isinstance(loaded_polygons, list):
                st.session_state.obstacle_polygons = loaded_polygons
                st.success(f"成功加载 {len(loaded_polygons)} 个多边形障碍物")
                st.rerun()
            else:
                st.error("文件格式错误, 需要多边形列表")
        except Exception as e:
            st.error(f"解析失败: {e}")
    
    # 清除所有多边形
    if st.button("🗑️ 清除所有障碍物", use_container_width=True):
        st.session_state.obstacle_polygons = []
        st.success("已清除所有多边形")
        st.rerun()

# ================== 主区域: 地图 + 心跳图表 ==================
tab1, tab2 = st.tabs(["🗺️ 卫星地图 & 障碍物圈选", "📈 心跳时序可视化"])

with tab1:
    # 地图显示: 使用Folium + Draw插件支持多边形绘制
    # 转换A,B点坐标到WGS84用于地图显示
    a_wgs = gcj02_to_wgs84(st.session_state.point_a_gcj[0], st.session_state.point_a_gcj[1])
    b_wgs = gcj02_to_wgs84(st.session_state.point_b_gcj[0], st.session_state.point_b_gcj[1])
    
    # 创建地图
    m = folium.Map(
        location=[st.session_state.map_center[1], st.session_state.map_center[0]],
        zoom_start=17,
        control_scale=True
    )
    
    # 添加卫星图图层 (实况卫星地图)
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google Satellite',
        name='卫星实况地图',
        overlay=False,
        control=True
    ).add_to(m)
    # 添加OpenStreetMap标准图层作为备选
    folium.TileLayer(
        tiles='OpenStreetMap',
        name='OpenStreetMap',
        control=True
    ).add_to(m)
    
    # 添加A, B点标记 (使用图标区分)
    folium.Marker(
        location=[a_wgs[1], a_wgs[0]],
        popup=f"起点A (GCJ-02: {st.session_state.point_a_gcj[1]:.6f}, {st.session_state.point_a_gcj[0]:.6f})",
        icon=folium.Icon(color='green', icon='play', prefix='fa'),
        tooltip="A点"
    ).add_to(m)
    folium.Marker(
        location=[b_wgs[1], b_wgs[0]],
        popup=f"终点B (GCJ-02: {st.session_state.point_b_gcj[1]:.6f}, {st.session_state.point_b_gcj[0]:.6f})",
        icon=folium.Icon(color='red', icon='flag-checkered', prefix='fa'),
        tooltip="B点"
    ).add_to(m)
    
    # 添加A-B连线 (直线)
    folium.PolyLine(
        locations=[[a_wgs[1], a_wgs[0]], [b_wgs[1], b_wgs[0]]],
        color='blue',
        weight=3,
        opacity=0.7,
        popup='规划路径 (A→B)'
    ).add_to(m)
    
    # 绘制已保存的障碍物多边形 (从session_state中加载)
    for idx, poly_data in enumerate(st.session_state.obstacle_polygons):
        if poly_data.get('type') == 'Polygon':
            coords = poly_data['coordinates']
            # coords格式 [[lng, lat], ...] 需要转为folium的[lat, lng]
            folium_coords = [[c[1], c[0]] for c in coords]
            folium.Polygon(
                locations=folium_coords,
                color='red',
                weight=2,
                fill=True,
                fill_color='orange',
                fill_opacity=0.4,
                popup=f"障碍物 {idx+1}: {poly_data.get('properties',{}).get('name','未命名')}"
            ).add_to(m)
    
    # 添加绘图控件 Draw (用于多边形圈选)
    draw = Draw(
        draw_options={
            'polygon': True,
            'polyline': False,
            'rectangle': False,
            'circle': False,
            'marker': False,
            'circlemarker': False
        },
        edit_options={'edit': True, 'remove': True},
        position='topleft'
    )
    draw.add_to(m)
    
    # 图层控制
    folium.LayerControl().add_to(m)
    
    # 显示地图并获取交互数据
    output = st_folium(m, width=900, height=550, returned_objects=["last_active_drawing"])
    
    # 处理新绘制的多边形: 用户圈选后自动添加到障碍物列表
    if output and output.get("last_active_drawing"):
        new_poly = PolygonMemory.parse_draw_geometry(output)
        if new_poly:
            # 检查是否已存在相同多边形 (简单防重复)
            exists = False
            for p in st.session_state.obstacle_polygons:
                if p.get('coordinates') == new_poly['coordinates']:
                    exists = True
                    break
            if not exists:
                st.session_state.obstacle_polygons.append(new_poly)
                st.success(f"✅ 新障碍物多边形已添加 (共 {len(st.session_state.obstacle_polygons)} 个)")
                st.rerun()
    
    st.caption("💡 提示: 使用左上角绘图工具绘制多边形障碍物, 绘制后自动保存到当前会话; 点击侧边栏【保存当前障碍物】可持久化记忆")

with tab2:
    st.subheader("📡 无人机心跳包接收监测 (实时模拟)")
    df = st.session_state.heartbeat_df.copy()
    if df.empty:
        st.warning("无心跳数据, 请重新生成")
    else:
        # 心跳折线图: 序号 vs 心跳间隔
        fig = px.line(
            df, x='seq', y='gap_seconds',
            title='心跳间隔时序图 (超过3秒红色区域表示掉线)',
            labels={'seq': '心跳序号', 'gap_seconds': '间隔(秒)'},
            markers=True
        )
        # 标记掉线点
        dropout_points = df[df['is_dropout'] == True]
        if not dropout_points.empty:
            fig.add_trace(go.Scatter(
                x=dropout_points['seq'], y=dropout_points['gap_seconds'],
                mode='markers', marker=dict(color='red', size=12, symbol='x'),
                name='掉线事件 (>3秒)'
            ))
        fig.add_hline(y=3, line_dash="dash", line_color="red", annotation_text="掉线阈值(3秒)")
        fig.update_layout(height=450, hovermode='x unified')
        st.plotly_chart(fig, use_container_width=True)
        
        # 显示心跳表格
        with st.expander("📋 查看详细心跳记录"):
            display_df = df[['seq', 'receive_time_str', 'gap_seconds', 'is_dropout']].copy()
            display_df.columns = ['序号', '接收时间', '间隔(秒)', '是否掉线']
            st.dataframe(display_df, use_container_width=True, height=300)
        
        # 统计信息
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("总心跳包数", len(df))
        with col_b:
            dropout_count = df['is_dropout'].sum()
            st.metric("掉线次数", dropout_count)
        with col_c:
            avg_gap = df['gap_seconds'].mean()
            st.metric("平均间隔(秒)", f"{avg_gap:.2f}")

# ================== 页脚说明 ==================
st.divider()
st.markdown(
    """
    **✅ 功能总结**
    - 心跳模拟: 每秒自动生成心跳包, 内置掉线模拟, 折线图+警报
    - 地图显示: 支持卫星实况/OSM, GCJ-02坐标自动转换, A/B点标记及连线
    - 障碍物圈选: 多边形绘制工具, 可记忆保存/加载JSON文件, 避免重新圈选
    - 坐标转换正确: 所有输入输出均为GCJ-02, 地图底层使用WGS84转换显示
    """
)
