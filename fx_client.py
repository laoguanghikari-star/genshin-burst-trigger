"""
镭射灯光特效 · 控制客户端
==========================
负责拉起 fx_server.py 进程并通过 stdin 发送命令（start/stop/quit）。
供 main.py（CLI）和 gui.py 共同使用；enabled=False 时全部为空操作。

用法:
  from fx_client import FxClient
  fx = FxClient(enabled=True)
  fx.start(duration=56.7)   # 开始灯光秀
  fx.stop()                 # 立即停止
  fx.close()                # 退出进程（程序结束时调用）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SERVER = BASE / "fx_server.py"


class FxClient:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.proc: subprocess.Popen | None = None

    def _ensure(self) -> bool:
        if not self.enabled:
            return False
        if self.proc is None or self.proc.poll() is not None:
            try:
                self.proc = subprocess.Popen(
                    [sys.executable, str(SERVER)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                self.proc = None
                return False
        return True

    def _send(self, line: str):
        if self.proc is not None and self.proc.stdin is not None:
            try:
                self.proc.stdin.write((line + "\n").encode("utf-8"))
                self.proc.stdin.flush()
            except Exception:
                pass

    def start(self, duration: float):
        if self._ensure():
            self._send(f"start {max(1.0, float(duration))}")

    def start_victory(self, duration: float = 12.0):
        """胜利模式：小人走入 + 中央礼花。"""
        if self._ensure():
            self._send(f"victory {max(1.0, float(duration))}")

    def warmup(self):
        """预启动特效进程（消除首次触发的冷启动延迟：Python/Tk 启动 + GIF 预解码）。"""
        self._ensure()

    def is_alive(self) -> bool:
        return bool(self.proc is not None and self.proc.poll() is None)

    def stop(self):
        self._send("stop")

    def close(self):
        if self.proc is not None:
            self._send("quit")
            try:
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
