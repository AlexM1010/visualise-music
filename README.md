# Visualise Music — web

An interactive map of Freesound samples, built for music producers. Samples are
drawn as vinyl discs; clicking one plays it, `Tab` walks to the next sound the
analyser thinks is like it, `S` keeps it, and anything you keep — or anything a
filter has left on screen — packs into a zip with its credits. **The page opens
by running ForceAtlas2**, so the graph assembles itself in front of you; the
same nodes can also be arranged four ways — including a scatter graph against
any two of sixteen measured fields.

Current build: **7,023 samples · 7,759 nodes · 31,849 edges · 19 communities**.

> The same engine over **your own folder of audio** lives in its own
> repository. It shares no code with this one any more: it has no API layer, no
> licence, no uploader and no credits, because a file on disk has none of those.
> The two were one dual-mode codebase until the split, and the guards each
> carried for the other's sake are gone from both.

## Running it

The built map is <https://alexm1010.github.io/visualise-music/>. Nothing to
install — it is the committed `index.html`, payload and all.

Locally, `index.html` is in the clone already, so there is nothing to build
first. The audio streams from `cdn.freesound.org`, so the page needs real
network access — it works from `localhost` or any ordinary browser, and stays
silent inside a sandbox that blocks remote hosts. Open it over HTTP, not
`file://`:

```bash
python -m http.server 8973 --bind 127.0.0.1
```

then <http://127.0.0.1:8973/>.

## The download button, and the coffee link

**desktop app for your library**, at the right-hand end of the header. It does
not start a download. It opens a panel, because the installer is unsigned and
Windows is about to say so in a blue box whose only button is *Don't run* — and
that is better said first, here, by the people shipping it, than met thirty
seconds later as an accusation from the operating system. The panel carries the
download, what SmartScreen will do and how to get past it, and the checksum to
check the file against.

The button is still an `<a>` with a real `href` — the releases page — so a
middle-click, a ctrl-click and a page whose script never ran all still go
somewhere sensible. Only a plain left-click is taken.

**buy me a coffee** sits beside it and is an ordinary outbound link to
<https://buymeacoffee.com/alexm1010>, opened in a new tab because the map is a
working session — a basket, a query, a running layout — and navigating away from
it loses all three. It is styled like the rest of the toolbar rather than like
the download: a tip jar that competes with the thing being offered is a tip jar
in the way.

The panel fills itself in from `download.json`, beside `index.html`:

```json
{
  "version": "0.2.0",
  "tag": "v0.2.0",
  "url": "https://github.com/AlexM1010/visualise-music/releases/download/v0.2.0/visualise-music_0.2.0_x64-setup.exe",
  "sha256": "429ea9…",
  "size": 8123456
}
```

**Nothing writes that file by hand.** The desktop repository's release workflow
publishes the installer to *this* repository — it holds the downloads as well as
the site — and in the same run commits the `download.json` naming it. So the
newest release is the one the button offers, and a version number never has to
be edited here.

The file is read from this page's own origin rather than from `github.com`,
which would cost a CORS header the page cannot require and a rate limit it
cannot see. Absent — in a clone, behind `serve_originals.py`, or at any moment
before the first release — the panel still opens and still gives the warning,
the download falls back to the releases page, and the checksum section stays
hidden rather than offering a command with nothing to compare against.

The link is only replaced if the URL in the file is a release download on this
repository. It is a file this origin serves and CI wrote, so that check is a
seatbelt rather than a boundary: the one outbound link on the page should not
become an arbitrary destination because something was garbled.

The panel is a `<dialog>`, so Esc closes it and the browser handles the focus.
One thing it does need from the page: the map's single-key shortcuts are bound
on `window` and skip keystrokes aimed at a control, which the panel's prose is
not — so the handler returns early while it is open, or reading it would work
`S` and `D` on a map nobody can see.

