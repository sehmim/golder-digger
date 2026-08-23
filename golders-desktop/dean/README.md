# Dean's development tooling

This directory contains personal development helpers. They are not required to
build or run Gold Digger.

## Launcher

`scripts/deans-dev-script.sh` starts the complete stack through the repository's
`start.sh`. It defaults to `--mock --restart`, which favors fast and predictable
UI development. Pass `--real` when measured audio features matter.

The convenience launcher outside the repository is:

```bash
/Users/nice/cody/_golder/_scripts/run-dev.sh
```

Both commands accept the options supported by `start.sh`.

## Logs

Each run creates a timestamped directory beneath `logs/`:

```text
logs/<timestamp>/
  frontend.log
  backend.log
  master.log
```

The terminal shows the same combined stream written to `master.log`.
`frontend.log` and `backend.log` keep the processes separate for later review.
