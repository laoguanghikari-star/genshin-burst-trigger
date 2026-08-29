"""
音频截取工具：从歌曲中裁出「一滴一滴刺痛我的心 …」段
==================================================
用 imageio-ffmpeg 自带的 ffmpeg，无需系统安装 ffmpeg。

用法:
  python tools/trim.py <歌曲文件> <起始秒> [结束秒] [-o 输出路径]

示例:
  python tools/trim.py "C:/music/梦的翅膀.mp3" 62 118
      -> 输出 assets/burst_bgm.wav（从 62 秒开始播到 118 秒）
  也可以只给起始秒，播到歌曲结尾:
  python tools/trim.py "C:/music/梦的翅膀.mp3" 62
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

BASE = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="截取歌曲片段为 WAV")
    parser.add_argument("input", help="歌曲文件路径（mp3/m4a/flac/wav）")
    parser.add_argument("start", type=float, help="起始秒数")
    parser.add_argument("end", type=float, nargs="?", default=None, help="结束秒数（默认到歌曲结尾）")
    parser.add_argument("-o", "--output", default=None, help="输出路径（默认 assets/burst_bgm.wav）")
    args = parser.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"[错误] 找不到文件: {src}")
        sys.exit(1)

    out = Path(args.output) if args.output else BASE / "assets" / "burst_bgm.wav"
    out.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y",
        "-ss", str(args.start),
        "-i", str(src),
    ]
    if args.end is not None:
        cmd += ["-t", str(max(0.0, args.end - args.start))]
    cmd += [
        "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
        str(out),
    ]

    print(f"[截取] {src.name} 从 {args.start}s 起"
          + (f" 到 {args.end}s" if args.end is not None else " 到结尾"))
    print(f"[输出] {out}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("[ffmpeg 错误]")
        print(result.stderr[-2000:])
        sys.exit(result.returncode)

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"[完成] {out.name} ({size_mb:.1f} MB)，可运行 python main.py --test 试听")


if __name__ == "__main__":
    main()
