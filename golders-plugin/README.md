# Gold Digger Bridge — AU / VST3

The bridge, not the brain. Insert it on a bus in any DAW; it passes audio
through untouched while keeping the last eight seconds in a ring. **DIG**
writes that capture to a temp wav and asks the engine on `localhost:8420` to
rank your library against it (`POST /session/analyze` with `context_paths`),
stating the host's transport tempo outright (`bpm`). Results come back as a
list, and a row dragged out of the list is a plain file drop the host accepts
onto its timeline — that drag is the whole reason this exists.

Every measurement stays in the Python engine. The plugin contains no analysis,
which is why it is ~500 lines and does not need to change when scoring does.

## Build

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release      # fetches JUCE 8 on first run
cmake --build build -j
```

`COPY_PLUGIN_AFTER_BUILD` installs into `~/Library/Audio/Plug-Ins/Components`
(AU) and `.../VST3` for the building user. Validate the AU with:

```bash
auval -v aufx Gdig Gldg
```

## Caveats

- **The engine must be running** — the desktop app or `golddigger serve`.
  Without it, DIG reports exactly that.
- HTTP is a hand-rolled request over a loopback socket on purpose:
  NSURLSession's transport-security policy belongs to whichever host DAW
  loaded us, and a plain socket cannot be vetoed by its Info.plist.
- Sandboxed hosts (GarageBand, and AUv3 contexts generally) may deny loopback
  networking entirely; Live, Logic (AUv2), Reaper and Bitwig do not.
- Unsigned, like the DMG: your own machine loads it fine; distribution needs
  the same Developer ID errand.