`viewer.html` holds all of this, so a **rebuild carries it into `index.html`** —
and a hand-edit of `index.html` alone does not survive the next build. That is
the one way this can quietly break, so `.github/workflows/site.yml` checks it on
every push: the button, its stylesheet rule, the panel, the coffee link and the
fetch all have to be in `index.html` byte for byte as `viewer.html` now writes
them, the panel has
to still contain the words that warn about SmartScreen, and any `download.json`
beside them has to be one the page would accept. It needs no secrets and
touches no network.

## Rebuilding

Only needed if you change `viewer.html` or the builder. `numpy` and `networkx`
are the only dependencies:

```bash
pip install -r requirements.txt
```

```bash
python -u producer_graph.py
```

Writes `index.html` — or wherever a positional argument points — by inlining the
payload into `viewer.html`. Reads `freesound-raw.json`, spends **no API
requests**, and takes about fifteen minutes, nearly all of it layout. Two
consecutive cached builds are byte-identical, which is asserted rather than
hoped for — see the note on `_ranked` in the builder.

| flag | what it does |
|---|---|
| *(none)* | rebuild the graph from cache |
| `--reseed` | top up similarity coverage; one request per uncovered sample |
| `--refetch` | re-run the tag searches from scratch |

`-u` matters: Python buffers stdout when piped, and the run is long enough that
you will think it has hung.

## What the graph is made of

**Nodes** are samples, tags, and families (Freesound's own `subcategory`
classifier). Key and tempo were nodes once and were removed — 24 keys and 19
tempo bands absorbed thousands of edges while telling you nothing the filters
don't. Both are still on every sample, in the tooltip, in search, and in the
`keyed` / `tempo` filters.

**Edges** are of two kinds, drawn differently on purpose. There are deliberately
few of them: the graph read as a blob until the structural edges were cut from
51,638 to 22,965, which took ink coverage from 47% of the canvas to 14%.

Two rules do that cutting. `TAG_MAX_SHARE` drops any tag on more than 6% of the
corpus - `drum` is on 1,012 samples of 7,023, so it joined a seventh of the graph
to itself and said nothing; a tag that common is the word "the". `TAGS_PER_SAMPLE`
then keeps only a sample's three *rarest* remaining tags, because its common tags
are what it shares with everything and its rare ones are what place it.

Dropping a tag drops an *edge*, and nothing else. Every tag a sample carries -
9.7 of them on average, against the three that can become edges - now ships on
the sample itself, in the tooltip and searchable through `tag:`. It rides as
indices into one shared vocabulary of 6,967 strings rather than 68,000 repeated
words, which is what keeps the whole corpus's tagging inside a fifth of the
payload it would otherwise cost.


- **similarity** (thick) — Freesound's own acoustic ranking via
  `similar_to` + `similarity_space=laion_clap`. The only thing joining two
  samples. 7,058 of them, covering 85.9% of the corpus. At an average degree of
  2 this subgraph *is* the web; turn tags and families off to see it alone.
- **structural** (hairline) — a sample to its family and its three rarest tags.

`STRUCT_W` (0.005) and `SIM_W` (2.2) are layout weights only, not visibility: the
shape is decided by what sounds like what, with tags and families barely tugging.
They are deliberately not fed to the community detection, which sees the graph
unweighted — weighting Louvain once split 11 clusters into 78 and filled the
legend with noise.

Timbre-space k-NN and pack co-membership were both tried as additional edge
kinds and removed: the first was a local approximation of the similarity
endpoint built while I wrongly believed that endpoint was too expensive to use
properly, and 15,670 purple lines buried the 4,428 real ones it stood in for.

## Using it as a sample library

The map is the index. This is the part that gets a sound into a track.

### Walking the similarity edges

The CLAP ranking is the only thing in this graph that knows two sounds are alike,
and until it could be walked it was decoration: you had to spot a thick line by
eye and mouse to the far end of it. `Tab` plays the next similarity neighbour of
whatever is playing, shift-`Tab` the previous, `Backspace` comes back up the path
you actually took. The trail is drawn behind you and the neighbours you have not
taken are marked, so a walk is a visible thing rather than a sequence of jumps.

