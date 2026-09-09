# -*- coding: utf-8 -*-
"""跨角色误触发分析：把某角色的素材喂给另一个角色的识别器，拆解评分构成。"""
import json
import sys
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


def breakdown(rec, frame, tag):
    """复现 check() 的每一项，打印构成。"""
    small, gi = rec._prepare(frame)
    ice = rec._ice(small)
    fhist = rec._hist(small)
    rows = []
    for idx, (hist, tpl, _o) in enumerate(rec._refs):
        corr = max(0.0, cv2.compareHist(hist, fhist, cv2.HISTCMP_CORREL))
        pos = rec._match(gi, tpl, _o)
        s = 0.25 * ice + 0.20 * corr + 0.55 * pos
        rows.append((idx, ice, corr, pos, s))
    neg_best = 0.0
    neg_name = "-"
    for name, t, _no in rec._neg_tpls:
        v = rec._match(gi, t, _no)
        if v > neg_best:
            neg_best, neg_name = v, name
    best = max(r[4] for r in rows) if rows else 0.0
    penalty = rec.neg_penalty * max(0.0, neg_best - max(r[3] for r in rows)) if rec._neg_tpls else 0.0
    final = max(0.0, best - penalty)
    print(f"  {tag:<26} ice={ice:.3f} " +
          " ".join(f"ref{i}:corr={c:.2f},pos={p:.3f}" for i, _, c, p, _ in rows) +
          f" | best={best:.3f} neg={neg_name}({neg_best:.3f}) penalty={penalty:.3f} "
          f"FINAL={final:.3f}")
    return final


def main():
    print("=== 玛薇卡识别器（阈值 0.5，无 baseline）===")
    rec = BurstRecognizer({"detection": CFG["mavuika"]})
    for n in ["mavuika_ref01.png", "mavuika_ref02.png"]:
        breakdown(rec, imread(BASE / "assets" / n), "SELF " + n)
    for n in ["burst_ref_face.png", "burst_ref_late.png"]:
        breakdown(rec, imread(BASE / "assets" / n), "ODETTE " + n)
    for n in ["奥黛塔01.png", "奥黛塔02.png", "玛薇卡01.png", "玛薇卡02.png",
              "哥伦比娅01.png", "七七01.png", "兹白01.png"]:
        p = PICS / n
        if p.exists():
            breakdown(rec, imread(p), n)

    print("\n=== 奥黛塔识别器（阈值 0.55，带 baseline）===")
    rec2 = BurstRecognizer({"detection": CFG["detection"]})
    for n in ["burst_ref_face.png", "burst_ref_late.png", "mavuika_ref01.png", "mavuika_ref02.png"]:
        breakdown(rec2, imread(BASE / "assets" / n), n)

    print("\n=== 哥伦比娅识别器（阈值 0.5，带 baseline）===")
    rec3 = BurstRecognizer({"detection": CFG["columbina"]})
    for n in ["columbina_ref01.png", "mavuika_ref01.png", "burst_ref_face.png"]:
        breakdown(rec3, imread(BASE / "assets" / n), n)


if __name__ == "__main__":
    main()
