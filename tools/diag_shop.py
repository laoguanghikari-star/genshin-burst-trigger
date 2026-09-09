# -*- coding: utf-8 -*-
"""商城误触发诊断：对误触图/氪金图逐项拆解三重信号 + 模板命中位置。"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from main import BurstRecognizer, ShopMonitor  # noqa: E402

PICS = Path(r"C:\Users\idolhikari\Pictures\Saved Pictures")
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
SHOP = CFG["shop"]


def imread(p):
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)


def build_rec():
    det = {
        "mode": "recognition",
        "reference": SHOP.get("reference", "assets/shop_tab_ref.png"),
        "template_roi": SHOP.get("template_roi", [60, 640, 300, 120]),
        "negative_roi": SHOP.get("negative_roi"),
        "negative_templates": SHOP.get("negative_templates", []),
        "neg_penalty": float(SHOP.get("neg_penalty", 1.0)),
        "match_threshold": float(SHOP.get("match_threshold", 0.45)),
        "match_frames": int(SHOP.get("match_frames", 2)),
        "window_seconds": 1.0,
    }
    return BurstRecognizer({"detection": det}), det


def analyze(name):
    rec, det = build_rec()
    frame = imread(PICS / name)
    if frame is None:
        print(f"{name}: READ FAIL")
        return
    small, gi = rec._prepare(frame)
    ice = rec._ice(small)
    fhist = rec._hist(small)
    print(f"\n=== {name} ({frame.shape[1]}x{frame.shape[0]}) ===")
    print(f"  ice={ice:.3f}  hl={ShopMonitor._mean_gray(frame, SHOP['highlight_roi']):.1f}"
          f"  dk={ShopMonitor._mean_gray(frame, SHOP['dark_roi']):.1f}"
          f"  (need hl>={SHOP['highlight_min']}, dk<={SHOP['dark_max']})")
    for idx, (hist, tpl) in enumerate(rec._refs):
        corr = max(0.0, cv2.compareHist(hist, fhist, cv2.HISTCMP_CORREL))
        res = cv2.matchTemplate(gi, tpl, cv2.TM_CCOEFF_NORMED)
        pos = float(res.max())
        _, _, _, maxloc = cv2.minMaxLoc(res)
        s = 0.25 * ice + 0.20 * corr + 0.55 * pos
        # 原图坐标（⅛ 尺度）
        px, py = maxloc[0] * 8, maxloc[1] * 8
        print(f"  ref{idx}: pos={pos:.3f}@({px},{py}) corr={corr:.3f} "
              f"-> score={s:.3f}  (thr={det['match_threshold']})")
    # 负样本情况
    if rec._neg_tpls:
        negs = [(n, float(cv2.matchTemplate(gi, t, cv2.TM_CCOEFF_NORMED).max()))
                for n, t in rec._neg_tpls]
        negs.sort(key=lambda x: -x[1])
        print("  top neg:", ", ".join(f"{n}={v:.3f}" for n, v in negs[:3]))
    print(f"  final check() = {rec.check(frame):.3f}")


for n in ["商城-氪金.png", "商城-氪金02.png",
          "商城误触发01.png", "商城误触发02.png",
          "商城误触发03.png", "商城误触发04.png"]:
    analyze(n)
