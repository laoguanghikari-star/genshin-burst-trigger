# -*- coding: utf-8 -*-
"""Test face-crop template (Gemini red box) against all known frames."""
import sys, json
from pathlib import Path
import numpy as np, cv2

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from main import BurstRecognizer  # noqa: E402

CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))


def imread(p):
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)


def score_with(rec, frame):
    return rec.check(frame)


def main():
    det = dict(CONFIG["detection"])
    det["reference"] = ["assets/burst_ref_face.png"]
    rec = BurstRecognizer({"detection": det})
    print("ready:", rec.ready, "| threshold:", rec.threshold)

    pics = Path(r"C:\Users\idolhikari\Pictures\Saved Pictures")
    fr02 = imread(pics / "奥黛塔02.png")      # 实战特写帧（用户实战截图）
    fr01 = imread(pics / "奥黛塔01.png")      # 晚段帧
    face = imread(BASE / "assets" / "burst_ref_face.png")

    print("\n== face template scores ==")
    print("self (face):       %.3f" % score_with(rec, face))
    print("vs frame 02 (burst close-up live): %.3f  <- KEY" % score_with(rec, fr02))
    print("vs frame 01 (late stage):          %.3f" % score_with(rec, fr01))

    print("\n== cross-character (must stay < %.2f) ==" % rec.threshold)
    others = {
        "mavuika01": "mavuika_ref01.png", "mavuika02": "mavuika_ref02.png",
        "columbina01": "columbina_ref01.png", "columbina02": "columbina_ref02.png",
        "columbina03": "columbina_ref03.png", "columbina04": "columbina_ref04.png",
        "columbina05": "columbina_ref05.png", "columbina06": "columbina_ref06.png",
        "qiqi": "neg_qiqi.png", "qiqi2": "neg_qiqi2.png",
        "sandrone": "neg_sandrone.png", "sandrone2": "neg_sandrone2.png",
        "citlali": "neg_citlali01.png", "party_setup": "neg_party_setup01.png",
        "completion": "completion_ref.png",
    }
    worst = 0.0
    for name, fn in others.items():
        f = imread(BASE / "assets" / fn)
        s = score_with(rec, f)
        worst = max(worst, s)
        print("  %-14s %.3f" % (name, s))
    print("worst cross: %.3f" % worst)


if __name__ == "__main__":
    main()