Neighbours are visited nearest-first *in the current layout*, which is the only
ordering that matches what you can see - the next sound is the one your eye was
already on. A filtered-out neighbour is not a stop - `shown()` is the truth about
what is on screen - but it is still a road. When nothing is one edge away, which
is a dead end, or a neighbour list the filters have emptied, or the only
neighbour being the one you came from, the walk widens instead of stopping:
everything one edge out, then everything two edges out, up to four, offering the
first ring that has something visible in it. From the keyboard that is going back
through the node you arrived from and out of it in a different direction.

It is the difference between a walk and a series of dead ends. Over every way of
arriving at every sample - 21,139 of them - `Tab` had nothing to offer on 23.4%
with nothing filtered and has nothing on 5.4% now; under the one-shot filter,
56.6% against 22.3%. Most of what is left is the 987 samples of 7,023 that
Freesound returned no similar sounds for at all, which no amount of widening
reaches. Four rings is where the curve flattens - six buys two more points under
a hard filter and stretches the word "similar" further than it will go - and the
whole sweep of 21,139 lookups takes 15ms, so one of them is not a cost.

Widening on its own still walks in circles, though. A ranking graph is mostly
small tight cliques, and nearest-visible inside one of them is a loop: three
kicks that all name each other pass the walk round and round for ever, because
the nearest thing to each of them is one it has just heard. A hundred `Tab`s
landed on 4.4 distinct sounds, and 84% of walks ended in a cycle three or four
long.

So the walk remembers where it has been, and a ring is offered fresh ground
first, then ground already heard, longest-ago first. Nothing is taken away - it
goes to the back of the queue - and a ring of nothing but old ground is not where
the walk stops either: it widens past that too, looking for something new, and
only comes back to the nearest such ring when there is nothing new within reach
at all. A hundred `Tab`s now land on 45, and the 7% of walks that still come
round do it in eights rather than threes, which is a neighbourhood genuinely that
small rather than a rule chasing its own tail.

The memory is an LRU `Map`: delete-then-set moves a key to the end of it, so the
oldest is whatever `keys()` hands back first, and the value doubles as the age
the old-ground sort needs. It is 400 deep, which is as far back as `Backspace`
goes, and it is cleared when a walk is - `Escape`, or clicking somewhere else and
starting a new path.

shift-`Tab` had to be told about the ordering too. Backwards from a step you have
not branched from yet means the far end of the list, and the far end of the list
is now precisely where the sounds you have just heard are - so holding it walked
4 distinct sounds in a hundred presses. Backwards from cold takes the far end of
the *fresh* ground instead, the other side of the ring rather than a lap of the
old one, and walks 38. (It was also off by one, landing on the last but one.)

Anything past the first ring says so on the now-playing line, `2 hops 1/6` rather
than `similar 1/6`: a sound two edges away is a weaker claim than one the ranking
put next to you, and the count is of a different list. Landing on something
already heard adds `· again`, which is the cue that this corner of the graph
is walked out and it is worth filtering or moving somewhere else.

The adjacency is a CSR pair of typed arrays built once at load (9.6ms), because
`E` is a flat list of 31,849 edges and rescanning it per hop is the kind of thing
that is free until it is not. Lighting the current and hovered node's edges costs
0.012ms a frame against a ~10.5ms frame.

The other half of a `Tab` is the network. The next sound is knowable - it is
whatever the cursor lands on next - so once you are walking it is fetched while
the current one is still playing, and the press after this one has it already.
The preview lives on Freesound's CDN and the loading symbol between the press and
the sound is that fetch: cold, an element reaches `canplay` in 217ms from here;
read ahead, 29ms. On a worse connection the gap is the same shape and wider.

Nothing extra is downloaded: it is the same request moved earlier. It arms only
on arrival, so someone who clicks around the map and never walks fetches nothing
they did not ask for, and it goes one ahead rather than two - a walk that stops,
or turns round with shift-`Tab`, wastes a single preview. It waits 300ms first so
the sound in hand has the network to itself, it is rearmed on every arrival so
tabbing quickly through a run never leaves a fetch behind for a sound nobody will
hear, and `Escape` drops it with the rest of the walk.

