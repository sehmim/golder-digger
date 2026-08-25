# Gold Digger — registration copy

Everything below is written against what is actually in the repo today. Claims that
the code can't back (time-signature detection, full mode detection, "AI understands
your music") are deliberately absent. Numbers come from `results/` and are
reproducible from commands in the repo.

---

## Name

**Gold Digger**

## Tagline (pick one)

1. Your sample library, at a chosen level of non-obviousness.
2. A distance dial for your own sample library.
3. Finds what fits your session — as far from obvious as you dare.

## Short description (for ~140–200 char form fields)

> Gold Digger reads your Ableton session and digs your own sample library for
> parts that work with it — with one dial for how far from the obvious to go.

## The value prop (revised)

We produce in an age of abundance. There are more samples on our drives than we
will ever hear, and finding a *working* idea is trivial. Being stuck is not about
access — it's that every way we navigate a library returns what we already had in
mind. Browse by name and you get what the pack vendor typed. Search by similarity
and you get more of what you just played. The results are functional, and they
regress to the mean; the interesting part is usually the one you would never have
typed into a search box.

Gold Digger answers one question: **what else in my library works with what I
already have — at a chosen level of non-obviousness?**

Point it at your sample folders. It slices every file at downbeats, measures key,
tempo, chroma and spectral character, embeds each chunk with CLAP, and infers the
sample's *role* (drums, bass, melody, texture…) — from your own filename first,
a zero-shot classifier second. Every estimate carries an honest confidence: a
hi-hat does not get to claim a key just because an algorithm returned one.

Then connect your actual working session. Drop in an Ableton `.als` and it
resolves every sample the set references against your library by content hash,
and takes the session's stated tempo and key as ground truth — things a
0.9-second one-shot could never tell us.

Ranking keeps two questions separate on purpose. **Fit** — *does this work with
my session?* — combines harmony, rhythm and role-complementarity into a gate.
It's ratio-aware (an 87 BPM loop matches a 174 BPM session) and complement-seeking
(it prefers the thing that goes *next to* your snare over another snare).
**Novelty** — *how non-obvious is this?* — is embedding distance converted to a
percentile across your whole corpus. One **DISTANCE dial** spans them: at 20 you
get safe swaps; at 90, the strange thing that still fits. And you don't judge
finds from a file name — each one auditions time-stretched to your session's
tempo, mixed under your actual session, so what reaches your ear is the
combination.

Because the corpus is *your* drive, this works on more than sample packs: point
it at the bounces and stems of projects you abandoned, and dig for gold in your
own unfinished work.

**It is not similarity search run backwards.** In our baseline runs over a
2,000-file library, only ~27% of what Gold Digger returns overlaps with simply
walking outward in embedding space; nearest-neighbour retrieval returns the same
role as your context 96% of the time; and at identical achieved novelty, the fit
gate keeps every selection above the compatibility floor where ungated distance
drops a quarter of them below it.

---

## Devpost-style long form (use the sections your form asks for)

### Inspiration

Producers get stuck not for lack of material but because every navigation tool is
a mirror: it returns what you already had in mind. We wanted the feeling of
digging through a crate and finding something you *wouldn't have looked for* —
except the crate is the sample library and abandoned projects you already own,
and the find is guaranteed to work with the session you have open.

### What it does

Gold Digger ingests your sample folders (slicing, key/tempo/spectral analysis,
CLAP embeddings, role inference with per-estimate confidence), reads your Ableton
set to establish the musical context (samples resolved by content hash; tempo and
key taken from Live as ground truth), and then ranks your library on two
deliberately separate axes: Fit (harmony · rhythm · role, used as a gate — never
a percentage) and Novelty (embedding distance as a corpus-relative percentile).
One DISTANCE dial chooses the novelty percentile *among things that already fit*.
Every result auditions time-stretched to the session tempo, mixed under the
session itself — pitch untouched, so the harmony you hear is the harmony that was
scored.

