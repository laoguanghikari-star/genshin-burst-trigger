# -*- coding: utf-8 -*-
"""性能基准（可复现 README 中的耗时/精度声明）

用法:
  python tools/bench.py            # 默认每帧测 20 次
  python tools/bench.py 50         # 每帧测 50 次

测什么:
  1. BurstRecognizer._prepare 单帧耗时（¼ 小图 + ⅛ 灰度）
  2. 三个识别器 check() 合计耗时（共享 shared，模拟主循环真实开销）
  3. ⅛ 尺度 vs ¼ 尺度模板匹配的分数偏差（同一批帧分别计算）

输出: output/bench_result.txt（同时打印到控制台，ASCII 标签避免 GBK 乱码）
"""
import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from main import BurstRecognizer  # noqa: E402

# 基准帧：仓库内已有的 2K 游戏截图（覆盖不同场景，无需录屏）
FRAMES = [
    "assets/burst_ref_late.png",     # 奥黛塔爆发晚段帧
    "assets/completion_ref.png",     # 通关结算页
    "assets/neg_qiqi.png",           # 其他角色
    "assets/neg_sandrone.png",       # 其他角色
]
RECOGNIZERS = ["detection", "mavuika", "columbina"]


class R4(BurstRecognizer):
    """¼ 尺度版本：用于与 ⅛ 尺度做分数偏差对比（图像与模板都用 ¼）。"""

    @staticmethod
    def _shrink(tpl):
        return cv2.resize(tpl, (tpl.shape[1] // 4, tpl.shape[0] // 4))

    @staticmethod
    def _prepare(frame):
        small = cv2.resize(frame, (frame.shape[1] // 4, frame.shape[0] // 4))
        return small, cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def imread(p: Path):
    data = np.fromfile(str(p), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def main():
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))

    recs = {k: BurstRecognizer({"detection": cfg[k]}) for k in RECOGNIZERS}
    recs4 = {k: R4({"detection": cfg[k]}) for k in RECOGNIZERS}

    lines = [f"bench: repeats={repeats} (median per frame)", ""]
    prep_ms, check_ms = [], []
    devs = []

    for name in FRAMES:
        p = BASE / name
        if not p.exists():
            lines.append(f"skip missing {name}")
            continue
        frame = imread(p)
        if frame is None:
            lines.append(f"skip unreadable {name}")
            continue

        # 1) _prepare 耗时
        t = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            recs["detection"]._prepare(frame)
            t.append((time.perf_counter() - t0) * 1000)
        pm = statistics.median(t)
        prep_ms.append(pm)

        # 2) 三个识别器 check 合计耗时（共享 shared）
        t = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            shared = recs["detection"]._prepare(frame)
            for k in RECOGNIZERS:
                recs[k].check(frame, shared)
            t.append((time.perf_counter() - t0) * 1000)
        cm = statistics.median(t)
        check_ms.append(cm)

        lines.append(f"{name}")
        lines.append(f"  prepare      : {pm:6.1f} ms")
        lines.append(f"  prepare+3x   : {cm:6.1f} ms")

        # 3) ⅛ vs ¼ 分数偏差
        for k in RECOGNIZERS:
            s8 = recs[k].check(frame)
            s4 = recs4[k].check(frame)
            devs.append(abs(s8 - s4))
            lines.append(f"  score {k:10s} 1/8={s8:.3f}  1/4={s4:.3f}  diff={abs(s8-s4):.4f}")

    if prep_ms:
        lines.append("")
        lines.append(f"median prepare      : {statistics.median(prep_ms):.1f} ms")
        lines.append(f"median prepare+3x   : {statistics.median(check_ms):.1f} ms")
        lines.append(f"max 1/8 vs 1/4 diff : {max(devs):.4f} (n={len(devs)})")

    out = BASE / "output" / "bench_result.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n[bench] written to {out}")


if __name__ == "__main__":
    main()