The guess is `walkNext()`, which reads the top frame exactly as `walkStep()` is
about to and returns the same index - without calling `walkFrame()`, because a
guess has no business starting a path or clearing the memory of one. It refuses
to guess when the frame is about to be thrown away: a filter change re-sorts the
list it read, and a sample under the cursor outranks the walk as the anchor.
`crossOrigin` is set to whatever `startAudio()` will ask for, since a response
cached without CORS is a different entry from the same response cached with it,
and a read-ahead under the wrong mode buys nothing at all.

### Searching

The box takes field terms, ANDed, with a leading `-` to negate any of them:

| | |
|---|---|
| `bpm:120-130` `bpm:>100` `bpm:128` | tempo, trusted readings only |
| `key:Amin` `key:"A minor"` `key:C` | key; a bare pitch matches both modes |
| `dur:<2` `dur:0.5-4` | duration in seconds |
| `dl:>1000` `rate:>4` | downloads, rating |
| `loud:>-14` `dyn:>6` | loudness, dynamic range |
| `tag:vinyl` `by:` `pack:` `fam:` `sub:` | substring on that field |
| `-tag:vocal` | drops whatever the term matches |

Anything else is matched as text over the name, uploader, pack, family and every
tag. A term that will not parse degrades to a text search and says so rather than
silently matching nothing - `bpm:banana` becomes a search for "bpm:banana".

`bpm:` and `key:` read the trusted flag, never the raw value. The analyser emits a
key for a car crash, so an untrusted reading is not a number that can answer a
question about numbers.

### Auditioning

A preview is up to 30 seconds and used to audition as its first one. The footer
now draws its waveform - decoded once and cached as peaks for the last 40 sounds,
because a walk revisits - and clicking it seeks. `L` loops; a sample flagged
`loopable` loops by default and a one-shot does not.

Playback runs through a gain node set from the sample's own loudness, so browsing
7,000 sounds is not a volume rollercoaster, with a limiter behind it because
integrated loudness says nothing about peaks and a +12dB boost on a quiet but
peaky one-shot would clip. A 15ms ramp on stop kills the click. Every part of that
chain falls back to a plain `Audio` element if it fails: the enhancement must
never become a new way for the page to be silent.

### Your project's tempo and key

Set both in the header and the page starts answering the question a producer
actually has. The tooltip gains the distance to them - `+6.7% to 137`, `-3 st to
A minor`. `T` auditions at the project tempo by resampling, which shifts pitch, so
the footer says by how much: `at 140 BPM, pitched +5.7 st`. Calling that
time-stretching would be a lie, and which one you are hearing is exactly what
decides whether the loop is usable. Ratios past an octave are left alone.

`fits` filters to keys compatible with the project: the same key, its relative
major or minor, and a semitone either side, because nobody thinks twice about
pitching a one-shot a semitone. Against the 1,403 trusted keys in the corpus, a
project key leaves a median of 224 samples standing across the 24 - fewest for
D major at 139, most for C# minor at 339.

### Keeping and exporting

`S` keeps the sample under the cursor, and so does **`+ keep`** in the footer
beside `save`: the sample that has just played is the one being decided about,
and its bar is already on screen. The same button drops what it kept, so it is
painted `✓ kept` while the sample is in the basket rather than labelled once.

The basket persists as **Freesound ids, not node indices** - the corpus grew by
500 samples in this very change and every index moved - so a basket survives a
rebuild, and an id the new build no longer carries stays in storage rather than
being quietly dropped. Those ids are strings on both sides of `localStorage`,
which is not a detail: one arithmetic `+` on the restore path is enough to hand
a map keyed by `"160213"` a lookup for `160213`, and that reads not as a wrong
lookup but as every kept sample quietly reported as one this build does not
carry - on exactly the reload the basket exists to survive.

The panel raises itself the first time anything is kept, because otherwise the
basket is a number in the header and a keystroke described in a footer nobody is
reading. After that its open state is remembered as well: closing it means closed
on the next load, and nothing later drags it back up.

