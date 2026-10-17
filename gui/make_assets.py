"""Builds gui/resources/ from the original animated GIFs.

You only need this to change the artwork:   python gui/make_assets.py "path/to/folder with B.G and ExtraGui"
(the originals are in the Jarvis Personal Archive, see its README)

Why not play the GIFs directly? They are big (up to 5.8 MB and 1440x900 pixels), so playing them as they
are would burn CPU on a modest PC, and one of them sits on a white background. This script keeps an evenly
spaced selection of frames, scales them to the size the window needs, cuts the white background away from
the JARVIS ring, and packs each animation into one PNG "sprite sheet" that the window can draw almost for free.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT = HERE / "resources"
DEFAULT_SOURCE = HERE.parent / "G.U.I Material"      # where the originals used to live inside the project

# name: (source file, frames to keep, frame width, cut the white background away)
JOBS = {
    "ring": ("ExtraGui/jarvis-4.gif", 20, 240, True),
    "earth": ("ExtraGui/Earth.gif", 72, 220, False),
    "hero": ("B.G/Iron_Template_1.gif", 30, 480, False),
}
MIN_FRAME_MS = 70            # never ask a PC to redraw faster than about 14 times a second
SHEET_WIDTH = 2400


def cut_white_background(frame):
    """Make the white that surrounds the artwork transparent, leaving white details inside it alone."""
    frame = frame.convert("RGBA")
    width, height = frame.size
    for seed in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1), (width // 2, 0), (width // 2, height - 1)):
        if frame.getpixel(seed)[:3] == (255, 255, 255) or sum(frame.getpixel(seed)[:3]) > 720:
            ImageDraw.floodfill(frame, seed, (255, 255, 255, 0), thresh=40)
    return frame


def build(name, source, keep, width, knockout):
    with Image.open(source) as gif:
        total = getattr(gif, "n_frames", 1)
        keep = min(keep, total)
        indexes = sorted({round(i * total / keep) % total for i in range(keep)})
        frames, milliseconds = [], 0
        for index in range(total):
            gif.seek(index)
            milliseconds += gif.info.get("duration", 60)
            if index in indexes:
                frame = cut_white_background(gif) if knockout else gif.convert("RGB")
                frames.append(frame.resize((width, round(frame.height * width / frame.width)), Image.LANCZOS))
    frame_ms = max(MIN_FRAME_MS, round(milliseconds / len(frames)))
    columns = max(1, min(len(frames), SHEET_WIDTH // width))
    rows = -(-len(frames) // columns)
    mode = "RGBA" if knockout else "RGB"
    sheet = Image.new(mode, (columns * frames[0].width, rows * frames[0].height))
    for number, frame in enumerate(frames):
        sheet.paste(frame.convert(mode), ((number % columns) * frame.width, (number // columns) * frame.height))
    target = OUT / f"{name}.png"
    sheet.save(target, optimize=True)
    return {"file": target.name, "frames": len(frames), "columns": columns, "size": list(frames[0].size), "frame_ms": frame_ms}


def make_icon():
    """The window icon: the first frame of the JARVIS ring, in the sizes Windows asks for."""
    ring = json.loads((OUT / "sprites.json").read_text(encoding="utf-8"))["ring"]
    width, height = ring["size"]
    frame = Image.open(OUT / ring["file"]).crop((0, 0, width, height)).convert("RGBA")
    frame.save(OUT / "jarvis.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main(source=None):
    source = Path(source) if source else DEFAULT_SOURCE
    if not source.is_dir():
        sys.exit(f"I can't find the original artwork at {source}.\nGive the folder that holds B.G and ExtraGui, "
                 "for example:  python gui/make_assets.py \"path/to/Original window artwork\"")
    OUT.mkdir(exist_ok=True)
    meta = {}
    for name, (file, keep, width, knockout) in JOBS.items():
        meta[name] = build(name, source / file, keep, width, knockout)
        print(f"{name}: {meta[name]['frames']} frames of {meta[name]['size']}, {(OUT / meta[name]['file']).stat().st_size / 1024:.0f} KB")
    (OUT / "sprites.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    make_icon()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
