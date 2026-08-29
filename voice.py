"""
语音命令监听（vosk 离线关键词识别 + SAPI 语音反馈）
====================================================
- 连续聆听麦克风，vosk 关键词模式识别命令短语（全本地、离线）
- 命中短语 → 回调对应动作
- TTS 语音反馈（SAPI.SpVoice，失败自动静默）

配置（config.json 的 voice 块）:
  enabled      总开关
  model_path   vosk 中文模型目录（随程序分发）
  device       麦克风设备名（None = 系统默认）
  game_path    原神游戏 exe 路径
  tts          是否语音播报
  commands     短语 → 动作名 映射
"""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import vosk

BASE = Path(__file__).resolve().parent


def speak(text: str) -> bool:
    """SAPI 语音播报（失败静默返回 False）。"""
    try:
        import win32com.client
        sp = win32com.client.Dispatch("SAPI.SpVoice")
        sp.Speak(text)
        return True
    except Exception:
        return False


class VoiceController:
    """连续聆听麦克风，vosk 关键词模式识别命令短语，触发回调。"""

    def __init__(self, cfg: dict, on_command=None, log=None):
        """
        cfg: 顶层配置（voice 块在 cfg['voice']）
        on_command: callable(action_name)，命中短语时调用（语音线程）
        log: callable(msg)
        """
        v = cfg.get("voice", {})
        self.enabled = bool(v.get("enabled", True))
        self.model_path = Path(v.get("model_path", "models/vosk-model-small-cn-0.22"))
        if not self.model_path.is_absolute():
            self.model_path = BASE / self.model_path
        self.sample_rate = int(v.get("sample_rate", 16000))
        self.device = v.get("device")  # None = 默认麦克风
        self.commands = v.get("commands", {})
        self.on_command = on_command
        self.log = log if callable(log) else (lambda m: print(f"[voice] {m}"))
        self._model = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_heard = ""

    # ------------------------------------------------------------ 生命周期
    def start(self):
        if self.listening:
            return
        if not self.enabled:
            self.log("语音功能未启用（config voice.enabled=false）")
            return
        try:
            self._model = vosk.Model(str(self.model_path))
        except Exception as e:
            self.log(f"语音模型加载失败: {e}")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        self.log("语音聆听已停止")

    @property
    def listening(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------ 识别循环
    def _run(self):
        keywords = list(self.commands.keys())
        try:
            rec = vosk.KaldiRecognizer(self._model, self.sample_rate,
                                       json.dumps(keywords, ensure_ascii=False))
        except Exception as e:
            self.log(f"识别器初始化失败: {e}")
            return
        q: queue.Queue = queue.Queue()

        def callback(indata, frames, time_info, status):
            q.put(bytes(indata))

        try:
            with sd.RawInputStream(samplerate=self.sample_rate, blocksize=4000,
                                   device=self.device, dtype="int16",
                                   channels=1, callback=callback):
                self.log(f"语音聆听中…（模型就绪，说「原神 启动」试试）")
                while not self._stop.is_set():
                    try:
                        data = q.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if rec.AcceptWaveform(data):
                        res = json.loads(rec.Result())
                        self._maybe_fire(res.get("text", ""))
                    else:
                        partial = json.loads(rec.PartialResult())
                        p = partial.get("partial", "")
                        if p and p != self.last_heard:
                            self.last_heard = p
                            self.log(f"听到: {p}")
        except Exception as e:
            self.log(f"麦克风错误: {e}")
        self.log("语音聆听已结束")

    def _maybe_fire(self, text: str):
        """命中判定：短语完整出现在文本中，或短语的所有词都在文本中
        （vosk 可能漏掉个别词，如只识别出「启动」，此时不触发以免误报）。"""
        for phrase, action in self.commands.items():
            words = phrase.split()
            hit = phrase in text or (len(words) > 1 and all(w in text for w in words))
            if hit:
                self.last_heard = phrase
                self.log(f"命中命令「{phrase}」-> {action}")
                try:
                    if self.on_command:
                        self.on_command(action)
                except Exception as e:
                    self.log(f"命令执行失败: {e}")
                return


def list_devices() -> list[str]:
    """列出可用音频输入设备（带索引，避免同名设备歧义）。"""
    try:
        return [f"{i}: {d['name']}"
                for i, d in enumerate(sd.query_devices())
                if d["max_input_channels"] > 0]
    except Exception:
        return []


def transcribe_sample(model_path, seconds: float = 3.0, device=None, sample_rate: int = 16000):
    """录一段音并做自由识别（诊断用）。返回 (电平, 识别文本)。"""
    import numpy as np
    model = vosk.Model(str(model_path))
    rec = vosk.KaldiRecognizer(model, sample_rate)
    data = sd.rec(int(seconds * sample_rate), samplerate=sample_rate,
                  channels=1, dtype="int16", device=device)
    sd.wait()
    level = float(np.abs(data).mean())
    rec.AcceptWaveform(data.tobytes())
    res = json.loads(rec.Result())
    return level, res.get("text", "")