The panel lists what you have, plays a row on click, and zips the lot.
**`↗ freesound`** opens every kept sample's page on freesound.org, and each row
carries its own `↗`. The zip holds preview mp3s; the uploader's original file,
the full licence text and the pack it came out of are on that page and nowhere
else. Ids again rather than nodes, so the kept samples this build does not carry
are opened alongside the ones it does. Above eight it asks first, and when a
pop-up blocker eats tabs two through two hundred - the ordinary case, not a
failure worth reporting and walking away from - the addresses go to the clipboard
so the basket can still be worked through by hand.

A row, and the now-playing chip, can be **dragged straight into a DAW** or onto
the desktop: the drag carries a `DownloadURL`, which is a Chromium behaviour and
is labelled as one. The canvas is deliberately not a drag source - `mousedown`
there already means pan the view and drag a node, and a native drag would break
both.

Every zip carries a `credits.txt` and a `manifest.csv`. CC0 needs no credit and
CC BY does, so credits.txt ends with a block of just the BY ones, ready to paste
into a track description. Without it a zip of 200 samples is 200 mp3s and no
record of who to name, which makes half the library unusable in practice rather
than in theory.

| key | |
|---|---|
| `Tab` / `shift-Tab` | walk to the next / previous similar sound |
| `Backspace` | back up the path you took |
| `Space` | play the hovered node |
| `D` | save the current sample |
| `S` | keep it in the basket |
| `L` | loop |
| `T` | audition at the project tempo |
| `Esc` | stop, and clear the trail |
| `1`-`3` | pick an arrangement |
| `P` | run / pause the simulation |
| `B` | back to the baked layout |
| `F` | fit to what is on screen |

## Arrangements

`arrange` in the header opens the panel. `1`-`3` switch between the three, each
animating from wherever the last one left off — including from wherever the
simulation has got to. **Only what is on screen is arranged**, so filtering first and
arranging second is the intended order — and every arrangement re-runs when a
filter changes.

The baked layout is not one of them: it is `B`, "undo all of this", and it never
moves. Re-normalising the reference to whatever survived a filter would make the
one fixed layout the least stable on the page. It is also the only thing that
puts the *hidden* nodes back — and through the same transform the visible ones
went through. Placing them raw was a bug you could only see after filtering: every
layout is normalised into a shared box, so the survivors came back at 2.2× the
scale of the 5,164 that had been filtered out, which returned as a clump in the
middle of their own graph.

| | |
|---|---|
| **clusters** | one sunflower disc per community, packed largest first |
| **grid** | every node once, in reading order by cluster then links. Not a picture of the graph — a contact sheet of it |
| **scatter graph** | any two of sixteen fields, with axes |

Each is a pure function from the active subgraph to positions, scaled uniformly
into the same world the physics uses — never stretched to the window, because
a scatter graph squashed to an aspect ratio is lying about both of its axes.
Pressing `P` from any of them starts the simulation there and retires the
arrangement.

### The scatter graph

The x and y pickers appear with the scatter graph and go away with it — they
are its own controls, and mean nothing under a layout that has no axes. They
cover the seven timbre descriptors, loudness and dynamic range, tempo, key,
duration, downloads, rating, link count and cluster. Duration, downloads and
links are on log axes; key runs chromatically through the minor block then the
major.

Loudness and dynamic range are measured for all but 8 samples, and were computed
and then thrown away until now. They are also the pair a producer reaches for
first: one against the other separates the sample that arrives ready from the one
that has already been squashed flat.

**Only trusted readings are placed.** An axis is a claim about where a sound
sits, and the low-confidence keys are the ones the analyser gave a car crash, so
they go in the margin with the rest of the missing data. A node missing one value
still knows the other, so it sits in that axis's margin *at its true position on
the axis it does have* — which turns the margin into a rug plot rather than a
bin. The margins are sized to their own population: only 1,679 samples carry a
trusted tempo, and a fixed thin strip holding the other 4,844 would be a black
line, not a margin.

Timbre is the axis pair this data is actually good for — every sample but 30 has
all seven descriptors, against 1,376 with a trusted key.

