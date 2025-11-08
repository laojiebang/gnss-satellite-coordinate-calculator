#!/usr/bin/env python3
import math
import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime, timezone, timedelta


MU = 3.986005e14  # m^3/s^2
OMEGA_E = 7.292115e-5  # rad/s, Earth rotation rate


def parse_float(s: str) -> float:
    return float(s.replace('D', 'E').replace('d', 'e'))


def read_file(path: str) -> list[str]:
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.readlines()


def split_header_body(lines: list[str]):
    header, body = [], []
    end = False
    for ln in lines:
        (header if not end else body).append(ln)
        if not end and 'END OF HEADER' in ln:
            end = True
    return header, body


def get_leap_seconds(header: list[str]) -> int:
    for ln in header:
        if 'LEAP SECONDS' in ln:
            try:
                return int(ln[:6])
            except Exception:
                return 18
    return 18


def parse_epoch_tokens(tokens: list[str]) -> datetime:
    yy = int(tokens[0]); year = 1900 + yy if yy >= 80 else 2000 + yy
    mo = int(tokens[1]); da = int(tokens[2])
    hh = int(tokens[3]); mm = int(tokens[4]); ss = int(float(tokens[5]))
    return datetime(year, mo, da, hh, mm, ss, tzinfo=timezone.utc)


