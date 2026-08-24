"""A Freesound sample-library graph for music producers, built on the analyser.

What changed from v1, and why it matters:

  v1 guessed. Tempo was parsed out of filenames (11% coverage) and musical key
  barely existed (2 samples in 1386), because an earlier probe concluded the
  analysis data could not be fetched in bulk. That conclusion was wrong: it used
  `fields=analysis`, which is not a field name. The descriptors come back under
  their own bare names, 150 rows at a time, at no extra request cost:

      fields=id,name,tonality,bpm,loopable,single_event,brightness,...

  The same names work as Solr filters (`loopable:true`, `bpm:[120 TO 130]`), and
  `similar_to` + `similarity_space` are search parameters, so acoustic
  similarity can be combined with a licence filter in one query.

So this build asks the analyser instead of the filename:

  * key      - `tonality` + `tonality_confidence`
  * tempo    - `bpm` + `bpm_confidence`
  * form     - `loopable` / `single_event`, instead of a duration heuristic
  * family   - `subcategory`, Freesound's own classifier taxonomy, which is what
               correctly calls "Kicking/Forcing/Breaking Wooden Door" an
               *Object* rather than percussion
  * timbre   - brightness, warmth, depth, hardness, boominess, roughness,
               sharpness, reverbness: the words producers actually use
  * acoustic - `similar_to` edges from seed sounds, so adjacency is sonic rather
               than merely lexical

CONFIDENCE IS LOAD-BEARING. `tonality` and `bpm` are emitted for *everything* -
the analyser gave a car crash "F minor" at 0.78 and a scream "A# minor". So a
value is only promoted to a graph node when its confidence clears a threshold;
below that it is shown in the tooltip, greyed, and joins nothing. The thresholds
are empirical, and the tooltip always shows the confidence so you can judge.

Licences are limited to CC0 and Attribution. NonCommercial is excluded: a sample
you cannot ship on a track you sell is not a sample.

THE CORPUS IS WINNOWED BEFORE IT IS DRAWN. The searches were bounded by tag and
duration, but the similarity expansion inherited neither: it followed whatever
its seeds pointed at, and the seeds included whooshes, screams and vinyl noise.
So `reject()` is the one gate every sample passes through - the cached corpus at
build time *and* every neighbour similarity hands back, which is the point, since
a request spent dragging in more speech is a request wasted. It is deliberately
short and first-match, so the printed breakdown attributes each drop to exactly
one rule:

  * category "Speech"          - solo speech, conversation, and the processed /
                                 synthetic speech that sits with them. The
                                 clearest cut there is.
  * the older NON_MUSICAL list - vehicles, animals, weather, room tone.
  * duration                   - the real gap. 30s is the widest bound any of
                                 the original searches used (pad, acapella,
                                 vinyl); past it a "sample" is a field recording,
                                 and the cache held one of 92 minutes.

Foley (Objects / House appliances), Experimental and Human sounds and actions are
deliberately KEPT. Producers mine all three - ice buckets, whips and metal impacts
are percussion, the Experimental bucket is mostly turntable scratches and
glitches, and the human bucket is where claps, breaths and vocal chops live.

`has_audio_problems` is fetched but NOT filtered on, and that is a measurement
rather than an oversight. A probe of the 150 most-downloaded sounds here came
back 87 true - "Deep Bass Kick", "Kick 23 - Minimal" and the rest of the flagship
drums among them - against 34% across the corpus at large. It fires on anything
hot, which is what a drum sample is, so as a quality gate it correlates with
*wanting* the sample. The rate is printed each build so the call can be
re-checked rather than taken on trust.

Coverage, second: `similar_to` costs one request per seed, so seeding is aimed
rather than round-robin. It asks only samples that survived the filter and still
have no similarity edge, richest-first, skipping any that an earlier seed's
neighbours already reached - which is most of them, and is where the requests are
saved. SIM_BUDGET is the hard ceiling and the count spent is printed.

Rate limits are 60 req/min and 2000/day, so requests are paced ~1.1s apart.
The API token is read from a file outside the repo and never written into the
output, so the HTML is safe to share.

The cache holds the *raw* fetch, unwinnowed, so changing `reject()` re-shapes the
graph with no requests at all. It also records which ids have been seeded; once
that record exists the coverage pass is done and a plain build spends nothing.
Pass --reseed to top it up again, --refetch to pull everything from scratch.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np
import networkx as nx
from networkx.algorithms.community import louvain_communities

SCRATCH = Path(__file__).parent
_POS = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = Path(_POS[0]) if _POS else SCRATCH / "producer-graph.html"
# Read only if something is going to be fetched. A local build makes no requests,
# and should not need a credential to prove it.
_KEYFILE = SCRATCH / "freesound.key"
TOKEN = _KEYFILE.read_text(encoding="ascii").strip() if _KEYFILE.exists() else ""
BASE = "https://freesound.org/apiv2"
LIC = '("Creative Commons 0" OR "Attribution")'
PAGE = 150          # the documented maximum
PACE = 1.1          # 60 req/min ceiling, with headroom

# Everything the analyser knows that a producer would use. Requesting these costs
# nothing extra - they ride along on the same search.
FIELDS = ",".join([
    "id", "name", "username", "tags", "duration", "license", "num_downloads",
    "avg_rating", "type", "previews", "pack", "pack_name", "is_remix", "was_remixed",
    "tonality", "tonality_confidence", "bpm", "bpm_confidence",
    "note_name", "note_midi", "note_confidence",
    "loopable", "single_event", "category", "subcategory", "has_audio_problems",
    "brightness", "warmth", "depth", "hardness", "boominess",
    "roughness", "sharpness", "reverbness", "dynamic_range", "loudness",
])

SPECS = [
    ("kick",       "drums",   "duration:[0.05 TO 2]"),
    ("snare",      "drums",   "duration:[0.05 TO 2]"),
    ("hi-hat",     "drums",   "duration:[0.05 TO 2]"),
    ("clap",       "drums",   "duration:[0.05 TO 2]"),
    ("breakbeat",  "drums",   "duration:[1 TO 12]"),
    ("percussion", "drums",   "duration:[0.05 TO 6]"),
    ("808",        "bass",    "duration:[0.1 TO 4]"),
    ("bassline",   "bass",    "duration:[1 TO 16]"),
    ("sub-bass",   "bass",    "duration:[0.2 TO 8]"),
    ("lead",       "melodic", "duration:[1 TO 16]"),
    ("pad",        "melodic", "duration:[2 TO 30]"),
    ("arpeggio",   "melodic", "duration:[1 TO 16]"),
    ("piano",      "melodic", "duration:[1 TO 16]"),
    ("guitar",     "melodic", "duration:[1 TO 16]"),
    ("vocal",      "vocal",   "duration:[0.2 TO 8]"),
    ("acapella",   "vocal",   "duration:[1 TO 30]"),
    ("riser",      "fx",      "duration:[0.5 TO 10]"),
    ("impact",     "fx",      "duration:[0.1 TO 4]"),
    ("whoosh",     "fx",      "duration:[0.2 TO 5]"),
    ("vinyl",      "texture", "duration:[1 TO 30]"),
    ("drone",      "texture", "duration:[2 TO 40]"),
]

# Empirical. A car crash scored 0.78 tonality confidence, so 0.75 is not enough;
# the genuinely tonal material in the probe sat at 0.80-0.87.
KEY_CONF = 0.80
BPM_CONF = 0.95
NOTE_CONF = 0.80

SIM_TAKE = 12       # neighbours per seed
# No ceiling, deliberately. The cap was starving the very pass it sat next to:
# a seed only gains an edge by importing its neighbours, so with the corpus full
# 500 seeds spent a request each and gained nothing. The corpus now grows to
# whatever full coverage costs.
CORPUS_CAP = None
                    # edges but no new samples
# A backstop against a runaway loop, not the plan: the run is meant to end by
# emptying the queue or by the API refusing. If this number is ever the reason
# a run stopped, the printed summary says so.
SIM_BUDGET = 20000
                    # allowance is 2000 and the search pass and earlier runs eat
                    # into it, so this is what is left, not what is permitted.


# --- what a producer cannot use -----------------------------------------------
# The one gate. `reject` returns the rule that turned a sample away, or None if
# it stays; every drop is counted under exactly one rule so the build can print
# an audit rather than a total. See the module docstring for the reasoning - the
# short version is that Freesound's own classifier is the best signal available,
# duration is the gap the similarity pass opened, and Foley stays.

DROP_CATEGORIES = {"Speech"}

DROP_SUBCATEGORIES = {
    # the original list: recordings of the world, not instruments
    "Vehicles", "Animals", "Nature", "Urban", "Indoors",
    "Conversation / Crowd", "Other mechanisms, engines, machines",
    "Natural elements and explosions",
    # "Human sounds and actions" was here, for the screams and the crying, and is
    # not any more: the same subcategory holds claps, breaths and vocal chops, and
    # 503 samples was too much of the corpus to spend on losing a few hundred
    # screams. Speech is still dropped, which is where the worst of it sits.
}

DUR_MAX = 30.0      # the widest bound any original search used (pad/acapella/vinyl)
DUR_MIN = 0.1       # below this there is no sound, only a click


def reject(s):
    """The rule that disqualifies a sample as production material, else None."""
    cat = (s.get("category") or "").strip()
    sub = (s.get("subcategory") or "").strip()
    if cat in DROP_CATEGORIES:
        return f"speech ({cat} / {sub or 'unclassified'})"
    if sub in DROP_SUBCATEGORIES:
        return f"non-musical ({sub})"
    dur = float(s.get("duration") or 0)
    if dur > DUR_MAX:
        return f"longer than {DUR_MAX:g}s"
    if dur < DUR_MIN:
        return f"shorter than {DUR_MIN:g}s"
    return None


def winnow(pool):
    """Split a sample dict into what survives `reject` and a per-rule tally."""
    kept, why = {}, Counter()
    for sid, s in pool.items():
        rule = reject(s)
        if rule:
            why[rule] += 1
        else:
            kept[sid] = s
    return kept, why


def audit(why, total, header):
    print(header)
    dropped = sum(why.values())
    for rule, n in sorted(why.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {n:>5}  {rule}")
    print(f"    {dropped:>5}  = dropped, of {total} ({100 * dropped / max(total, 1):.1f}%)")
    return dropped


STOPTAGS = {"field-recording", "sound", "audio", "recording", "sample", "samples",
            "wav", "mp3", "aiff", "free", "loop", "loops", "noise", "effect", "fx"}
# A tag has to be on enough samples to be worth an edge, and "enough" is a share
# of the corpus rather than a count: 14 was tuned against 7,023 samples, and the
# same 14 against a 250-file folder keeps nothing at all - the local build came
# out with zero tag nodes and named its communities off the families instead.
# 0.2% reproduces the tuned value exactly at the size it was tuned at
# (7,023 x 0.002 = 14.0) and degrades sensibly either side of it. The floor of 3
# is where a "shared" tag stops meaning anything.
TAG_MIN_SHARE = 0.002
TAG_MIN_FLOOR = 3

# A tag on more than this share of the corpus is structure-free: `drum` was on
# 1,011 samples of 6,523, so it joined a sixth of the graph to itself and told
# you nothing. Dropped from the graph entirely - still searchable, still in the
# tooltip, just not an edge.
TAG_MAX_SHARE = 0.06

# Keep only a sample's rarest tags. Its common ones are what it shares with
# everything; its rare ones are what make it that sample. Eight edges each was
# a mat, three is a filament.
TAGS_PER_SAMPLE = 3

# Layout weights. A tag hub joins hundreds of samples; left at parity with the
# similarity edges it would decide the whole picture, so it is damped to a
# twentieth. The layout then reads as 'what sounds like what', with the shared
# tags only tugging.
STRUCT_W = 0.005
SIM_W = 2.2

# spring_layout IS the force simulation - Fruchterman-Reingold, run as a batch
# rather than interactively. k is the ideal edge length (the repulsion/spring
# balance), iterations is how long it relaxes, and DECROWD afterwards pushes the
# dense middle outwards (1.0 = leave it alone, lower = more spread).
# A hand-written sim briefly replaced this and measured worse: 0.0088 median
# nearest-neighbour against 0.0115 here, for ~60 lines more code.


LAYOUT_K = 26.0
LAYOUT_ITERS = 300
# Small on purpose. This exists to stop the force layout leaving a sparse
# middle, not to make the density uniform - uniform is a blob. At 0.88 it was
# erasing the clusters the layout had just found.
DECROWD = 0.0   # FA2 linlog separates on its own; blending toward a uniform disc undoes it



class RateLimited(Exception):
    """The daily quota is spent. Distinct from a transient 429 so the seeding
    loop can stop cleanly and still write its cache, instead of spinning through
    the rest of the queue printing failures."""


def get(path, **params):
    params["token"] = TOKEN
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:            # throttled - back off and retry
                if attempt == 3:
                    raise RateLimited(e.read().decode("utf-8", "replace")[:140]) from e
                time.sleep(8 * (attempt + 1))
                continue
            raise
        except Exception:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(2)
    return None


CACHE = SCRATCH / "freesound-raw.json"
samples = {}
sim_edges = []
seeded = set()          # ids already asked for neighbours; a request each, never repeated
sim_cached = False      # True once the coverage pass's result is on disk
reqs = 0

if CACHE.exists() and "--refetch" not in sys.argv:
    raw = json.loads(CACHE.read_text(encoding="utf-8"))
    samples = {int(k): v for k, v in raw["samples"].items()}
    sim_edges = [tuple(e) for e in raw["sim_edges"]]
    seeded = {int(i) for i in raw.get("seeded", [])}
    # A cache written before the coverage pass existed has no "seeded" record, so
    # the pass has not run against it and is allowed to. Once the record is there
    # the pass is done and a plain build spends nothing.
    sim_cached = "seeded" in raw and "--reseed" not in sys.argv
    print(f"=== cached fetch: {len(samples)} samples, {len(sim_edges)} similarity edges,"
          f" {len(seeded)} seeded ===")
    print("    (pass --refetch to pull again, --reseed to top up similarity)")

print("=== search pass ===")
for tag, family, dur in (SPECS if not samples else []):
    flt = f"tag:{tag} {dur} license:{LIC}"
    try:
        d = get("/search/text/", filter=flt, page_size=PAGE, sort="downloads_desc", fields=FIELDS)
    except Exception as exc:  # noqa: BLE001
        print(f"  tag:{tag:<11} FAILED {exc}")
        continue
    reqs += 1
    got = d.get("results") or []
    fresh = 0
    for s in got:
        if s["id"] not in samples:
            fresh += 1
        s.setdefault("_family", family)
        samples.setdefault(s["id"], s)
    print(f"  tag:{tag:<11} [{family:<7}] {len(got):>3} returned, {fresh:>3} new   (of {d.get('count',0):>7,})")
    time.sleep(PACE)

print(f"\n{len(samples)} unique samples from {reqs} requests")

# --- the producer filter ------------------------------------------------------
# Applied before anything is seeded, because a smaller corpus is a smaller
# seeding bill: every sample turned away here is a request not spent on it.
print("\n=== producer filter ===")
corpus, why = winnow(samples)
audit(why, len(samples), "  dropped as not usable in a track:")
print(f"  {len(corpus)} samples usable")


def audio_problem_rate(pool):
    """Printed, never filtered on - see the docstring. The rate is reported so
    the decision stays checkable instead of being a claim in a comment."""
    seen = [s for s in pool.values() if "has_audio_problems" in s]
    if not seen:
        return
    bad = sum(1 for s in seen if s.get("has_audio_problems"))
    print(f"  has_audio_problems true on {bad} of {len(seen)} measured"
          f" ({100 * bad / len(seen):.0f}%) - NOT filtered on: it fires on anything"
          f" hot, which is what a drum sample is")


def linked_in(pool, edges):
    """Sample ids joined to another *surviving* sample by a similarity edge."""
    out = set()
    for a, b in edges:
        if a in pool and b in pool:
            out.add(a)
            out.add(b)
    return out


# --- acoustic neighbours ------------------------------------------------------
# similar_to is a search parameter, so the licence filter applies to the
# neighbours too - every edge lands on something clearable. The producer filter
# is applied to them here in Python, which the API cannot do for us.
#
# Seeding is aimed, not round-robin. The old selection took the 500 most
# downloaded per family and never asked which samples already had an edge, so it
# re-seeded covered material while two thousand neighbours sat isolated. This one
# asks exactly the samples that survive the filter and have no edge yet, richest
# first, and re-checks before every request: a seed's twelve neighbours routinely
# reach other uncovered samples, and each one of those is a request saved.
print("\n=== similarity pass ===")
linked = linked_in(corpus, sim_edges)
cov_before = 100 * len(linked) / max(len(corpus), 1)
print(f"  coverage before: {len(linked)} of {len(corpus)} carry a similarity edge ({cov_before:.1f}%)")

sim_reqs = 0
hit_limit = False
sim_why = Counter()
freebies = 0
if sim_cached:
    print("  cached - no requests (pass --reseed to top up)")
else:
    todo = sorted((s for sid, s in corpus.items() if sid not in linked),
                  key=lambda s: -(s.get("num_downloads") or 0))
    _again = sum(1 for s in todo if s["id"] in seeded)
    print(f"  {len(todo)} uncovered; {_again} of them were seeded before, against the old cap")
    print("  running until the queue empties or the API refuses")
    for s in todo:
        if sim_reqs >= SIM_BUDGET:
            break
        sid = s["id"]
        if sid in linked:           # an earlier seed's neighbours got here first
            freebies += 1
            continue
        try:
            d = get("/search/text/", similar_to=sid, similarity_space="laion_clap",
                    filter=f"license:{LIC}", page_size=SIM_TAKE, fields=FIELDS)
        except RateLimited as exc:
            print(f"  API limit reached after {sim_reqs} requests -- {exc}")
            hit_limit = True
            break
        except Exception as exc:  # noqa: BLE001
            print(f"  seed {sid}: FAILED {exc}")
            continue
        reqs += 1
        sim_reqs += 1
        seeded.add(sid)
        for r in (d.get("results") or []):
            rid = r.get("id")
            if rid is None or rid == sid:
                continue
            if rid not in samples:
                rule = reject(r)                 # do not pay to import more speech
                if rule:
                    sim_why[rule] += 1
                    continue
                r.setdefault("_family", s.get("_family", ""))
                samples[rid] = r
                corpus[rid] = r
            elif rid not in corpus:
                continue                         # known, and already turned away
            sim_edges.append((sid, rid))
            linked.add(sid)
            linked.add(rid)
        if sim_reqs % 100 == 0:
            print(f"  {sim_reqs:>5} requests -> {len(linked)} of {len(corpus)} covered"
                  f" ({100 * len(linked) / max(len(corpus), 1):.1f}%), {freebies} seeds skipped as already reached")
        time.sleep(PACE)

    _why_stopped = ("STOPPED BY THE API LIMIT" if hit_limit
                    else "hit the SIM_BUDGET backstop" if sim_reqs >= SIM_BUDGET
                    else "queue emptied")
    print(f"  spent {sim_reqs} requests - {_why_stopped}; {freebies} seeds skipped"
          f" because a neighbour had already reached them")
    if sim_why:
        audit(sim_why, sum(sim_why.values()), "  neighbours refused by the producer filter:")

corpus, why = winnow(samples)   # new arrivals included; identical on a cached run
audio_problem_rate(corpus)
linked = linked_in(corpus, sim_edges)
cov_after = 100 * len(linked) / max(len(corpus), 1)
print(f"  coverage after:  {len(linked)} of {len(corpus)} carry a similarity edge ({cov_after:.1f}%)")

print(f"\n{len(samples)} samples fetched, {len(corpus)} usable, {len(sim_edges)} similarity edges,"
      f" {reqs} requests this run")
if reqs or not sim_cached:
    CACHE.write_text(json.dumps({"samples": {str(k): v for k, v in samples.items()},
                                 "sim_edges": [list(e) for e in sim_edges],
                                 "seeded": sorted(seeded)}), encoding="utf-8")
    print(f"cached raw fetch to {CACHE.name}")


def num(v):
    return v if isinstance(v, (int, float)) else None


# --- graph --------------------------------------------------------------------
tag_counts = Counter()
for s in corpus.values():
    for t in s.get("tags") or []:
        t = t.strip().lower()
        if t and t not in STOPTAGS:
            tag_counts[t] += 1
TAG_MIN = max(TAG_MIN_FLOOR, round(len(corpus) * TAG_MIN_SHARE))
_hub_cut = max(TAG_MIN + 1, int(len(corpus) * TAG_MAX_SHARE))
keep_tags = {t for t, c in tag_counts.items() if TAG_MIN <= c < _hub_cut}
_hubs = sorted(((c, t) for t, c in tag_counts.items() if c >= _hub_cut), reverse=True)
print(f"  {len(_hubs)} hub tags dropped (on >={_hub_cut} samples): "
      f"{', '.join(t for _, t in _hubs[:6])}")

G = nx.Graph()
meta = {}
stats = Counter()


def add(nid, label, kind, **extra):
    if nid not in G:
        G.add_node(nid)
        meta[nid] = {"l": label, "k": kind, **extra}


for s in corpus.values():       # already winnowed; `reject` is the only gate
    sid = f"s{s['id']}"
    dur = round(float(s.get("duration") or 0), 2)
    ton, tonc = s.get("tonality"), num(s.get("tonality_confidence")) or 0
    bpm, bpmc = num(s.get("bpm")), num(s.get("bpm_confidence")) or 0
    note, notec = s.get("note_name"), num(s.get("note_confidence")) or 0
    key_ok = bool(ton) and tonc >= KEY_CONF
    bpm_ok = bool(bpm) and bpmc >= BPM_CONF and 40 <= bpm <= 220
    note_ok = bool(note) and notec >= NOTE_CONF
    stats["key_trusted"] += key_ok
    stats["key_present"] += bool(ton)
    stats["bpm_trusted"] += bpm_ok
    stats["bpm_present"] += bool(bpm)
    stats["note_trusted"] += note_ok
    stats["loopable"] += bool(s.get("loopable"))
    stats["single_event"] += bool(s.get("single_event"))

    sub = (s.get("subcategory") or s.get("category") or "").strip()
    # The *whole* tag set, not the three that became nodes. Only a handful of a
    # sample's tags clear TAG_MIN and survive TAGS_PER_SAMPLE, and the ones that
    # do not are still what a producer types into the search box. Sorted here so
    # the payload does not inherit set iteration order.
    _tags = sorted({t.strip().lower() for t in (s.get("tags") or []) if t.strip()})
    add(sid, s.get("name") or sid, "sample",
        user=s.get("username") or "",
        dur=dur,
        lic="CC0" if "publicdomain/zero" in (s.get("license") or "") else "BY",
        dl=int(s.get("num_downloads") or 0),
        rate=round(float(s.get("avg_rating") or 0), 1),
        fam=s.get("_family", ""),
        fmt=(s.get("type") or "").lower(),
        pack=(s.get("pack") or "").rstrip("/").rsplit("/", 1)[-1],
        packname=(s.get("pack_name") or "").strip(),
        remix=bool(s.get("is_remix")), remixed=bool(s.get("was_remixed")),
        prev=(s.get("previews") or {}).get("preview-hq-mp3")
             or (s.get("previews") or {}).get("preview-lq-mp3") or "",
        key=ton or "", keyc=round(tonc, 2), keyok=key_ok,
        bpm=int(bpm) if bpm else 0, bpmc=round(bpmc, 2), bpmok=bpm_ok,
        note=note or "", noteok=note_ok,
        loop=bool(s.get("loopable")), one=bool(s.get("single_event")),
        sub=sub,
        bright=num(s.get("brightness")), warm=num(s.get("warmth")),
        deep=num(s.get("depth")), hard=num(s.get("hardness")),
        boom=num(s.get("boominess")), rough=num(s.get("roughness")),
        sharp=num(s.get("sharpness")), rev=bool(s.get("reverbness")),
        loud=num(s.get("loudness")), dyn=num(s.get("dynamic_range")),
        tags=_tags)

    if sub:
        add(f"c:{sub}", sub, "family")
        G.add_edge(sid, f"c:{sub}", weight=STRUCT_W)
    # Rarest first: a sample's unusual tags are the ones that place it.
    _mine = sorted(set(_tags) & keep_tags,
                   key=lambda t: (tag_counts[t], t))[:TAGS_PER_SAMPLE]
    for t in _mine:
        add(f"t:{t}", t, "tag")
        G.add_edge(sid, f"t:{t}", weight=STRUCT_W)
    # Key and tempo are no longer nodes. They stayed accurate but they were hubs:
    # 24 keys and 19 tempo bands absorbing thousands of edges, which crowded the
    # canvas without telling anyone anything they could not get from the filters.
    # Both are still on the sample, in the tooltip, in search and in the
    # keyed/tempo filters.
    # Uploaders are deliberately NOT nodes. There are ~1200 of them with one
    # edge each, and as high-degree hubs they dominated Louvain: a community
    # of 377 nodes was being named "Vehicles" off the back of 14 vehicle
    # samples. The uploader stays on the sample, and stays in the tooltip.

for a, b in sim_edges:
    na, nb = f"s{a}", f"s{b}"
    if na in G and nb in G:
        G.add_edge(na, nb, sim=1, weight=SIM_W)

G.remove_nodes_from([n for n in list(G.nodes) if G.degree(n) == 0])

print(f"\n=== how much of it is trustworthy ===")
print(f"  key      present on {stats['key_present']:>4}, trusted (conf>={KEY_CONF}) on {stats['key_trusted']:>4}"
      f"  ({100*stats['key_trusted']/max(len(corpus),1):.0f}%)")
print(f"  bpm      present on {stats['bpm_present']:>4}, trusted (conf>={BPM_CONF}) on {stats['bpm_trusted']:>4}"
      f"  ({100*stats['bpm_trusted']/max(len(corpus),1):.0f}%)")
print(f"  note     trusted on {stats['note_trusted']:>4}")
print(f"  loopable {stats['loopable']:>4}   single_event {stats['single_event']:>4}")
print(f"  {len(keep_tags)} tags kept ({TAG_MIN}+ uses, of {len(tag_counts)})")
print(f"  {sum(why.values())} samples dropped by the producer filter, {len(corpus)} kept")

# weight=None on purpose: STRUCT_W/SIM_W exist to shape the *layout*. Feeding
# them to Louvain damped the shared-tag edges that actually define a community
# and split 11 clusters into 78, so the legend filled with noise like
# "wobble (115)". Community detection sees the graph unweighted.
comms = louvain_communities(G, seed=7, resolution=1.15, weight=None)
comm_of = {n: i for i, c in enumerate(comms) for n in c}
def _ranked(counts):
    """Candidate names, best first. Ties break alphabetically: Counter.most_common
    breaks them by insertion order, which follows set iteration order, which
    follows the per-process string hash seed - so the same cached graph came back
    named "Multiple instruments" one build and "Solo instrument" the next."""
    return [k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if k]


# Size, then the lowest node id: two communities of equal size would otherwise
# swap ranks between builds for the same reason the names flipped.
order = sorted(range(len(comms)), key=lambda i: (-len(comms[i]), min(comms[i])))

# Candidates are counted over the community's *samples*, not its family hubs. Each
# hub is a single node, so counting hubs was counting 1s and picking among ties: a
# community holding one String hub and 900 percussion samples could be called
# "String". What the members are is the thing worth naming it after.
cands = {}
for i, c in enumerate(comms):
    subs = Counter(meta[n]["sub"] for n in c
                   if meta[n]["k"] == "sample" and meta[n].get("sub"))
    tags = {meta[n]["l"]: tag_counts[meta[n]["l"]] for n in c if meta[n]["k"] == "tag"}
    fams = Counter(meta[n].get("fam", "") for n in c if meta[n]["k"] == "sample")
    cands[i] = _ranked(subs) + _ranked(tags) + _ranked(fams)

# Names must be distinct or the legend lies: two rows reading "Percussion" cannot
# be told apart, and the colour swatch is the only thing separating them. Assigned
# largest community first, so the biggest gets its best name and a smaller one
# falls through to its next most common subcategory, then its top tag.
names = {}
used = set()
for i in order:
    for cand in cands[i]:
        if cand not in used:
            names[i] = cand
            used.add(cand)
            break
    else:
        # Everything this community could be called is taken. Qualify rather than
        # collide - a numbered name is ugly but honest.
        base = cands[i][0] if cands[i] else "misc"
        k = 2
        while f"{base} {k}" in used:
            k += 1
        names[i] = f"{base} {k}"
        used.add(names[i])
rank = {c: r for r, c in enumerate(order)}

# Fruchterman-Reingold, and only that.
#
# ForceAtlas2 and igraph DRL were both built in and measured against it, then
# removed with the engine switch. Recorded so neither gets retried blind: DRL
# separates clusters by knotting each one tight (nearest-neighbour 0.0016 against
# 0.0081 here), which reads as solid lumps at whole-graph zoom. FA2's advantage
# was real but narrower than it first looked - an early comparison flattered it
# by measuring each engine at a different zoom.
_t0 = time.time()
pos = nx.spring_layout(G, k=LAYOUT_K / (G.number_of_nodes() ** 0.5),
                       iterations=LAYOUT_ITERS, seed=7, weight="weight")
print(f"  layout: Fruchterman-Reingold k={LAYOUT_K}, {LAYOUT_ITERS} iters "
      f"({time.time() - _t0:.0f}s)")

# De-crowding, by rank rather than by a power of the radius.
#
# The previous version did r' = r**0.62 from the centroid, and that punches a
# hole: the expansion factor is r**p / r, which diverges as r -> 0, so the points
# nearest the middle are thrown outward hardest. Measured on the last build,
# 0.0% of nodes were left inside the inner tenth and only 18% sat in the outer
# band where half of them belong - everything piled into a ring.
#
# Instead each point is moved to the radius its *rank* deserves. Sorting by r and
# mapping the i-th point to sqrt((i+0.5)/n) gives uniform density over the disc,
# starts at ~0 so there is no hole, and is monotone in r so nothing crosses
# anything else. DECROWD blends between the raw layout (0.0) and that uniform
# disc (1.0); part-way keeps real clusters denser than empty space, which is
# information worth keeping.
_ids = list(pos)
_P = np.array([pos[n] for n in _ids], dtype=float)
_P -= _P.mean(axis=0)
_r = np.linalg.norm(_P, axis=1)
_rmax = _r.max() or 1.0
_order = np.argsort(_r)
_rank = np.empty_like(_order, dtype=float)
_rank[_order] = np.arange(len(_r))
_target = _rmax * np.sqrt((_rank + 0.5) / len(_r))
_want = _r * (1.0 - DECROWD) + _target * DECROWD
_scale = np.divide(_want, _r, out=np.ones_like(_r), where=_r > 1e-9)
_P *= _scale[:, None]
pos = {n: _P[j] for j, n in enumerate(_ids)}

xs = [p[0] for p in pos.values()]
ys = [p[1] for p in pos.values()]
minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
spanx, spany = (maxx - minx) or 1, (maxy - miny) or 1

# Which samples are actually joined to another sample, measured on the built
# graph rather than on the edge list - a node with no other edge at all is
# already gone by here. The viewer can hide whatever is left isolated.
linked = set()
for a, b in G.edges:
    if G.edges[a, b].get("sim") == 1:
        linked.add(a)
        linked.add(b)
n_sample_nodes = sum(1 for n in G if meta[n]["k"] == "sample")
print(f"  {len(linked)} samples carry a similarity edge, {n_sample_nodes - len(linked)} do not"
      f"  ({100 * len(linked) / max(n_sample_nodes, 1):.1f}% similarity coverage)")

ids = list(G.nodes)
idx = {n: i for i, n in enumerate(ids)}

# One shared vocabulary, indices on the samples. Inlining the strings instead
# costs ~6 tags x 8 chars x 6.5k samples on a payload already over 3MB, and every
# tag worth searching for is on more than one sample anyway. Built off the nodes
# that survived the degree-0 sweep, so a tag only in the payload is a tag some
# visible sample actually carries.
tagv = sorted({t for n in ids if meta[n]["k"] == "sample" for t in meta[n]["tags"]})
tag_ix = {t: i for i, t in enumerate(tagv)}
_tagged = sum(len(meta[n]["tags"]) for n in ids if meta[n]["k"] == "sample")
_ld = sum(1 for n in ids if meta[n]["k"] == "sample" and meta[n]["loud"] is not None)
_dr = sum(1 for n in ids if meta[n]["k"] == "sample" and meta[n]["dyn"] is not None)
print(f"  {len(tagv)} distinct tags in tagv, {_tagged / max(n_sample_nodes, 1):.1f} per sample on average"
      f" (against {TAGS_PER_SAMPLE} max as graph edges)")
print(f"  loudness on {_ld} samples, dynamic range on {_dr}, of {n_sample_nodes}")

nodes_out = []
for n in ids:
    m = meta[n]
    x, y = pos[n]
    o = {"l": m["l"], "x": round((x - minx) / spanx, 5), "y": round((y - miny) / spany, 5),
         "c": rank[comm_of[n]], "d": G.degree(n), "k": m["k"]}
    if m["k"] == "sample":
        o.update({
            "u": m["user"], "s": m["dur"], "g": m["lic"], "n": m["dl"], "r": m["rate"],
            "fam": m["fam"], "f": m["fmt"], "p": m["prev"], "i": n[1:],
            "key": m["key"], "kc": m["keyc"], "ko": 1 if m["keyok"] else 0,
            "bpm": m["bpm"], "bc": m["bpmc"], "bo": 1 if m["bpmok"] else 0,
            "note": m["note"] if m["noteok"] else "",
            "lp": 1 if m["loop"] else 0, "one": 1 if m["one"] else 0,
            "pk": m.get("packname", ""), "rx": 1 if m.get("remix") else 0,
            "ln": 1 if n in linked else 0,
            "sub": m["sub"],
            "tb": [None if v is None else round(v, 1) for v in
                   (m["bright"], m["warm"], m["deep"], m["hard"], m["boom"], m["rough"], m["sharp"])],
            # Not timbre, so not in `tb`: loudness and dynamic range are the pair
            # that says whether a hit is punchy or already squashed flat, which
            # is a filter, not a colour.
            "ld": None if m["loud"] is None else round(m["loud"], 1),
            "dr": None if m["dyn"] is None else round(m["dyn"], 1),
            "rv": 1 if m["rev"] else 0,
            "tg": sorted(tag_ix[t] for t in m["tags"]),
        })
    nodes_out.append(o)

# Median distance to the nearest other node, in the normalised 0-1 layout.
# Printed so a layout change can be judged by a number, not by squinting.
_Q = np.array([[nodes_out[j]['x'], nodes_out[j]['y']] for j in range(len(nodes_out))])
_step = max(1, len(_Q) // 900)
_S = _Q[::_step]
_d = np.sqrt(((_S[:, None, :] - _S[None, :, :]) ** 2).sum(-1))
np.fill_diagonal(_d, np.inf)
print(f"  spacing: median nearest-neighbour {np.median(_d.min(axis=1)):.4f} of the 0-1 canvas (sampled {len(_S)})")

# Each engine is normalised into the same 0-1 box so the viewer can swap between
# them without the zoom jumping. Percentile-based, not min/max: one stray node
# would otherwise squeeze the whole graph into a corner.
def _norm(pmap):
    ids = list(pmap)
    A = np.array([pmap[n] for n in ids], dtype=float)
    lo, hi = np.percentile(A, 0.5, axis=0), np.percentile(A, 99.5, axis=0)
    span = np.where(hi - lo > 0, hi - lo, 1.0)
    A = np.clip((A - lo) / span, -0.05, 1.05)
    return {n: A[j] for j, n in enumerate(ids)}


pos = _norm(pos)

edges_out = [[idx[a], idx[b], int(G.edges[a, b].get("sim", 0))] for a, b in G.edges]
counts = Counter(meta[n]["k"] for n in ids)

payload = {
    "nodes": nodes_out, "edges": edges_out, "tagv": tagv,
    "legend": [{"r": rank[i], "n": names[i], "s": len(comms[i])} for i in order[:15]],
    "counts": dict(counts),
    "cc0": sum(1 for n in ids if meta[n]["k"] == "sample" and meta[n]["lic"] == "CC0"),
    "keyed": stats["key_trusted"], "tempoed": stats["bpm_trusted"],
    "loopable": stats["loopable"], "oneshot": stats["single_event"],
    "sims": sum(1 for e in edges_out if e[2] == 1),
    "specs": len(SPECS), "reqs": reqs,
    "keyconf": KEY_CONF, "bpmconf": BPM_CONF,
}

HTML = Path(SCRATCH / "viewer_v2.html").read_text(encoding="utf-8")
OUT.write_text(HTML.replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":"))),
               encoding="utf-8")
print(f"\nwrote {OUT} ({OUT.stat().st_size:,} bytes)")
print(f"nodes={len(nodes_out)} edges={len(edges_out)} ({payload['sims']} similarity) communities={len(comms)}")
print("kinds: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
print("communities: " + ", ".join(f"{l['n']} ({l['s']})" for l in payload["legend"][:9]))
