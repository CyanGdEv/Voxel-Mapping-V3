# Adaptive research and learning

The `research_learning_cycle` desktop job uses the reviewed dataset's component classes, independent source-group coverage and saved cross-source recall to select public research queries. Public site profiles supply names, locations, application references, ride types and exact starting links. Local source text and file paths do not become search terms. Coaster track/support tasks target coaster profiles; independent owner sites are prioritized.

Choose **Adaptive research / source learning cycle** in the desktop job selector and submit `examples/desktop/adaptive-research-cycle.json` after setting its dataset and encoder paths. Paths are relative to the request JSON. The normal desktop worker, cancellation, persistent history and heavy-job concurrency controls apply. This change integrates source code; a new Windows EXE has not been built or installed as part of this validation.

For a source checkout with the existing dependencies and registered encoder:

```sh
python -m voxel_mapper.research_learning_cycle --config request.json --output run-001 --memory research-memory --cache web-cache
```

Use a fresh output directory and retain the same memory/cache directories on subsequent runs. Each submission is a bounded cycle, not a continuously running background trainer. `max_research_jobs: 0` performs checkpoint validation/fitting and curriculum generation without web jobs. Successful task IDs are remembered; `refresh_research: true` explicitly revisits them. Sites and tags are literal relevance hints, not verification of a document's identity.

## What learns automatically

A changed, verified source-pair dataset triggers CPU fitting of the existing class and mask heads. The registered MobileNet encoder remains frozen. An unchanged dataset reuses its checked checkpoint. The SQLite memory records source body hashes, completed queries and model/report hashes. Interrupted checkpoint registration can recover a complete checkpoint only after lineage validation. Reserved evaluation datasets are rejected by the dataset reader.

The current training dataset drives research priorities. The cycle remembers new source bodies and searches other configured sites for comparable components. It does **not** infer trustworthy geometry labels from arbitrary downloaded images. New media remain candidates until reviewed labels and independent source evidence enter a new dataset version. There is no production-model promotion, self-modifying code, or demonstrated accuracy gain from this research cycle alone.

## Web and reasoning capabilities

`research_profile` adds site, location, tags, applications and exclude_tags to the standalone web research job. Focused views rank links before truncation and examine native text on the first 80 PDF pages, retaining up to six cited excerpts. This preserves the immutable original cache receipt and download SHA. Scanned images still require visual interpretation/OCR; the new native-text scan does not solve that automatically.

PDFs and single-frame PNG/JPEG/WebP images are downloaded with byte hashes; image decoders verify format and limit decoded size to 16 million pixels. Images receive no invented captions or labels. Original assets are exported under each web job's `downloads/` directory.

`allow_public_discovery: true` permits literal search-result/source links and public redirects outside the initial host list, up to 32 hosts. It retains URL and per-hop DNS checks, private/local/metadata exclusions, authentication stripping and cookie clearing. The default remains explicitly scoped hosts. Each research job allows at most 24 sources, six optional model rounds, 64 MB and 600 seconds; each source allows 16 MB. A learning cycle shares a 64 MB / 600 second research budget across at most six jobs. Training happens before that research timer and is separately controlled by the desktop worker.

An installed local Ollama model can guide cited read-only link following through the existing `model`, `endpoint` and `model_options` settings. The validation below used no configured reasoning model: it exercised data-driven priorities, web search, link selection, native PDF inspection and actual head training. No language-model weight training occurred.

## Validation on current ride data

The first real cycle fitted heads on 96 reviewed pairs from three rides, produced 13 curriculum tasks, and ran two searches: Thorpe Park support frames and Alton Towers support frames. It retained three source bodies, two previously absent from the dataset/source memory, using 13,347,588 network bytes. Distinct body hashes do not establish independent geometry supervision; the Thorpe report may overlap the committee pack. A separate restart reused the identical checkpoint with zero network bytes and no weight update.

A separate focused run downloaded the council LVIA PDF and a Library of Congress machinery drawing JPEG, using 512,097 bytes. The PDF's useful passage was on page 23, beyond the original three-page cache excerpt. Both originals were exported and hashed. See `evidence/adaptive-research-validation.json` for pins and test results.

The previous ride cross-source class result remains 7/96, including 78 held-out examples whose classes were absent from their training fold. The existing frozen-feature mask result did not beat the template baseline. This change supplies better research and repeatable fitting infrastructure; it does not demonstrate improved ride geometry or change world blocks.

## Wicker source correction

Two earlier survey candidates concern Wildwood and Field O, not Wicker Man. They cannot establish the ride's datum. The continued source review recovered five retained original PDFs and one revised site plan, and catalogued 89 attachments on the current application page. Eight attempted section drawings did not yield verified PDFs.

LVIA part 1, PDF page 23 (printed page 17), paragraph 3.27 states a maximum proposed track high point of 201 m AOD. This corroborates the unique HP1=201 plan marker. It does not establish ODN/Newlyn, verify the built ride or every height label, or resolve ambiguous HP7. These sources remain research evidence; no XYZ training eligibility is granted. See `evidence/sw8-height-source-corroboration.json`.
