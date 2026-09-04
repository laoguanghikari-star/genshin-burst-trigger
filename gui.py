"""
原神爆发触发 · 图形化控制台
============================
tkinter 界面（Python 自带，零额外依赖）：
  - 配置表单：所有常用 config.json 参数可视化编辑
  - 保存配置 / 试听 BGM / 启动检测 / 停止检测
  - 实时状态：当前画面亮度、识别到的出战槽位
  - 运行日志：完整记录判定过程（勾选「详细日志」可看到每帧决策）

用法:
  python gui.py
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from fx_client import FxClient
from voice import VoiceController, list_devices
import theme

BASE = (Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)).resolve().parent
CONFIG_PATH = BASE / "config.json"


def load_cfg() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cfg(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class App(tk.Tk):
    # 面板矩形（用于烘焙半透明圆角面板进背景图）：(x, y, w, h, 圆角)
    PANEL_RECTS = [
        (10, 52, 800, 232, 18),   # 检测设置
        (10, 290, 800, 104, 18),  # 音乐音频
        (10, 400, 800, 104, 18),  # 灯光特效
        (10, 510, 800, 62, 18),   # 语音控制
        (10, 650, 800, 220, 18),  # 运行日志
    ]

    def __init__(self):
        super().__init__()
        self.title("❖ 原神爆发触发 · 控制台")
        self.geometry("820x880")
        self.minsize(760, 820)

        self.cfg = load_cfg()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.trigger: object | None = None  # 运行中的 BurstTrigger（供轮询状态）
        self.fx = FxClient(enabled=self.cfg.get("fx", {}).get("enabled", True))
        self.voice = VoiceController(self.cfg, on_command=self._voice_action, log=self.log)
        self._log_queue: queue.Queue = queue.Queue()
        self._cmd_queue: queue.Queue = queue.Queue()

        self._build()
        self._poll_status()

    # ------------------------------------------------------------ UI
    def _ensure_bg(self) -> bool:
        """烘焙半透明面板进背景图（奥黛塔透出来）。返回是否成功。"""
        src = BASE / "assets" / "gui_bg.png"
        out = BASE / "assets" / "gui_bg_comp.png"
        if not src.exists():
            return False
        try:
            if not out.exists() or src.stat().st_mtime > out.stat().st_mtime:
                # 面板填充色 = 控件底色 BG，控件"黑边"与面板融为一体
                theme.bake_panels(src, out, self.PANEL_RECTS,
                                  alpha=185, fill=(13, 27, 46), title_band=44)
            self._bg_photo = tk.PhotoImage(file=str(out))
            return True
        except Exception:
            return False

    def _build(self):
        theme.apply_theme(self)

        # -- 背景（奥黛塔 + 半透明圆角面板） --
        if self._ensure_bg():
            tk.Label(self, image=self._bg_photo, bg=theme.BG).place(x=0, y=0, relwidth=1, relheight=1)

        # -- 窗内标题横幅（◆ 钻石 + ❋ 羽饰） --
        theme.HeaderBanner(self, "原神爆发触发 · 控制台").pack(fill="x")

        lab = theme.BG  # 控件底色与烘焙面板色一致，视觉上"浮"在半透明面板上

        def L(x, y, text, fg=theme.TEXT, bold=False):
            tk.Label(self, text=text, bg=lab, fg=fg, bd=0, highlightthickness=0,
                     font=("Microsoft YaHei UI", 10, "bold" if bold else "normal")).place(x=x, y=y)

        def VL(x, y, var, fg=theme.TEXT):
            """值标签（无边框）。"""
            lbl = tk.Label(self, textvariable=var, bg=lab, fg=fg, bd=0, highlightthickness=0,
                           font=("Microsoft YaHei UI", 10))
            lbl.place(x=x, y=y)
            return lbl

        # -- 检测设置 --
        L(26, 94, "触发快捷键")
        self.var_hotkey = tk.StringVar(value=str(self.cfg.get("hotkey", "q")))
        ttk.Combobox(self, textvariable=self.var_hotkey, values=["q", "e", "r", "f", "t"],
                     width=4).place(x=150, y=90)

        det_cfg = self.cfg.get("detection", {})
        L(26, 126, "识别匹配阈值")
        self.var_threshold = tk.DoubleVar(value=float(det_cfg.get("match_threshold", 0.55)))
        theme.RoundSlider(self, 0.30, 0.80, variable=self.var_threshold,
                          command=lambda v: self._sync_slider_label()).place(x=150, y=124)
        self.lbl_threshold = tk.Label(self, text=f"{self.var_threshold.get():.2f}",
                                      bg=lab, fg=theme.TEXT, bd=0, highlightthickness=0)
        self.lbl_threshold.place(x=560, y=128)

        L(26, 158, "识别窗口 (秒)")
        self.var_window = tk.DoubleVar(value=float(det_cfg.get("window_seconds", 2.5)))
        theme.RoundSlider(self, 1.0, 4.0, variable=self.var_window,
                          command=lambda v: self._sync_window_label()).place(x=150, y=156)
        self.lbl_window = tk.Label(self, text=f"{self.var_window.get():.1f}",
                                   bg=lab, fg=theme.TEXT, bd=0, highlightthickness=0)
        self.lbl_window.place(x=560, y=160)

        L(26, 190, "冷却时间 (秒)")
        self.var_cooldown = tk.IntVar(value=int(self.cfg.get("cooldown_seconds", 20)))
        theme.RoundSlider(self, 5, 60, variable=self.var_cooldown,
                          command=lambda v: self._sync_cooldown_label()).place(x=150, y=188)
        self.lbl_cooldown = tk.Label(self, text=f"{self.var_cooldown.get()}",
                                     bg=lab, fg=theme.TEXT, bd=0, highlightthickness=0)
        self.lbl_cooldown.place(x=560, y=192)

        L(26, 222, "抓帧率 (fps)")
        self.var_fps = tk.StringVar(value=str(self.cfg.get("capture_fps", 30)))
        ttk.Combobox(self, textvariable=self.var_fps, values=["15", "20", "30", "45", "60"],
                     width=4).place(x=150, y=218)

        self.var_debug = tk.BooleanVar(value=bool(self.cfg.get("debug", False)))
        theme.round_check(self, "详细日志（打印每帧评分/判定）", self.var_debug).place(x=26, y=248)

        # -- 音乐音频 --
        L(26, 324, "音量 (%)")
        self.var_volume = tk.IntVar(value=int(self.cfg.get("volume", 0.9) * 100))
        theme.RoundSlider(self, 0, 100, variable=self.var_volume,
                          command=lambda v: self._sync_volume_label()).place(x=150, y=322)
        self.lbl_volume = tk.Label(self, text=f"{self.var_volume.get()}%",
                                   bg=lab, fg=theme.TEXT, bd=0, highlightthickness=0)
        self.lbl_volume.place(x=560, y=326)

        L(26, 356, "BGM 文件")
        self.var_audio = tk.StringVar(value=str(self.cfg.get("audio_file", "assets/burst_bgm.wav")))
        ttk.Entry(self, textvariable=self.var_audio).place(x=150, y=352, width=380)
        theme.round_button(self, "浏览", self._browse_audio, kind="normal").place(x=545, y=350)

        # -- 灯光特效 --
        self.var_fx = tk.BooleanVar(value=bool(self.cfg.get("fx", {}).get("enabled", True)))
        theme.round_check(self, "灯光特效（探照灯 / 频谱 / 粒子 / 雪花 / GIF）", self.var_fx).place(x=26, y=436)

        L(26, 468, "灯光强度 (%)")
        self.var_fx_intensity = tk.IntVar(value=int(self.cfg.get("fx", {}).get("intensity", 0.6) * 100))
        theme.RoundSlider(self, 10, 100, variable=self.var_fx_intensity,
                          command=lambda v: self._sync_fx_label()).place(x=150, y=466)
        self.lbl_fx = tk.Label(self, text=f"{self.var_fx_intensity.get()}%",
                               bg=lab, fg=theme.TEXT, bd=0, highlightthickness=0)
        self.lbl_fx.place(x=560, y=470)

        # -- 语音控制 --
        self.var_voice = tk.BooleanVar(value=bool(self.cfg.get("voice", {}).get("enabled", False)))
        theme.round_check(self, "语音命令", self.var_voice,
                          command=self._voice_toggle).place(x=26, y=534)
        self.var_voice_status = tk.StringVar(value="语音：未开启")
        tk.Label(self, textvariable=self.var_voice_status, bg=lab,
                 fg=theme.TEXT_DIM, bd=0, highlightthickness=0,
                 font=("Microsoft YaHei UI", 9)).place(x=130, y=538)
        tk.Label(self, text="麦克风:", bg=lab, fg=theme.TEXT, bd=0, highlightthickness=0,
                 font=("Microsoft YaHei UI", 10)).place(x=310, y=536)
        self.var_mic = tk.StringVar(value=self.cfg.get("voice", {}).get("device") or "默认")
        self.mic_combo = ttk.Combobox(self, textvariable=self.var_mic,
                                      values=["默认"] + list_devices(), width=14)
        self.mic_combo.place(x=370, y=532)
        theme.round_button(self, "测试麦克风", self._voice_test, kind="normal").place(x=540, y=530)

        # -- 控制按钮（胶囊） --
        theme.round_button(self, "保存配置", self._save, kind="normal").place(x=24, y=582)
        theme.round_button(self, "试听 BGM", self._preview, kind="accent").place(x=140, y=582)
        self.btn_start = theme.round_button(self, "启动检测", self._start, kind="accent")
        self.btn_start.place(x=256, y=582)
        self.btn_stop = theme.round_button(self, "停止检测", self._stop, kind="danger")
        self.btn_stop.place(x=372, y=582)
        self.btn_stop.config(state="disabled")
        theme.round_button(self, "测试通关", self._test_victory, kind="normal").place(x=488, y=582)
        theme.round_button(self, "测试玛薇卡", self._test_mavuika, kind="normal").place(x=604, y=582)
        theme.round_button(self, "测试派蒙", self._test_paimon, kind="normal").place(x=720, y=582)

        # -- 状态行 --
        self.status_dot = tk.Label(self, text="●", bg=lab, fg=theme.ERR, bd=0, highlightthickness=0,
                                   font=("Microsoft YaHei UI", 10))
        self.status_dot.place(x=26, y=628)
        self.var_status = tk.StringVar(value="状态：已停止")
        tk.Label(self, textvariable=self.var_status, bg=lab, fg=theme.TEXT_DIM, bd=0, highlightthickness=0,
                 font=("Microsoft YaHei UI", 9)).place(x=42, y=628)

        # -- 运行日志 --
        self.log_text = tk.Text(self, state="disabled", font=("Consolas", 9),
                                bg="#0a1424", fg="#cfe3ff", insertbackground="#cfe3ff",
                                relief="flat", borderwidth=0, padx=10, pady=8)
        self.log_text.place(x=24, y=690, width=740, height=160)
        scroll = ttk.Scrollbar(self, command=self.log_text.yview)
        scroll.place(x=768, y=690, height=160)
        self.log_text.config(yscrollcommand=scroll.set)
        theme.configure_log_tags(self.log_text)

        self.log("控制台就绪。改完配置记得点「保存配置」；启动检测前请把游戏切成无边框窗口。")

    # ------------------------------------------------------------ voice
    def _current_mic_device(self):
        """下拉框选择的设备（返回 sounddevice 索引 int 或 None=默认）。
        下拉项格式为 "索引: 名称"，避免同名设备歧义。"""
        text = self.var_mic.get().strip()
        if text in ("", "默认"):
            return None
        try:
            return int(text.split(":", 1)[0].strip())
        except ValueError:
            return None

    def _voice_toggle(self):
        if self.var_voice.get():
            # 勾选框是实时开关：直接启用（不受 config 旧值 voice.enabled=false 影响）
            self.voice.enabled = True
            self.voice.device = self._current_mic_device()
            self.voice.start()
        else:
            self.voice.stop()

    def _voice_test(self):
        def work():
            try:
                from voice import list_devices, transcribe_sample
                devs = list_devices()
                self.log(f"可用麦克风: {devs}")
                self.log("请对着麦克风说「原神 启动」…（录音 3 秒）")
                path = self.cfg.get("voice", {}).get("model_path", "models/vosk-model-small-cn-0.22")
                if not Path(path).is_absolute():
                    path = BASE / path
                level, text = transcribe_sample(path, seconds=3.0, device=self._current_mic_device())
                self.log(f"录音电平: {level:.1f} | 识别结果: 「{text}」")
            except Exception as e:
                self.log(f"麦克风测试失败: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _voice_action(self, action: str):
        """语音命令分发（语音线程调用）：只入队，主线程 _poll_status 时执行。
        不用 tkinter after 跨线程调度（不可靠，会静默丢失）。"""
        self._cmd_queue.put(action)

    def _drain_cmds(self):
        while True:
            try:
                action = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            self._run_voice_action(action)

    def _run_voice_action(self, action: str):
        # 主线程执行语音动作
        if action == "launch_game":
            self._voice_launch_game()
        elif action == "quit_game":
            self._voice_quit_game()
        elif action == "fx_on":
            self.log("语音指令：打开特效（30 秒演示）")
            self.fx.start(30)
        elif action == "fx_off":
            self.log("语音指令：关闭特效")
            self.fx.stop()
        elif action == "preview_music":
            self._preview()
        elif action == "start_detect":
            self._start()
        elif action == "stop_detect":
            self._stop()
        else:
            self.log(f"未知语音命令: {action}")

    def _voice_launch_game(self):
        path = self.cfg.get("voice", {}).get("game_path", "")
        if not (path and Path(path).exists()):
            self.log(f"未找到游戏: {path}（可在 config.json 的 voice.game_path 配置）")
            return
        import subprocess as sp
        launched = False
        try:
            sp.Popen([str(path)])
            launched = True
        except OSError as e:
            if getattr(e, "winerror", None) == 740:
                # 游戏清单要求管理员权限 → runas 提权启动（弹一次 UAC）
                self.log("⚠ 游戏需要管理员权限，正在提权启动（请在 UAC 弹窗点击「是」）…")
                import ctypes
                rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(path), None, None, 1)
                if rc > 32:
                    launched = True
                else:
                    self.log(f"以管理员启动失败（错误码 {rc}），请右键游戏 exe 手动以管理员运行")
            else:
                self.log(f"游戏启动失败: {e}")
        if launched:
            self.log("⚡ 原神——启动！！！")
            if self.cfg.get("voice", {}).get("tts", True):
                def _speak():
                    try:
                        from voice import speak
                        speak("原神，启动！")
                    except Exception:
                        pass
                threading.Thread(target=_speak, daemon=True).start()

    # ------------------------------------------------------------ victory
    def _test_victory(self):
        """测试通关庆祝：Unbelievable 音效 → 通关 BGM → 胜利特效（无需真通关）。"""
        self.log("[通关] 测试按钮：播放庆祝特效")

        def work():
            try:
                # 特效进程未运行时先预热（首次点击会多等 2 秒）
                if not self.fx.is_alive():
                    self.fx.warmup()
                    time.sleep(2.5)
                comp = self.cfg.get("completion", {})
                fx_dur = float(comp.get("fx_duration", 12))
                fade = float(self.cfg.get("fx", {}).get("fade_seconds", 2.0))
                fade_delay = float(comp.get("bgm_fade_delay_seconds", 2.0))
                from main import BgmPlayer
                # 上一次的 BGM 若还在放，先快速收掉
                prev = getattr(self, "_victory_bgm", None)
                if prev is not None and prev.is_playing():
                    try:
                        prev.channel.fadeout(300)
                    except Exception:
                        pass
                # 音效（unbelievable!）与胜利特效同时启动
                snd = Path(comp.get("sound_file", "assets/unbelievable.wav"))
                if not snd.is_absolute():
                    snd = BASE / snd
                player = BgmPlayer(snd, 0.9)
                t0 = time.time()
                player.play()
                if self.cfg.get("fx", {}).get("enabled", True):
                    self.fx.start_victory(fx_dur)
                # 音效放完 → 接通关 BGM
                bgm = None
                bgm_path = Path(comp.get("bgm_file", "assets/victory_bgm.wav"))
                if not bgm_path.is_absolute():
                    bgm_path = BASE / bgm_path
                if bgm_path.exists():
                    bgm = BgmPlayer(bgm_path, 0.9)
                    self._victory_bgm = bgm
                if bgm is not None:
                    while player.is_playing():
                        time.sleep(0.05)
                    bgm.play()
                    self.log("[通关] BGM 开始播放（unbelievable 之后）")
                # 特效结束后 fade_delay 秒，BGM 开始淡出
                wait = max(0.0, t0 + fx_dur + fade_delay - time.time())
                time.sleep(wait)
                if bgm is not None and bgm.channel is not None:
                    bgm.channel.fadeout(int(fade * 1000))
                    self.log("[通关] BGM 与特效同时淡出")
            except Exception as e:
                self.log(f"[通关] 测试失败: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _test_mavuika(self):
        """测试玛薇卡：专属 BGM + 火焰爆炸特效（绿幕素材，播放一次）。"""
        self.log("[玛薇卡] 测试按钮：专属 BGM + 火焰爆炸特效")

        def work():
            try:
                if not self.fx.is_alive():
                    self.fx.warmup()
                    time.sleep(2.5)
                mav = self.cfg.get("mavuika", {})
                bgm = Path(mav.get("audio_file", "assets/mavuika_bgm.wav"))
                if not bgm.is_absolute():
                    bgm = BASE / bgm
                from main import BgmPlayer
                player = BgmPlayer(bgm, self.cfg.get("volume", 0.9))
                player.play()
                if self.cfg.get("fx", {}).get("enabled", True):
                    self.fx.start_fire(float(mav.get("fx_duration", 3.0)))
                self.log("[玛薇卡] BGM 播放中，火焰爆炸播放一次")
            except Exception as e:
                self.log(f"[玛薇卡] 测试失败: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _test_paimon(self):
        """测试派蒙迎接视频（绿幕抠像素材，全屏播放一次）。"""
        self.log("[启动] 测试按钮：派蒙迎接视频")

        def work():
            try:
                if not self.fx.is_alive():
                    self.fx.warmup()
                    time.sleep(2.5)
                dur = float(self.cfg.get("startup", {}).get("paimon_duration", 7.1))
                if self.cfg.get("fx", {}).get("enabled", True):
                    self.fx.start_paimon(dur)
                    self.log(f"[启动] 派蒙迎接视频播放（{dur:.1f}s，一次）")
            except Exception as e:
                self.log(f"[启动] 测试失败: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _voice_quit_game(self):
        import subprocess as sp
        sp.run(["taskkill", "/IM", "YuanShen.exe"], capture_output=True)
        self.log("语音指令：关闭原神")

    # ------------------------------------------------------------ actions
    def _sync_slider_label(self):
        self.lbl_threshold.config(text=f"{self.var_threshold.get():.2f}")

    def _sync_window_label(self):
        self.lbl_window.config(text=f"{self.var_window.get():.1f}")

    def _sync_cooldown_label(self):
        self.lbl_cooldown.config(text=f"{self.var_cooldown.get()}")

    def _sync_volume_label(self):
        self.lbl_volume.config(text=f"{self.var_volume.get()}%")

    def _sync_fx_label(self):
        self.lbl_fx.config(text=f"{self.var_fx_intensity.get()}%")

    def _browse_audio(self):
        path = filedialog.askopenfilename(
            title="选择 BGM 文件",
            filetypes=[("音频文件", "*.wav *.mp3 *.m4a *.flac"), ("所有文件", "*.*")],
        )
        if path:
            self.var_audio.set(path)

    def _collect_cfg(self) -> dict:
        cfg = dict(self.cfg)  # 保留未在表单中的键（flash 模式/槽位校验等高级键）
        cfg["hotkey"] = self.var_hotkey.get().strip().lower() or "q"
        cfg["detection"] = {
            **cfg.get("detection", {}),
            "match_threshold": round(float(self.var_threshold.get()), 2),
            "window_seconds": round(float(self.var_window.get()), 1),
        }
        cfg["cooldown_seconds"] = int(self.var_cooldown.get())
        cfg["volume"] = round(int(self.var_volume.get()) / 100, 2)
        cfg["capture_fps"] = int(self.var_fps.get())
        cfg["audio_file"] = self.var_audio.get().strip()
        cfg["debug"] = bool(self.var_debug.get())
        cfg["fx"] = {
            **cfg.get("fx", {}),
            "enabled": bool(self.var_fx.get()),
            "intensity": round(int(self.var_fx_intensity.get()) / 100, 2),
        }
        cfg["voice"] = {
            **cfg.get("voice", {}),
            "enabled": bool(self.var_voice.get()),
            "device": self._current_mic_device(),
        }
        return cfg

    def _save(self):
        try:
            cfg = self._collect_cfg()
            save_cfg(cfg)
            self.cfg = cfg
            self.log("配置已保存到 config.json ✓")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _preview(self):
        def work():
            try:
                from main import BgmPlayer
                audio = Path(self.cfg.get("audio_file", "assets/burst_bgm.wav"))
                if not audio.is_absolute():
                    audio = BASE / audio
                player = BgmPlayer(audio, self.cfg.get("volume", 0.9))
                player.play()
                self.log("试听中…（播放完毕自动结束）")
                if self.var_fx.get():
                    self.fx.start(player.sound.get_length())
                    self.log("灯光特效已联动启动")
                while player.is_playing():
                    time.sleep(0.2)
                self.log("试听结束。")
            except Exception as e:
                self.log(f"试听失败: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _start(self):
        if self.worker and self.worker.is_alive():
            self.log("检测已在运行中。")
            return
        self._save()  # 先落盘再按当前表单启动
        cfg = self.cfg
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._run_detector, args=(cfg,), daemon=True)
        self.worker.start()
        # 预启动特效进程：首次爆发不再有冷启动延迟
        if cfg.get("fx", {}).get("enabled", True):
            self.fx.warmup()
            self.log("灯光特效进程预热中…")
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.var_status.set("状态：检测运行中（识别模式）")

    def _run_detector(self, cfg):
        try:
            from main import BurstTrigger
            self.trigger = BurstTrigger(cfg, stop_event=self.stop_event, log=self.log, fx=self.fx)
            self.trigger.run()
        except Exception as e:
            self.log(f"[错误] {e}")
        finally:
            self.after(0, self._on_worker_done)

    def _on_worker_done(self):
        self.trigger = None
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.var_status.set("状态：已停止")

    def _stop(self):
        self.log("正在停止…")
        self.stop_event.set()
        self.fx.stop()

    # ------------------------------------------------------------ misc
    def _poll_status(self):
        """每 500ms 刷新状态行（运行中时显示实时亮度与出战槽位）。"""
        self._drain_cmds()
        self._drain_log()
        t = self.trigger
        if t is not None:
            lum = f"{t.last_lum:.0f}" if t.last_lum is not None else "--"
            slot = t.last_slot if t.last_slot is not None else "?"
            self.var_status.set(f"状态：检测运行中 | 亮度 {lum} | 出战槽位 {slot}")
            self.status_dot.config(foreground=theme.OK)
        else:
            self.status_dot.config(foreground=theme.ERR)
        # 语音状态
        if self.voice.listening:
            heard = f" | 最近: {self.voice.last_heard}" if self.voice.last_heard else ""
            self.var_voice_status.set(f"语音：聆听中…{heard}")
        elif self.var_voice.get():
            self.var_voice_status.set("语音：已开启但未运行（检查日志）")
        else:
            self.var_voice_status.set("语音：未开启")
        self.after(500, self._poll_status)

    def log(self, msg: str):
        """线程安全的日志：任何线程只入队，主线程轮询时写入界面。"""
        self._log_queue.put(msg)

    def _drain_log(self):
        while not self._log_queue.empty():
            try:
                msg = self._log_queue.get_nowait()
            except queue.Empty:
                break
            stamp = time.strftime("%H:%M:%S")
            tag = theme.log_tag_for(msg)
            self.log_text.config(state="normal")
            self.log_text.insert("end", f"[{stamp}] {msg}\n", tag)
            self.log_text.see("end")
            self.log_text.config(state="disabled")

    def destroy(self):
        self.stop_event.set()
        self.voice.stop()
        self.fx.close()
        super().destroy()


def _selftest() -> int:
    """打包自检：验证关键依赖在 exe 环境下可用。结果写入 output/selftest_result.txt。"""
    lines: list[str] = []
    ok = True

    def note(msg: str, good: bool = True):
        nonlocal ok
        lines.append(msg)
        ok = ok and good

    try:
        cfg = load_cfg()
        note("config.json OK")

        from main import BurstRecognizer
        rec = BurstRecognizer({"detection": cfg["detection"]})
        note(f"BurstRecognizer ready={rec.ready}", rec.ready)
        if rec.ready:
            probe = BurstRecognizer(
                {"detection": {**cfg["detection"], "negative_templates": []}}
            )
            import cv2
            for ref in cfg["detection"].get("reference", []):
                img = cv2.imread(str(BASE / ref))
                if img is None:
                    note(f"ref {ref}: READ FAIL", False)
                    continue
                s = probe.check(img)
                note(f"ref {ref}: match {s:.3f} (need {probe.threshold:.2f})", s >= probe.threshold)

        import dxcam
        cam = dxcam.create(output_idx=0)
        f = cam.grab()
        note(f"dxcam grab: {None if f is None else f.shape}", f is not None)

        import pygame
        note(f"pygame {pygame.version.ver} OK")

        from voice import VoiceController
        mdl = Path(cfg.get("voice", {}).get("model_path", "models/vosk-model-small-cn-0.22"))
        if not mdl.is_absolute():
            mdl = BASE / mdl
        note("vosk model dir exists=%s" % mdl.exists(), mdl.exists())

        from fx_client import FxClient
        FxClient(enabled=False)
        note("FxClient OK")
    except Exception as e:
        note("ERROR: %s: %s" % (type(e).__name__, e), False)

    out = BASE / "output" / "selftest_result.txt"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass
    return 0 if ok else 1


def main():
    if "--fx-server" in sys.argv:
        # 打包 exe 内部拉起模式：fx_server 子进程（stdin 命令管道）
        import fx_server as _fs
        _fs.main()
        return
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    # 允许从任意目录运行
    sys.path.insert(0, str(BASE))
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
