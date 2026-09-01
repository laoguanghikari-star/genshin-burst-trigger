# -*- coding: utf-8 -*-
"""Offline sanity test: new Odette burst_ref (02 close-up frame) vs old (01)."""
import sys, json
from pathlib import Path
import numpy as np, cv2

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from main import BurstRecognizer  # noqa: E402

CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))


def imread(p):
    data = np.fromfile(str(p), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def run(name, rec, frame, baseline=None):
    s = rec.check(frame, baseline=baseline)
    print(f"{name}: {s:.3f}")
    return s


def main():
    det = CONFIG["detection"]
    rec = BurstRecognizer({"detection": det})
    print("recognizer ready:", rec.ready, "| neg:", rec.neg_ready)
    print("threshold:", rec.threshold, "| match_frames:", rec.match_frames)

    pics = Path(r"C:\Users\idolhikari\Pictures\Saved Pictures")
    old01 = imread(pics / "奥黛塔01.png")
    new02 = imread(BASE / "assets" / "burst_ref.png")

    print("\n== current config refs (face early + late) ==")
    run("  live burst close-up frame (Odette 02)", rec, new02)
    run("  late-stage frame (Odette 01)", rec, old01)

    print("\n== cross-character false-positive check (expect < 0.55) ==")
    others = {
        "mavuika01": BASE / "assets" / "mavuika_ref01.png",
        "mavuika02": BASE / "assets" / "mavuika_ref02.png",
        "columbina01": BASE / "assets" / "columbina_ref01.png",
        "columbina02": BASE / "assets" / "columbina_ref02.png",
        "columbina03": BASE / "assets" / "columbina_ref03.png",
        "columbina04": BASE / "assets" / "columbina_ref04.png",
        "columbina05": BASE / "assets" / "columbina_ref05.png",
        "columbina06": BASE / "assets" / "columbina_ref06.png",
        "qiqi": BASE / "assets" / "neg_qiqi.png",
        "qiqi2": BASE / "assets" / "neg_qiqi2.png",
        "sandrone": BASE / "assets" / "neg_sandrone.png",
        "sandrone2": BASE / "assets" / "neg_sandrone2.png",
        "citlali": BASE / "assets" / "neg_citlali01.png",
        "party_setup": BASE / "assets" / "neg_party_setup01.png",
        "completion": BASE / "assets" / "completion_ref.png",
        "shop_ref": BASE / "assets" / "shop_tab_ref.png",
    }
    worst = 0.0
    for name, p in others.items():
        f = imread(p)
        if f is None:
            print(f"  {name}: MISSING {p.name}")
            continue
        s = run(f"  {name}", rec, f)
        worst = max(worst, s)
    print(f"\nworst cross score: {worst:.3f} (threshold {rec.threshold})")

    print("\n== other recognizers still healthy (burst_ref is their negative) ==")
    for name, key in [("mavuika", "mavuika"), ("columbina", "columbina")]:
        r2 = BurstRecognizer({"detection": CONFIG[key]})
        ok = True
        for ref_name in CONFIG[key]["reference"]:
            f = imread(BASE / "assets" / Path(ref_name).name)
            s = r2.check(f)
            flag = "OK" if s >= r2.threshold else "<-- BELOW THRESHOLD!"
            if flag != "OK":
                ok = False
            print(f"  {name} self {Path(ref_name).name}: {s:.3f} {flag}")
        print(f"  {name} overall: {'healthy' if ok else 'BROKEN'}")


if __name__ == "__main__":
    main()
