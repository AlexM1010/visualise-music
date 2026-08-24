"""Test the two claims from the docs that contradict my earlier conclusions:

1. Descriptors are returnable via `fields=` using their bare names (I tried
   `fields=analysis` and `fields=ac_analysis`, which are not field names).
2. Descriptors are filterable under bare names (I tried the old `ac_` prefixes,
   which 400).

Plus `similar_to` / `similarity_space` as SEARCH parameters, which would make
acoustic similarity a filterable query rather than a per-sound endpoint.
"""
import json
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
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:200]


DESC = ("id,name,duration,license,previews,tags,username,num_downloads,"
        "tonality,tonality_confidence,bpm,bpm_confidence,note_name,note_midi,"
        "note_confidence,loopable,single_event,brightness,hardness,depth,warmth,"
        "boominess,roughness,sharpness,reverbness,dissonance,dynamic_range,"
        "loudness,log_attack_time,spectral_centroid,category,subcategory")

print("=== 1. descriptors via fields= (bare names) ===")
st, d = get("/search/text/", filter=f"tag:bassline duration:[1 TO 16] license:{LIC}",
            page_size=3, sort="downloads_desc", fields=DESC)
if st == 200:
    r = d["results"][0]
    print("  keys returned:", sorted(r.keys()))
    for k in ("tonality", "tonality_confidence", "bpm", "bpm_confidence", "note_name",
              "loopable", "single_event", "brightness", "warmth", "subcategory"):
        print(f"    {k:<22} = {r.get(k)}")
else:
    print(f"  [{st}] {d}")

print("\n=== 2. descriptors as filters (bare names) ===")
for label, flt in [
    ("loopable:true", f"tag:bassline loopable:true license:{LIC}"),
    ("tonality exact", f'tonality:"C minor" license:{LIC}'),
    ("brightness range", f"tag:kick brightness:[60 TO 100] license:{LIC}"),
    ("single_event:true", f"tag:kick single_event:true license:{LIC}"),
    ("note_name:C2", f'note_name:"C2" license:{LIC}'),
    ("bpm range", f"tag:bassline bpm:[120 TO 130] license:{LIC}"),
    ("warmth + depth", f"tag:pad warmth:[50 TO 100] depth:[50 TO 100] license:{LIC}"),
    ("old ac_ prefix", f"tag:bassline ac_loop:true license:{LIC}"),
]:
    st, d = get("/search/text/", filter=flt, page_size=1, fields="id,name")
    n = d.get("count") if st == 200 and isinstance(d, dict) else None
    print(f"  [{st}] {label:<20} count={n}  {'' if st==200 else str(d)[:90]}")

print("\n=== 3. similar_to as a SEARCH parameter (combinable with filters) ===")
st, seed = get("/search/text/", filter=f"tag:bassline license:{LIC}", page_size=1,
               sort="downloads_desc", fields="id,name")
sid = seed["results"][0]["id"] if st == 200 else 45610
print(f"  seed sound: {sid} ({seed['results'][0]['name'] if st==200 else '?'})")
for space in ("laion_clap", "freesound_classic"):
    st, d = get("/search/text/", similar_to=sid, similarity_space=space,
                page_size=5, fields="id,name,tonality,bpm")
    if st == 200:
        print(f"  [{200}] similarity_space={space}: count={d.get('count')}")
        for r in d["results"][:5]:
            print(f"      {r['id']:>8}  {str(r['name'])[:40]:<40} {r.get('tonality')} {r.get('bpm')}")
    else:
        print(f"  [{st}] similarity_space={space}: {str(d)[:120]}")

print("\n=== 4. similar_to COMBINED with a filter (the useful case) ===")
st, d = get("/search/text/", similar_to=sid, similarity_space="laion_clap",
            filter=f"license:{LIC} duration:[0.1 TO 6]", page_size=5,
            fields="id,name,duration,license")
if st == 200:
    print(f"  [200] count={d.get('count')} — acoustically similar AND licence/duration filtered")
    for r in d["results"][:5]:
        print(f"      {r['id']:>8}  {str(r['name'])[:44]:<44} {r.get('duration',0):.1f}s")
else:
    print(f"  [{st}] {str(d)[:160]}")

print("\n=== 5. remix relationships (potential sound-to-sound edges) ===")
for label, flt in [("is_remix", f"is_remix:true license:{LIC}"),
                   ("was_remixed", f"was_remixed:true license:{LIC}")]:
    st, d = get("/search/text/", filter=flt, page_size=2, fields="id,name,is_remix,was_remixed")
    print(f"  [{st}] {label}: count={d.get('count') if st==200 else d}")

print("\n=== 6. how many descriptor fields survive page_size=150 ===")
st, d = get("/search/text/", filter=f"tag:kick license:{LIC}", page_size=150, fields=DESC)
if st == 200:
    got = d["results"]
    withdesc = sum(1 for r in got if r.get("tonality") is not None)
    withbpm = sum(1 for r in got if r.get("bpm") is not None)
    print(f"  [200] returned {len(got)} results; tonality on {withdesc}, bpm on {withbpm}")
else:
    print(f"  [{st}] {str(d)[:160]}")