def extract_gps_ephemeris(body: list[str]):
    """
    ====================================================================================
    从RINEX 2格式GPS导航文件中提取卫星广播星历参数
    RINEX 2格式: 每颗卫星占8行数据，每行80个字符
    ====================================================================================
    """
    ephs = []
    i = 0
    while i + 7 < len(body):
        seg = body[i:i+8]  # 提取一颗卫星的8行数据块
        i += 8
        
        # ============================================================================
        # 【参数提取 - 第1行(seg[0)]】卫星号和时钟参数
        # RINEX 2格式第1行结构: 
        #   列1-2: 卫星号(PRN, 2位数字)
        #   列3-22: 年(2位), 月, 日, 时, 分, 秒 (历元时间toc)
        #   列23-41: af0 (卫星钟差, 单位: 秒)
        #   列42-60: af1 (卫星钟速, 单位: 秒/秒)
        #   列61-79: af2 (卫星钟漂, 单位: 秒/秒²)
        # ============================================================================
        prn_raw = seg[0][0:2].strip()  # <-- 【PRN提取】从第1行前2列提取卫星号
        if not prn_raw:
            continue
        # GPS satellites are in RINEX 2 often without 'G' prefix
        if prn_raw.startswith('R') or prn_raw.startswith('E'):
            # skip non-GPS
            continue
        try:
            prn = f"G{int(prn_raw):02d}"  # <-- 【PRN格式化】转换为G01, G02等格式
        except ValueError:
            continue
        
        # <-- 【toc提取】从第1行第3列开始提取历元时间(年,月,日,时,分,秒)
        tks = seg[0][2:]  # 跳过前2列(卫星号)，提取剩余部分
        nums = re.findall(r'[+-]?\d+(?:\.\d*)?(?:[DEde][+-]?\d+)?', tks)  # 提取所有数字(支持科学计数法D/E格式)
        if len(nums) < 8:
            continue
        try:
            # <-- 【toc解析】前6个数字组成历元时间: 年(2位), 月, 日, 时, 分, 秒
            toc = parse_epoch_tokens(nums[:6])
            # <-- 【af0提取】第7个数字: 卫星钟差 (单位: 秒)
            af0 = parse_float(nums[6])
            # <-- 【af1提取】第8个数字: 卫星钟速 (单位: 秒/秒)
            af1 = parse_float(nums[7])
            # <-- 【af2提取】第9个数字(如果存在): 卫星钟漂 (单位: 秒/秒²)
            af2 = parse_float(nums[8]) if len(nums) > 8 else 0.0
        except (ValueError, IndexError):
            continue

        def four(ln: str):
            """
            ====================================================================================
            从RINEX 2格式的一行中提取4个参数
            RINEX 2格式: 每行从第4列(索引3)开始，每19个字符为一个字段，共4个字段
            列位置: 3-22, 22-41, 41-60, 60-79 (每个字段19个字符宽)
            修正: 使用正则表达式从整行提取所有数字，避免字段边界问题
            ====================================================================================
            """
            # 从第4列(索引3)开始，提取所有科学计数法数字（支持D/E格式）
            # 这样可以避免字段边界导致的数字截断问题
            line_content = ln[3:].strip()  # 跳过前3列
            # 提取所有完整的科学计数法数字
            numbers = re.findall(r'[+-]?\d+(?:\.\d+)?(?:[DEde][+-]?\d+)?', line_content)
            # 取前4个数字，如果不足4个则用0.0填充
            while len(numbers) < 4:
                numbers.append('0.0')
            return [parse_float(n) for n in numbers[:4]]  # 转换为浮点数

        try:
            # ============================================================================
            # 【参数提取 - 第2行(seg[1])】轨道参数1
            # 列3-22: IODE (星历表数据龄期, 无单位)
            # 列22-41: Crs (卫星矢径的正弦调和项改正振幅, 单位: 米)
            # 列41-60: Δn (平均角速度差, 单位: 弧度/秒)
            # 列60-79: M0 (参考历元的平近点角, 单位: 弧度)
            # ============================================================================
            IODE, Crs, DeltaN, M0 = four(seg[1])
            # <-- 【IODE提取】从第2行第1个字段提取
            # <-- 【Crs提取】从第2行第2个字段提取
            # <-- 【DeltaN提取】从第2行第3个字段提取 (公式中的Δn)
            # <-- 【M0提取】从第2行第4个字段提取 (公式中的M0)
            
            # ============================================================================
            # 【参数提取 - 第3行(seg[2])】轨道参数2
            # 列3-22: Cuc (升交距角的余弦调和项改正振幅, 单位: 弧度)
            # 列22-41: e (轨道第一偏心率, 无单位)
            # 列41-60: Cus (升交距角的正弦调和项改正振幅, 单位: 弧度)
            # 列60-79: √A (轨道半长轴的平方根, 单位: 米^0.5) <-- 【公式中的A来源】
            # ============================================================================
            Cuc, e, Cus, sqrtA = four(seg[2])
            # <-- 【Cuc提取】从第3行第1个字段提取
            # <-- 【e提取】从第3行第2个字段提取 (公式中的偏心率e)
            # <-- 【Cus提取】从第3行第3个字段提取
            # <-- 【sqrtA提取】从第3行第4个字段提取 (公式中的√A, 用于计算 a = (√A)²)
            
            # ============================================================================
            # 【参数提取 - 第4行(seg[3])】轨道参数3
            # 列3-22: Toe (星历表参考历元, 单位: GPS周内秒) <-- 【公式中的toe来源】
            # 列22-41: Cic (轨道倾角的余弦调和项改正振幅, 单位: 弧度)
            # 列41-60: Ω0 (参考历元的升交点赤经, 单位: 弧度) <-- 【公式中的Ω0来源】
            # 列60-79: Cis (轨道倾角的正弦调和项改正振幅, 单位: 弧度)
            # ============================================================================
            Toe, Cic, Omega0, Cis = four(seg[3])
            # <-- 【Toe提取】从第4行第1个字段提取 (公式中的toe, 用于计算 tk = t - toe)
            # <-- 【Cic提取】从第4行第2个字段提取
            # <-- 【Omega0提取】从第4行第3个字段提取 (公式中的Ω0)
            # <-- 【Cis提取】从第4行第4个字段提取
            
            # ============================================================================
            # 【参数提取 - 第5行(seg[4])】轨道参数4
            # 列3-22: i0 (参考历元的轨道倾角, 单位: 弧度) <-- 【公式中的i0来源】
            # 列22-41: Crc (卫星矢径的余弦调和项改正振幅, 单位: 米)
            # 列41-60: ω (近地点角距, 单位: 弧度) <-- 【公式中的ω来源】
            # 列60-79: Ω̇ (升交点赤经变化率, 单位: 弧度/秒) <-- 【公式中的Ω̇来源】
            # ============================================================================
            i0, Crc, omega, OmegaDot = four(seg[4])
            # <-- 【i0提取】从第5行第1个字段提取 (公式中的i0)
            # <-- 【Crc提取】从第5行第2个字段提取
            # <-- 【omega提取】从第5行第3个字段提取 (公式中的ω, 近地点角距)
            # <-- 【OmegaDot提取】从第5行第4个字段提取 (公式中的Ω̇)
            
            # ============================================================================
            # 【参数提取 - 第6行(seg[5])】轨道参数5
            # 列3-22: IDOT (轨道倾角变化率, 单位: 弧度/秒) <-- 【公式中的IDOT来源】
            # 列22-41: (保留字段, 通常为0)
            # 列41-60: (保留字段, 通常为0)
            # 列60-79: (保留字段, 通常为0)
            # ============================================================================
            IDOT, _, _, _ = four(seg[5])
            # <-- 【IDOT提取】从第6行第1个字段提取 (公式中的IDOT)
            # 后3个字段通常为0或保留，不使用
            
        except (ValueError, IndexError) as ex:
            continue

        # ============================================================================
        # 【参数存储】将所有提取的参数存储到字典中，供后续计算使用
        # ============================================================================
        ephs.append({
            'prn': prn,      # 卫星号 (G01, G02, ...)
            'toc': toc,      # 历元时间 (datetime对象)
            'af0': af0,      # 卫星钟差 (秒)
            'af1': af1,      # 卫星钟速 (秒/秒)
            'af2': af2,      # 卫星钟漂 (秒/秒²)
            'IODE': IODE,    # 星历表数据龄期
            'Crs': Crs,      # 卫星矢径的正弦调和项改正振幅 (米)
            'DeltaN': DeltaN,  # 平均角速度差 (弧度/秒) <-- 用于公式 n = n0 + Δn
            'M0': M0,        # 参考历元的平近点角 (弧度) <-- 用于公式 Mk = M0 + n·tk
            'Cuc': Cuc,      # 升交距角的余弦调和项改正振幅 (弧度)
            'e': e,          # 轨道第一偏心率 <-- 用于开普勒方程和真近点角计算
            'Cus': Cus,      # 升交距角的正弦调和项改正振幅 (弧度)
            'sqrtA': sqrtA,  # 轨道半长轴的平方根 (米^0.5) <-- 用于公式 a = (√A)²
            'Toe': Toe,      # 星历表参考历元 (GPS周内秒) <-- 用于公式 tk = t - toe
            'Cic': Cic,      # 轨道倾角的余弦调和项改正振幅 (弧度)
            'Omega0': Omega0,  # 参考历元的升交点赤经 (弧度) <-- 用于公式 Lk = Ω0 + (Ω̇ - ωe)·tk - ωe·toe
            'Cis': Cis,      # 轨道倾角的正弦调和项改正振幅 (弧度)
            'i0': i0,        # 参考历元的轨道倾角 (弧度) <-- 用于公式 ik = i0 + IDOT·tk + δi
            'Crc': Crc,      # 卫星矢径的余弦调和项改正振幅 (米)
            'omega': omega,  # 近地点角距 (弧度) <-- 用于公式 Φk = Vk + ω
            'OmegaDot': OmegaDot,  # 升交点赤经变化率 (弧度/秒) <-- 用于公式 Lk = Ω0 + (Ω̇ - ωe)·tk - ωe·toe
            'IDOT': IDOT     # 轨道倾角变化率 (弧度/秒) <-- 用于公式 ik = i0 + IDOT·tk + δi
        })
    return ephs


