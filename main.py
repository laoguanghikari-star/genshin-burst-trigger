"""
原神 · 元素爆发音效触发原型 v1.5
================================
检测逻辑（三重信号确认）:
  1. 键盘钩子捕获 Q 键按下（爆发快捷键）
  2. 出战角色校验：队伍面板右侧数字角标——出战角色的角标是半透明灰色，
     非出战是纯白。只有当前出战角色 == target_slot（默认 2 = 奥黛塔）才武装触发
  3. 按下后短暂时间窗内，屏幕中心亮度突增（爆发施放闪光）
  BGM 播放期间屏蔽一切新触发（防止"禁忌三重奏"叠音）

使用:
  python main.py            # 正常运行
  python main.py --test     # 只测试音频播放（不启动检测）
  python main.py --debug    # 控制台输出每帧亮度与出战槽位，便于调参
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"


# ---------------------------------------------------------------- config
def resolve_audio(cfg: dict) -> Path:
    """解析音频文件路径（相对路径基于项目根）。不依赖 cfg['audio_path'] 派生字段。"""
    audio = Path(cfg.get("audio_file", "assets/burst_bgm.wav"))
    if not audio.is_absolute():
        audio = BASE / audio
    return audio


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["audio_path"] = resolve_audio(cfg)
    return cfg


# ---------------------------------------------------------------- audio
class BgmPlayer:
    """预加载音频，低延迟触发播放。"""

    def __init__(self, wav_path: Path, volume: float = 0.9):
        import pygame

        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        self.pygame = pygame
        self.sound = pygame.mixer.Sound(str(wav_path))
        self.sound.set_volume(volume)
        self.channel = None

    def play(self, loops: int = 0) -> None:
        self.channel = self.sound.play(loops=loops)

    def is_playing(self) -> bool:
        return bool(self.channel is not None and self.channel.get_busy())


# ---------------------------------------------------------------- party panel
class PartyPanel:
    """队伍面板出战角色检测。

    原理：右侧队伍面板每个角色头像旁有数字角标（1/2/3/4）。
    非出战角色角标 = 不透明纯白背景；出战角色角标 = 半透明灰背景。
    采样每个角标「上部横条」（x+10..x+30, y0+3..y0+9，避开圆角与数字）的平均亮度：
    白色 ≈ 250+，灰色 ≈ 190。亮度显著低于中位数的那个槽位 = 当前出战角色。
    连续 3 帧读数一致才切换判定，防抖。
    2K 分辨率坐标（2560x1440）写死在 config.party_panel。
    """

    def __init__(self, cfg: dict):
        p = cfg["party_panel"]
        self.x = p["x"]  # 角标框左边缘（绝对屏幕坐标）
        self.slot_centers = p["slot_centers"]  # 各槽位角标中心 y（绝对屏幕坐标）
        self.half_h = p["slot_half_h"]
        self.margin = cfg.get("active_margin", 20)
        self._last_active: int | None = None
        self._cand_slot: int | None = None
        self._cand_count = 0

    def _strip_lums(self, gray) -> list[float]:
        lums = []
        for cy in self.slot_centers:
            y0 = cy - self.half_h
            # 上部横条：避开圆角（x 方向向内 10px）与数字（数字在垂直中部）
            patch = gray[y0 + 3 : y0 + 9, self.x + 10 : self.x + 30]
            lums.append(float(patch.mean()))
        return lums

    def update(self, frame) -> None:
        """每帧调用；连续 3 帧一致的读数才更新 self.active_slot，否则保留上一次判定。"""
        gray = frame[..., 0] * 0.114 + frame[..., 1] * 0.587 + frame[..., 2] * 0.299
        lums = self._strip_lums(gray)
        med = float(np.median(lums))
        active_idx = int(np.argmin(lums))
        margin = med - lums[active_idx]
        if margin > self.margin:
            cand = active_idx + 1  # 1-based
            if cand == self._cand_slot:
                self._cand_count += 1
            else:
                self._cand_slot = cand
                self._cand_count = 1
            if self._cand_count >= 3:
                self._last_active = cand
        else:
            # 读数不可信（面板隐藏/闪光干扰）：清空候选，保留已确认值
            self._cand_slot = None
            self._cand_count = 0

    @property
    def active_slot(self) -> int | None:
        return self._last_active


# ---------------------------------------------------------------- recognizer
class BurstRecognizer:
    """爆发画面识别：Q 按下后，对每帧计算「与目标角色爆发演示的相似度」。

    评分（0-1）:
      score = 0.25*ice + 0.20*hist + 0.55*pos_body - neg_penalty*max(0, max(neg_body) - pos_body)

      - ice      冰蓝高光占比
      - hist     与参考图的 HSV 色相-饱和直方图相关性
      - pos_body 与参考图「身体/舞姿模板」的归一化互相关（主判别特征）
      - neg_body 与各「负样本模板」的归一化互相关；
                  只有当负匹配超过正匹配时才扣分（条件扣分），防止其他角色误触发
      reference 支持多张参考图（列表）：分别评分取最大，覆盖爆发演示的不同阶段；
      negative_roi 可单独指定负样本裁剪区域（默认与 template_roi 相同）

      baseline 场景自适应：传入 (ice0, corr0列表)（Q 按下瞬间的画面统计）时，
      ice/hist 改为相对增量 max(0, 当前-基准)。大范围蓝色场景（海边/天云峠等）
      会天然抬高绝对 ice/hist，导致玛薇卡爆发误触发奥黛塔；增量形式只保留
      「爆发带来的突变」，场景底色不再贡献分数。
    """

    def __init__(self, cfg: dict):
        d = cfg.get("detection", {})
        self.threshold = float(d.get("match_threshold", 0.55))
        self.match_frames = int(d.get("match_frames", 2))
        self.template_roi = d.get("template_roi")  # [x,y,w,h] 正参考裁剪
        self.negative_roi = d.get("negative_roi") or self.template_roi  # 负样本裁剪
        self.neg_penalty = float(d.get("neg_penalty", 0.75))
        refs = d.get("reference", "assets/burst_ref.png")
        if isinstance(refs, str):
            refs = [refs]
        self.ref_path = refs[0] if refs else ""
        self._refs: list = []  # [(直方图, ¼ 模板), ...]
        for ref_name in refs:
            ref = Path(ref_name)
            if not ref.is_absolute():
                ref = BASE / ref
            if ref.exists():
                img = self._imread(ref)
                if img is not None:
                    tpl = self._crop_gray(img, self.template_roi)
                    if tpl is not None:
                        # 直方图与帧同尺度（¼ 小图）计算，保证可比且省算力
                        small = cv2.resize(img, (img.shape[1] // 4, img.shape[0] // 4))
                        self._refs.append((self._hist(small), self._shrink(tpl)))
        # 负样本模板（¼ 缩放，裁剪用 negative_roi）
        self._neg_tpls: list = []  # (名称, ¼ 模板)
        for neg_name in d.get("negative_templates", []):
            p = Path(neg_name)
            if not p.is_absolute():
                p = BASE / p
            if p.exists():
                ng = self._imread(p)
                if ng is not None:
                    tpl = self._crop_gray(ng, self.negative_roi)
                    if tpl is not None:
                        self._neg_tpls.append((p.stem, self._shrink(tpl)))

    @staticmethod
    def _imread(path) -> np.ndarray | None:
        """Unicode 安全读图（中文路径兼容）。"""
        try:
            data = np.fromfile(str(path), dtype=np.uint8)
            return cv2.imdecode(data, cv2.IMREAD_COLOR)
        except Exception:
            return None

    @staticmethod
    def _crop_gray(img, roi) -> np.ndarray | None:
        """按 ROI 裁剪出灰度模板；图片比 ROI 小（已是裁剪好的模板）时整图使用。"""
        if not roi:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        x, y, w, h = roi
        if x + w > img.shape[1] or y + h > img.shape[0]:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[y : y + h, x : x + w]

    @staticmethod
    def _shrink(tpl) -> np.ndarray:
        return cv2.resize(tpl, (tpl.shape[1] // 8, tpl.shape[0] // 8))

    @property
    def ready(self) -> bool:
        return len(self._refs) > 0

    @property
    def neg_ready(self) -> bool:
        return len(self._neg_tpls) > 0

    def _hist(self, img):
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return hist

    @staticmethod
    def _ice(img) -> float:
        """冰蓝高光像素占比（蓝主导 + 高亮 + 有一定饱和度）。"""
        b = img[..., 0].astype(np.float32)
        g = img[..., 1].astype(np.float32)
        r = img[..., 2].astype(np.float32)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        v = hsv[..., 2].astype(np.float32)
        s = hsv[..., 1].astype(np.float32)
        mask = (b > r * 1.2) & (b > g * 1.05) & (v > 160) & (s > 40)
        return float(mask.mean())

    def _match(self, gi, tpl) -> float:
        """⅛ 灰度帧上的模板匹配（模板已预缩放）。⅛ 尺度与 ¼ 分数几乎一致
        （实测偏差 <0.01），但快约 4 倍——三角色识别器合计量从 ~200ms/帧
        降到 ~53ms/帧，显著降低触发延迟。"""
        return max(0.0, float(cv2.matchTemplate(gi, tpl, cv2.TM_CCOEFF_NORMED).max()))

    @staticmethod
    def _prepare(frame):
        """帧预处理：¼ 小图（ice/hist 用）+ ⅛ 灰度（模板匹配用）。
        多个识别器共享，省重复计算。"""
        small = cv2.resize(frame, (frame.shape[1] // 4, frame.shape[0] // 4))
        gi = cv2.cvtColor(cv2.resize(frame, (frame.shape[1] // 8, frame.shape[0] // 8)),
                          cv2.COLOR_BGR2GRAY)
        return small, gi

    def check(self, frame, shared=None, baseline=None) -> float:
        """组合评分 0-1；未就绪返回 0。多参考图取最大得分。
        shared: _prepare 的输出，同一帧多个识别器共享。
        baseline: (ice0, corr0列表) —— Q 按下瞬间的画面统计；给出后 ice/hist
        改为相对增量（max(0, 当前-基准)），消除大范围蓝色场景对绝对值的抬高。"""
        if not self._refs:
            return 0.0
        if shared is not None:
            small, gi = shared
        else:
            small, gi = self._prepare(frame)
        # 冰蓝占比与直方图都在 ¼ 小图上统计：比例/分布稳定，速度提升 10 倍以上
        ice = self._ice(small)
        fhist = self._hist(small)
        best = 0.0
        neg_best = None  # 惰性：仅当某参考 pos>0.40 时计算一次（与参考图无关，可复用）
        for idx, (hist, tpl) in enumerate(self._refs):
            corr = max(0.0, cv2.compareHist(hist, fhist, cv2.HISTCMP_CORREL))
            pos = self._match(gi, tpl)
            if baseline is not None:
                ice0, corr0 = baseline
                ice_t = max(0.0, ice - ice0)
                corr_t = max(0.0, corr - (corr0[idx] if idx < len(corr0) else 0.0))
            else:
                ice_t, corr_t = ice, corr
            s = 0.25 * ice_t + 0.20 * corr_t + 0.55 * pos
            # 条件扣分：仅在负样本匹配度超过正样本时扣分（省算力 + 精准压制）
            if self.neg_ready and pos > 0.40:
                if neg_best is None:
                    neg_best = max(self._match(gi, t) for _, t in self._neg_tpls)
                s -= self.neg_penalty * max(0.0, neg_best - pos)
            best = max(best, s)
        return max(0.0, best)


# ---------------------------------------------------------------- completion
class CompletionMonitor:
    """幽境危战通关页持续监控：识别通关结算画面，边沿触发 + 冷却。
    复用 BurstRecognizer（参考图 + 负样本 + 条件扣分）。"""

    def __init__(self, cfg: dict):
        c = cfg.get("completion", {})
        self.enabled = bool(c.get("enabled", False))
        self.check_interval = float(c.get("check_interval", 0.5))
        self.reset_seconds = float(c.get("reset_seconds", 8))
        self.sound_file = c.get("sound_file", "assets/unbelievable.wav")
        self.fx_duration = float(c.get("fx_duration", 12))
        self.recognizer = None
        if self.enabled:
            det = {
                "mode": "recognition",
                "reference": c.get("reference", "assets/completion_ref.png"),
                "template_roi": c.get("template_roi", [0, 0, 2560, 1440]),
                "negative_templates": c.get("negative_templates", []),
                "neg_penalty": float(c.get("neg_penalty", 1.0)),
                "match_threshold": float(c.get("match_threshold", 0.45)),
                "match_frames": int(c.get("match_frames", 2)),
                "window_seconds": 1.0,
            }
            self.recognizer = BurstRecognizer({"detection": det})
            self.threshold = det["match_threshold"]
            self.match_frames = det["match_frames"]
        self._hits = 0
        self._active = False
        self._last_check = 0.0
        self._last_trigger_at = 0.0

    def update(self, frame, now: float) -> bool:
        """每帧调用（内部按 check_interval 节流）。返回 True = 本次触发。"""
        if self.recognizer is None:
            return False
        if now - self._last_check < self.check_interval:
            return False
        self._last_check = now
        score = self.recognizer.check(frame)
        if score >= self.threshold:
            self._hits += 1
            if (self._hits >= self.match_frames and not self._active
                    and now - self._last_trigger_at > self.reset_seconds):
                self._active = True
                self._last_trigger_at = now
                self._hits = 0
                return True
        else:
            self._hits = 0
            self._active = False
        return False


# ---------------------------------------------------------------- shop
class ShopMonitor:
    """商城「购买创世结晶」界面持续监控：进入 → 循环 BGM，离开 → 停止。

    与通关监控不同：需要边沿事件分别驱动 BGM 的启动与淡出停止。
    update() 返回 (进入边沿, 离开边沿)；离开需连续 stop_misses 次未命中
    （容忍界面短暂遮挡/加载），避免误停。"""

    def __init__(self, cfg: dict):
        s = cfg.get("shop", {})
        self.enabled = bool(s.get("enabled", False))
        self.check_interval = float(s.get("check_interval", 0.5))
        self.stop_misses = int(s.get("stop_misses", 6))
        self.recognizer = None
        if self.enabled:
            det = {
                "mode": "recognition",
                "reference": s.get("reference", "assets/shop_ref.png"),
                "template_roi": s.get("template_roi", [480, 240, 1570, 970]),
                "negative_roi": s.get("negative_roi"),
                "negative_templates": s.get("negative_templates", []),
                "neg_penalty": float(s.get("neg_penalty", 1.0)),
                "match_threshold": float(s.get("match_threshold", 0.5)),
                "match_frames": int(s.get("match_frames", 2)),
                "window_seconds": 1.0,
            }
            self.recognizer = BurstRecognizer({"detection": det})
            self.threshold = det["match_threshold"]
            self.match_frames = det["match_frames"]
        self._hits = 0
        self._active = False
        self._misses = 0
        self._last_check = 0.0

    def update(self, frame, now: float) -> tuple[bool, bool]:
        """每帧调用（内部按 check_interval 节流）。返回 (进入边沿, 离开边沿)。"""
        if self.recognizer is None:
            return False, False
        if now - self._last_check < self.check_interval:
            return False, False
        self._last_check = now
        score = self.recognizer.check(frame)
        if score >= self.threshold:
            self._hits += 1
            self._misses = 0
            if self._hits >= self.match_frames and not self._active:
                self._active = True
                return True, False
        else:
            self._hits = 0
            if self._active:
                self._misses += 1
                if self._misses >= self.stop_misses:
                    self._active = False
                    return False, True
        return False, False


# ---------------------------------------------------------------- startup
class StartupMonitor:
    """启动加载屏「元素读条读满」监控 → 触发派蒙迎接视频。

    加载屏特征（实测 2560x1440）：
      - 整屏近乎纯白（>90% 像素亮度 >240）
      - 中央元素图标带（灰色，从左到右逐个出现）随加载进度变满：
        未满约 2.2% 深色覆盖（启动界面02），读满约 13.7%（启动界面01）
    四重条件判定（全部满足才触发，连续 match_frames 次）：
      1) 整屏纯白 ≥ white_ratio        —— 拦截一切游戏/菜单画面
      2) 图标带深色覆盖 ≥ trigger_ratio —— 「读满」
      3) 图标带深色列簇数 ≥ min_clusters —— 元素图标行 5~7 个分离簇；
         mihoyo/原神 logo 只有 1~3 个宽簇
      4) 图标带上下边缘区域纯白 ≥ margin_white —— 竖排大 logo 会越出图标带
    读满后触发一次；cooldown 防止同一次启动重复触发。"""

    def __init__(self, cfg: dict):
        s = cfg.get("startup", {})
        self.enabled = bool(s.get("enabled", False))
        self.check_interval = float(s.get("check_interval", 0.5))
        self.icon_roi = s.get("icon_roi", [900, 660, 850, 130])  # x, y, w, h
        self.white_ratio = float(s.get("white_ratio", 0.9))
        self.trigger_ratio = float(s.get("trigger_ratio", 0.11))
        self.release_ratio = float(s.get("release_ratio", 0.06))
        self.min_clusters = int(s.get("min_clusters", 5))
        self.margin_white = float(s.get("margin_white", 0.995))
        self.match_frames = int(s.get("match_frames", 2))
        self.cooldown = float(s.get("cooldown_seconds", 60.0))
        self._hits = 0
        self._active = False
        self._last_check = 0.0
        self._last_trigger_at = -1e9

    def _band_coverage(self, frame) -> float:
        """图标带内深色像素占比（0-1）。"""
        x, y, w, h = self.icon_roi
        band = frame[y : y + h, x : x + w]
        gray = band[..., 0] * 0.114 + band[..., 1] * 0.587 + band[..., 2] * 0.299
        return float((gray < 200).mean())

    def _band_clusters(self, frame) -> int:
        """图标带内深色列簇数：元素图标行（从左到右逐个出现）= 5~7 个分离簇；
        米哈游/原神 logo 为 1~3 个宽簇。用于区分标志界面与读条界面。"""
        x, y, w, h = self.icon_roi
        band = frame[y : y + h, x : x + w]
        gray = band[..., 0] * 0.114 + band[..., 1] * 0.587 + band[..., 2] * 0.299
        col = (gray < 200).sum(axis=0)
        xs = np.where(col > 10)[0]
        if len(xs) == 0:
            return 0
        n = 1
        prev = xs[0]
        for xx in xs[1:]:
            if xx - prev > 25:
                n += 1
            prev = xx
        return n

    def _margin_white(self, frame) -> float:
        """图标带上下边缘区域的纯白占比（取两者较小值）。
        读条界面上下纯白；竖排大 logo（米哈游/原神）越出图标带 → 显著下降。"""
        x, y, w, h = self.icon_roi
        hf, wf = frame.shape[:2]
        gray = frame[..., 0] * 0.114 + frame[..., 1] * 0.587 + frame[..., 2] * 0.299
        up = gray[max(0, y - 160) : max(0, y - 30), x : min(wf, x + w)]
        dn = gray[min(hf, y + h + 30) : min(hf, y + h + 160), x : min(wf, x + w)]
        a = float((up > 240).mean())
        b = float((dn > 240).mean())
        return min(a, b)

    def update(self, frame, now: float) -> bool:
        """每帧调用（内部节流）。返回 True = 读满边沿触发。"""
        if not self.enabled:
            return False
        if now - self._last_check < self.check_interval:
            return False
        self._last_check = now
        gray = frame[..., 0] * 0.114 + frame[..., 1] * 0.587 + frame[..., 2] * 0.299
        white = float((gray > 240).mean())
        cov = self._band_coverage(frame)
        ncl = self._band_clusters(frame)
        mw = self._margin_white(frame)
        if (white >= self.white_ratio and cov >= self.trigger_ratio
                and ncl >= self.min_clusters and mw >= self.margin_white):
            self._hits += 1
            if (self._hits >= self.match_frames and not self._active
                    and now - self._last_trigger_at > self.cooldown):
                self._active = True
                self._last_trigger_at = now
                return True
        else:
            self._hits = 0
            if cov < self.release_ratio:
                self._active = False
        return False


# ---------------------------------------------------------------- detector
class BurstTrigger:
    def __init__(self, cfg: dict, stop_event=None, log=None, fx=None):
        """
        cfg: 配置字典
        stop_event: threading.Event，置位后主循环退出（供 GUI 停止使用）
        log: 日志回调 callable(msg)；缺省打印到控制台
        fx: FxClient 实例（灯光特效），可为 None；触发时同步启动灯光秀
        """
        self.cfg = cfg
        self.hotkey = cfg["hotkey"].lower()
        self.cooldown = cfg["cooldown_seconds"]
        self.threshold = cfg["flash_threshold"]
        self.target_slot = cfg.get("target_slot", 2)
        self.debug = cfg.get("debug", False)
        self.fx = fx
        self.use_slot_check = bool(cfg.get("use_slot_check", False))
        d = cfg.get("detection", {})
        self.det_mode = d.get("mode", "recognition")  # recognition | flash | both
        self.window_sec = float(d.get("window_seconds", cfg.get("flash_window_seconds", 1.2)))
        self.recognizer = BurstRecognizer(cfg) if self.det_mode in ("recognition", "both") else None
        self._recog_hits = 0
        self.completion = CompletionMonitor(cfg)
        self.shop = ShopMonitor(cfg)
        self.startup = StartupMonitor(cfg)
        self._fx_until = 0.0  # 特效结束时间戳：期间暂停通关检测（避免灯光干扰）

        import threading
        self._stop = stop_event if stop_event is not None else threading.Event()
        self._log = log if callable(log) else (lambda msg: print(msg))

        self._q_pressed_at: float | None = None
        self._q_pending_at: float | None = None
        self._lum_at_q: float | None = None
        self._baseline: tuple | None = None  # Q 瞬间场景基准 (ice0, corr0列表) — 奥黛塔
        self._baseline_col: tuple | None = None  # 同上 — 哥伦比娅
        self._last_trigger_at = 0.0
        self._last_q_at = 0.0

        # 玛薇卡独立识别器（可选；config 的 mavuika 段启用）
        self.mavuika_rec: BurstRecognizer | None = None
        self._mav_hits = 0
        self.last_mavuika_score = 0.0
        mav_cfg = cfg.get("mavuika", {})
        if mav_cfg.get("enabled", False) and self.det_mode in ("recognition", "both"):
            try:
                mr = BurstRecognizer({"detection": mav_cfg})
                if mr.ready:
                    self.mavuika_rec = mr
                    self._log(f"[玛薇卡] 爆发识别已加载（{len(mr._refs)} 张参考图，{len(mr._neg_tpls)} 个负样本）")
                else:
                    self._log("[玛薇卡] 参考图缺失，识别未启用")
            except Exception as e:
                self._log(f"[玛薇卡] 识别加载失败: {e}")

        # 哥伦比娅独立识别器（可选；config 的 columbina 段启用）
        self.columbina_rec: BurstRecognizer | None = None
        self._col_hits = 0
        self.last_columbina_score = 0.0
        col_cfg = cfg.get("columbina", {})
        if col_cfg.get("enabled", False) and self.det_mode in ("recognition", "both"):
            try:
                cr = BurstRecognizer({"detection": col_cfg})
                if cr.ready:
                    self.columbina_rec = cr
                    self._log(f"[哥伦比娅] 爆发识别已加载（{len(cr._refs)} 张参考图，{len(cr._neg_tpls)} 个负样本）")
                else:
                    self._log("[哥伦比娅] 参考图缺失，识别未启用")
            except Exception as e:
                self._log(f"[哥伦比娅] 识别加载失败: {e}")

        # GUI 轮询用（只读状态）
        self.last_lum: float | None = None
        self.last_slot: int | None = None

    # -- 键盘钩子回调（pynput 线程）--
    def _on_press(self, key) -> None:
        try:
            name = key.char.lower() if hasattr(key, "char") and key.char else None
        except Exception:
            name = None
        if name == self.hotkey:
            now = time.monotonic()
            if now - self._last_q_at > 1.0:  # 1 秒内连按只算一次
                self._last_q_at = now
                self._q_pressed_at = now
                if self.debug:
                    self._log(f"[Q] 按下")

    # -- 亮度统计 --
    @staticmethod
    def _luminance(frame: np.ndarray) -> float:
        gray = frame[..., 0] * 0.114 + frame[..., 1] * 0.587 + frame[..., 2] * 0.299
        return float(gray.mean())

    # -- 主循环 --
    def run(self) -> None:
        import dxcam
        from pynput import keyboard

        camera = dxcam.create(output_idx=0, output_color="BGR")
        if camera is None:
            print("无法创建屏幕捕获（dxcam）—— 请确认游戏运行在无边框窗口模式。")
            sys.exit(1)

        fps = self.cfg.get("capture_fps", 30)
        player = None
        listener = None
        victory_sound = None
        victory_bgm = None
        mavuika_player = None
        columbina_player = None
        shop_player = None
        try:
            camera.start(target_fps=fps, video_mode=True)

            # 音频路径自行解析（不依赖调用方补 audio_path 派生字段）
            player = BgmPlayer(resolve_audio(self.cfg), self.cfg.get("volume", 0.9))
            panel = PartyPanel(self.cfg)

            # 通关音效（unbelievable!）
            if self.completion.enabled and self.completion.recognizer is not None:
                try:
                    victory_sound = BgmPlayer(
                        Path(self.completion.sound_file) if Path(self.completion.sound_file).is_absolute()
                        else BASE / self.completion.sound_file, 0.9)
                    self._log("[通关] 幽境危战通关监控已启用（等待通关结算页…）")
                except Exception as e:
                    self._log(f"[通关] 音效加载失败（监控仍会触发特效）: {e}")
            # 通关 BGM（unbelievable 结束后播放，特效结束后延迟淡出）
            if self.completion.enabled:
                try:
                    comp = self.cfg.get("completion", {})
                    bgm_path = Path(comp.get("bgm_file", "assets/victory_bgm.wav"))
                    if not bgm_path.is_absolute():
                        bgm_path = BASE / bgm_path
                    if bgm_path.exists():
                        victory_bgm = BgmPlayer(bgm_path, 0.9)
                        self._log("[通关] 通关 BGM 已加载（unbelievable 之后播放）")
                    else:
                        self._log(f"[通关] BGM 文件不存在（跳过）: {bgm_path}")
                except Exception as e:
                    self._log(f"[通关] BGM 加载失败（跳过）: {e}")
            # 玛薇卡专属 BGM（元素爆发触发播放；特效为火焰爆炸）
            if self.mavuika_rec is not None:
                try:
                    mav_cfg = self.cfg.get("mavuika", {})
                    audio = Path(mav_cfg.get("audio_file", "assets/mavuika_bgm.wav"))
                    if not audio.is_absolute():
                        audio = BASE / audio
                    if audio.exists():
                        mavuika_player = BgmPlayer(audio, mav_cfg.get("volume", self.cfg.get("volume", 0.9)))
                        self._log("[玛薇卡] 专属 BGM 就绪")
                    else:
                        self._log(f"[玛薇卡] BGM 文件不存在（仅识别不播音乐）: {audio}")
                except Exception as e:
                    self._log(f"[玛薇卡] BGM 加载失败: {e}")
            # 哥伦比娅专属 BGM（元素爆发触发播放；特效待定）
            if self.columbina_rec is not None:
                try:
                    col_cfg = self.cfg.get("columbina", {})
                    audio = Path(col_cfg.get("audio_file", "assets/columbina_bgm.wav"))
                    if not audio.is_absolute():
                        audio = BASE / audio
                    if audio.exists():
                        columbina_player = BgmPlayer(audio, col_cfg.get("volume", self.cfg.get("volume", 0.9)))
                        self._log("[哥伦比娅] 专属 BGM 就绪")
                    else:
                        self._log(f"[哥伦比娅] BGM 文件不存在（仅识别不播音乐）: {audio}")
                except Exception as e:
                    self._log(f"[哥伦比娅] BGM 加载失败: {e}")
            # 商城 BGM（进入创世结晶购买页循环播放，离开淡出停止）
            if self.shop.enabled and self.shop.recognizer is not None:
                try:
                    sp = self.cfg.get("shop", {})
                    audio = Path(sp.get("audio_file", "assets/shop_bgm.mp3"))
                    if not audio.is_absolute():
                        audio = BASE / audio
                    if audio.exists():
                        shop_player = BgmPlayer(audio, sp.get("volume", self.cfg.get("volume", 0.9)))
                        self._log("[商城] 创世结晶购买页 BGM 就绪（进入播放/离开淡出）")
                    else:
                        self._log(f"[商城] BGM 文件不存在（仅识别不播音乐）: {audio}")
                except Exception as e:
                    self._log(f"[商城] BGM 加载失败: {e}")

            listener = keyboard.Listener(on_press=self._on_press)
            listener.start()

            if self.recognizer is not None and not self.recognizer.ready:
                self._log(f"[识别] 警告：参考图未加载（{self.recognizer.ref_path}），识别将始终不匹配")

            self._log("[启动] Q + " + self.det_mode + "模式 | 冷却 " + str(self.cooldown) + "s" +
                      (" | 出战槽位校验 " + str(self.target_slot) if self.use_slot_check else " | 无槽位校验"))
            self._log("[提示] 奥黛塔/玛薇卡/哥伦比娅各自的爆发演示画面会触发专属效果；播放期间不会重复触发。Ctrl+C 退出。")

            while True:
                if self._stop.is_set():
                    break
                frame = camera.get_latest_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue

                # 出战槽位持续跟踪（仅开启槽位校验时需要）
                if self.use_slot_check:
                    panel.update(frame)
                    self.last_slot = panel.active_slot
                now = time.monotonic()

                # 持续监控（通关/商城/启动）：仅在非确认窗口期运行——
                # 确认窗口（Q 后 2.5s）内爆发识别优先级最高，避免监控抢帧拖慢触发
                if self._q_pending_at is None:
                    # 幽境危战通关页监控（持续，独立于 Q；特效播放期间暂停，避免灯光干扰识别）
                    if now >= self._fx_until and self.completion.update(frame, now):
                        self._log("[通关] 幽境危战通关！胜利特效启动 🎉")
                        self._start_victory(victory_sound, victory_bgm)

                    # 商城创世结晶购买页监控（持续，独立于 Q；特效播放期间暂停）
                    if now >= self._fx_until:
                        enter, leave = self.shop.update(frame, now)
                        if enter:
                            if shop_player is not None and not shop_player.is_playing():
                                shop_player.play(loops=-1)
                                self._log("[商城] 检测到创世结晶购买页！《朋友的酒》开始循环播放")
                        elif leave:
                            if shop_player is not None and shop_player.is_playing():
                                try:
                                    fade = float(self.cfg.get("shop", {}).get("fade_seconds", 1.5))
                                    shop_player.channel.fadeout(int(fade * 1000))
                                except Exception:
                                    pass
                                self._log("[商城] 已离开购买页，BGM 淡出停止")

                    # 启动加载屏「元素读条读满」监控 → 派蒙迎接视频（播放一次）
                    if now >= self._fx_until and self.startup.update(frame, now):
                        sp = self.cfg.get("startup", {})
                        dur = float(sp.get("paimon_duration", 10.0))
                        fx_cfg = self.cfg.get("fx", {})
                        if (self.fx is not None and fx_cfg.get("enabled", True)
                                and fx_cfg.get("paimon_frames")):
                            try:
                                self.fx.start_paimon(dur)
                                self._fx_until = time.monotonic() + dur + 2.0
                                self._log(f"[启动] 元素读条读满！派蒙迎接视频播放（{dur:.1f}s，一次）")
                            except Exception as e:
                                self._log(f"[启动] 派蒙视频启动失败: {e}")
                        else:
                            self._log("[启动] 元素读条读满（派蒙帧未加载，跳过视频）")

                # Q 按下 → （可选出战校验）→ 武装确认
                if self._q_pressed_at is not None and now - self._q_pressed_at > 0.05:
                    if (player.is_playing()
                            or (mavuika_player is not None and mavuika_player.is_playing())
                            or (columbina_player is not None and columbina_player.is_playing())):
                        self._log("[跳过] BGM 播放中，不重复触发")
                    else:
                        slot_ok = True
                        if self.use_slot_check:
                            slot_ok = self.active_slot_ok(panel)
                        if slot_ok:
                            region = self.cfg.get("flash_region")
                            f = frame
                            if region is not None:
                                x, y, w, h = region
                                f = frame[y : y + h, x : x + w]
                            self._q_pending_at = now
                            self._lum_at_q = self._luminance(f)
                            self._recog_hits = 0
                            self._mav_hits = 0
                            self._col_hits = 0
                            # 场景基准：Q 瞬间全帧的冰蓝占比 + 各参考图直方图相关度。
                            # 识别器据此把 ice/hist 转为相对增量——大范围蓝色场景
                            # （海边/天云峠）或蓝色 UI（队伍配置页）天然抬高绝对值
                            # 导致误触发，增量形式只保留爆发带来的突变，底色不再计分。
                            self._baseline = None
                            self._baseline_col = None
                            if self.recognizer is not None:
                                try:
                                    s0, _ = self.recognizer._prepare(frame)
                                    fhist0 = self.recognizer._hist(s0)
                                    corr0 = [max(0.0, cv2.compareHist(h, fhist0, cv2.HISTCMP_CORREL))
                                             for h, _ in self.recognizer._refs]
                                    self._baseline = (self.recognizer._ice(s0), corr0)
                                except Exception:
                                    self._baseline = None
                            if self.columbina_rec is not None:
                                try:
                                    s0, _ = self.columbina_rec._prepare(frame)
                                    fhist0 = self.columbina_rec._hist(s0)
                                    corr0c = [max(0.0, cv2.compareHist(h, fhist0, cv2.HISTCMP_CORREL))
                                              for h, _ in self.columbina_rec._refs]
                                    self._baseline_col = (self.columbina_rec._ice(s0), corr0c)
                                except Exception:
                                    self._baseline_col = None
                            if self.debug:
                                self._log(f"[武装] 等待爆发确认（{self.det_mode}，窗口 {self.window_sec:.1f}s）")
                        else:
                            if self.debug:
                                self._log(f"[忽略] 出战=槽{panel.active_slot}（目标=槽{self.target_slot}）")
                    self._q_pressed_at = None

                # 确认阶段
                if self._q_pending_at is not None:
                    fired = False
                    fired_kind = "odette"
                    shared = None  # 帧预处理结果（奥黛塔/玛薇卡识别器共享）
                    # 闪光通道（方向不限的亮度突变）
                    if self.det_mode in ("flash", "both"):
                        region = self.cfg.get("flash_region")
                        f = frame
                        if region is not None:
                            x, y, w, h = region
                            f = frame[y : y + h, x : x + w]
                        lum = self._luminance(f)
                        self.last_lum = lum
                        delta = lum - self._lum_at_q
                        if self.debug:
                            self._log(f"[待确认] lum={lum:6.1f} delta={delta:+6.1f}")
                        if abs(delta) > self.threshold:
                            fired = True
                    # 识别通道（奥黛塔爆发演示画面比对）
                    if self.det_mode in ("recognition", "both") and not fired:
                        if shared is None:
                            shared = self.recognizer._prepare(frame)
                        score = self.recognizer.check(frame, shared, baseline=self._baseline)
                        self.last_score = score
                        if score >= self.recognizer.threshold:
                            self._recog_hits += 1
                        else:
                            self._recog_hits = 0
                        if self.debug:
                            self._log(f"[识别] score={score:+.3f} hits={self._recog_hits}/{self.recognizer.match_frames}")
                        if self._recog_hits >= self.recognizer.match_frames:
                            fired = True
                            fired_kind = "odette"
                    # 识别通道（玛薇卡爆发演示，独立识别器）
                    if self.det_mode in ("recognition", "both") and not fired and self.mavuika_rec is not None:
                        if shared is None:
                            shared = self.mavuika_rec._prepare(frame)
                        mscore = self.mavuika_rec.check(frame, shared)
                        self.last_mavuika_score = mscore
                        if mscore >= self.mavuika_rec.threshold:
                            self._mav_hits += 1
                        else:
                            self._mav_hits = 0
                        if self.debug:
                            self._log(f"[玛薇卡] score={mscore:+.3f} hits={self._mav_hits}/{self.mavuika_rec.match_frames}")
                        if self._mav_hits >= self.mavuika_rec.match_frames:
                            fired = True
                            fired_kind = "mavuika"
                    # 识别通道（哥伦比娅爆发演示，独立识别器）
                    if self.det_mode in ("recognition", "both") and not fired and self.columbina_rec is not None:
                        if shared is None:
                            shared = self.columbina_rec._prepare(frame)
                        cscore = self.columbina_rec.check(frame, shared, baseline=self._baseline_col)
                        self.last_columbina_score = cscore
                        if cscore >= self.columbina_rec.threshold:
                            self._col_hits += 1
                        else:
                            self._col_hits = 0
                        if self.debug:
                            self._log(f"[哥伦比娅] score={cscore:+.3f} hits={self._col_hits}/{self.columbina_rec.match_frames}")
                        if self._col_hits >= self.columbina_rec.match_frames:
                            fired = True
                            fired_kind = "columbina"

                    if fired:
                        if fired_kind == "mavuika":
                            if (player.is_playing()
                                    or (mavuika_player is not None and mavuika_player.is_playing())
                                    or (columbina_player is not None and columbina_player.is_playing())):
                                self._log("[跳过] BGM 播放中，不重复触发")
                            elif now - self._last_trigger_at > self.cooldown:
                                self._last_trigger_at = now
                                self._log("[玛薇卡] 识别到玛薇卡元素爆发！播放专属 BGM + 火焰爆炸特效")
                                if mavuika_player is not None:
                                    mavuika_player.play()
                                # 火焰爆炸绿幕素材特效：前 3 秒，播放一次
                                fx_cfg = self.cfg.get("fx", {})
                                if (self.fx is not None and fx_cfg.get("enabled", True)
                                        and fx_cfg.get("fire_frames")):
                                    try:
                                        dur = float(self.cfg.get("mavuika", {}).get("fx_duration", 3.0))
                                        self.fx.start_fire(dur)
                                        self._fx_until = time.monotonic() + dur + 2.0
                                        self._log(f"[特效] 玛薇卡火焰爆炸启动（{dur:.1f}s，播放一次）")
                                    except Exception as e:
                                        self._log(f"[特效] 火焰爆炸启动失败: {e}")
                            else:
                                self._log("[触发] 检测到玛薇卡爆发，但处于冷却中，忽略")
                        elif fired_kind == "columbina":
                            if (player.is_playing()
                                    or (mavuika_player is not None and mavuika_player.is_playing())
                                    or (columbina_player is not None and columbina_player.is_playing())):
                                self._log("[跳过] BGM 播放中，不重复触发")
                            elif now - self._last_trigger_at > self.cooldown:
                                self._last_trigger_at = now
                                self._log("[哥伦比娅] 识别到哥伦比娅元素爆发！播放专属 BGM")
                                if columbina_player is not None:
                                    columbina_player.play()
                                # 哥伦比娅专属特效待定（用户后续补充）
                            else:
                                self._log("[触发] 检测到哥伦比娅爆发，但处于冷却中，忽略")
                        else:
                            if (player.is_playing()
                                    or (mavuika_player is not None and mavuika_player.is_playing())
                                    or (columbina_player is not None and columbina_player.is_playing())):
                                self._log(f"[跳过] BGM 播放中，不重复触发")
                            elif now - self._last_trigger_at > self.cooldown:
                                self._last_trigger_at = now
                                self._log(f"[触发] 识别到奥黛塔元素爆发！")
                                player.play()
                                self._start_fx(player)
                            else:
                                self._log(f"[触发] 检测到爆发，但处于冷却中，忽略")
                        self._q_pending_at = None
                        self._lum_at_q = None
                        self._recog_hits = 0
                        self._mav_hits = 0
                        self._col_hits = 0
                    elif now - self._q_pending_at > self.window_sec:
                        if self.debug:
                            self._log("[放弃] 窗口期结束，未确认爆发（能量不满？）")
                        self._q_pending_at = None
                        self._lum_at_q = None
                        self._recog_hits = 0
                        self._mav_hits = 0
                        self._col_hits = 0
        except KeyboardInterrupt:
            pass
        finally:
            # 任何路径退出（含初始化中途报错）都先停干净，避免 dxcam 缓存占用
            try:
                camera.stop()
            except Exception:
                pass
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass
            self._log("[退出] 已停止。")

    def active_slot_ok(self, panel: PartyPanel) -> bool:
        """出战角色 == 目标槽位 才允许触发；判定未知时默认不触发（安全优先）。"""
        return panel.active_slot == self.target_slot

    def _start_victory(self, victory_sound, victory_bgm) -> None:
        """通关庆祝序列：胜利特效 + unbelievable 音效 → 音效结束接 BGM →
        特效结束后 bgm_fade_delay_seconds 秒开始淡出（与 fx.fade_seconds 同长）。"""
        comp = self.cfg.get("completion", {})
        fx_dur = float(comp.get("fx_duration", 12))
        if self.fx is not None and self.cfg.get("fx", {}).get("enabled", True):
            self.fx.start_victory(fx_dur)
            self._fx_until = time.monotonic() + fx_dur + 2.0
        # 上一次的 BGM 若还在放，先快速收掉，避免叠音
        if victory_bgm is not None and victory_bgm.is_playing():
            try:
                victory_bgm.channel.fadeout(300)
            except Exception:
                pass
        if victory_sound is not None:
            victory_sound.play()
            if victory_bgm is not None:
                length = victory_sound.sound.get_length()
                threading.Timer(max(0.1, length + 0.05), victory_bgm.play).start()
        elif victory_bgm is not None:
            # 音效缺失时 BGM 直接开播，庆祝序列不中断
            victory_bgm.play()
        if victory_bgm is not None:
            fade_delay = float(comp.get("bgm_fade_delay_seconds", 2.0))
            fade = float(self.cfg.get("fx", {}).get("fade_seconds", 2.0))
            threading.Timer(max(0.1, fx_dur + fade_delay), self._fade_out_bgm,
                            args=(victory_bgm, fade)).start()

    def _start_fx(self, player) -> None:
        """BGM 响起的同时启动镭射灯光秀（时长取 fx.burst_duration，默认 27 秒）；
        BGM 在特效结束前同步淡出，避免长时间遮挡屏幕影响通关页检测。"""
        if self.fx is None:
            return
        fx_cfg = self.cfg.get("fx", {})
        if not fx_cfg.get("enabled", True):
            return
        try:
            duration = float(fx_cfg.get("burst_duration", 27))
            fade = float(fx_cfg.get("fade_seconds", 2.0))
            self.fx.start(duration)
            self._fx_until = time.monotonic() + duration + 2.0  # 特效期间暂停通关检测
            self._log(f"[特效] 镭射灯光秀启动（{duration:.0f}s），BGM 同步淡出")
            # 特效淡出前 fade 秒开始淡出 BGM，与灯光收尾同步
            threading.Timer(max(0.1, duration - fade), self._fade_out_bgm,
                            args=(player, fade)).start()
        except Exception as e:
            self._log(f"[特效] 启动失败: {e}")

    @staticmethod
    def _fade_out_bgm(player, fade: float) -> None:
        """让 BGM 在 fade 毫秒内淡出（pygame channel.fadeout 非阻塞）。"""
        try:
            if player.channel is not None:
                player.channel.fadeout(int(fade * 1000))
        except Exception:
            pass


# ---------------------------------------------------------------- entry
def main() -> None:
    parser = argparse.ArgumentParser(description="原神元素爆发音效触发原型")
    parser.add_argument("--test", action="store_true", help="只测试音频播放")
    parser.add_argument("--debug", action="store_true", help="调试模式（打印亮度与槽位）")
    args = parser.parse_args()

    cfg = load_config()
    if args.debug:
        cfg["debug"] = True

    if args.test:
        print(f"[测试] 播放 {cfg['audio_path']} …（Ctrl+C 停止）")
        player = BgmPlayer(cfg["audio_path"], cfg.get("volume", 0.9))
        player.play()
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            player.stop()
            print("\n[测试] 播放结束。")
        return

    from fx_client import FxClient

    fx_cfg = cfg.get("fx", {})
    fx = FxClient(enabled=fx_cfg.get("enabled", True))
    fx.warmup()  # 预启动特效进程，首次爆发零冷启动延迟
    try:
        BurstTrigger(cfg, fx=fx).run()
    finally:
        fx.close()


if __name__ == "__main__":
    main()
