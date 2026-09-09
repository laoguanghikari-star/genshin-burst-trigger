# -*- coding: utf-8 -*-
"""集成测试：真实启动 GUI → 启动检测 → 跑几秒主循环 → 检查日志无错误。

覆盖「单独测类构造」漏掉的路径：BGM 加载、各监控初始化、dxcam 抓帧、
fx 预热、主循环内的属性引用（曾漏过 self.shop.recognizer 导致启动即崩）。

用法: python tools/test_integration.py [秒数]
输出: output/integration_test.log（UTF-8），退出码 0=通过
"""
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import gui as G  # noqa: E402


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    app = G.App()
    app.update()
    app._start()
    t0 = time.time()
    while time.time() - t0 < secs:
        app.update()
        time.sleep(0.3)
        app._drain_cmds()
        app._drain_log()
    txt = app.log_text.get("1.0", "end")
    out = BASE / "output" / "integration_test.log"
    out.write_text(txt, encoding="utf-8")

    lines = txt.splitlines()
    bad = [l for l in lines if "错误" in l or "Traceback" in l or "AttributeError" in l]
    started = any("[启动]" in l for l in lines)
    shop_bgm = any("商城" in l and "BGM" in l for l in lines)

    app._stop()
    time.sleep(1.0)
    app.update()
    app.destroy()

    print(f"log lines={len(lines)} started={started} shop_bgm={shop_bgm} errors={len(bad)}")
    for l in bad[:5]:
        print("  ERROR:", l)
    print(f"log -> {out}")
    return 0 if (started and not bad) else 1


if __name__ == "__main__":
    sys.exit(main())
