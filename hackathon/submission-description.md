# Gold Digger

**A distance dial for your own sample library.**

Producers own more samples than we'll ever hear — packs, stems, bounces, whole abandoned projects — and we still get stuck, because every way of navigating a library is a mirror: browse by name and you get what the vendor typed; search by similarity and you get more of what you just played. Functional ideas that regress to the mean, while the sample that would make the track is the one you'd never have searched for.

**Gold Digger answers one question: what else in my library works with what I already have — at a chosen level of non-obviousness?**

## How it works

- **Ingest your folders.** Every file is sliced at downbeats and measured — key, tempo, spectral character, a CLAP embedding, and a musical *role* (read from your own filename first, a zero-shot classifier second). Every estimate carries an honest confidence: a hi-hat doesn't get to claim a key.
- **Connect your session.** Drop in an Ableton `.als`. Every sample it references is resolved against your library by content hash — surviving moves and renames — and Live's stated tempo and key become ground truth for the context.
- **Dig.** *Fit* (harmony · rhythm · role, combined as a geometric mean and used as a gate) decides what works with your session. *Novelty* (embedding distance converted to a corpus-relative percentile) measures how non-obvious it is. One **DISTANCE dial** picks the novelty percentile among things that already fit — 20 is safe swaps, 90 is strange-but-still-compatible.
- **Judge with your ears.** Every find auditions time-stretched to the session tempo, mixed under your actual session. Pitch is never shifted — what you hear is what was scored.

## Not similarity search sorted backwards

Baseline runs over a 2,000-file corpus: only **~27%** of what Gold Digger returns overlaps with walking outward in embedding space. Nearest-neighbour retrieval hands you the same role as your context **96%** of the time — another snare, when you needed what goes next to the snare — and scores below random on fit. Gold Digger's gate keeps **every** selection above the compatibility floor at identical achieved novelty. The extractors are validated against ground truth parsed from sample filenames: tempo 48.5% exact (chance ≈3%), key pitch-class 45.3% (chance ≈8%).

## Built with

Python · FastAPI · SQLite · librosa · beat-this · LAION-CLAP · Essentia · Electron + React. Retrieval, not generation — it surfaces your own sounds.

## What's next

Every axis of the sound becomes a match ↔ contrast dial against your session — density, fluidity, transient sharpness, reverberation — and automatic effect-chain building closes the remaining gap, so a find lands in Live already dressed.
