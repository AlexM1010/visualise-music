"""Check the download button survived into the page GitHub Pages serves.

index.html is viewer.html with the payload inlined, built by hand and committed.
Nothing rebuilds it on push, so the only thing standing between an edit to
viewer.html and a site that does not have it is somebody remembering. This is
that somebody.

Deliberately no regular expressions and no dependencies: it runs on a bare
runner and the things it looks for are literal.
"""

import json
import pathlib
import sys

REPO = "AlexM1010/visualise-music"
PREFIX = "https://github.com/" + REPO + "/releases/download/"

viewer = pathlib.Path("viewer.html").read_text(encoding="utf-8")
index = pathlib.Path("index.html").read_text(encoding="utf-8")
bad = []


def block(text, opener, closer):
    """The span from opener to the first closer after it, or None."""
    i = text.find(opener)
    if i < 0:
        return None
    j = text.find(closer, i)
    return None if j < 0 else text[i:j + len(closer)]


# Verbatim rather than merely present. A stale index.html can hold an older
# version of the same block, which is the failure worth catching: the button is
# there, it looks right, and it points somewhere that stopped being true.
PIECES = [
    ("the anchor", '<a id="getapp"', "</a>"),
    ("its stylesheet rule", "#getapp {", "}"),
    ("the panel it opens", '<dialog id="getapp-dl">', "</dialog>"),
    ("the coffee link beside it", '<a id="bmc"', "</a>"),
    ("the fetch that names the newest release", 'fetch("download.json"', ")"),
]

for what, opener, closer in PIECES:
    want = block(viewer, opener, closer)
    if want is None:
        bad.append("viewer.html has no " + what + ".")
    elif want not in index:
        bad.append("index.html does not have " + what + " as viewer.html now "
                   "writes it. Rebuild it: python -u producer_graph.py")

# The panel is the whole point of the button: it is where somebody is told, in
# advance, that Windows is about to accuse the installer of being unrecognised.
# Losing that wording and keeping the download is the bad half to keep.
for phrase in ("not signed", "More info", "Run anyway", "SmartScreen"):
    if phrase not in viewer:
        bad.append("viewer.html no longer warns about " + repr(phrase) + ", so "
                   "the panel no longer says what Windows is going to do.")

# download.json is written by the desktop repository's release workflow. The
# page ignores one it does not recognise, which is safe and silent - so say so
# here instead, where somebody is looking.
path = pathlib.Path("download.json")
if not path.exists():
    print("No download.json. The button points at the releases page, which is "
          "the right answer until the first release writes one.")
else:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        bad.append("download.json is not JSON: " + str(e))
        d = None

    if isinstance(d, dict):
        for key in ("version", "tag", "url", "sha256", "size"):
            if key not in d:
                bad.append("download.json has no " + repr(key) + ".")

        url, sha = str(d.get("url", "")), str(d.get("sha256", ""))
        version = str(d.get("version", ""))

        if not url.startswith(PREFIX):
            bad.append("download.json url is not a release download on " + REPO
                       + ", so the page will ignore it and keep the fallback.")
        elif version not in url:
            bad.append("download.json says " + version + " and links to " + url
                       + ", which does not name that version.")

        if len(sha) != 64 or sha.strip("0123456789abcdef"):
            bad.append("download.json sha256 is not a lowercase sha256.")

        if not isinstance(d.get("size"), int):
            bad.append("download.json size is not a number of bytes.")

        print("download.json offers " + version + " at " + url)
    elif d is not None:
        bad.append("download.json is not an object.")

if bad:
    print("", *bad, sep="\n  - ", file=sys.stderr)
    sys.exit(1)

print("The download button is in index.html as viewer.html writes it.")
