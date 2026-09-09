# -*- coding: utf-8 -*-
"""玛薇卡识别器全量扫描（精确分解，结果写 UTF-8 文件避免控制台乱码）。"""
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


def main():
    rec = BurstRecognizer({"detection": CFG["mavuika"]})
    rows = []
    for p in sorted(PICS.glob("*.png")):
        f = imread(p)
        if f is None or f.shape[:2] != (1440, 2560):
            continue
        score = rec.check(f)
        # 分解（与 check 相同逻辑）
        small, gi = rec._prepare(f)
        ice = rec._ice(small)
        fhist = rec._hist(small)
        detail = []
        for idx, (hist, tpl, _o) in enumerate(rec._refs):
            corr = max(0.0, cv2.compareHist(hist, fhist, cv2.HISTCMP_CORREL))
            pos = rec._match(gi, tpl, _o)
            s = 0.25 * ice + 0.20 * corr + 0.55 * pos
            pen = 0.0
            negb, negn = 0.0, "-"
            if rec.neg_ready and pos > 0.40:
                for nm, t in rec._neg_tpls:
                    v = rec._match(gi, t, _no)
                    if v > negb:
                        negb, negn = v, nm
                pen = rec.neg_penalty * max(0.0, negb - pos)
            detail.append(f"ref{idx}:corr={corr:.2f},pos={pos:.3f},neg={negn}({negb:.2f}),pen={pen:.2f},s={s - pen:.3f}")
        rows.append((score, p.name, ice, " | ".join(detail)))

    rows.sort(reverse=True)
    lines = ["MAVUIKA recognizer scan (threshold 0.5)", ""]
    for score, name, ice, detail in rows[:20]:
        lines.append(f"{score:.3f}  ice={ice:.3f}  {name}")
        lines.append(f"        {detail}")
    out = BASE / "output" / "diag_mavuika_scan.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    above = [r for r in rows if r[0] >= 0.5]
    print(f"total={len(rows)} above_thr={len(above)}")
    for s, n, _, _ in above:
        print(f"  ABOVE {s:.3f} {n.encode('ascii', 'replace').decode()}")
    print("detail ->", out)


if __name__ == "__main__":
    main()