def utc_to_gps_seconds_of_week(dt_utc: datetime, leap_seconds: int) -> tuple[int, float]:
    gps_epoch = datetime(1980, 1, 6, tzinfo=timezone.utc)
    # GPS time = UTC + leap_seconds
    dt_gps = dt_utc + timedelta(seconds=leap_seconds)
    delta = dt_gps - gps_epoch
    total_seconds = delta.total_seconds()
    week = int(total_seconds // 604800)
    sow = total_seconds - week * 604800
    return week, sow


def normalize_tk(tk: float) -> float:
    # wrap to [-302400, 302400]
    half = 302400.0
    while tk > half:
        tk -= 604800.0
    while tk < -half:
        tk += 604800.0
    return tk


def normalize_angle(x: float) -> float:
    # wrap angle to [-pi, pi]
    x = (x + math.pi) % (2.0 * math.pi) - math.pi
    return x


def compute_gps_ecef(e: dict, t_obs_utc: datetime, leap_seconds: int):
    """
    ====================================================================================
    计算GPS卫星在地心地固坐标系(ECEF)中的坐标
    按照RINEX 2格式GPS广播星历参数计算，参考IS-GPS-200标准
    ====================================================================================
    """
    
    # ============================================================================
    # 【步骤1】计算轨道半长轴 a (单位: m)
    # 公式: a = (√A)²
    # <-- 【A的使用】A来自星历参数sqrtA，在extract_gps_ephemeris函数中从RINEX文件提取
    # ============================================================================
    a = e['sqrtA'] * e['sqrtA']  # <-- e['sqrtA'] 是从RINEX文件第3行提取的√A值
    
    # ============================================================================
    # 【步骤2】计算平均角速度 n0 和修正后的平均角速度 n (单位: rad/s)
    # 公式(4.27): n0 = √(μ / a³) 其中 μ = 3.986005×10¹⁴ m³/s² (地球引力常数)
    # 公式(4.28): n = n0 + Δn  (Δn 是星历中给出的摄动修正值)
    # ============================================================================
    n0 = math.sqrt(MU / (a ** 3))
    n = n0 + e['DeltaN']
    
    # ============================================================================
    # 【步骤3】计算归化时间 tk (单位: s)
    # 公式(4.29): tk = t - toe
    # <-- 【t的使用】t是观测时间，从GUI界面输入框获取，格式为UTC时间
    # 其中: t_obs_utc 是用户输入的UTC观测时间，通过utc_to_gps_seconds_of_week转换为GPS周内秒(sow)
    #       toe 是星历参考历元(从星历中读取的Toe参数，单位: GPS周内秒)
    # 注意: tk 需要归一化到 [-302400, 302400] 秒范围内(±0.5周)
    # ============================================================================
    _, sow = utc_to_gps_seconds_of_week(t_obs_utc, leap_seconds)  # <-- t转换为GPS周内秒
    tk = normalize_tk(sow - e['Toe'])  # <-- tk = t - toe，其中t=sow(观测时刻GPS周内秒)，toe=e['Toe'](星历参考历元)

    # ============================================================================
    # 【步骤4】计算观测时刻的平近点角 Mk (单位: rad)
    # 公式(4.30): Mk = M0 + n·tk
    # 其中: M0 是参考历元toe时的平近点角(从星历中读取)
    # ============================================================================
    Mk = e['M0'] + n * tk

    # ============================================================================
    # 【步骤5】计算偏近点角 Ek (单位: rad) - 迭代求解开普勒方程
    # 公式(4.31): Ek = Mk + e·sin(Ek)  (开普勒方程，需迭代求解)
    # 迭代方法: Ek^(i+1) = Mk + e·sin(Ek^(i))
    # 初始值: Ek^(0) = Mk
    # 收敛条件: |Ek^(i+1) - Ek^(i)| < 1e-12
    # 注意: GPS卫星轨道偏心率e很小(约0.01)，通常2-3次迭代即可收敛
    # ============================================================================
    Ek = Mk
    for _ in range(10):
        Ek_next = Mk + e['e'] * math.sin(Ek)
        if abs(Ek_next - Ek) < 1e-12:
            Ek = Ek_next; break
        Ek = Ek_next

    # ============================================================================
    # 【步骤6】计算真近点角 Vk (单位: rad)
    # 公式(4.32): 
    #   cos(Vk) = (cos(Ek) - e) / (1 - e·cos(Ek))
    #   sin(Vk) = (√(1-e²)·sin(Ek)) / (1 - e·cos(Ek))
    # 公式(4.33): Vk = arctan(sin(Vk), cos(Vk))
    # ============================================================================
    sin_vk = math.sqrt(1 - e['e']**2) * math.sin(Ek) / (1 - e['e'] * math.cos(Ek))
    cos_vk = (math.cos(Ek) - e['e']) / (1 - e['e'] * math.cos(Ek))
    Vk = math.atan2(sin_vk, cos_vk)

    # ============================================================================
    # 【步骤7】计算升交距角(未修正的纬度幅角) Φk (单位: rad)
    # 公式(4.34): Φk = Vk + ω
    # 其中: ω 是近地点角距(argument of perigee, 从星历中读取)
    # ============================================================================
    Phi = Vk + e['omega']

    # ============================================================================
    # 【步骤8】计算摄动改正项 δu, δr, δi
    # 公式(4.26): 
    #   δu = Cus·sin(2Φk) + Cuc·cos(2Φk)  (升交距角改正, 单位: rad)
    #   δr = Crs·sin(2Φk) + Crc·cos(2Φk)  (卫星矢径改正, 单位: m)
    #   δi = Cis·sin(2Φk) + Cic·cos(2Φk)  (轨道倾角改正, 单位: rad)
    # 其中: Cus, Cuc, Crs, Crc, Cis, Cic 是星历中给出的6个调和改正振幅
    # ============================================================================
    du = e['Cus'] * math.sin(2*Phi) + e['Cuc'] * math.cos(2*Phi)
    dr = e['Crs'] * math.sin(2*Phi) + e['Crc'] * math.cos(2*Phi)
    di = e['Cis'] * math.sin(2*Phi) + e['Cic'] * math.cos(2*Phi)

    # ============================================================================
    # 【步骤9】计算经摄动改正后的升交距角、卫星矢径和轨道倾角
    # 公式(4.35):
    #   uk = Φk + δu  (修正后的升交距角, 单位: rad)
    #   rk = a·(1 - e·cos(Ek)) + δr  (修正后的卫星矢径, 单位: m)
    #   ik = i0 + IDOT·tk + δi  (修正后的轨道倾角, 单位: rad)
    # 其中: i0 是参考历元时的轨道倾角, IDOT 是轨道倾角变化率
    # ============================================================================
    u = normalize_angle(Phi + du)  # 归一化到[-π, π]以提高数值稳定性
    r = a * (1 - e['e'] * math.cos(Ek)) + dr
    i_k = e['i0'] + e['IDOT'] * tk + di

    # ============================================================================
    # 【步骤10】计算卫星在轨道平面坐标系中的坐标 (单位: m)
    # 公式(4.36):
    #   xk = rk·cos(uk)
    #   yk = rk·sin(uk)
    #   zk = 0  (轨道平面内z坐标为0)
    # 坐标系定义: x轴指向升交点方向, y轴与x轴垂直形成右手系, z轴垂直于轨道平面
    # ============================================================================
    x_prime = r * math.cos(u)
    y_prime = r * math.sin(u)

    # ============================================================================
    # 【步骤11】计算观测时刻t的升交点大地经度 Lk (单位: rad)
    # 公式(4.43): Lk = Ω0 + (Ω̇ - ωe)·tk
    # 其中: 
    #   Ω0 是参考历元toe时的升交点赤经(从星历中读取, 单位: rad)
    #   Ω̇ 是升交点赤经变化率(从星历中读取, 单位: rad/s)
    #   ωe = 7.292115×10⁻⁵ rad/s (地球自转角速度)
    #   tk = t - toe (归化时间)
    # 注意: 这里计算的是地固坐标系中的升交点经度，考虑了地球自转
    # 修正: 根据GPS ICD-200标准，公式中不需要 -ωe·toe 项，因为toe已经包含在tk的计算中
    # ============================================================================
    Omega_k = e['Omega0'] + (e['OmegaDot'] - OMEGA_E) * tk
    # 归一化到[0, 2π]范围
    Omega_k = Omega_k % (2.0 * math.pi)

    # ============================================================================
    # 【步骤12】计算卫星在地心地固坐标系(ECEF/WGS-84)中的坐标 (单位: m)
    # 公式(4.46): 通过旋转矩阵将轨道平面坐标转换到ECEF坐标系
    #   X = xk·cos(Lk) - yk·cos(ik)·sin(Lk)
    #   Y = xk·sin(Lk) + yk·cos(ik)·cos(Lk)
    #   Z = yk·sin(ik)
    # 坐标系: WGS-84地心地固坐标系, 原点在地心, Z轴指向北极, X轴指向本初子午线与赤道交点
    # ============================================================================
    X = x_prime * math.cos(Omega_k) - y_prime * math.cos(i_k) * math.sin(Omega_k)
    Y = x_prime * math.sin(Omega_k) + y_prime * math.cos(i_k) * math.cos(Omega_k)
    Z = y_prime * math.sin(i_k)
    
    return X, Y, Z, {
        'a': a, 'n0': n0, 'n': n, 'tk': tk, 'Mk': Mk, 'Ek': Ek, 'Vk': Vk,
        'Phi': Phi, 'u': u, 'r': r, 'i': i_k, 'Omega_k': Omega_k
    }


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('GNSS卫星坐标计算器')
        self.geometry('900x700')  # 增加窗口高度以显示更多内容
        try:
            style = ttk.Style()
            if 'clam' in style.theme_names():
                style.theme_use('clam')
        except Exception:
            pass

        # 设置默认文件路径（相对于程序所在目录）
        # 程序结构: GNSS小程序/app/gui_gnss.py
        # 星历文件放在: GNSS小程序/nav/GPS_Broadcast_Ephemeris_RINEX.n
        script_dir = os.path.dirname(os.path.abspath(__file__))  # app目录
        root_dir = os.path.dirname(script_dir)  # GNSS小程序目录
        nav_dir = os.path.join(root_dir, 'nav')  # nav文件夹
        self.default_file = os.path.join(nav_dir, 'GPS_Broadcast_Ephemeris_RINEX.n')
        self.default_time = '2023-09-09 00:00:09'
        
        # 使用相对路径显示（相对于GNSS小程序目录）
        if os.path.exists(self.default_file):
            # 显示相对路径 nav/GPS_Broadcast_Ephemeris_RINEX.n
            rel_path = os.path.relpath(self.default_file, root_dir)
            self.file_path = tk.StringVar(value=rel_path)
        else:
            self.file_path = tk.StringVar(value='')
        self.obs_time = tk.StringVar(value=self.default_time)  # 默认观测时间
        self.leap_seconds = 18
        self.ephs = []
        
        # 保存根目录和nav目录路径，用于路径转换
        self.root_dir = root_dir
        self.nav_dir = nav_dir

        self._build_ui()
        
        # 绑定变量变化事件，用于检测用户是否修改了默认值
        self.file_path.trace_add('write', self._on_file_changed)
        self.obs_time.trace_add('write', self._on_time_changed)
        
        # 如果默认文件存在，自动加载星历
        if os.path.exists(self.default_file):
            self.after(100, self.auto_load_default)  # 延迟100ms后自动加载，确保UI已完全初始化

    def _build_ui(self):
        # 创建主容器和滚动条
        main_container = ttk.Frame(self)
        main_container.pack(fill='both', expand=True)
        
        # 创建Canvas和Scrollbar
        canvas = tk.Canvas(main_container)
        scrollbar = ttk.Scrollbar(main_container, orient='vertical', command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        scrollable_frame.bind("<Configure>", _on_frame_configure)
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 确保canvas窗口宽度正确
        def _on_canvas_configure(event):
            canvas_width = event.width
            canvas.itemconfig(canvas_window, width=canvas_width)
        canvas.bind('<Configure>', _on_canvas_configure)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮事件（支持Windows、Linux和macOS）
        def _on_mousewheel(event):
            # Windows
            if event.delta:
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            # Linux
            elif event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
        # 绑定不同平台的滚轮事件
        canvas.bind_all("<MouseWheel>", _on_mousewheel)  # Windows
        canvas.bind_all("<Button-4>", _on_mousewheel)   # Linux向上
        canvas.bind_all("<Button-5>", _on_mousewheel)   # Linux向下
        
        # 使用scrollable_frame作为主框架
        frm = scrollable_frame
        frm.configure(padding=10)
        
        # 保存canvas引用，用于更新滚动区域
        self.canvas = canvas
        self.scrollable_frame = scrollable_frame

        row = 0
        ttk.Label(frm, text='导航文件：').grid(row=row, column=0, sticky='e')
        ttk.Entry(frm, textvariable=self.file_path, width=60).grid(row=row, column=1, sticky='we', padx=6)
        ttk.Button(frm, text='选择文件', command=self.choose_file).grid(row=row, column=2)

        row += 1
        # 默认文件提示
        self.lbl_default_file = ttk.Label(frm, text='默认文件', foreground='blue', font=('', 9))
        self.lbl_default_file.grid(row=row, column=1, sticky='w', padx=6)
        row += 1
        # 手动选择提示
        self.lbl_manual_hint = ttk.Label(frm, text='如需使用其他文件，请点击选择文件手动添加', 
                                         foreground='gray', font=('', 8))
        self.lbl_manual_hint.grid(row=row, column=1, sticky='w', padx=6)

        row += 1
        ttk.Label(frm, text='观测时间(UTC)：').grid(row=row, column=0, sticky='e')
        ttk.Entry(frm, textvariable=self.obs_time, width=25).grid(row=row, column=1, sticky='w', padx=6)
        ttk.Label(frm, text='格式：YYYY-MM-DD HH:MM:SS').grid(row=row, column=2, sticky='w')
        
        row += 1
        # 默认时间提示
        self.lbl_default_time = ttk.Label(frm, text='默认时间', foreground='blue', font=('', 9))
        self.lbl_default_time.grid(row=row, column=1, sticky='w', padx=6)
        row += 1
        # 时间格式提示
        self.lbl_time_format_hint = ttk.Label(frm, text='必须严格按照右边的格式填写观测时间', 
                                               foreground='gray', font=('', 8))
        self.lbl_time_format_hint.grid(row=row, column=1, sticky='w', padx=6)

        row += 1
        ttk.Label(frm, text='选择卫星：').grid(row=row, column=0, sticky='e')
        self.cbo_sv = ttk.Combobox(frm, state='readonly', width=10)
        self.cbo_sv.grid(row=row, column=1, sticky='w', padx=6)
        ttk.Button(frm, text='解析星历', command=self.load_nav).grid(row=row, column=2, sticky='w')

        row += 1
        ttk.Button(frm, text='计算坐标', command=self.calculate).grid(row=row, column=1, sticky='w')

        row += 1
        ttk.Label(frm, text='提取的参数：').grid(row=row, column=0, sticky='ne')
        self.tree = ttk.Treeview(frm, columns=('k','v'), show='headings', height=14)
        self.tree.heading('k', text='参数')
        self.tree.heading('v', text='数值')
        self.tree.column('k', width=160)
        self.tree.column('v', width=460)
        self.tree.grid(row=row, column=1, columnspan=2, sticky='nsew', padx=6, pady=6)

        row += 1
        ttk.Label(frm, text='卫星地心地固坐标：').grid(row=row, column=0, sticky='ne')
        self.tree_xyz = ttk.Treeview(frm, columns=('axis','value_m','value_km'), show='headings', height=4)
        self.tree_xyz.heading('axis', text='坐标轴')
        self.tree_xyz.heading('value_m', text='数值 (m)')
        self.tree_xyz.heading('value_km', text='数值 (km)')
        self.tree_xyz.column('axis', width=100)
        self.tree_xyz.column('value_m', width=260)
        self.tree_xyz.column('value_km', width=260)
        self.tree_xyz.grid(row=row, column=1, columnspan=2, sticky='nsew', padx=6, pady=6)

        row += 1
        ttk.Label(frm, text='卫星与地心距离：').grid(row=row, column=0, sticky='ne')
        self.tree_distance = ttk.Treeview(frm, columns=('axis','value_m','value_km'), show='headings', height=1)
        self.tree_distance.heading('axis', text='坐标轴')
        self.tree_distance.heading('value_m', text='数值 (m)')
        self.tree_distance.heading('value_km', text='数值 (km)')
        self.tree_distance.column('axis', width=100)
        self.tree_distance.column('value_m', width=260)
        self.tree_distance.column('value_km', width=260)
        self.tree_distance.grid(row=row, column=1, columnspan=2, sticky='nsew', padx=6, pady=6)

        frm.grid_columnconfigure(1, weight=1)
        frm.grid_rowconfigure(4, weight=1)
        
        # 初始化提示标签的显示状态（延迟执行，确保所有组件都已创建）
        self.after(50, self._update_default_hints)
        
        # 更新canvas滚动区域
        self.after(100, self._update_scroll_region)

    def _update_scroll_region(self):
        """更新canvas的滚动区域"""
        if hasattr(self, 'canvas') and hasattr(self, 'scrollable_frame'):
            self.canvas.update_idletasks()
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _get_absolute_path(self, path: str) -> str:
        """将相对路径或绝对路径转换为绝对路径"""
        if not path:
            return ''
        if os.path.isabs(path):
            return path
        # 相对路径：先尝试相对于nav目录，再尝试相对于根目录
        nav_path = os.path.join(self.nav_dir, path)
        if os.path.exists(nav_path):
            return nav_path
        root_path = os.path.join(self.root_dir, path)
        if os.path.exists(root_path):
            return root_path
        return path  # 如果都不存在，返回原路径（可能用户输入了其他路径）

    def _get_relative_path(self, path: str) -> str:
        """将绝对路径转换为相对路径（相对于根目录）"""
        if not path:
            return ''
        try:
            return os.path.relpath(path, self.root_dir)
        except ValueError:
            return path  # 如果无法转换，返回原路径

    def _update_default_hints(self):
        """更新默认值提示标签的显示状态"""
        # 检查文件是否为默认文件（使用相对路径比较）
        current_file = self.file_path.get()
        default_rel_path = self._get_relative_path(self.default_file)
        is_default_file = (os.path.exists(self.default_file) and 
                          current_file and 
                          current_file == default_rel_path)
        
        if is_default_file:
            self.lbl_default_file.config(text='默认文件', foreground='blue')
            self.lbl_manual_hint.config(text='如需使用其他文件，请点击选择文件手动添加', foreground='gray')
        else:
            self.lbl_default_file.config(text='', foreground='blue')
            self.lbl_manual_hint.config(text='', foreground='gray')
        
        # 检查时间是否为默认时间
        current_time = self.obs_time.get()
        is_default_time = current_time == self.default_time
        
        if is_default_time:
            self.lbl_default_time.config(text='默认时间', foreground='blue')
        else:
            self.lbl_default_time.config(text='', foreground='blue')

    def choose_file(self):
        path = filedialog.askopenfilename(
            title='选择RINEX导航文件',
            filetypes=[
                ('GPS导航文件 (*.n)', '*.n'),
                ('GPS导航文件 (*.N)', '*.N'),
                ('GLONASS导航文件 (*.g)', '*.g'),
                ('GLONASS导航文件 (*.G)', '*.G'),
                ('所有文件', '*.*')
            ],
            defaultextension='.n',
            initialdir=self.nav_dir  # 默认打开nav目录
        )
        if path:
            # 转换为相对路径显示
            rel_path = self._get_relative_path(path)
            self.file_path.set(rel_path)

    def _on_file_changed(self, *args):
        """当文件路径改变时，更新默认文件提示的显示状态"""
        self._update_default_hints()

    def _on_time_changed(self, *args):
        """当观测时间改变时，更新默认时间提示的显示状态"""
        self._update_default_hints()

    def auto_load_default(self):
        """
        自动加载默认文件（静默加载，不显示消息框）
        """
        file_path = self._get_absolute_path(self.file_path.get())
        if file_path and os.path.exists(file_path):
            try:
                lines = read_file(file_path)
            except Exception:
                return  # 如果加载失败，静默失败，用户可以手动点击解析
            if not lines:
                return
            header, body = split_header_body(lines)
            if not body:
                return
            # 检查文件类型
            file_type = 'UNKNOWN'
            for ln in header:
                if 'GLONASS' in ln.upper():
                    file_type = 'GLONASS'
                    break
                elif 'GPS' in ln.upper() or 'NAV DATA' in ln.upper():
                    file_type = 'GPS'
                    break
            fname = self.file_path.get().lower()
            if file_type == 'UNKNOWN':
                if fname.endswith('.g'):
                    file_type = 'GLONASS'
                elif fname.endswith('.n'):
                    file_type = 'GPS'
            if file_type == 'GLONASS':
                return  # GLONASS文件不自动加载
            self.leap_seconds = get_leap_seconds(header)
            self.ephs = extract_gps_ephemeris(body)
            if self.ephs:
                svs = sorted({e['prn'] for e in self.ephs})
                self.cbo_sv['values'] = svs
                if svs:
                    self.cbo_sv.set(svs[0])

    def load_nav(self):
        if not self.file_path.get():
            messagebox.showwarning('提示', '请先选择导航文件。')
            return
        file_path = self._get_absolute_path(self.file_path.get())
        if not os.path.exists(file_path):
            messagebox.showerror('错误', f'文件不存在：{file_path}\n请确保文件已放在nav文件夹中。')
            return
        try:
            lines = read_file(file_path)
        except Exception as ex:
            messagebox.showerror('错误', f'无法读取文件：{ex}')
            return
        if not lines:
            messagebox.showerror('错误', '文件为空。')
            return
        header, body = split_header_body(lines)
        if not body:
            messagebox.showerror('错误', '文件中没有星历数据。')
            return
        # Check file type from header
        file_type = 'UNKNOWN'
        for ln in header:
            if 'GLONASS' in ln.upper():
                file_type = 'GLONASS'
                break
            elif 'GPS' in ln.upper() or 'NAV DATA' in ln.upper():
                file_type = 'GPS'
                break
        # Also check filename extension
        fname = self.file_path.get().lower()
        if file_type == 'UNKNOWN':
            if fname.endswith('.g'):
                file_type = 'GLONASS'
            elif fname.endswith('.n'):
                file_type = 'GPS'
        if file_type == 'GLONASS':
            messagebox.showwarning('提示', '当前文件是GLONASS格式（.g），本程序目前仅支持GPS格式（.n）。\n请选择GPS广播星历文件（brdc*.n）。')
            self.cbo_sv['values'] = []
            return
        self.leap_seconds = get_leap_seconds(header)
        self.ephs = extract_gps_ephemeris(body)
        if not self.ephs:
            messagebox.showwarning('提示', '未在文件中找到GPS星历记录。\n请确认文件是RINEX 2格式的GPS导航文件（.n）。')
            self.cbo_sv['values'] = []
            return
        svs = sorted({e['prn'] for e in self.ephs})
        self.cbo_sv['values'] = svs
        self.cbo_sv.set(svs[0])
        messagebox.showinfo('完成', f'解析到 {len(self.ephs)} 条GPS星历；闰秒={self.leap_seconds}')

    def fill_params(self, eph: dict):
        self.tree.delete(*self.tree.get_children())
        show_keys = ['af0','af1','af2','IODE','Crs','DeltaN','M0','Cuc','e','Cus','sqrtA','Toe','Cic','Omega0','Cis','i0','Crc','omega','OmegaDot','IDOT']
        for k in show_keys:
            self.tree.insert('', 'end', values=(k, f"{eph[k]:.12e}" if isinstance(eph[k], float) else str(eph[k])))

    def calculate(self):
        if not self.ephs:
            messagebox.showwarning('提示', '请先解析星历。')
            return
        sv = self.cbo_sv.get()
        if not sv:
            messagebox.showwarning('提示', '请选择一个卫星。')
            return
        try:
            # <-- 【公式中的t来源】观测时间t从GUI界面的"观测时间(UTC)"输入框获取
            # 用户输入的格式: YYYY-MM-DD HH:MM:SS (UTC时间)
            # 例如: "2023-09-10 00:00:00"
            t = datetime.strptime(self.obs_time.get(), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        except Exception:
            messagebox.showerror('错误', '观测时间格式应为 YYYY-MM-DD HH:MM:SS')
            return
        # pick the record with Toe closest to observation time within same file
        # <-- 【t的转换】将UTC时间t转换为GPS周内秒(sow)，用于后续计算 tk = t - toe
        _, sow = utc_to_gps_seconds_of_week(t, self.leap_seconds)
        cand = [e for e in self.ephs if e['prn'] == sv]
        if not cand:
            messagebox.showerror('错误', f'未找到 {sv} 的星历记录')
            return
        e = min(cand, key=lambda x: abs((sow - x['Toe'] + 302400) % 604800 - 302400))
        self.fill_params(e)
        X, Y, Z, _ = compute_gps_ecef(e, t, self.leap_seconds)
        # 使用Treeview显示坐标（包含m和km两列）
        self.tree_xyz.delete(*self.tree_xyz.get_children())
        self.tree_xyz.insert('', 'end', values=('X', f'{X:,.3f}', f'{X/1000:,.6f}'))
        self.tree_xyz.insert('', 'end', values=('Y', f'{Y:,.3f}', f'{Y/1000:,.6f}'))
        self.tree_xyz.insert('', 'end', values=('Z', f'{Z:,.3f}', f'{Z/1000:,.6f}'))
        
        # 计算并显示卫星与地心的距离
        distance = math.sqrt(X**2 + Y**2 + Z**2)
        self.tree_distance.delete(*self.tree_distance.get_children())
        self.tree_distance.insert('', 'end', values=('D', f'{distance:,.3f}', f'{distance/1000:,.6f}'))
        
        # 更新滚动区域，确保新内容可见
        self._update_scroll_region()


if __name__ == '__main__':
    App().mainloop()