Stacked points are the real problem at 7,023 samples, so `spacing` pushes them
apart into a beeswarm; at 0 you get exact positions and nothing legible. That
relaxation does its own collision on a uniform grid rather than reusing the
physics quadtree, because a fresh scatter graph is the one input that tree is
worst at — a few thousand near-identical values drive it to its depth cap. It
also caps the radius at the 90th percentile first: a cell has to be twice the
largest radius in it, the biggest node here is 4.5× the median, and left
uncapped one family node set the grid resolution for seven thousand samples and
turned a 30ms pass into 925ms.

## Live physics

**This is what the page opens on.** It loads holding the builder's layout and
immediately settles it under ForceAtlas2 on its defaults — about 150 ticks, some
four seconds, with auto-fit following it out — so the first thing you see is the
graph arranging itself rather than a still. `P` stops it and `B` puts the
baked layout back. Someone who has asked for reduced motion gets the same layout
without watching it arrive: the same ticks, eight to a frame, painted once at
the end.

**It used to take 357 ticks and about nine.** The stop test asks whether mean
per-node motion has fallen below a share of the graph's own size, which is the
right question; the share was the wrong number. Traced across the 7,759-node
build, motion falls to 0.036% of span by tick 100 and 0.014% by 150, and only
reaches the old threshold of 0.002% at tick 357 — so more than half the run went
on resolving movement of about a fifth of a pixel a frame, while the span was
already within 3% of final by tick 150. `QUIET` is now 2e-4 and it stops where
the picture stops changing. Anyone who wants the last 0.01% presses `P`.

Raising the tolerance was tried instead and is worse in both directions: at
`tol` 2 it saves 25 ticks and each tick costs 70ms against 19, because bigger
steps clump the graph sooner and a clumped graph is what the quadtree is
slowest at.

Everything here is on **a slider** rather than buried in the builder.

### ForceAtlas2

Jacomy, Venturini, Heymann and Bastian's layout — Gephi's. Three things make it
what it is, and all three are here: **repulsion scaled by (deg+1) at both ends**
so a hub clears space for its own neighbours, **attraction linear in distance**
with no rest length at all, and an **adaptive global speed** derived from how
much the graph is *swinging* rather than travelling. That last one is what it has
instead of friction, and it is why it settles 7,000 nodes without anyone tuning a
damping constant. LinLog attraction, strong gravity and dissuade-hubs are there
as flags. `VX`/`VY` hold this tick's force rather than a velocity: nothing
carries over but the previous force, which is what swinging is measured against.

Four presets, each naming every control it touches so switching between them is
symmetric — one that left a shared slider where the last one put it would not be
a preset. From the baked layout they settle to spans of 2,445 (`default`, 366
ticks), 2,153 (`linlog`, 162), 3,136 (`hubs out`, 121) and 739 (`compact`, 595).

**`compact` had to be rebuilt to do what its name says.** The first version only
turned strong gravity on, and settled *wider* than the default: strong gravity
grows with distance while repulsion falls off, so the two balance at a radius the
*scaling* sets, and turning gravity up moves that radius far less than pulling
the scaling down does. At a scaling of 0.04 against a gravity of 1.5 it settles
at 739 where the default settles at 2,445. It also drops `spacing` to 2 — at a
third of the span the collision radii are what stops it getting any tighter, and
they jitter while they do it, which left the stop test hovering on its own
threshold forever. Both sides are fixed: the quiet counter now decays instead of
resetting, so a run ends when the graph is *mostly* still rather than needing
thirty flawless ticks in a row.

Two more things the textbook version does not mention. **ForceAtlas2 has no
natural scale** — it settles wherever repulsion and attraction happen to balance,
and the first scaling tried here, 6, settled at a span of 13,400 with a mean edge
length of 1,247. Nothing is wrong with that in itself; what breaks is `spacing`,
whose collision radii come off the node's drawn size and mean nothing beside it.
The default scaling is 0.2, and every threshold the model uses is relative to the
size the layout has actually reached. And **strong gravity grows with distance**,
making the same slider number about a thousand times stronger, so it is rescaled
internally rather than given a second gravity control to explain.

