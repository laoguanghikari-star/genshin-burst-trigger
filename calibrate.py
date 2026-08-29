"""
校准工具：实时预览 + 亮度监测 + 出战槽位检测
============================================
用途:
  1. 确认 dxcam 能抓到游戏画面（游戏请用「无边框窗口」模式）
  2. 观察待机亮度 vs 爆发时亮度，确定 flash_threshold 阈值
  3. 实时验证出战角色检测：窗口左上角会显示当前识别到的出战槽位

操作:
  - 窗口内实时显示画面（缩小预览）、平均亮度和出战槽位
  - 按 T：标记「这是一帧爆发画面」
  - 按 R：重置标记
  - 按 ESC：退出

启动后先进游戏放一次元素爆发（不要按 Q），标记几次爆发帧后给出建议阈值。

用法:
  python calibrate.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import dxcam
import numpy as np

BASE = Path(__file__).resolve().parent


def luminance(frame: np.ndarray) -> float:
    gray = frame[..., 0] * 0.114 + frame[..., 1] * 0.587 + frame[..., 2] * 0.299
    return float(gray.mean())


def load_panel_cfg() -> dict:
    with open(BASE / "config.json", "r", encoding="utf-8") as f:
        return json.load(f).get("party_panel", {})


def detect_active_slot(frame, panel_cfg) -> int | None:
    """与 main.py 的 PartyPanel 相同逻辑，供校准预览使用。"""
    x, w = panel_cfg["x"], panel_cfg["w"]
    half_h = panel_cfg["slot_half_h"]
    margin = 25
    gray = frame[..., 0] * 0.114 + frame[..., 1] * 0.587 + frame[..., 2] * 0.299
    lums = []
    for cy in panel_cfg["slot_centers"]:
        y0 = cy - half_h
        patch = gray[y0 + 4 : y0 + 12, x + 4 : x + 12]
        lums.append(float(patch.mean()))
    med = float(np.median(lums))
    idx = int(np.argmin(lums))
    if med - lums[idx] > margin:
        return idx + 1
    return None


def main() -> None:
    camera = dxcam.create(output_idx=0, output_color="BGR")
    if camera is None:
        print("无法创建屏幕捕获（dxcam）—— 请确认显卡驱动正常。")
        return
    camera.start(target_fps=30, video_mode=True)

    panel_cfg = load_panel_cfg()
    idle_lums: list[float] = []
    burst_lums: list[float] = []
    last_t = time.monotonic()
    fps = 0.0
    frame_count = 0

    print("[校准] ESC 退出 | T 标记爆发帧 | R 重置标记")
    print("[校准] 请先保持待机 3 秒，然后释放元素爆发并立刻按 T …")

    try:
        while True:
            frame = camera.get_latest_frame()
            if frame is None:
                time.sleep(0.01)
                continue

            lum = luminance(frame)
            slot = detect_active_slot(frame, panel_cfg)
            now = time.monotonic()
            frame_count += 1
            if now - last_t >= 1.0:
                fps = frame_count / (now - last_t)
                last_t = now
                frame_count = 0

            if len(idle_lums) < 90 and now < 5:
                idle_lums.append(lum)

            h, w = frame.shape[:2]
            scale = min(1.0, 960 / w)
            preview = cv2.resize(frame, (int(w * scale), int(h * scale)))
            info = (
                f"lum={lum:6.1f}  fps={fps:4.1f}  "
                f"待机均值={np.mean(idle_lums) if idle_lums else 0:6.1f}  "
                f"爆发标记={len(burst_lums)}  "
                f"出战槽位={slot if slot else '?'}"
            )
            cv2.putText(
                preview, info, (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2,
            )
            cv2.imshow("burst calibrate", preview)
            cv2.setWindowProperty("burst calibrate", cv2.WND_PROP_TOPMOST, 1)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            elif key == ord("t"):
                burst_lums.append(lum)
                print(f"[标记] 爆发帧亮度 = {lum:.1f}")
            elif key == ord("r"):
                burst_lums.clear()
                idle_lums.clear()
                print("[重置] 标记已清空")
    finally:
        camera.stop()
        cv2.destroyAllWindows()

    idle = np.mean(idle_lums) if idle_lums else None
    if idle is not None and burst_lums:
        peak = np.max(burst_lums)
        suggest = max(10.0, round((peak - idle) * 0.5, 1))
        print()
        print("=" * 46)
        print(f"待机平均亮度 : {idle:.1f}")
        print(f"爆发峰值亮度 : {peak:.1f}")
        print(f"建议 flash_threshold = {suggest}")
        print(f"（写入 config.json 的 flash_threshold 字段即可）")
        print("=" * 46)
    else:
        print("[结果] 没有足够的标记数据（至少标记一次爆发帧）")


if __name__ == "__main__":
    main()
