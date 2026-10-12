# Source runtime and Windows evidence replay

Fresh installations previously selected a PyArrow wheel that could not import
with the NumPy 1.26 runtime used by Amulet. The live Overture source check failed
before reading any buildings. The project now constrains Arrow below version
20, verified with 19.0.1. A regression imports the actual Overture/Arrow runtime and checks
a NumPy round trip, in addition to the existing mocked acquisition tests.

The Overture worker now checks exact serialized byte counts before each write
on every platform. Unix also retains its process file-size guard. Windows can
run the reader without the unavailable `resource` module. Exceeding either the
byte or feature budget still rejects acquisition and discards the partial feed.

Windows export and replay fixes:

- SQLite composition connections close on every exit, including budget and
  unsupported-material failures, before temporary directories are removed.
- Packaged attribution and metadata use UTF-8 and LF, preserving international
  attribution text when the world is reopened elsewhere.
- Survey discovery and frame qualification write exactly the UTF-8/LF bytes
  whose hashes appear in their receipts. Resume still rejects altered evidence.
- Git attributes preserve LF in committed text fixtures and source models, so
  Windows checkout conversion cannot invalidate their pinned hashes.
- Synthetic benchmarks run without Unix memory APIs. Unavailable peak memory
  is recorded as `null`; it does not prevent compilation or resume checks.

The complete regression suite now also runs on Windows in GitHub Actions.
Tests that require unavailable external PDF/OCR executables retain their
existing explicit skips.

## Competing original font subsets

CAD sheets can include different embedded subsets with the same font name.
The glyph screen now compares up to four original font candidates, limited to
two MB each and four MB in total, against the unchanged rendered source. It
retains each candidate's hash, resource references and result. Only one candidate
passing the existing per-glyph and surrounding-ink checks can supply a raster
consistency hint. Multiple passing fonts, incompletely screened alternatives,
erased glyphs and exceeded budgets
remain withheld. There is no font substitution or geographic-registration claim.

The changed glyph and map-check versions invalidate dependent evidence facts.
Synthetic regressions cover a uniquely supported original subset, visually
indistinguishable alternatives and erased source ink. The real third Mutiny
sheet still needs a successful original-PDF rerun: the official source endpoint
was unavailable from the local machine during this validation. Existing failed
boundary checks and missing independent survey controls remain unresolved.

The validation receipt is
`docs/evidence/windows-source-runtime-validation.json`. Raw downloads and generated
test worlds are retained outside the code repository.