**The forces.** Repulsion is Barnes-Hut over a quadtree rebuilt each tick, and
that is what makes this real time rather than a slideshow: 7,759 nodes against
each other is 30M pairs a frame. One tree serves repulsion (centre of mass per
quad) and collision (largest radius per quad), carrying a *weight* rather than a
count, since the mass here is deg+1. The two edge kinds get separate attraction
weights, keeping the builder's own ordering - `SIM_W` 2.2 against `STRUCT_W`
0.005 - because a similarity edge is a claim about how two sounds actually sound
and a tag edge is filing.

**A tick gets dearer as the layout clusters**, which is worth knowing before
timing one: repulsion over the spread-out baked layout costs a fraction of what
it costs once the graph has been pulled together, because the tree has to be
opened further. `approximation` (Barnes-Hut theta) is the lever, and a good one -
on the settled graph, theta 0.9 costs 38ms a tick against theta 1.3's 20ms, for a
force error of 0.9% against 3.1%, which is nothing you can see in a layout. The
default is 1.2. While the layout is moving, nodes draw as plain discs and labels
are skipped; the grooves come back on pause, because across 7,759 nodes they are
the entire frame budget.

Everything persists in `localStorage`.

Because a live layout has no idea how big it wants to be, the view follows it -
auto-fit eases toward the bounding box of whatever is shown. Touching the wheel
or dragging the background hands control back and switches it off, since a view
that re-frames while you are reading it is worse than one that occasionally
needs `F`. `fit()` now measures real bounds instead of assuming the 0-1 box the
builder emits, which is also why nothing can wander off the edge and be lost.

## Things the data will not do, learned the hard way

- **`tonality` and `bpm` are emitted for everything**, including material with no
  pitch or pulse — the analyser gave a car crash "F minor" at 0.78 confidence and
  a scream "A# minor". Nothing is promoted to a graph node unless its confidence
  clears a threshold (`KEY_CONF`, `BPM_CONF`); below that it shows greyed in the
  tooltip and joins nothing. That is why only ~19% of samples are "keyed" —
  raising it means trusting readings that are wrong.
- **The descriptors come back on the search itself**, under their bare names
  (`fields=id,name,tonality,bpm,loopable,...`), 150 rows at a time, at no extra
  request cost. `fields=analysis` and `fields=ac_analysis` are silently ignored —
  they are not field names, and believing they were cost this project a day of
  thinking enrichment was one request per sound.
- **The same names work as Solr filters** (`loopable:true`, `bpm:[120 TO 130]`).
  The legacy `ac_`-prefixed forms return HTTP 400.
- **Embeddings cannot be fetched in bulk.** `fields=laion_clap` is dropped like
  `analysis`, and `/sounds/{id}/analysis/` is one request per sound — 6,500
  against a 2,000/day limit.
- **`is_remix` / `was_remixed` are booleans only.** There is no pointer to *which*
  sound was remixed, so remix can be a badge but never an edge.
- **`has_audio_problems` is fetched and reported but deliberately not filtered
  on** — 87 of the 150 most-downloaded sounds are flagged, flagship kicks
  included. Filtering on it would gut the best of the library.

Each of these was established by probing the live API rather than reading the
documentation, which is wrong or silent on all of them.

## Outstanding

- **987 samples have no similarity edge** (85.9% coverage). They arrived as
  somebody else's neighbour and were never seeded, so nothing points onward from
  them. `--reseed` finishes them at roughly one request each; the daily quota is
  2,000 and resets at 00:00 UTC. Expect the corpus to grow substantially when it
  runs — each seed imports ~9 neighbours — because the cap that used to prevent
  that was starving the seeding and has been removed.
- Downloads serve the **preview** MP3 (~128 kbps), not the uploader's original.
  The original needs an OAuth2 session a static page cannot hold, so every zip
  carries a `manifest.csv` of ids and urls instead - the record that lets the
  originals be fetched later by something that can hold a session. The footer
  links to each sound's page for one at a time.

## Originals, not previews

