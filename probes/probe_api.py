"""Probe the Freesound API for anything that could become a node, an edge or a
node attribute. Reports what works rather than what the docs claim."""
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN = (Path(__file__).parent / "freesound.key").read_text(encoding="ascii").strip()
BASE = "https://freesound.org/apiv2"


def get(path, **params):
    params["token"] = TOKEN
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:180]
        return e.code, body
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:180]


def show(label, status, data, keys=None, depth=0):
    if status != 200:
        print(f"  [{status}] {label}  ->  {str(data)[:150]}")
        return
    if isinstance(data, dict):
        if keys:
            got = {k: data.get(k) for k in keys if k in data}
            print(f"  [200] {label}  ->  {json.dumps(got, default=str)[:400]}")
        else:
            print(f"  [200] {label}  ->  keys: {sorted(data.keys())[:24]}")
    else:
        print(f"  [200] {label}  ->  {str(data)[:200]}")


# A melodic sound is the interesting case for key/pitch. Find one first.
print("=== finding a melodic test sound ===")
st, d = get("/search/text/", filter='tag:piano duration:[1 TO 16] license:("Creative Commons 0" OR "Attribution")',
            page_size=3, sort="downloads_desc", fields="id,name,pack,samplerate,channels,bitdepth,num_ratings,num_comments,geotag,type,filesize")
if st == 200:
    for r in d["results"]:
        print("   ", r["id"], "|", r["name"][:44], "| pack:", r.get("pack"), "| sr:", r.get("samplerate"),
              "| ch:", r.get("channels"), "| bits:", r.get("bitdepth"), "| ratings:", r.get("num_ratings"),
              "| comments:", r.get("num_comments"), "| bytes:", r.get("filesize"))
    SID = d["results"][0]["id"]
else:
    print("   search failed:", d)
    SID = 171104

print(f"\n=== per-sound endpoints (sound {SID}) ===")
show("/sounds/{id}/", *get(f"/sounds/{SID}/"))
show("/sounds/{id}/similar/", *get(f"/sounds/{SID}/similar/", page_size=5), keys=["count"])
show("/sounds/{id}/analysis/", *get(f"/sounds/{SID}/analysis/"))
show("/sounds/{id}/comments/", *get(f"/sounds/{SID}/comments/", page_size=3), keys=["count"])

print("\n=== targeted descriptors (the key + pitch question) ===")
for desc in ["tonal.key_key,tonal.key_scale,tonal.key_strength",
             "rhythm.bpm,rhythm.bpm_confidence",
             "lowlevel.spectral_centroid.mean,lowlevel.average_loudness",
             "sfx.tempo,lowlevel.pitch.mean"]:
    st, d = get(f"/sounds/{SID}/analysis/", descriptors=desc)
    show(f"analysis?descriptors={desc[:44]}", st, d)

print("\n=== similar sounds, in detail ===")
st, d = get(f"/sounds/{SID}/similar/", page_size=6, fields="id,name,tags")
if st == 200 and isinstance(d, dict):
    print(f"  count={d.get('count')}")
    for r in (d.get("results") or [])[:6]:
        print("   ", r.get("id"), "|", str(r.get("name"))[:48])
else:
    print("  ->", str(d)[:220])

print("\n=== search-level extras ===")
for label, params in [
    ("descriptors on search", dict(query="piano", page_size=2, fields="id,name",
                                   descriptors="lowlevel.spectral_centroid.mean")),
    ("descriptors + normalized", dict(query="piano", page_size=2, fields="id,name",
                                      descriptors="tonal.key_key,tonal.key_scale", normalized=1)),
    ("group_by_pack", dict(query="piano", page_size=2, fields="id,name,pack", group_by_pack=1)),
    ("filter samplerate", dict(query="kick", page_size=2, fields="id,name,samplerate",
                               filter="samplerate:44100")),
    ("filter channels/bitdepth", dict(query="kick", page_size=2, fields="id,name,channels,bitdepth",
                                      filter="channels:2 bitdepth:24")),
    ("filter is_geotagged", dict(query="rain", page_size=2, fields="id,name,geotag",
                                 filter="is_geotagged:true")),
    ("filter pack presence", dict(query="drum", page_size=2, fields="id,name,pack",
                                  filter="pack:*")),
    ("sort by rating", dict(query="snare", page_size=2, fields="id,name,avg_rating,num_ratings",
                            sort="rating_desc")),
]:
    st, d = get("/search/text/", **params)
    if st == 200 and isinstance(d, dict):
        print(f"  [200] {label}: count={d.get('count')}  sample={json.dumps((d.get('results') or [{}])[0], default=str)[:220]}")
    else:
        print(f"  [{st}] {label}: {str(d)[:150]}")

print("\n=== content search (acoustic query) ===")
st, d = get("/search/content/", target="lowlevel.pitch.mean:220", page_size=3, fields="id,name")
show("/search/content/", st, d, keys=["count"])

print("\n=== packs ===")
st, d = get("/search/text/", query="drum kit", page_size=6, fields="id,name,pack", group_by_pack=1)
if st == 200:
    packs = [r.get("pack") for r in d.get("results", []) if r.get("pack")]
    print("  pack urls seen:", packs[:3])
    if packs:
        pid = packs[0].rstrip("/").rsplit("/", 1)[-1]
        show(f"/packs/{pid}/", *get(f"/packs/{pid}/"))
        show(f"/packs/{pid}/sounds/", *get(f"/packs/{pid}/sounds/", page_size=3), keys=["count"])
