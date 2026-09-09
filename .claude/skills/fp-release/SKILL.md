---
name: fp-release
description: Packaging and shipping an fpGyroSup card — building the archive, verifying the build that actually ships, writing the release notes, and pushing. Use when cutting a release or touching anything under gyro/release/.
---

# Shipping a card

## Build it with the script, never by hand

```sh
cd fpSup-v1/gyro
python3 release_card.py gcsv v1.11b        # or: base v1
```

It builds, checks every section the card must carry, writes the zip and the
checksums. Two guards in it exist because of real losses:

- **Section list.** v1.4 shipped without its two orientation sections because a
  rebuild silently dropped two arguments someone had been passing by hand. The
  only visible sign was a VSHL.BIN that hashed differently.
- **It refuses to overwrite an existing archive.** `release/<edition>/` is a
  build directory and drifts from the archive as the shared core moves —
  rebuilding an old version there produces a *different* card under the same
  version number. Rebuilding Base v1 once produced a VSHL.BIN 240 bytes longer
  than the one in its zip.

`--force` exists. It discards a version somebody may already have. Do not.

## Verify the thing that ships

Not a rebuild, not a debug card, not the USB deploy — **write the release
build's own `AutoRun.txt` and `VSHL.BIN` to the card and test that**. Confirm
the hashes match `SHA256SUMS-<version>.txt` before handing it over.

Then run the procedure that reproduces whatever is being fixed, plus the paths
that already worked, so the fix is not paying for itself with something else.

The debug card (`build_base_card.py --edition gcsv --debug`) is the same code
with the USB shell in. Use it to *find* a fault; verify the fix on the release
build.

## The banner names the build

`fpSup-Gyro-v1.11b!` — the card build fills it in from the edition and version.
Two cards look identical in the camera; this is the only way to know which one
is in there. If a test result and a version do not line up, check the banner
before anything else.

## Release notes

Two audiences, and the page is for the second one:

- The commit message carries the reasoning, the addresses, and what was ruled
  out.
- The page gets **short bullets in plain words**: what was broken, what it cost
  the user, what changed. No firmware addresses, no function names. If a
  sentence needs the reader to know what a volume handle is, rewrite it.

Both languages, and keep the previous release listed with what it does wrong
written next to it — people do find old links.

## Push

```sh
git push origin <branch> && git push origin <branch>:main
```

`main` is what the download links and Pages serve, so a release is not released
until main moves. Check the link afterwards and compare the served bytes:

```sh
curl -sL <raw url> | shasum -a 256
```

## What went wrong before

- **v1.4 shipped without two sections.** A rebuild dropped two arguments
  someone had been passing by hand; the only sign was a different hash. Hence
  the section list in `release_card.py`.
- **Rebuilding Base v1 produced a different card** — 240 bytes longer than the
  one in its published zip, because the shared core had moved underneath.
  Hence the refusal to overwrite an existing archive.
- **v1.10a was verified on a build that was not the one that shipped.** Hence
  writing the release build's own files to the card before saying it works.
