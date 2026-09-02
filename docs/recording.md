# Recording the demo

A ninety-second capture of the guided demo, reproducible in one take.

## One command

```bash
make record
```

That brings the stack up, waits until the core, all three connectors and the web app
answer, seeds history **only if the core is empty** (so a second take does not pile up
duplicate incidents), and opens `/demo?pace=slow` in a dedicated 1440×900 window with
no browser chrome.

Three things it guarantees, each of which would otherwise force a retake:

- **The stack is healthy before the browser opens.** A recording that starts on a
  spinner is wasted.
- **The dashboard is not empty.** A cold core shows no correlations, which reads as
  broken rather than as *not yet run*.
- **The window is the same width every time.** The layout is responsive, so a
  different width moves every panel and invalidates the scroll timings below.

`?pace=slow` triples the step pauses. Without it the run finishes in **14 seconds** —
correct, but far too fast to read on video. The default stays snappy for interactive
use and is what Playwright runs, so the test suite does not slow down.

## Shot list

Timings measured on the default `make run` configuration, where
`MARSAD_LLM_PROVIDER=stub` selects the deterministic extractor.

| Time | Action | On screen |
|---|---|---|
| **0:00–0:10** | Record. Do not click. | Header, the note about the deterministic extractor, and the six-step rail — the viewer sees the shape of what is coming |
| **0:10** | **Click `▶ Run the guided demo`** | Step 1 highlights |
| 0:10–0:18 | Nothing. Let it sit. | **Step 1** — Al Maha's boundary panel. Green column: `credential-harvesting…`, `sso-almaha-verify.com`, `Nexa KYC`. Yellow column: `IP:a3f8…`, `T1566.002`, `BANK · LARGE · HIGH` |
| 0:18–0:26 | Scroll slowly | **Step 2** — the Arabic narrative, right-aligned. A different domain: rotated infrastructure |
| 0:26–0:34 | **Rest here** | **What the core sees** — the actual JSON. The one panel worth dwelling on |
| 0:34–0:42 | Scroll | **Step 3** — `◆ SIMILAR ATTACK METHOD`, and the line about the attacker changing infrastructure |
| 0:42–0:50 | Scroll | **Step 4** — `SAFE TO PUBLISH: NOT YET` |
| 0:50–0:58 | Scroll | **Step 5** — provider name and `AED … bn at risk` |
| 0:58–1:06 | Scroll | **Step 6** — `◆ TRICK DETECTED`, four signature chips, severity still HIGH |
| 1:06–1:14 | Rest | The completion banner |
| **1:14–1:30** | Scroll back to Step 1 | Close on the two boundary columns side by side |

The run itself ends around **0:52**. Everything after that is scrolling through panels
that have already rendered, so there is no dead air waiting on the network.

If you narrate, two moments are worth saying out loud: at **0:26**, that the JSON on
screen is the payload itself and you can search it; at **0:58**, that the injection was
caught by fixed rules rather than a model, and the report still filed at HIGH.

## Timing stability — measured, so the shot list holds on take two

Five consecutive runs of the full demo path against the stub provider, timing only the
network work (the pauses are fixed by the code):

| | |
|---|---|
| Mean network work, whole demo | **0.30s** |
| Standard deviation | 0.25s |
| Spread, slowest to fastest | **0.58s** |
| Total at `?pace=slow` | **~41s** |

The entire spread is the first run being cold (0.74s) against ~0.19s once warm — the
same cold-start pattern the model path shows. Against **8.3-second gaps between
steps**, a 0.58s worst-case spread is noise: the step boundaries in the shot list hold
to within about a second on a second take, and drift by roughly 1s cumulatively across
the whole run.

Two things would break that, and neither is subtle:

- **Pointing the connectors at Ollama.** Each filing then costs ~30s on CPU instead of
  0.15s, and the script does not survive it. Record on the default `make run` config.
  This is why the note is on the page itself rather than added in post.
- **Recording at a different window width.** The layout is responsive; a narrower
  window restacks the boundary columns and every scroll cue moves. `make record` fixes
  the viewport at 1440×900 for exactly this reason.

## Converting the capture to a GIF

Record to `.mov` (QuickTime: File → New Screen Recording) or `.mp4`, then:

```bash
# 1. Palette first — a GIF is limited to 256 colours, and letting ffmpeg pick them
#    from the whole clip rather than per-frame is the difference between a dashboard
#    that looks like a dashboard and one that looks like a fax.
ffmpeg -i demo.mov -vf "fps=12,scale=1200:-1:flags=lanczos,palettegen=stats_mode=diff" \
       -y /tmp/palette.png

# 2. Encode against that palette.
ffmpeg -i demo.mov -i /tmp/palette.png \
       -lavfi "fps=12,scale=1200:-1:flags=lanczos[v];[v][1:v]paletteuse=dither=bayer:bayer_scale=3" \
       -y docs/demo.gif

# 3. Check the size. GitHub will render a large GIF but a reader on a phone will not
#    wait for it. Under ~8MB is comfortable; if it is bigger, drop to fps=10 or
#    scale=1000.
du -h docs/demo.gif
```

`fps=12` is a deliberate compromise: the demo is mostly static panels appearing and
slow scrolling, so motion smoothness matters less than text staying legible.
`stats_mode=diff` weights the palette toward the parts of the frame that change, which
is what keeps the JSON panel readable.

The README already contains the embed pointing at `docs/demo.gif`. Drop the file in
and it renders — no further edits.

## Trimming

If the take runs long, cut from the start rather than the end; the completion banner
and the final scroll back to the boundary columns are the payoff.

```bash
ffmpeg -i demo.mov -ss 00:00:04 -to 00:01:34 -c copy demo-trimmed.mov
```
