"""Draw the site's favicon as one of the records on the map.

A node is a vinyl disc (see drawVinyl in viewer.html): dark body, a bright rim,
three grooves, a centre label in the node's colour, and a spindle hole. This
draws the same record, with two departures the map does not need.

The map strokes the rim at 22% and the grooves at 10% because a disc there sits
on a near-black page among six thousand others, where anything louder is noise.
One disc alone in a 16px tab is the opposite problem, so the rim and grooves are
lifted to 55% and 22%. Second, everything is flattened to opaque before it is
drawn: a translucent stroke on a transparent canvas punches a hole rather than
blending, and the record ends up a zebra target over a light background. So the
disc is built as concentric opaque fills, outside in, and only its silhouette
carries the alpha.

    python make_favicon.py        # rewrites favicon.ico
"""
import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "favicon.ico"
SIZES = [16, 24, 32, 48, 64]   # a tab, a bookmark, a taskbar pin; nothing needs 256
SS = 8                         # supersample; ImageDraw has no antialiasing of its own

BODY = (15, 19, 25)            # #0f1319, the disc
INK = (200, 214, 232)          # the rim and groove colour, before it is faded
LABEL = (75, 139, 214)         # #4b8bd6 - PAL[0], the first cluster colour
HOLE = (11, 14, 20)            # #0b0e14, the page showing through
RIM_A, GROOVE_A = 0.55, 0.22   # the map uses .22 and .10; see above


def over(fg, a, bg=BODY):
    """Flatten a translucent ink onto the disc, so no stroke costs opacity."""
    return tuple(round(f * a + b * (1 - a)) for f, b in zip(fg, bg)) + (255,)


def render(size):
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = n / 2
    r = n * 0.47                      # a tab is small; let the record fill it

    def disc(rad, col):
        d.ellipse([c - rad, c - rad, c + rad, c + rad], fill=col)

    # Outside in. Each ring is its own colour laid down and then cut back to the
    # body by the next fill, which is cheaper than stroking and leaves no seam.
    w = r * 0.09                                    # the rim, as drawVinyl weights it
    disc(r + w / 2, over(INK, RIM_A))
    disc(r - w / 2, BODY + (255,))
    gw = max(SS * 0.5, r * 0.045)
    for f in (0.84, 0.69, 0.54):                    # the three grooves
        disc(r * f + gw / 2, over(INK, GROOVE_A))
        disc(r * f - gw / 2, BODY + (255,))
    disc(r * 0.40, LABEL + (255,))                  # the centre label
    disc(max(SS, r * 0.09), HOLE + (255,))          # the spindle hole

    # BOX is a plain area average, which is what an 8x supersample wants. LANCZOS
    # rings against the hard edges and speckles the flat body, doubling the PNG.
    return img.resize((size, size), Image.BOX)


def write_ico(path, frames):
    """Pack the frames as PNGs inside an ICO.

    Pillow writes everything below 256px as a raw 32-bit BMP, which turns five
    flat-coloured discs into 34kB. The container has allowed a PNG payload since
    Vista and every browser that will ever load this reads one, so the frames go
    in compressed and the icon halves.
    """
    blobs = []
    for f in frames:
        b = io.BytesIO()
        f.save(b, format="PNG", optimize=True)
        blobs.append(b.getvalue())

    head = struct.pack("<HHH", 0, 1, len(blobs))          # reserved, type 1 = icon, count
    offset = len(head) + 16 * len(blobs)
    entries = b""
    for f, b in zip(frames, blobs):
        # 256 is stored as 0: the width and height fields are one byte each.
        entries += struct.pack("<BBBBHHII", f.width % 256, f.height % 256, 0, 0,
                               1, 32, len(b), offset)
        offset += len(b)
    path.write_bytes(head + entries + b"".join(blobs))


if __name__ == "__main__":
    write_ico(OUT, [render(s) for s in SIZES])
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes) - "
          + ", ".join(f"{s}x{s}" for s in SIZES))
