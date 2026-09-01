"""
原神爆发触发 · 舞台灯光特效（独立进程 v3）
==========================================
真正的半透明灯光特效：
  - tkinter 创建顶层窗口（经验证本机可正常合成显示）
  - UpdateLayeredWindow 每像素 alpha（AC_SRC_ALPHA 预乘），加法混合渲染
  - 无子控件 + 全窗口 WS_EX_TRANSPARENT：鼠标完全穿透，不影响游戏操作
  - 内部分辨率 640x360，4 倍上采样 + 高斯模糊柔边
  - 队伍面板角标区域（protected_region）保持完全透明，不干扰检测

命令（stdin 逐行）:
  start <duration_seconds>   开始灯光秀：四种效果按周期轮换，结束前淡出
  stop                       立即停止并清屏
  quit                       退出进程

自测:
  python fx_server.py --demo 5    # 演示 5 秒后自动退出（不读 stdin）

效果（舞台灯光风格，红/紫/绿，加法混合半透明）:
  0 顶部探照灯（多色宽光束，缓慢摆动，柔边透光）
  1 旋转镭射（中心细光束旋转）
  2 扫射光柱（宽柱横移）
  3 霓虹光晕（边缘/角落柔光脉冲 + 轻微全屏色晕）
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import random
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import tkinter as tk

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"

W, H = 2560, 1440          # 窗口（屏幕）尺寸
RW, RH = 640, 360          # 渲染分辨率（4 倍上采样）
SC = 4

PALETTE = [
    (90, 40, 255),    # 红 (BGR)
    (255, 60, 175),   # 紫
    (110, 255, 40),   # 绿
]
WHITE = (255, 255, 255)

# ---- 胜利礼花配色（BGR）：每朵礼花必带金 + 红，其余从彩池随机补充 ----
GOLD = (80, 205, 255)        # 金
RED = (110, 95, 255)         # 红
FIREWORK_EXTRAS = [
    (60, 150, 255),          # 橙
    (215, 95, 255),          # 品红
    (255, 130, 205),         # 紫
    (255, 225, 160),         # 冰青
    (240, 245, 255),         # 暖白
]

WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
WS_EX_NOACTIVATE = 0x08000000
ULW_ALPHA = 2
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01


def load_fx_cfg() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("fx", {})
    except Exception:
        return {}


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class LaserApp:
    def __init__(self, cfg: dict, prev_fg=None):
        self.cfg = cfg
        self.prev_fg = prev_fg  # 创建窗口前的前台窗口（创建后要还回去，避免抢游戏键盘焦点）
        self.intensity = float(cfg.get("intensity", 0.6))
        self.cycle = float(cfg.get("cycle_seconds", 14.0))
        self.fade = float(cfg.get("fade_seconds", 2.0))
        self.protected = cfg.get("protected_region")
        self.quit_event = threading.Event()

        self.running = False
        self.t0 = 0.0
        self.duration = 0.0
        self.cmd_queue: list[str] = []
        self._rand = random.Random(20260830)
        self._last_stats = 0.0
        # 漂浮粒子光点（分布在顶/底波浪带附近）：(x0, y0, vx, vy, 半径, 颜色索引, 相位)
        self._particles = []
        for _ in range(48):
            top = self._rand.random() < 0.5
            y0 = self._rand.uniform(4, 44) if top else self._rand.uniform(RH - 44, RH - 4)
            self._particles.append((
                self._rand.uniform(0, RW),
                y0,
                self._rand.uniform(-0.5, 0.5),
                self._rand.uniform(-0.2, 0.2),
                self._rand.randint(1, 2),
                self._rand.randint(0, 4),  # 0-2=红紫绿, 3-4=白色
                self._rand.uniform(0, math.tau),
            ))
        # 雪花粒子（全屏飘动）：(x0, y0, vx, vy, 尺寸, 相位)
        self._snowflakes = [
            (
                self._rand.uniform(0, RW),
                self._rand.uniform(0, RH),
                self._rand.uniform(-0.6, 0.6),
                self._rand.uniform(-0.4, 0.4),
                self._rand.randint(2, 4),
                self._rand.uniform(0, math.tau),
            )
            for _ in range(24)
        ]
        # 左右 GIF 动态图（预解码缓存）
        self._gif_frames = []
        self._gif_fps = 20.0
        self._load_gif(cfg)
        # 胜利模式：走入小人 + 礼花
        self.mode = "show"  # show | victory | fire
        self._victory_frames = []
        self._load_victory(cfg)
        # 玛薇卡火焰爆炸（绿幕抠像帧序列，触发后播放一次）
        self._fire_frames = []
        self._fire_fps = 30.0
        self._load_fire(cfg)
        # 派蒙迎接视频（绿幕抠像帧序列，启动读满播放一次）
        self._paimon_frames = []
        self._paimon_fps = 24.0
        self._paimon_gain = float(cfg.get("paimon_intensity", 1.15))
        self._load_paimon(cfg)
        # 商城立绘（朋友的酒特效：许家空/许家萤 + 警示语，随 BGM 启停）
        self._shop_kong = None
        self._shop_ying = None
        self._shop_text = None
        self._load_shop(cfg)
        # 礼花编组（发射-上升-爆炸完整过程，金红必带 + 彩池补充）
        self._fireworks = self._make_fireworks()

        # ---- tkinter 外壳（无子控件；ULW 提供全部像素）----
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.geometry(f"{W}x{H}+0+0")
        self.root.configure(bg="black")
        self.root.update_idletasks()
        self.root.update()

        # 顶层 hwnd（Tk 的 wrapper 窗口）
        self.hwnd = ctypes.c_void_p(user32.GetParent(self.root.winfo_id()))
        self._setup_window_style()
        self._setup_dib()

        # 渲染线程只负责「计算帧」，主线程（窗口属主）负责 ULW present
        self.frame = np.zeros((H, W, 4), np.uint8)
        self.frame_ready = threading.Event()

        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._render_loop, daemon=True).start()
        self.root.after(16, self._tick_frame)
        self.root.after(100, self._tick_cmds)
        self._restore_focus()

    # ------------------------------------------------------------ win32
    def _setup_window_style(self):
        """WS_EX_LAYERED + 点击穿透 + 置顶。
        注意：不能加 WS_EX_NOACTIVATE / WS_EX_TOOLWINDOW，也不能给子窗口设
        WS_EX_LAYERED —— 实测这些都会导致 ULW 内容不合成（黑窗/不可见）。"""
        GWL_EXSTYLE = -20
        style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        # 强制置顶（手动设位 + 提升 z 序）
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE,
                              user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE) | 0x8)  # WS_EX_TOPMOST
        user32.SetWindowPos(self.hwnd, ctypes.c_void_p(-1), 0, 0, 0, 0,
                            0x0001 | 0x0002 | 0x0010)

    def _setup_dib(self):
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = W
        bmi.bmiHeader.biHeight = -H
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        sdc = user32.GetDC(None)
        self.memdc = gdi32.CreateCompatibleDC(sdc)
        user32.ReleaseDC(None, sdc)
        bits = ctypes.c_void_p()
        self.hbmp = gdi32.CreateDIBSection(self.memdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        gdi32.SelectObject(self.memdc, self.hbmp)
        self.buf = np.ctypeslib.as_array(ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint8)), shape=(H, W, 4))
        self.blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        self.size = SIZE(W, H)
        self.pt = POINT(0, 0)

    def present(self, bgra: np.ndarray):
        self.buf[:] = bgra
        ret = user32.UpdateLayeredWindow(
            self.hwnd, self.memdc, ctypes.byref(self.pt), ctypes.byref(self.size),
            self.memdc, ctypes.byref(self.pt), 0, ctypes.byref(self.blend), ULW_ALPHA,
        )
        if ret == 0:
            self._log(f"ULW 失败 error={ctypes.get_last_error()}")

    # ------------------------------------------------------------ commands
    def _reader(self):
        for line in sys.stdin:
            line = line.strip()
            if line:
                self.cmd_queue.append(line)

    def _tick_cmds(self):
        while self.cmd_queue:
            cmd = self.cmd_queue.pop(0).split()
            if not cmd:
                continue
            if cmd[0] == "start":
                try:
                    self.duration = max(1.0, float(cmd[1]))
                except (IndexError, ValueError):
                    self.duration = 57.0
                self.t0 = time.monotonic()
                self.running = True
                self.mode = "show"
                self._log(f"灯光秀开始（{self.duration:.0f}s）")
            elif cmd[0] == "victory":
                try:
                    self.duration = max(1.0, float(cmd[1]))
                except (IndexError, ValueError):
                    self.duration = 12.0
                self.t0 = time.monotonic()
                self.running = True
                self.mode = "victory"
                self._log(f"胜利特效开始（{self.duration:.0f}s）")
            elif cmd[0] == "fire":
                try:
                    self.duration = max(0.5, float(cmd[1]))
                except (IndexError, ValueError):
                    self.duration = 4.0
                self.t0 = time.monotonic()
                self.running = True
                self.mode = "fire"
                self._log(f"火焰爆炸特效开始（{self.duration:.1f}s，播放一次）")
            elif cmd[0] == "paimon":
                try:
                    self.duration = max(0.5, float(cmd[1]))
                except (IndexError, ValueError):
                    self.duration = 10.0
                self.t0 = time.monotonic()
                self.running = True
                self.mode = "paimon"
                self._log(f"派蒙迎接视频开始（{self.duration:.1f}s，播放一次）")
            elif cmd[0] == "shopfx":
                try:
                    self.duration = max(1.0, float(cmd[1]))
                except (IndexError, ValueError):
                    self.duration = 600.0
                self.t0 = time.monotonic()
                self.running = True
                self.mode = "shopfx"
                self._log(f"许家空/许家萤立绘开始（最长 {self.duration:.0f}s）")
            elif cmd[0] == "stop":
                if self.mode == "shopfx" and self.running:
                    # 商城立绘优雅淡出（fade 秒）后自动停止，不瞬间消失
                    self.duration = time.monotonic() - self.t0
                else:
                    self.running = False
                self._log("灯光秀停止")
            elif cmd[0] == "quit":
                self.running = False
                self.quit_event.set()
                self.root.destroy()
                return
        if not self.quit_event.is_set():
            self.root.after(100, self._tick_cmds)

    # -- 左右 GIF 动态图 --
    def _load_gif(self, cfg):
        g = cfg.get("gif", {})
        path = g.get("path", "")
        self._gif_pos = (int(g.get("x_left", 30)) // SC, int(g.get("y", 252)) // SC,
                         int(g.get("x_right", 1800)) // SC)
        self._gif_size = (int(g.get("width", 640)) // SC, int(g.get("height", 360)) // SC)
        if not path:
            return
        try:
            from PIL import Image
            im = Image.open(path)
            n = getattr(im, "n_frames", 1)
            dur = 0
            try:
                im.seek(0)
                dur = im.info.get("duration", 50)
            except Exception:
                dur = 50
            self._gif_fps = max(1.0, 1000.0 / max(20, dur))
            w, h = self._gif_size
            frames = []
            for i in range(n):
                im.seek(i)
                fr = im.convert("RGBA").resize((w, h), Image.LANCZOS)
                arr = np.array(fr)
                frames.append(arr[..., [2, 1, 0, 3]])  # RGB→BGR（渲染管线为 BGR）
            self._gif_frames = frames
            self._log(f"GIF 已加载: {n} 帧 @{self._gif_fps:.0f}fps，尺寸 {w}x{h}（360p）")
        except Exception as e:
            self._log(f"GIF 加载失败（跳过）: {e}")

    def _draw_gifs(self, color, alpha, tp, k):
        if not self._gif_frames:
            return
        idx = int(tp * self._gif_fps) % len(self._gif_frames)
        fr = self._gif_frames[idx]
        h, w = fr.shape[:2]
        # 预乘 alpha（0..255 尺度）：颜色贡献 = rgb * (a*k/255)，alpha 贡献 = a*k
        a255 = fr[..., 3:4].astype(np.float32) * k
        col = fr[..., :3].astype(np.float32) * (a255 / 255.0)
        col_u8 = np.clip(col, 0, 255).astype(np.uint8)
        a_u8 = np.clip(a255, 0, 255).astype(np.uint8)
        for x0 in (self._gif_pos[0], self._gif_pos[2]):
            y0 = self._gif_pos[1]
            cv2.add(color[y0 : y0 + h, x0 : x0 + w], col_u8, color[y0 : y0 + h, x0 : x0 + w])
            cv2.add(alpha[y0 : y0 + h, x0 : x0 + w], a_u8, alpha[y0 : y0 + h, x0 : x0 + w])

    # ------------------------------------------------------------ 焦点
    def _restore_focus(self):
        """窗口创建时可能被 Windows 激活、抢走游戏键盘焦点；
        若前台已变成我们的窗口，立即把焦点还给创建前的窗口。"""

        def do():
            try:
                if self.prev_fg and user32.GetForegroundWindow() == self.hwnd:
                    user32.SetForegroundWindow(self.prev_fg)
            except Exception:
                pass

        do()
        self.root.after(400, do)  # Tk 后续事件可能再次激活，稍后重试一次

    # -- 胜利模式帧（无损 NPZ，GIF 调色板会毁颜色） --
    def _load_victory(self, cfg):
        path = cfg.get("victory_frames", "assets/victory_frames.npz")
        if not Path(path).is_absolute():
            path = str(BASE / path)
        if not Path(path).exists():
            self._log(f"胜利帧不存在（跳过）: {path}")
            return
        try:
            data = np.load(path)
            arr = data["frames"]  # (N, H, W, 4) BGRA
            # 缩放到 360p 工作分辨率（显示高 360 -> 90）
            vh = 90
            frames = []
            for fr in arr:
                h, w = fr.shape[:2]
                scale = vh / h
                nw = max(1, int(w * scale))
                frames.append(cv2.resize(fr, (nw, vh), interpolation=cv2.INTER_AREA))
            self._victory_frames = frames
            self._victory_fps = 30.0
            self._log(f"胜利帧已加载: {len(frames)} 帧，尺寸 {nw}x{vh}（360p）")
        except Exception as e:
            self._log(f"胜利帧加载失败: {e}")

    # -- 玛薇卡火焰爆炸帧（绿幕抠像 BGRA，全屏播放一次） --
    def _load_fire(self, cfg):
        path = cfg.get("fire_frames", "assets/mavuika_fire_frames.npz")
        if not Path(path).is_absolute():
            path = str(BASE / path)
        if not Path(path).exists():
            return
        try:
            data = np.load(path)
            arr = data["frames"]  # (N, H, W, 4) BGRA
            frames = []
            for fr in arr:
                if fr.shape[0] != RH:
                    sc = RH / fr.shape[0]
                    nw = max(1, int(fr.shape[1] * sc))
                    fr = cv2.resize(fr, (nw, RH), interpolation=cv2.INTER_AREA)
                frames.append(fr)
            self._fire_frames = frames
            self._fire_fps = float(cfg.get("fire_fps", 30.0))
            self._log(f"火焰帧已加载: {len(frames)} 帧（{frames[0].shape[1]}x{RH}，{self._fire_fps:.0f}fps）")
        except Exception as e:
            self._log(f"火焰帧加载失败: {e}")

    def _draw_fire(self, color, alpha, elapsed, k):
        """火焰爆炸：抠像帧序列全屏加法混合，播完即止（素材已裁掉第二次爆炸）。"""
        if not self._fire_frames:
            return
        idx = int(elapsed * self._fire_fps)
        if idx >= len(self._fire_frames):
            return
        self._blit_rgba(color, alpha, self._fire_frames[idx], 0, 0, k)

    # -- 派蒙迎接视频帧（绿幕抠像 BGRA，全屏播放一次） --
    def _load_paimon(self, cfg):
        path = cfg.get("paimon_frames", "assets/paimon_frames.npz")
        if not Path(path).is_absolute():
            path = str(BASE / path)
        if not Path(path).exists():
            return
        try:
            data = np.load(path)
            arr = data["frames"]  # (N, H, W, 4) BGRA
            frames = []
            for fr in arr:
                if fr.shape[0] != RH:
                    sc = RH / fr.shape[0]
                    nw = max(1, int(fr.shape[1] * sc))
                    fr = cv2.resize(fr, (nw, RH), interpolation=cv2.INTER_AREA)
                frames.append(fr)
            self._paimon_frames = frames
            self._paimon_fps = float(cfg.get("paimon_fps", 24.0))
            self._log(f"派蒙帧已加载: {len(frames)} 帧（{frames[0].shape[1]}x{RH}，{self._paimon_fps:.0f}fps）")
        except Exception as e:
            self._log(f"派蒙帧加载失败: {e}")

    def _draw_paimon(self, color, alpha, elapsed, k):
        """派蒙迎接：抠像帧序列全屏加法混合，播完即止。"""
        if not self._paimon_frames:
            return
        idx = int(elapsed * self._paimon_fps)
        if idx >= len(self._paimon_frames):
            return
        self._blit_rgba(color, alpha, self._paimon_frames[idx], 0, 0, k)

    # -- 商城立绘（朋友的酒：许家空/许家萤 + 警示语） --
    def _load_shop(self, cfg):
        for attr, key in (("_shop_kong", "shop_kong"), ("_shop_ying", "shop_ying")):
            path = cfg.get(key, "")
            if not path:
                continue
            p = Path(path)
            if not p.is_absolute():
                p = BASE / p
            if not p.exists():
                self._log(f"商城立绘不存在（跳过）: {p}")
                continue
            try:
                from PIL import Image as PILImage
                im = PILImage.open(p).convert("RGBA")
                # 两张立绘统一尺寸（与许家空对齐：宽 129 x 高 150）
                tw, th = 129, 150
                im = im.resize((tw, th), PILImage.LANCZOS)
                arr = np.array(im)
                setattr(self, attr, arr[..., [2, 1, 0, 3]])  # RGBA→BGRA
                self._log(f"商城立绘已加载: {p.name} {tw}x{th}")
            except Exception as e:
                self._log(f"商城立绘加载失败: {e}")
        try:
            lines = cfg.get("shop_text", ["许家空和许家萤提醒您", "适度游戏，理性消费"])
            size = int(cfg.get("shop_font_size", 30))
            self._shop_text = self._render_shop_text(lines, size)
            self._log(f"商城警示语已渲染: {lines[0]} / {lines[1]}")
        except Exception as e:
            self._log(f"警示语渲染失败: {e}")

    @staticmethod
    def _render_shop_text(lines, size):
        """黑体红色大字 + 黑色描边（两行居中），返回 BGRA。"""
        from PIL import Image, ImageDraw, ImageFont
        font = ImageFont.truetype(str(Path("C:/Windows/Fonts/simhei.ttf")), size)
        tmp = Image.new("RGBA", (8, 8))
        td = ImageDraw.Draw(tmp)
        ws = [td.textlength(t, font=font) for t in lines]
        w = int(max(ws)) + 12
        line_h = int(size * 1.4)
        h = line_h * len(lines) + 8
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for i, t in enumerate(lines):
            tw = d.textlength(t, font=font)
            d.text(((w - tw) / 2, 4 + i * line_h), t, font=font,
                   fill=(255, 0, 0, 255), stroke_width=3, stroke_fill=(20, 20, 20, 255))
        arr = np.array(img)
        return arr[..., [2, 1, 0, 3]]

    def _draw_shop(self, color, alpha, elapsed, k):
        """许家空/许家萤左右立绘（中偏下）+ 中央警示语（中偏下）。"""
        ky = int(RH * 0.52)
        if self._shop_kong is not None:
            self._blit_rgba(color, alpha, self._shop_kong, 24, ky, k)
        if self._shop_ying is not None:
            w = self._shop_ying.shape[1]
            self._blit_rgba(color, alpha, self._shop_ying, RW - 24 - w, ky, k)
        if self._shop_text is not None:
            th, tw = self._shop_text.shape[:2]
            # 中偏下，但自适应贴底：多行文字不被裁掉
            self._blit_rgba(color, alpha, self._shop_text,
                            (RW - tw) // 2, min(int(RH * 0.76), RH - th - 8), k)

    def _blit_rgba(self, color, alpha, fr, x0, y0, k):
        """把 BGRA 帧加法混合到画布（带边界裁剪）。"""
        h, w = fr.shape[:2]
        if x0 + w <= 0 or x0 >= RW or y0 + h <= 0 or y0 >= RH:
            return
        cx0, cy0 = max(0, x0), max(0, y0)
        cx1, cy1 = min(RW, x0 + w), min(RH, y0 + h)
        frc = fr[cy0 - y0 : cy1 - y0, cx0 - x0 : cx1 - x0]
        a255 = frc[..., 3:4].astype(np.float32) * k
        col = frc[..., :3].astype(np.float32) * (a255 / 255.0)
        col_u8 = np.clip(col, 0, 255).astype(np.uint8)
        a_u8 = np.clip(a255, 0, 255).astype(np.uint8)
        cv2.add(color[cy0:cy1, cx0:cx1], col_u8, color[cy0:cy1, cx0:cx1])
        cv2.add(alpha[cy0:cy1, cx0:cx1], a_u8, alpha[cy0:cy1, cx0:cx1])

    def _draw_victory(self, color, alpha, elapsed, k):
        if not self._victory_frames:
            return
        vh = self._victory_frames[0].shape[0]
        vw = self._victory_frames[0].shape[1]
        y0 = int(RH * 0.30) - vh // 2
        # 走入：3 秒内从屏幕外水平走到左右约 1/4 处，之后原地循环
        p = min(1.0, elapsed / 3.0)
        left_stop = int(RW * 0.13)
        right_stop = int(RW * 0.87)
        left_x = int(-vw + p * (left_stop + vw))
        right_x = int(RW - p * (RW - right_stop))
        idx = int(elapsed * self._victory_fps) % len(self._victory_frames)
        fr = self._victory_frames[idx]
        self._blit_rgba(color, alpha, fr, left_x, y0, k)
        self._blit_rgba(color, alpha, np.flip(fr, axis=1), right_x, y0, k)
        self._draw_fireworks(color, alpha, elapsed, k)

    def _make_fireworks(self) -> list[dict]:
        """生成礼花编组：9 朵错峰发射；每朵必带金 + 红，另随机补 2 种彩池色。"""
        rnd = self._rand
        fws = []
        for i in range(9):
            fws.append({
                "launch": 0.7 + i * 1.45 + rnd.uniform(-0.1, 0.1),
                "x0": RW * rnd.uniform(0.06, 0.94),   # 发射点（屏幕底部）
                "y0": RH + 14,
                "cx": RW * rnd.uniform(0.16, 0.84),   # 爆点
                "cy": RH * rnd.uniform(0.16, 0.40),
                "rise": rnd.uniform(0.95, 1.35),      # 上升时长
                "scale": rnd.uniform(1.25, 1.6),      # 爆炸大小
                "colors": [GOLD, RED] + rnd.sample(FIREWORK_EXTRAS, 2),
                "spin": rnd.uniform(0, math.tau),
            })
        return fws

    def _draw_fireworks(self, color, alpha, elapsed, k):
        """礼花齐放：先见火箭拖着金红尾焰升空，到顶炸成多层光环。"""
        for fw in self._fireworks:
            t = elapsed - fw["launch"]
            if t < 0:
                continue
            if t < fw["rise"]:
                self._draw_rocket(color, alpha, t, k, fw)
            else:
                self._draw_burst(color, alpha, t - fw["rise"], k, fw)

    def _draw_rocket(self, color, alpha, t, k, fw):
        """火箭上升：加速爬升 + 金红交替尾焰拖尾 + 白亮弹头。"""
        r = fw["rise"]
        p = min(1.0, t / r)
        pe = p * p  # 加速感
        x = fw["x0"] + (fw["cx"] - fw["x0"]) * pe
        y = fw["y0"] + (fw["cy"] - fw["y0"]) * pe
        mg = np.zeros((RH, RW), np.uint8)  # 金
        mr = np.zeros((RH, RW), np.uint8)  # 红
        for s in range(1, 9):
            ps = (t - s * 0.03) / r
            if ps <= 0:
                break
            xs = fw["x0"] + (fw["cx"] - fw["x0"]) * ps * ps
            ys = fw["y0"] + (fw["cy"] - fw["y0"]) * ps * ps
            a = int((100 - s * 9) * k)
            if a > 0:
                cv2.line(mr if s % 2 else mg, (int(x), int(y)), (int(xs), int(ys)),
                         a, max(1, int(2.4 - s * 0.2)))
        # 弹头下方两团尾焰光点
        cv2.circle(mr, (int(x - 2), int(y + 2)), 2, int(190 * k), -1)
        cv2.circle(mg, (int(x + 2), int(y + 2)), 2, int(190 * k), -1)
        cv2.circle(mg, (int(x), int(y + 3)), 2, int(190 * k), -1)
        self._blit_mask(color, alpha, mg, GOLD)
        self._blit_mask(color, alpha, mr, RED)
        mw = np.zeros((RH, RW), np.uint8)
        cv2.circle(mw, (int(x), int(y)), 3, int(255 * k), -1)
        self._blit_mask(color, alpha, mw, WHITE)

    def _draw_burst(self, color, alpha, tt, k, fw):
        """爆炸：爆心金白闪光 + 三层金红光环扩散 + 拖尾，大而华丽。"""
        if tt > 2.9:
            return
        fade = 1.0 - tt / 2.9
        sc = fw["scale"]
        cx, cy = fw["cx"], fw["cy"]
        colors = fw["colors"]
        masks = {i: np.zeros((RH, RW), np.uint8) for i in range(len(colors))}
        n = 40
        rings = [(0.0, 1.0), (0.38, 1.5), (0.17, 2.0)]  # (角度偏移, 速度倍率)
        for (aoff, spd) in rings:
            for j in range(n):
                ang = j * (math.tau / n) + aoff + fw["spin"]
                sp = spd * (0.82 + 0.32 * ((j * 37) % 5) / 5.0)
                x = cx + math.cos(ang) * sp * tt * 35 * sc
                y = cy + math.sin(ang) * sp * tt * 34 * sc + 6.0 * tt * tt
                if 0 <= x < RW and 0 <= y < RH:
                    ci = j % len(colors)
                    xi, yi = int(x), int(y)
                    cv2.circle(masks[ci], (xi, yi), 3, int(235 * fade * k), -1)
                    # 拖尾（从爆心拉线）
                    ttx = max(0.0, tt - 0.16)
                    txi = int(cx + math.cos(ang) * sp * ttx * 35 * sc)
                    tyi = int(cy + math.sin(ang) * sp * ttx * 35 * sc + 6.0 * ttx * ttx)
                    cv2.line(masks[ci], (xi, yi), (txi, tyi), int(130 * fade * k), 1)
        # 爆心闪光（金 + 红双层）
        if tt < 0.4:
            flash = int(250 * (1 - tt / 0.4) * k)
            cv2.circle(masks[0], (int(cx), int(cy)), int(30 * sc * (1 - tt / 0.4)), flash, -1)
            cv2.circle(masks[1], (int(cx), int(cy)), int(16 * sc * (1 - tt / 0.4)), flash, -1)
        for ci, m in masks.items():
            self._blit_mask(color, alpha, m, colors[ci])

    @staticmethod
    def _blit_mask(color, alpha, m, bgr):
        """把单色蒙版加法叠到画布上。"""
        if m.any():
            tmp = np.zeros((RH, RW, 3), np.uint8)
            tmp[m > 0] = bgr
            cv2.add(color, tmp, color)
            cv2.add(alpha, m, alpha)

    # ------------------------------------------------------------ 渲染
    def _render_loop(self):
        """计算帧（纯 CPU/OpenCV），不碰 Win32 窗口。"""
        color = np.zeros((RH, RW, 3), np.uint8)
        alpha = np.zeros((RH, RW), np.uint8)
        try:
            while not self.quit_event.is_set():
                if self.running:
                    color[:] = 0
                    alpha[:] = 0
                    self._draw(color, alpha, time.monotonic())
                    self.frame[:] = self._compose(color, alpha)
                    self.frame_ready.set()
                    if time.monotonic() - self._last_stats > 1.0:
                        self._last_stats = time.monotonic()
                        a = self.frame[..., 3]
                        self._log(f"帧统计: alpha>0 占比 {(a > 0).mean() * 100:.0f}%, 最大 alpha {a.max()}")
                time.sleep(0.016)
        except Exception as e:
            self._log(f"渲染线程异常: {e}")

    def _tick_frame(self):
        """主线程（窗口属主）执行 ULW present。"""
        if self.frame_ready.is_set():
            self.frame_ready.clear()
            self.present(self.frame)
        elif not self.running:
            self.present(np.zeros((H, W, 4), np.uint8))
        if not self.quit_event.is_set():
            self.root.after(16, self._tick_frame)

    def _compose(self, color, alpha) -> np.ndarray:
        # 派蒙模式用专属不透明度增益抵消全局灯光强度（默认 0.87），
        # 让派蒙本体实心不透明；其他特效维持原样
        k = self.intensity * (self._paimon_gain if self.mode == "paimon" else 1.0)
        a = cv2.multiply(alpha, np.array([k])) if k < 1.0 else alpha
        a = cv2.GaussianBlur(a, (0, 0), 2.5)
        af = a.astype(np.float32) / 255.0
        out = np.zeros((RH, RW, 4), np.float32)
        out[..., :3] = color.astype(np.float32) * af[..., None]
        out[..., 3] = a
        out8 = np.clip(out, 0, 255).astype(np.uint8)
        big = cv2.resize(out8, (W, H), interpolation=cv2.INTER_LINEAR)
        if self.protected:
            x, y, w, h = self.protected
            big[y : y + h, x : x + w] = 0
        return big

    # ------------------------------------------------------------ 效果
    def _draw(self, color, alpha, t):
        elapsed = t - self.t0
        remaining = self.duration + self.fade - elapsed
        k = max(0.0, min(1.0, remaining / self.fade)) if elapsed > self.duration else 1.0
        if elapsed >= self.duration + self.fade:
            self.running = False
            return
        if k <= 0.05:
            return
        if self.mode == "victory":
            self._draw_victory(color, alpha, elapsed, k)
            return
        if self.mode == "fire":
            self._draw_fire(color, alpha, elapsed, k)
            return
        if self.mode == "paimon":
            self._draw_paimon(color, alpha, elapsed, k)
            return
        if self.mode == "shopfx":
            self._draw_shop(color, alpha, elapsed, k)
            return
        tp = elapsed  # 用总时长（连续），GIF 按自身 26 秒周期完整循环，特效不跳变
        # 探照灯固定 3 束（摆动速度/张开角做轻微呼吸变化，不改变光束数量）
        swing = 0.09 + 0.02 * math.sin(tp * 0.4)
        spread = 0.30 + 0.03 * math.sin(tp * 0.5)
        self._draw_searchlights(color, alpha, tp, k, n=3, swing=swing, spread=spread, speed=0.6)
        # 频谱跳动波（顶/底边）+ 波浪旁粒子 + 雪花 + GIF（与探照灯同时）
        self._draw_spectrum(color, alpha, tp, k)
        self._draw_particles(color, alpha, tp, k)
        self._draw_snowflakes(color, alpha, tp, k)
        self._draw_gifs(color, alpha, tp, k)

    def _beam(self, color, alpha, pts, bgr, a):
        m = np.zeros((RH, RW), np.uint8)
        cv2.fillPoly(m, [np.array(pts, np.int32)], a)
        if m.any():
            tmp = np.zeros((RH, RW, 3), np.uint8)
            tmp[m > 0] = bgr
            cv2.add(color, tmp, color)
            cv2.add(alpha, m, alpha)

    def _glow(self, color, alpha, cx, cy, r, bgr, a):
        m = np.zeros((RH, RW), np.uint8)
        cv2.circle(m, (int(cx), int(cy)), int(r), a, -1)
        if m.any():
            tmp = np.zeros((RH, RW, 3), np.uint8)
            tmp[m > 0] = bgr
            cv2.add(color, tmp, color)
            cv2.add(alpha, m, alpha)

    # -- 探照灯（顶部 3 束多色光束；光源集中在中段，中央始终被覆盖） --
    def _draw_searchlights(self, color, alpha, tp, k, n=3, swing=0.09, spread=0.30, speed=0.6):
        for i in range(n):
            col = PALETTE[i % 3]
            # 光源横坐标集中在中段（0.30W~0.70W），摆动幅度收窄，不会甩到屏幕边缘
            base_x = (W * (0.30 + 0.20 * i) + math.sin(tp * speed + i * 2.1) * W * swing) / SC
            sp = spread + 0.05 * math.sin(tp * speed * 0.8 + i * 1.7)
            half = math.tan(sp) * (RH * 1.35)
            pts = [(base_x, -40), (base_x - half, RH + 40), (base_x + half, RH + 40)]
            self._beam(color, alpha, pts, col, int(42 * k))
            self._glow(color, alpha, base_x, 0, 18, WHITE, int(190 * k))
        m = np.zeros((RH, RW), np.uint8)
        cv2.rectangle(m, (0, 0), (RW, 12), int(26 * k), -1)
        if m.any():
            tmp = np.zeros((RH, RW, 3), np.uint8)
            tmp[m > 0] = (140, 120, 220)
            cv2.add(color, tmp, color)
            cv2.add(alpha, m, alpha)

    # -- 顶边/底边频谱跳动波（音乐播放器风格：细密频率条原地跳动，不平移） --
    def _draw_spectrum(self, color, alpha, tp, k):
        n_seg = 48
        seg_w = RW / n_seg
        bar_w = max(2.0, seg_w * 0.62)  # 细条 + 间隙
        beat = max(0.0, math.sin(tp * 2.4)) ** 4  # 鼓点包络
        for edge in (0, 1):
            for layer in range(2):
                col = PALETTE[(layer + 1) % 3] if layer == 0 else (200, 190, 255)
                rects = []
                for i in range(n_seg):
                    h = self._seg_height(tp, i, layer, beat)
                    x0 = i * seg_w + (seg_w - bar_w) / 2
                    if edge == 0:
                        rects.append([(x0, 0), (x0 + bar_w, 0), (x0 + bar_w, h), (x0, h)])
                    else:
                        rects.append([(x0, RH), (x0 + bar_w, RH), (x0 + bar_w, RH - h), (x0, RH - h)])
                self._beam_many(color, alpha, rects, col, int(46 * k))

    def _beam_many(self, color, alpha, rects, bgr, a):
        """一次性批量叠加多个多边形（频谱条用，避免逐条 fillPoly 开销）。"""
        m = np.zeros((RH, RW), np.uint8)
        cv2.fillPoly(m, [np.array(p, np.int32) for p in rects], a)
        if m.any():
            tmp = np.zeros((RH, RW, 3), np.uint8)
            tmp[m > 0] = bgr
            cv2.add(color, tmp, color)
            cv2.add(alpha, m, alpha)

    @staticmethod
    def _seg_height(tp, i, layer, beat):
        """每段独立的"频率条"高度：双正弦叠加 + 鼓点包络，随音乐节奏跳动。"""
        h = (abs(math.sin(tp * 4.0 + i * 1.7 + layer * 2.3)) * 0.55
             + abs(math.sin(tp * 9.2 + i * 0.9 + layer)) * 0.45)
        h = h * (1.0 + beat * 0.9)
        return max(5.0, h * 22.0 + 5.0)

    # -- 波浪旁粒子光点（分布在顶/底频谱带附近） --
    def _draw_particles(self, color, alpha, tp, k):
        for (x0, y0, vx, vy, r, ci, ph) in self._particles:
            x = (x0 + vx * tp * 12) % RW
            y = (y0 + vy * tp * 8 + math.sin(tp * 0.9 + ph) * 18) % RH
            col = PALETTE[ci % 3] if ci < 3 else WHITE
            self._glow(color, alpha, x, y, r, col, int((130 + 70 * (0.5 + 0.5 * math.sin(tp * 2.0 + ph))) * k))

    # -- 雪花粒子（全屏飘动，六角形状） --
    def _draw_snowflakes(self, color, alpha, tp, k):
        m = np.zeros((RH, RW), np.uint8)
        for (x0, y0, vx, vy, s, ph) in self._snowflakes:
            x = (x0 + vx * tp * 14) % RW
            y = (y0 + vy * tp * 12 + math.sin(tp * 0.7 + ph) * 20) % RH
            xi, yi = int(x), int(y)
            a = int(150 * k)
            cv2.circle(m, (xi, yi), max(1, s), a, -1)
            for k2 in range(6):  # 六角分支
                ang = math.pi / 3 * k2
                cv2.line(m, (xi, yi),
                         (int(xi + math.cos(ang) * s * 2.2), int(yi + math.sin(ang) * s * 2.2)), a, 1)
        if m.any():
            tmp = np.zeros((RH, RW, 3), np.uint8)
            tmp[m > 0] = (235, 242, 255)  # 淡蓝白
            cv2.add(color, tmp, color)
            cv2.add(alpha, m, alpha)

    # ------------------------------------------------------------ misc
    def _log(self, msg: str):
        print(f"[fx] {msg}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="舞台灯光特效进程 v3")
    parser.add_argument("--demo", default="", help="演示（show:秒数 / fire:秒数；到点自动退出）")
    args = parser.parse_args()

    cfg = load_fx_cfg()
    prev_fg = user32.GetForegroundWindow()  # 创建窗口前记录前台，创建后归还焦点
    app = LaserApp(cfg, prev_fg=prev_fg)

    if args.demo:
        mode, _, d = args.demo.partition(":")
        try:
            secs = float(d) if d else 4.0
        except ValueError:
            secs = 4.0
        app.cmd_queue.append(f"{mode} {secs}" if mode in ("fire", "paimon", "shopfx") else f"start {secs}")
        deadline = time.monotonic() + secs + 3.0
    else:
        deadline = None

    # 手动 update 循环（不用 mainloop：Tk 的 mainloop 会重绘黑背景盖掉 ULW 内容）
    try:
        while not app.quit_event.is_set():
            if deadline is not None and time.monotonic() > deadline:
                break
            try:
                app.root.update()
            except tk.TclError:
                break  # 窗口已销毁
            time.sleep(0.02)
    finally:
        app.quit_event.set()
    print("[fx] 退出", flush=True)
    os._exit(0)  # 确保守护线程全部终止，进程必然退出


if __name__ == "__main__":
    main()
