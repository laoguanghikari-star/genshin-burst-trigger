# -*- coding: utf-8 -*-
"""商城苛刻匹配回归验证（走真实 ShopMonitor 代码路径）。

判据：凝取结晶行 ROI 匹配 ≥ tab_threshold 且 提示语 ROI 匹配 ≥ notice_threshold
用法：python tools/verify_shop_strict.py
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from main import ShopMonitor  # noqa: E402

PICS = Path(r"C:\Users\idolhikari\Pictures\Saved Pictures")


def imread(p):
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)


def main():
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    mon = ShopMonitor(cfg)
    print(f"ready={mon.ready} tab_tpls={len(mon.tab_tpls)} notice_tpls={len(mon.notice_tpls)}")
    print(f"thresholds: tab>={mon.tab_threshold} notice>={mon.notice_threshold}")
    print(f"{'image':<26} {'tab':>7} {'notice':>8}  verdict")

    hits = []
    total = 0
    for p in sorted(PICS.glob("*.png")):
        f = imread(p)
        if f is None or f.shape[:2] != (1440, 2560):
            continue
        total += 1
        mon._last_check = 0.0
        mon.update(f, 1e9)  # 单帧判定
        hit = mon.last_tab >= mon.tab_threshold and mon.last_notice >= mon.notice_threshold
        if hit:
            hits.append(p.name)
        print(f"{p.name:<26} {mon.last_tab:7.3f} {mon.last_notice:8.3f}  {'HIT' if hit else 'miss'}")

    print(f"\n2K images: {total} | hits: {len(hits)}")
    for n in hits:
        print(f"  HIT {n}")


if __name__ == "__main__":
    main()
