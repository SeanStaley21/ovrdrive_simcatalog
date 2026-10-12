"""Build WebP card thumbnails under thumbs/ from the car and track images in data/."""
import io
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
THUMBS = ROOT / "thumbs"
MAX_WIDTH = 640


def source_paths():
    cars = json.loads((ROOT / "data" / "cars.json").read_text(encoding="utf-8"))["cars"]
    tracks = json.loads((ROOT / "data" / "tracks.json").read_text(encoding="utf-8"))["tracks"]
    paths = [c["img"] for c in cars.values() if c.get("img")]
    paths += [t["img"] for t in tracks.values() if t.get("img")]
    return sorted(set(paths))


def encode(src):
    with Image.open(src) as im:
        im.load()
        has_alpha = "A" in im.getbands() or "transparency" in im.info
        im = im.convert("RGBA" if has_alpha else "RGB")
        if im.width > MAX_WIDTH:
            height = max(1, round(im.height * MAX_WIDTH / im.width))
            im = im.resize((MAX_WIDTH, height), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=75, method=6)
        return buf.getvalue()


def main():
    paths = source_paths()
    missing = [p for p in paths if not (ROOT / p).is_file()]
    if missing:
        sys.exit("Missing source images:\n  " + "\n  ".join(missing))

    expected = set()
    written = unchanged = 0
    for p in paths:
        dest = THUMBS / Path(p).with_suffix(".webp")
        expected.add(dest)
        data = encode(ROOT / p)
        if dest.is_file() and dest.read_bytes() == data:
            unchanged += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written += 1

    removed = 0
    if THUMBS.is_dir():
        for f in THUMBS.rglob("*.webp"):
            if f not in expected:
                f.unlink()
                removed += 1
        for d in sorted((d for d in THUMBS.rglob("*") if d.is_dir()), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()

    print(f"written: {written}, unchanged: {unchanged}, removed: {removed}")


if __name__ == "__main__":
    main()
