# -*- coding: utf-8 -*-
"""搜索区域约束 + 负样本无条件计算的综合验证。

验证点：
  1) 真阳性不退化（各角色对自己参考图仍高分）
  2) 干扰画面分数下降（限定区域后峰值不再来自画面别处）
  3) 性能提升（每帧耗时）
"""
import json
import sys
import time
import statistics
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from main import BurstRecognizer  # noqa: E402

PICS = Path(r"C:\Users\idolhikari\Pictures\Saved Pictures")
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))


def imread(p):
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)


def bench(fn, n=15):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    return statistics.median(ts)


def main():
    recs = {k: BurstRecognizer({"detection": CFG[k]}) for k in ("detection", "mavuika", "columbina")}
    lines = []
    lines.append("== 1) 真阳性（用 2560x1440 原始截图，与实际运行时同尺寸）==")
    # 注意：必须用原始截图测。参考图自身是裁剪后的小图（如 1024x864），
    # ⅛ 后比搜索窗口还小，会误判为 0（不是代码问题，是测试输入尺寸问题）。
    for key, shots in [("detection", ["奥黛塔01.png", "奥黛塔02.png"]),
                       ("mavuika", ["玛薇卡01.png", "玛薇卡02.png"]),
                       ("columbina", ["哥伦比娅01.png", "哥伦比娅02.png",
                                      "哥伦比娅03.png", "哥伦比娅04.png",
                                      "哥伦比娅05.png", "哥伦比娅06.png"])]:
        r = recs[key]
        for n in shots:
            f = imread(PICS / n)
            if f is None:
                continue
            lines.append(f"  {key:<10} {n:<18} {r.check(f):.3f} (thr {r.threshold})")

    lines.append("")
    lines.append("== 2) 干扰画面（限定区域后应明显下降）==")
    trouble = ["七七01.png", "七七02.png", "商城误触发01.png", "商城误触发02.png",
               "商城误触发03.png", "商城误触发04.png", "奥黛塔01.png", "奥黛塔02.png",
               "哥伦比娅误触发01.png", "通关误触发01.png", "兹白01.png"]
    for key in ("mavuika", "detection", "columbina"):
        r = recs[key]
        vals = []
        for n in trouble:
            f = imread(PICS / n)
            if f is None:
                continue
            vals.append((n, r.check(f)))
        top = sorted(vals, key=lambda x: -x[1])[:4]
        lines.append(f"  {key:<10} thr={r.threshold}  top: " +
                     ", ".join(f"{n.split('.')[0]}={v:.3f}" for n, v in top))

    lines.append("")
    lines.append("== 3) 性能 ==")
    frame = imread(PICS / "玛薇卡01.png")
    shared = recs["detection"]._prepare(frame)
    for key in ("detection", "mavuika", "columbina"):
        r = recs[key]
        lines.append(f"  {key:<10} check = {bench(lambda r=r: r.check(frame, shared)):.2f} ms")
    lines.append(f"  3x total  = {bench(lambda: [recs[k].check(frame, shared) for k in recs]):.2f} ms")

    out = BASE / "output" / "verify_search_pad.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print("\n->", out)


if __name__ == "__main__":
    main()
