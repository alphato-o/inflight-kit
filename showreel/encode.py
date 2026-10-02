#!/usr/bin/env python3
"""Encode captured frame folders (frames/<clip>/NNNNN.jpg + times.json, page-time ms) to Twitter-ready H.264."""
import json, os, subprocess, sys

def encode(name):
    d = f"frames/{name}"
    times = json.load(open(f"{d}/times.json"))
    frames = sorted(f for f in os.listdir(d) if f.endswith(".jpg"))[: len(times)]
    with open(f"{d}/list.txt", "w") as f:
        for k, fr in enumerate(frames):
            dur = (times[k + 1] - times[k]) / 1000 if k + 1 < len(times) else 1 / 30
            f.write(f"file '{fr}'\nduration {max(dur, 0.001):.4f}\n")
        f.write(f"file '{frames[-1]}'\n")
    out = f"{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{d}/list.txt",
                    "-vf", "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p",
                    "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "slow", "-crf", "18",
                    "-movflags", "+faststart", out], check=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=codec_name,profile,width,height,r_frame_rate:format=duration,size", "-of", "csv=p=0", out],
                           capture_output=True, text=True).stdout.split()
    print(f"{out:28s} {' '.join(probe)}")

for n in sys.argv[1:] or sorted(os.listdir("frames")):
    encode(n)
