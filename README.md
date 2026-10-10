# omr-regress

Regression checks for [Audiveris](https://github.com/Audiveris/audiveris): run two builds on
the same test set and see, input by input and measure by measure, what changed and whether
it got better or worse.

- **What changed:** each export is compared with the other build's. Equal exports are set
  aside, and every measure that differs is listed with the page region it was read from.
- **Better or worse:** when an input has a reference (a correct transcription), both builds
  are scored against it. Each changed measure is *fixed*, *broken* or still *changed*.
- **No reference yet:** look at the changes once, then *accept* a build's output as the
  reference. The next comparison judges changes against it.

It needs Python 3.10 or later and nothing else: no packages, no Java beyond what Audiveris
needs.

## Quick start

```bash
pip install git+https://github.com/vilpter/omr-regress   # or run from a clone: python -m omr_regress

# Transcribe a test set with the base build and with the build under test
omr-regress run --audiveris /path/to/base/bin/Audiveris --inputs testset/ --out runs/base
omr-regress run --audiveris /path/to/fix/bin/Audiveris  --inputs testset/ --out runs/fix

# Compare them
omr-regress compare runs/base runs/fix --html report.html
```

`--audiveris` is the launcher of an installed Audiveris or of a build (`gradlew
installDist` writes it to `app/build/install/app/bin/`). Each input is transcribed with
`-batch -transcribe -export -save`; add more options after `--`, for example
`-- -constant org.audiveris.omr.Main.sheetStepTimeOut=300`. `--jobs` sets how many
inputs run at once (default 2), and `--timeout` the limit per input (default 900 s).
An interrupted run resumes where it stopped.

The comparison prints a summary and, with `--html`, writes a report:

```
A: base  B: fix
156 inputs: 4 worse, 14 changed, 9 better, 1 same, 121 identical, 7 no export
  worse     repertoire/joplin/scan.png  parts 1  measures 16  exact 71.9% -> 68.8%  notes F1 93.2%  changed measures 1 (fixed 0, broken 1)
  better    seed/satb-07/score.pdf  parts 4  measures 8  exact 0.0% -> 6.2%  notes F1 27.6% -> 28.6%  changed measures 7 (fixed 2, broken 0)
  ...
```

For each changed measure, the report shows the measure on the page and each build's
reading of it, and the reference's when there is one. A reading looks like this:

```
reference  <Ab5 Ab6>:8 <Ab5 Ab6>:8 <Ab5 Ab6>:8 <Ab5 Ab6>:16 <Ab5 Ab6>:16~
A (base)   <Ab5 Ab6>:8 <Ab5 Ab6>:8 <Ab5 Ab6>:8 <Ab5 Ab6>:16 <Ab5 Ab6>:16~
B (fix)    <Ab5 Ab6>:8 <Ab5 Ab6>:8 <Ab5 Ab6>:8 <Ab5 Ab6>:16 <Ab5 Ab6~>:16
```

Pitches are scientific pitch names and durations are note values: `4` is a quarter, `8.`
a dotted eighth, `8*2/3` an eighth in a triplet. Other marks:

- `<...>` is a chord; `~` a tie, on a chord or on one of its notes;
- `(` and `)` are slurs; `r` is a rest, `R` a whole-measure rest;
- `g` marks a grace note;
- `s:8` is time a voice leaves out, and `//` separates voices, upper voice first;
- `[clef F4]`, `[key -3]`, `[time 3/4]`, `|:` and `:|` are set in the measure.

Words a build reads differently from the reference are highlighted (from the other build
when there is no reference).

## Test sets and references

A test set is a folder of images and PDFs, searched recursively. An input's id is its path
in that folder. A reference is found, in this order:

1. `<references>/<id>/*.mxl`: the folder that `accept` writes, given with `--references`;
2. a MusicXML file next to the input with the same name (`page.musicxml` for `page.png`);
3. `ground_truth.musicxml` or `reference.musicxml` (`.mxl` and `.xml` work too) in the
   input's folder, shared by its inputs (a scan and a photo of the same page).

Inputs without a reference are still compared between builds; they are only listed as
*changed* rather than *better* or *worse*.

To build references from outputs you have checked:

```bash
omr-regress accept runs/base --references refs/                 # every input of the run
omr-regress accept runs/fix page7.png --references refs/ --replace   # a corrected one
omr-regress compare runs/base runs/fix --references refs/ --html report.html
```

## What is compared

Each staff of one build is paired with the staff in the same position in the other, top
to bottom across parts. Measures are aligned, so a measure missed or added costs that
measure only, not every measure after it. Two measures are equal when they hold:

- the same clef, key, time and repeats;
- the same notes and rests: onset, duration, pitch, grace, ties and slurs.

Voices are ignored for equality; a measure that differs only in its voices is listed as
*voices*.

A clef written after a measure's last note counts as the next measure's clef, where it
takes effect. A multi-measure rest counts as the measures it stands for.

Not compared yet: text, lyrics, dynamics, articulations, ornaments, beams and stem
directions, and layout. An input whose exports differ only in these is listed as *same*.

Scores against a reference:

- **exact:** the share of the reference's staff measures that a build reads exactly;
- **notes F1:** precision and recall of the reference's notes (onset, pitch and duration),
  measure by measure.

An input is *better* when neither score drops and one rises, *worse* when neither rises
and one drops, and *mixed* when one rises and the other drops. It is *failed* when the
base build exported it and the build under test did not, and *recovered* the other way
round.

## Using it in CI

`compare` exits with 1 when an input got worse, failed, or mixed. `--fail-on change`
fails on any change, and `--fail-on never` always succeeds. `--json` writes the results
for other tools.

## Development

```bash
python -m unittest discover -s tests
```

## Licence

AGPL-3.0-or-later, like Audiveris.
