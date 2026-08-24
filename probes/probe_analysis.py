"""What exactly does /sounds/{id}/analysis/ return, and can it be had in bulk?"""
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
        return e.code, e.read().decode("utf-8", "replace")[:160]
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:160]


# A tonal sample, so the pitch/key fields have something to say.
st, d = get("/search/text/", filter='tag:piano duration:[1 TO 16]', page_size=1,
            sort="downloads_desc", fields="id,name")
SID = d["results"][0]["id"]
print(f"analysing sound {SID}: {d['results'][0]['name']}\n")

st, a = get(f"/sounds/{SID}/analysis/")
print(f"[{st}] total descriptors: {len(a) if isinstance(a, dict) else '-'}\n")
if isinstance(a, dict):
    print("=== every key, with its value shape ===")
    for k in sorted(a):
        v = a[k]
        if isinstance(v, list):
            desc = f"list[{len(v)}]  e.g. {str(v[:3])[:60]}"
        elif isinstance(v, dict):
            desc = f"dict keys={sorted(v)[:8]}"
        else:
            desc = repr(v)[:80]
        print(f"  {k:<34} {desc}")

print("\n=== the fields a producer would actually use ===")
WANT = ["bpm", "bpm_confidence", "beat_count", "loop", "single_event",
        "tonality", "tonality_confidence", "key", "note_name", "note_midi",
        "note_frequency", "note_confidence", "brightness", "hardness", "depth",
        "boominess", "warmth", "roughness", "sharpness", "reverb", "dissonance",
        "dynamic_range", "loudness", "amplitude_peak_ratio", "decay_strength",
        "duration_effective", "category", "has_audio_problems", "is_loopable"]
if isinstance(a, dict):
    for k in WANT:
        if k in a:
            v = a[k]
            print(f"  {k:<24} = {str(v)[:70]}")
    print("\n  absent:", [k for k in WANT if k not in a])

print("\n=== can analysis come back with the search, in bulk? ===")
for label, params in [
    ("fields=analysis", dict(query="piano", page_size=2, fields="id,name,analysis")),
    ("fields=ac_analysis", dict(query="piano", page_size=2, fields="id,name,ac_analysis")),
    ("descriptors=brightness", dict(query="piano", page_size=2, fields="id,name",
                                    descriptors="brightness,bpm,tonality")),
    ("descriptors_filter", dict(query="piano", page_size=2, fields="id,name,analysis",
                                descriptors_filter="brightness:[50 TO 100]")),
]:
    st, r = get("/search/text/", **params)
    if st == 200 and isinstance(r, dict):
        first = (r.get("results") or [{}])[0]
        print(f"  [200] {label}: count={r.get('count')} keys_on_result={sorted(first.keys())}")
        for probe in ("analysis", "ac_analysis"):
            if probe in first and first[probe]:
                print(f"        {probe} ->", json.dumps(first[probe], default=str)[:260])
    else:
        print(f"  [{st}] {label}: {str(r)[:130]}")

print("\n=== similarity: what does it cost and what does it give ===")
st, s = get(f"/sounds/{SID}/similar/", page_size=8, fields="id,name,tags,duration")
if st == 200 and isinstance(s, dict):
    print(f"  [200] count={s.get('count')} (this is the whole corpus ranked, not a shortlist)")
    for r in (s.get("results") or [])[:8]:
        print(f"    {r.get('id'):>8}  {str(r.get('name'))[:44]:<44} {r.get('duration', 0):.1f}s")
else:
    print(f"  [{st}] {str(s)[:150]}")

print("\n=== rate limit headers ===")
req = urllib.request.Request(f"{BASE}/sounds/{SID}/?token={TOKEN}")
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        for h, v in r.headers.items():
            if "rate" in h.lower() or "limit" in h.lower() or "throttle" in h.lower():
                print(f"  {h}: {v}")
        else:
            print("  (no explicit rate-limit headers returned)")
except Exception as e:  # noqa: BLE001
    print("  ", e)