Every download this project made for its first year was a **preview**: the
~128 kbps mp3 Freesound generates for streaming. The uploader's actual file is
behind `GET /apiv2/sounds/<id>/download/`, which requires OAuth2, and a static
page cannot hold an OAuth2 session. That is why the zips have always carried a
`manifest.csv` of ids and urls — the record that lets the originals be fetched
later by something that can hold one.

`serve_originals.py` is that something: a static file server with three extra
routes, serving the same page, so the only thing that changes is where
`downloadOne` and the zip get their bytes.

```bash
python serve_originals.py --dir . --port 8973 --open
```

Once, first:

1. Register an application at <https://freesound.org/apiv2/apply/>.
2. Set its redirect URI to exactly `http://127.0.0.1:8973/api/auth/callback`.
3. Write `freesound-oauth.key` beside the script:
   `{"client_id": "...", "client_secret": "..."}`

Then click **originals** in the header. The access token lasts 24 hours and is
refreshed from the refresh token behind a lock, so the browser dance happens
about once and a 250-file zip cannot start 250 refreshes racing into the same
file. Both the key and the token file are gitignored.

### The callback checks a `state`, and has to

`/api/auth/callback` listens on loopback, and loopback is reachable from any page
the browser happens to be on. Without a check, a site you are merely visiting can
point your own browser at

    http://127.0.0.1:8973/api/auth/callback?code=<the attacker's code>

and the server would exchange that code and store the token - after which every
"original" runs through a stranger's Freesound account, on their quota, and
nothing on the page would look wrong.

So a random `state` is minted when the flow starts, sent to Freesound, echoed
back, and has to match one this process issued. It is single-use, and it expires
with the ten-minute life of the authorization code it protects. A forged callback
- with no state or a guessed one - is refused with a 400 and stores nothing.

The cost is that restarting the server mid-sign-in invalidates the flow, since
the pending states are in memory. That is the right way round: it fails closed,
and the rejection page says to start again from the **originals** chip.

**Nothing about this is required.** `serve_originals.py` is itself the web
server, so it only ever serves the page from `127.0.0.1` — which means the page
only probes `/api/auth/status` when its own origin is loopback. Anywhere else,
GitHub Pages included, the probe is not made at all: the header chip stays
hidden and every download is a preview exactly as before. Served from a plain
`http.server` on localhost the probe is made and simply fails, to the same
effect.

A 401 mid-zip — nobody authorised, or the day's quota gone — falls back to the
preview per file rather than failing the download, and the footer says whether
what you got was originals, previews, or the mix that means the quota ran out
partway.

`safeName()` follows: an original is named with the format the uploader posted,
`n.f`, and only a preview is `.mp3`. Dragging into a DAW carries the original
too — but a drag hands over a URL and walks away, with no callback to fall back
from, so it uses the original only when the session is known to be live.

**Downloads count against the quota** — 2,000 a day, the same pool the builder's
similarity seeding draws from. A 250-sample zip of originals is 250 requests.
That, not the code, is the limit on this.

### The zip compresses now, per member

STORE-only was right while every member was a Freesound preview: an mp3 is
already compressed, and deflating it burns CPU to save nothing. An originals zip
can be full of 24-bit wav, where it saves a great deal, so the method is decided
per file — `mp3`, `ogg`, `opus`, `m4a`, `flac` and `aac` are stored, everything
else is offered to `CompressionStream("deflate-raw")` and kept compressed only
if that actually came out smaller. `credits.txt` and `manifest.csv` compress to
almost nothing either way.

`deflate-raw` and not `deflate`: the latter wraps the stream in a zlib header
and every unzipper would reject the member. The CRC and the uncompressed size
are always of the original bytes; only the stored length and the method change.
A browser without `CompressionStream` stores everything, exactly as before.

The footer only mentions the saving when there is one, so a zip of previews does
not announce "0% smaller".

## The API key

`freesound.key` sits beside the builder and is listed in `.gitignore`. It is a
plain-text credential — rotate it at <https://freesound.org/apiv2/apply/> if this
folder is ever shared, and never commit it.
