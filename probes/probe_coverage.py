"""How consistently are the useful descriptors populated, across sample types?
A field that is null on every drum hit is not a feature, it is a footnote."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN = (Path(__file__).parent / "freesound.key").read_text(encoding="ascii").strip()
BASE = "https://freesound.org/apiv2"
LIC = '("Creative Commons 0" OR "Attribution")'


def get(path, **params):
    params["token"] = TOKEN
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8")), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:120], e.headers
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:120], {}


PROBE = [("kick", 0.05, 2.0), ("bassline", 1.0, 16.0), ("piano", 1.0, 16.0),
         ("riser", 0.5, 10.0), ("vocal", 0.2, 8.0)]
FIELDS = ["tonality", "tonality_confidence", "note_name", "note_midi", "note_confidence",
          "bpm", "bpm_confidence", "loopable", "single_event", "brightness", "hardness",
          "depth", "warmth", "boominess", "roughness", "sharpness", "reverbness",
          "loudness", "dynamic_range", "log_attack_time", "category", "subcategory",
          "has_audio_problems", "laion_clap", "spectral_centroid"]

present = {f: 0 for f in FIELDS}
total = 0
rows = []
t0 = time.time()

for tag, lo, hi in PROBE:
    st, d, _ = get("/search/text/", filter=f"tag:{tag} duration:[{lo} TO {hi}] license:{LIC}",
                   page_size=4, sort="downloads_desc", fields="id,name")
    if st != 200:
        print(f"search {tag} failed: {d}")
        continue
    for r in d["results"]:
        st2, a, hdr = get(f"/sounds/{r['id']}/analysis/")
        if st2 != 200:
            print(f"  analysis {r['id']} -> [{st2}] {str(a)[:80]}")
            continue
        total += 1
        for f in FIELDS:
            v = a.get(f)
            if v is not None and v != [] and v != "":
                present[f] += 1
        rows.append((tag, r["id"], str(r["name"])[:30], a.get("tonality"),
                     a.get("tonality_confidence"), a.get("note_name"), a.get("bpm"),
                     a.get("bpm_confidence"), a.get("loopable"), a.get("single_event"),
                     a.get("brightness"), a.get("subcategory"),
                     len(a.get("laion_clap") or [])))
        time.sleep(0.35)

print(f"\nanalysed {total} sounds in {time.time()-t0:.1f}s "
      f"({(time.time()-t0)/max(total,1):.2f}s each)\n")

print(f"{'tag':<9}{'id':>8}  {'name':<30} {'tonality':<12}{'conf':>5} {'note':>5} "
      f"{'bpm':>5}{'conf':>6} {'loop':>5} {'1shot':>6} {'bright':>7} {'subcategory':<24}{'clap':>5}")
for r in rows:
    tag, sid, name, ton, tc, note, bpm, bc, lp, se, br, sub, clap = r
    print(f"{tag:<9}{sid:>8}  {name:<30} {str(ton):<12}{(tc or 0):>5.2f} {str(note):>5} "
          f"{str(bpm):>5}{(bc or 0):>6.2f} {str(lp):>5} {str(se):>6} "
          f"{(br if isinstance(br,(int,float)) else 0):>7.1f} {str(sub):<24}{clap:>5}")

print("\n=== populated in how many of the sample ===")
for f in FIELDS:
    pct = 100 * present[f] / max(total, 1)
    bar = "#" * int(pct / 5)
    print(f"  {f:<24} {present[f]:>2}/{total}  {pct:5.1f}%  {bar}")
