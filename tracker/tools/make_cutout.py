#!/usr/bin/env python3
"""Cut an aircraft out of a blue-sky photo, for the 2D chart marker and the fly-by.

    python3 tools/make_cutout.py photo.jpg static/photos/<reg>-cutout.png

Works on shots against clear sky (the usual approach photo): blue-dominant pixels
connected to the image border become transparent. Needs Pillow, NumPy and SciPy.
"""
import sys

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage


def cutout(src, dst, width=640):
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    sky = (b - r > 35) & (b >= g)
    lab, _ = ndimage.label(sky)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    fg = ndimage.binary_opening(~np.isin(lab, list(edge)), iterations=2)
    lab2, n2 = ndimage.label(fg)
    sizes = ndimage.sum(fg, lab2, range(1, n2 + 1))
    keep = np.zeros_like(fg)
    for i, s in enumerate(sizes, 1):
        if s > sizes.max() * 0.002:   # the airframe plus detached gear and engines
            keep |= lab2 == i
    keep = ndimage.binary_fill_holes(keep)
    alpha = Image.fromarray((keep * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(1.2))
    out = im.copy()
    out.putalpha(alpha)
    out = out.crop(alpha.point(lambda v: 255 if v > 20 else 0).getbbox())
    out.thumbnail((width, width), Image.LANCZOS)
    out.save(dst, optimize=True)
    print(f"{dst}: {out.size[0]}x{out.size[1]}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    cutout(sys.argv[1], sys.argv[2])
