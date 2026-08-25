"""Check the download button survived into the page GitHub Pages serves.

index.html is viewer.html with the payload inlined, built by hand and committed.
Nothing rebuilds it on push, so the only thing standing between an edit to
viewer.html and a site that does not have it is somebody remembering. This is
that somebody.

It also reads any download.json beside them. That file is written by the desktop
repository's release workflow, and it now names a file per platform rather than
one installer - so there is more in it that can be wrong, and the page's answer
to all of it is the same silent shrug: a row it does not recognise is dropped and
that platform falls back to the releases page. Silent is right in a browser and
wrong here, where somebody is looking.

Deliberately no regular expressions and no dependencies: it runs on a bare
runner and the things it looks for are literal.
"""

import json
import pathlib
import sys

REPO = "AlexM1010/visualise-music"
PREFIX = "https://github.com/" + REPO + "/releases/download/"

# Every platform the page has words for, and what it is allowed to call a file.
# Both lists are the page's own, in `GETAPP_OS` and `GETAPP_KIND`: a row using
# anything else is a row the page silently drops. The release workflow builds
# for both, and the same list lives in its matrix - add a platform in one place
# and it has to be added in the other two.
OSES = ("windows", "linux")
KINDS = ("exe", "appimage", "deb")

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
#
# The dialog is one span, so everything inside it - the picker, both warnings,
# the checksum block - is covered by that one entry. The others are the pieces
# that live outside it.
PIECES = [
    ("the anchor", '<a id="getapp"', "</a>"),
    ("its stylesheet rule", "#getapp {", "}"),
    ("the panel it opens", '<dialog id="getapp-dl">', "</dialog>"),
    ("the coffee link beside it", '<a id="bmc"', "</a>"),
    ("the platform switch", 'document.getElementById("dl_pick")', "});"),
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
# advance, what their own machine is about to accuse this of being. Losing that
# wording and keeping the download is the bad half to keep - and there is a set
# of it per platform, only one of which is ever on screen at a time, so losing
# one is a thing nobody looking at the page would see.
WORDING = {
    "windows": ("not signed", "More info", "Run anyway", "SmartScreen"),
    "Linux": ("AppImage", "libfuse2", "sudo apt install"),
}
for os_name, phrases in WORDING.items():
    for phrase in phrases:
        if phrase not in viewer:
            bad.append("viewer.html no longer says " + repr(phrase) + ", so the "
                       "panel no longer says what " + os_name + " is going to do.")

# download.json is written by the desktop repository's release workflow.
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
        for key in ("version", "tag", "downloads"):
            if key not in d:
                bad.append("download.json has no " + repr(key) + ".")

        version = str(d.get("version", ""))
        rows = d.get("downloads")

        if not isinstance(rows, list) or not rows:
            bad.append("download.json lists no downloads, so the button has "
                       "nothing to offer on any platform.")
            rows = []

        for n, row in enumerate(rows):
            where = "download.json row " + str(n)
            if not isinstance(row, dict):
                bad.append(where + " is not an object.")
                continue

            if row.get("os") not in OSES:
                bad.append(where + " is for " + repr(row.get("os")) + ", which "
                           "the page has no panel for and will drop.")
            if row.get("kind") not in KINDS:
                bad.append(where + " is a " + repr(row.get("kind")) + ", which "
                           "the page has no name for.")

            url, sha = str(row.get("url", "")), str(row.get("sha256", ""))
            if not url.startswith(PREFIX):
                bad.append(where + " is not a release download on " + REPO
                           + ", so the page will drop it and that platform "
                             "falls back to the releases page.")
            elif version not in url:
                bad.append(where + " links to " + url + ", which does not name "
                           "version " + version + ".")

            if len(sha) != 64 or sha.strip("0123456789abcdef"):
                bad.append(where + " sha256 is not a lowercase sha256, so the "
                           "page will offer the file with no way to check it.")

            if not isinstance(row.get("size"), int):
                bad.append(where + " size is not a number of bytes.")

        have = [r.get("os") for r in rows if isinstance(r, dict)]
        for os_name in OSES:
            if os_name not in have:
                bad.append("download.json offers nothing for " + os_name + ". "
                           "The release workflow publishes every platform it "
                           "builds or none of them, so this file has been "
                           "edited by hand.")

        # The page offers the *first* row for a platform and puts any others on
        # the quiet line underneath. On Linux that order is a decision: the
        # AppImage needs no install and no root and runs on everything, so it is
        # the one to hand somebody who has not said which they want.
        linux = [r for r in rows if isinstance(r, dict) and r.get("os") == "linux"]
        if linux and linux[0].get("kind") != "appimage":
            bad.append("download.json offers the " + str(linux[0].get("kind"))
                       + " before the AppImage on Linux, so that is the one the "
                         "button hands over.")

        for row in rows:
            if isinstance(row, dict):
                print("download.json offers " + version + " for "
                      + str(row.get("os")) + " as " + str(row.get("kind"))
                      + ": " + str(row.get("url")))
    elif d is not None:
        bad.append("download.json is not an object.")

if bad:
    print("", *bad, sep="\n  - ", file=sys.stderr)
    sys.exit(1)

print("The download button is in index.html as viewer.html writes it.")
