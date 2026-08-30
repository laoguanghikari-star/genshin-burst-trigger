"""绿幕抠像：提取 victory_green.mp4 第 3-13 秒，绿幕变透明，输出透明 GIF。"""
import cv2
import numpy as np
from pathlib import Path
from PIL import Image, ImageSequence

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "assets" / "victory_green.mp4"
OUT = BASE / "assets" / "victory_walk.gif"

START_S, END_S = 3.0, 13.0
FPS = 30


def chroma_key(frame: np.ndarray) -> np.ndarray:
    """BGR 帧 -> BGRA（绿色透明 + 去绿溢出 + 边缘渐隐）。"""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hh, ss, vv = hsv[..., 0].astype(np.int16), hsv[..., 1].astype(np.int16), hsv[..., 2].astype(np.int16)
    dh = np.minimum(abs(hh - 60), 180 - abs(hh - 60))

    # 硬绿区：alpha = 0
    hard = (dh < 15) & (ss > 70) & (vv > 40)
    # 边缘渐隐带：alpha 从 0 线性升到 255
    edge = (dh >= 15) & (dh < 40) & (ss > 50) & (vv > 30) & ~hard

    alpha = np.full((h, w), 255, np.uint8)
    alpha[hard] = 0
    edge_a = np.clip((dh[edge] - 15) / 25.0 * 255, 0, 255).astype(np.uint8)
    alpha[edge] = edge_a
    alpha = cv2.GaussianBlur(alpha, (0, 0), 1.0)

    # 去绿溢出：绿通道压到红蓝的 1.15 倍（绿色残留区域）
    b, g, r = frame[..., 0].astype(np.int16), frame[..., 1].astype(np.int16), frame[..., 2].astype(np.int16)
    green_zone = (dh < 40) & (ss > 50) & (vv > 30)
    spill = green_zone & (g > b * 1.15) & (g > r * 1.15)
    g[spill] = np.maximum(b[spill], r[spill]) * 1.10
    g = np.clip(g, 0, 255).astype(np.uint8)

    out = np.dstack([frame[..., 0], g, frame[..., 2], alpha])
    return out


def main():
    cap = cv2.VideoCapture(str(SRC))
    fps = cap.get(cv2.CAP_PROP_FPS)
    start_idx = int(START_S * fps)
    end_idx = int(END_S * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_idx)

    frames = []
    for i in range(start_idx, end_idx):
        ok, f = cap.read()
        if not ok:
            break
        frames.append(chroma_key(f))
    cap.release()
    print(f"处理帧数: {len(frames)}")

    # 全局内容包围盒（跨帧并集）
    ys, xs = [], []
    for fr in frames:
        a = fr[..., 3]
        if (a > 10).any():
            yy, xx = np.where(a > 10)
            ys.extend([yy.min(), yy.max()])
            xs.extend([xx.min(), xx.max()])
    if not xs:
        print("未检测到内容!"); return
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pad = 8
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(719, x1 + pad), min(1279, y1 + pad)
    print(f"内容包围盒: ({x0},{y0})-({x1},{y1})")

    # 裁切 + 缩放到高约 360（2K 显示尺寸）/4 = 90 @360p… 先按显示高 360 存，渲染时再缩
    target_h = 360
    pil_frames = []
    for fr in frames:
        crop = fr[y0:y1 + 1, x0:x1 + 1]
        ch, cw = crop.shape[:2]
        scale = target_h / ch
        nw, nh = max(1, int(cw * scale)), target_h
        crop = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
        pil_frames.append(Image.fromarray(crop, "RGBA"))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pil_frames[0].save(OUT, save_all=True, append_images=pil_frames[1:],
                       duration=1000 / FPS, loop=0, disposal=2, optimize=True)
    print(f"输出: {OUT} 尺寸 {pil_frames[0].size} 帧数 {len(pil_frames)} "
          f"({OUT.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