### How we built it

Two halves. A Python engine — librosa + HPSS-gated Krumhansl key estimation,
beat-this for downbeats and tempo, LAION-CLAP for embeddings and zero-shot
tags, Essentia as an independent second opinion, FastAPI over SQLite, the whole
corpus held in RAM as one `(N, 512)` matrix so moving the dial re-ranks without
touching a model. An Electron + React desktop app in three steps (ingest →
connect project → dig), where the renderer never opens a socket — Electron main
owns the Python child process and audio crosses as bytes over IPC.

We built the entire mechanism against a deterministic mock feature extractor
first — synthetic features seeded by file hash, same shapes and ranges as the
real thing — so ingest, storage, scoring, API and UI were tested end to end at
150 files/second before a single model download. Then we flipped the real
extractors on and validated them against ground truth parsed from sample
filenames (`120bpm`, `Cm`…): tempo 48.5% exact / 58.8% ratio-aware (chance ≈ 3% /
12%), key pitch-class 45.3% (chance ≈ 8.3%), over 2,041 real files in ~13 minutes
on Apple Silicon.

### Challenges we ran into

Honesty was the hard part. Every audio tool returns *an* answer — librosa hands a
hi-hat a key as readily as a pad — so we had to build confidence measures that
mean something: key confidence is the winner's margin scaled by tonalness (the
harmonic share of an HPSS split — a kick's 0.006 tonalness collapses whatever key
the correlation preferred), and tempo confidence needed mean-removal before it
stopped scoring steady noise *above* a metronome. Ableton's file format drifted
across Live 9–12 (three different ways to write a sample path, two to write a
key), so the resolver tries every shape and labels each match with the method
that found it. And extraction is GIL-bound, so ingest spreads work over a process
pool — threads measured no faster than serial; four processes were 3.6×.

### Accomplishments we're proud of

The baseline study. It was entirely possible that this system was just a
similarity search sorted backwards — that was the named risk. It isn't: ~27%
overlap with inverse similarity across the whole dial, fit held at 0.644 vs 0.545
at identical novelty with zero selections below the compatibility floor, and an
ablation showing the fit gate alone changes ~40% of what gets selected.
Nearest-neighbour search — the industry default — turned out to be *actively
wrong* for layering: it scores below random on fit because it hands you the same
role as your context 96.3% of the time. Another snare, when you needed what goes
next to the snare.

### What we learned

Small samples flattered us — our 202-file validation said mode detection was
fine; 2,041 files said otherwise (21% → 13%), so every number we publish now
comes from the full corpus. Confidence that doesn't separate right from wrong
answers is decoration; ours now carries a 4× ratio between them, which is what
lets an unconfident key soften toward neutral instead of hard-excluding a
candidate.

### What's next

Expansive controls. DISTANCE proved the interaction — one dial steering overall
contrast with your session among things that fit — so the next controls
decompose it: browsing by *contrast* on new perceptual axes (density, fluidity,
transient sharpness, reverberation), each a bipolar match ↔ contrast dial whose
center is your session's own measured value, all composing with the Fit gate.
Then automatic effect-chain building that closes the remaining gap — EQ tilt,
transient shaping, reverb — auditioned non-destructively under the session and
exported into Live as a device chain, so a find lands in the project already
dressed. Under the hood: making scoring consume the confidences it already
stores (deliberately deferred — it changes ranking, and that wants listening
tests, not unit tests), listener studies to tune the three by-ear constants,
and packaging the engine for a distributable build.

---

## Tech stack (checkbox fields)

Python · FastAPI · SQLite · NumPy · librosa · beat-this · LAION-CLAP · Essentia ·
Electron · React · TypeScript · Vite

## Category / track suggestions

Music & Audio tools · Creative tools · ML/AI applications (retrieval, not
generation — worth saying out loud: it surfaces *your own* recordings, it
generates nothing).
