# fp Card Composer

**Policy, 2026-09-13: merged cards are produced here and nowhere else.**

Tick the cards you want, get `AutoRun.txt` and `VSHL.BIN`. Drop in someone
else's `VSHL.BIN` to merge that too.

## Which copy to open

**A person wants the page rendered.** Open `index.html` from disk — it is one
self-contained file, no server and no build step. Everything works from a
`file://` URL, downloads included.

What does *not* work is opening it from GitHub's raw host:

    raw.githubusercontent.com  ->  content-type: text/plain

GitHub serves every raw file as plain text on purpose, so it cannot be used as
a web host, and the browser shows you the source instead of the page. jsDelivr
does the same for `.html`. To get a rendered page from a URL you need GitHub
Pages (Settings → Pages → deploy from this branch, folder `/`), which puts it at
`…github.io/<repo>/tools/card-composer/`.

**An agent wants the text, and `text/plain` is exactly right.** Fetch the raw
file and pull the two blocks out of it — there is no rendering step anywhere in
the path, and no browser:

```js
const html = await fetch(RAW_URL).then(r => r.text());
```

Then follow "Using it from a script, or from an agent" below. The catalogue and
the composition code are both inside that one file, so the fetch is the whole
install.

## Why the rule exists

`build_og3k_gyro.py` used to emit a merged OG3K+gyro card directly, and for
weeks it emitted the wrong one: it called `build_card.py --gcsv-stream`, while
the shipped v1.11b was built by `build_base_card.py --edition gcsv`. Those two
produce completely different payloads. The card was called `og3k_gyro_release`,
its manifest said "gyro", and the gyro inside it was not the gyro we shipped.
Nothing failed. Nobody noticed until the two were compared section by section.

One place that merges, and that verifies its own output against the shipping
artefacts, cannot drift like that.

The build scripts still exist and are still the only thing that can *create* a
card — OG3K's 554 writes come out of `og3k_plan`, and that needs an assembler.
What they no longer do is combine. `build_og3k_gyro.py` refuses to emit a merged
card without `--reference`, which is for regenerating this tool's comparison
baseline, not for putting in a camera.

## How it works

Two facts make browser-side composition exact:

* `VSHL.BIN` is a plain container — `"VBIN"`, a count, the entry, the payload
  length, then one `(dest, len)` record per section, blobs 4-byte aligned.
  Sections are independent, so merging is concatenation plus checks.
* `AutoRun.txt` does not depend on the section list, or even on the entry — the
  loader reads that out of VSHL.BIN's header. Measured: the OG3K-only card
  (entry 0) and the OG3K+gyro card (entry `0xC072E064`) have the same 135
  commands and differ in three banner lines.

What AutoRun *does* depend on is the **loader**, and there are three
configurations — each one flag of `build_autorun.py`, generated on every run:

```
plain      --no-shell        NOTASK=1, 135 commands
shell      --no-ep-patches   task loader + interface patch, 189
shellpush  (neither)         the same plus the EP 0x83 patches, 195
```

An earlier version lifted two of them out of merged cards that had been built and
left in the tree, which made a merge tool look like it depended on merged cards.
It never did — the cards were just the first place each configuration could be
found. Verified line-for-line identical to generating them directly. They are carried whole rather than assembled from optional
blocks, because splitting them would be rebuilding `build_autorun.py`'s option
matrix in JavaScript, and that matrix grows:

```
plain      135 cmds   loader.S with NOTASK=1.  The file read happens in the
                      borrowed dispatcher task, once, at boot.  236 bytes.
shell      189 cmds   loader.S without it -- 356 bytes, because the worker
                      blocks in FN_WAIT on the endpoint and cannot run in a
                      borrowed callback, so it needs a task of its own.  Plus
                      68 bytes zeroing the worker's state (a warm restart does
                      not clear RAM) and the interface-class patch, without
                      which the host's PTP stack claims interface 0.
shellpush  193 cmds   the same, plus the six EP 0x83 patches.
```

The page picks between them from whether a selected card carries the worker at
`0xC072F050`, and a checkbox for the push patches.

## Checks

The same rules `build_base_card.py`'s `check()` runs, plus two the merge needs:

