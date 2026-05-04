"""Generate a looping pulse animation of logo.png.

Outputs:
  - logo_pulse.gif         (drop-in for st.image)
  - logo_pulse.json        (Lottie with base64-embedded asset, for streamlit-lottie)

Run once:  python mcp_local/_make_logo_animation.py
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "logo.png")
GIF_OUT = os.path.join(HERE, "logo_pulse.gif")
JSON_OUT = os.path.join(HERE, "logo_pulse.json")
EMBED_MAX_PX = 480  # downscale for embedded base64 to keep JSON small

CANVAS = 480           # output square canvas
FRAMES = 60            # 60 frames @ 24fps = 2.5s loop
FPS = 24
SCALE_MIN = 1.00
SCALE_MAX = 1.04       # subtle 4% pulse
OPACITY_MIN = 0.92     # subtle breathing dip
OPACITY_MAX = 1.00


def ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * t)


def build_gif() -> None:
    src = Image.open(SRC).convert("RGBA")
    s = max(src.size)
    sq = Image.new("RGBA", (s, s), (0, 0, 0, 255))
    sq.paste(src, ((s - src.size[0]) // 2, (s - src.size[1]) // 2), src)
    base = sq.resize((int(CANVAS * 0.85), int(CANVAS * 0.85)), Image.LANCZOS)

    # Global palette: build from a reference frame at max-scale (richest colors)
    ref_canvas = Image.new("RGB", (CANVAS, CANVAS), (0, 0, 0))
    ref_w = int(base.size[0] * SCALE_MAX)
    ref_h = int(base.size[1] * SCALE_MAX)
    ref_scaled = base.resize((ref_w, ref_h), Image.LANCZOS)
    ref_canvas.paste(ref_scaled, ((CANVAS - ref_w) // 2, (CANVAS - ref_h) // 2), ref_scaled)
    palette_img = ref_canvas.convert("P", palette=Image.ADAPTIVE, colors=256)

    frames: list[Image.Image] = []
    for i in range(FRAMES):
        # Triangle wave 0->1->0 over the loop (perfect loop)
        t = i / FRAMES
        tri = 1 - abs(2 * t - 1)
        eased = ease_in_out(tri)
        scale = SCALE_MIN + (SCALE_MAX - SCALE_MIN) * eased
        opacity = OPACITY_MIN + (OPACITY_MAX - OPACITY_MIN) * eased

        w = int(base.size[0] * scale)
        h = int(base.size[1] * scale)
        scaled = base.resize((w, h), Image.LANCZOS)

        a = scaled.split()[3].point(lambda v, o=opacity: int(v * o))
        scaled.putalpha(a)

        canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 255))
        canvas.paste(scaled, ((CANVAS - w) // 2, (CANVAS - h) // 2), scaled)
        rgb = canvas.convert("RGB")
        # Quantize against the SAME global palette so colors stay consistent
        frames.append(rgb.quantize(palette=palette_img, dither=Image.Dither.FLOYDSTEINBERG))

    frames[0].save(
        GIF_OUT,
        save_all=True,
        append_images=frames[1:],
        duration=int(1000 / FPS),
        loop=0,
        disposal=2,
        optimize=True,
    )
    print(f"[gif] {GIF_OUT}  ({os.path.getsize(GIF_OUT) // 1024} KB, {FRAMES} frames)")


def build_lottie() -> None:
    src = Image.open(SRC).convert("RGBA")
    # Downscale + re-encode PNG, then embed as base64 (browser-rendered, no Cairo)
    src.thumbnail((EMBED_MAX_PX, EMBED_MAX_PX), Image.LANCZOS)
    buf = io.BytesIO()
    src.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    data_uri = f"data:image/png;base64,{b64}"
    w, h = src.size
    # Build keyframes: 0 -> mid -> end (perfect loop)
    op_frame = FRAMES
    mid = FRAMES // 2

    def kf(t, s, easing_in=True):
        return {
            "t": t,
            "s": s,
            "i": {"x": [0.42], "y": [1.0]} if easing_in else {"x": [0.42], "y": [0.58]},
            "o": {"x": [0.58], "y": [0.0]} if easing_in else {"x": [0.58], "y": [0.42]},
        }

    scale_kfs = [
        kf(0, [SCALE_MIN * 100, SCALE_MIN * 100]),
        kf(mid, [SCALE_MAX * 100, SCALE_MAX * 100]),
        {"t": op_frame, "s": [SCALE_MIN * 100, SCALE_MIN * 100]},
    ]
    opacity_kfs = [
        kf(0, [OPACITY_MAX * 100]),
        kf(mid, [OPACITY_MIN * 100]),
        {"t": op_frame, "s": [OPACITY_MAX * 100]},
    ]

    lottie = {
        "v": "5.7.4",
        "fr": FPS,
        "ip": 0,
        "op": op_frame,
        "w": w,
        "h": h,
        "nm": "Workmates Pulse",
        "ddd": 0,
        "assets": [{"id": "logo_image", "w": w, "h": h, "u": "", "p": data_uri, "e": 1}],
        "layers": [
            {
                "ddd": 0,
                "ind": 1,
                "ty": 2,
                "nm": "Logo",
                "refId": "logo_image",
                "sr": 1,
                "ks": {
                    "o": {"a": 1, "k": opacity_kfs},
                    "r": {"a": 0, "k": 0},
                    "p": {"a": 0, "k": [w / 2, h / 2, 0]},
                    "a": {"a": 0, "k": [w / 2, h / 2, 0]},
                    "s": {"a": 1, "k": scale_kfs},
                },
                "ao": 0,
                "ip": 0,
                "op": op_frame,
                "st": 0,
                "bm": 0,
            }
        ],
        "markers": [],
    }

    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(lottie, f, separators=(",", ":"))
    print(f"[lottie] {JSON_OUT}  ({os.path.getsize(JSON_OUT)} bytes)")


if __name__ == "__main__":
    build_gif()
    build_lottie()
