"""Deterministic, structured test images (no binary fixtures)."""

import io
import random

from PIL import Image, ImageChops, ImageDraw


def structured_image(seed: int = 4, size: int = 256) -> Image.Image:
    """Smooth gradient background plus a few large coloured shapes: stable under resizing/JPEG.

    Seed 4 is the canonical fixture. pHash alone is weak against a 10% crop (seeds 1, 5, 7, 8 drift
    past distance 8), which is why the embedding path exists; seed 4 happens to stay within 8.
    """
    rng = random.Random(seed)
    base = Image.linear_gradient("L").resize((size, size))
    if rng.random() < 0.5:
        base = base.rotate(90 * rng.randint(0, 3))
    img = Image.merge("RGB", [base, base.transpose(Image.Transpose.FLIP_LEFT_RIGHT), base])
    draw = ImageDraw.Draw(img)
    for _ in range(6):
        x0, y0 = rng.randint(0, size // 2), rng.randint(0, size // 2)
        x1, y1 = x0 + rng.randint(size // 5, size // 2), y0 + rng.randint(size // 5, size // 2)
        colour = tuple(rng.randint(0, 255) for _ in range(3))
        shape = draw.ellipse if rng.random() < 0.5 else draw.rectangle
        shape((x0, y0, x1, y1), fill=colour)
    return img


def encode(img: Image.Image, fmt: str = "PNG", **kw) -> bytes:
    out = io.BytesIO()
    img.save(out, format=fmt, **kw)
    return out.getvalue()


def resized(img: Image.Image) -> Image.Image:
    return img.resize((img.width // 2, img.height // 2), Image.Resampling.LANCZOS)


def cropped(img: Image.Image) -> Image.Image:
    dx, dy = img.width // 20, img.height // 20  # 5% off each side = 10% of each dimension
    return img.crop((dx, dy, img.width - dx, img.height - dy))


def recompressed(img: Image.Image) -> Image.Image:
    return Image.open(io.BytesIO(encode(img, "JPEG", quality=40))).convert("RGB")


def colour_shifted(img: Image.Image) -> Image.Image:
    r, g, b = img.split()
    shifted = [
        ImageChops.add(r, Image.new("L", img.size, 25)),
        g,
        ImageChops.subtract(b, Image.new("L", img.size, 25)),
    ]
    return Image.merge("RGB", shifted)


VARIANTS = {
    "resized": resized,
    "cropped": cropped,
    "recompressed": recompressed,
    "colour_shifted": colour_shifted,
}