- no two sections overlap
- no pool section lands in the loader's read window (`pool+0x7000..0x28000`,
  read out of `loader.S`, never written down twice)
- payload sections stay between the loader and the park stub

  > The cave is not one flat region. `0xC072DE64` loader, `0xC072E064` payload,
  > `0xC072EFB4` park stub, `0xC072F000` shell state, `0xC072F050` worker. Only
  > the payload window is bounded by the park stub; the first version of this
  > check treated the cave as flat and failed every card carrying the shell.
  > The park stub and the F_WRITE restore are exempt entirely — they go in as
  > `--also`, not `--also-bin`, so the build scripts' own check never sees them,
  > and the park stub lives *at* the bound it would be tested against.

- every selected card branches to the same entry
- VSHL.BIN fits in 32,768 bytes
- the banner is printable ASCII (the OSD font has no glyph for anything else)

## Using it from a script, or from an agent

The page is self-contained, and the composition logic is in one `<script>` block
that touches no DOM. Pull that block and the catalogue out of the file and run
them anywhere:

```js
// node, no browser, no dependencies
const fs   = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const CAT  = JSON.parse(html.match(/<script id="cat"[^>]*>([\s\S]*?)<\/script>/)[1]);
const src  = html.match(/<script id="compose">([\s\S]*?)<\/script>/)[1];

// The block declares with const/let, so give it a scope and ask for what it made.
// CAT and atob are the only things it needs from outside.
const api = new Function('CAT', 'atob', src + `
  ; return {picked, entryOf, composeVshl, composeAutorun, runChecks, on,
            setPush: v => pushOn = v};`
)(CAT, s => Buffer.from(s, 'base64').toString('binary'));

api.on.clear(); api.on.add('gyro'); api.on.add('og3k');   // ids: gyro, og3k, shell
api.setPush(false);                                       // EP 0x83 patches

const banner = 'fpSup-OG3K-Gyro!';
const recs   = api.picked();
const entry  = api.entryOf(recs);
const vshl   = api.composeVshl(recs, entry);
const auto   = api.composeAutorun(banner);

const bad = api.runChecks(recs, vshl, banner, entry).filter(c => !c.ok);
if (bad.length) throw new Error(bad.map(c => c.t + ': ' + c.d).join('\n'));

fs.writeFileSync('VSHL.BIN', Buffer.from(vshl.bytes));
fs.writeFileSync('AutoRun.txt', auto);
```

`on` takes card ids — `gyro`, `og3k`, `shell` — and `pushOn = true` adds the
EP 0x83 patches. There is no second implementation to keep in step: this is the
same block the page runs.

**Check the result before writing it.** `runChecks` returns the same list the
page shows; a card that fails one of them is a card that does nothing, or
freezes the camera at boot.

## Regenerating

    ./build_catalogue.py

Reads the shipping artefacts, tags every section by which card it came from,
embeds them, and writes `index.html`. It **refuses to write the page** unless
the catalogue reproduces all of this byte for byte:

```
gyro              == fp-gyro-sup-v1.11b.zip
og3k              == og3k_release/
shell             == fp_usb_shell/autorun/
og3k+gyro         == build_og3k_gyro.py --reference --release
shell+og3k+gyro   == build_og3k_gyro.py --reference
```

The last two are built into a temporary directory and deleted when the run
finishes. They used to sit in the tree as `og3k_gyro_release/` and `og3k_gyro/`,
which quietly contradicted the policy this tool exists to enforce: a merged card
that looks like a finished artefact invites someone to put it on an SD card. They
are still built on every run, because they are what the page's output is checked
against — they just do not survive it.

The last two are the ones that matter: they are the merges, and they come out
identical to what the build scripts produce.

To add a card, put its directory in `CARDS` and run this. Data, not code.

## Not covered

Sections are placed in listed order, and uploaded cards go after the built-in
ones. Nothing runs until the loader branches to the entry, which is forced last,
so ordering is only a hazard where two sections fight over the same bytes — and
that is checked. A firmware hook placed before the payload it calls is a hazard
no static check here can see. Each card keeps its own internal order, so this
only matters if an uploaded card hooks something a built-in card supplies.
