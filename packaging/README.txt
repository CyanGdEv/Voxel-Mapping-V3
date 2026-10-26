Voxel Mapper V3 — CPU Windows desktop prototype

Extract the whole ZIP to a writable folder. Keep VoxelMapperV3.exe and its
_internal folder together. Double-click VoxelMapperV3.exe to open the desktop.
Python is included in the distribution; a separate Python installation is not
required. A console remains available for diagnostics and worker errors.

Review and accuracy opens a source PDF beside its local building geometry.
Try correction demo supplies an offline synthetic example with a deliberate
6 m frontage error against an 8 m drawing. Add an X dimension correction of
8 m, save the draft, then press Regenerate saved corrections. The new model
and native world appear as a separate candidate/job, with before/after metrics.
Original geometry and labels are retained. Review Wicker
building prepares the retained provisional shop and matches original PDFs from
your chosen folder or cache. Save correction drafts without training labels;
reviewed decisions require an external reference and explicit feedback import.
The included accuracy benchmark example is synthetic. It deliberately includes
wrong and missing geometry; measurement completion does not mean geometry passed.

The default profile needs no GPU: two CPU workers, a 16384 MB (16 GiB)
observed managed-process memory budget, and one heavy generation job at a time.
Memory is monitored and over-budget jobs are cancelled; this is not a hard OS
memory reservation or allocation at startup. Settings allow 512-16384 MB;
lower the budget to leave RAM for Windows and other applications, especially
on a PC with 16 GB total RAM. The previous 2048 MB setting remains available.
Independent model servers are outside this budget. Large regions and local
language models may need more RAM.

Evidence, job history, reviewed feedback and model checkpoints are persistent
in %LOCALAPPDATA%\VoxelMapperV3, or the folder selected in the UI. Application
updates do not automatically erase that folder. Start with Generate an area for the included real Alton pilot, without JSON
setup. Wicker building/plaza studies need their pinned original PDFs, supplied
from a retained folder or recovered from the recorded council attachments.
Advanced jobs still accept versioned JSON inputs. Original planning PDFs, survey data, online provider
credentials, and optional reasoning-model weights are not supplied by this ZIP.

The CPU neural network learns candidate priorities from independently reviewed
outcomes. It does not invent verified geometry, treat its own predictions as
correctness labels, or expand the program's source code automatically. Model
promotion is evaluated separately from training and physical acceptance.

Default builds include English Tesseract and Poppler; manual builds can omit
them. Their actual OCR/text/render results are recorded by
VoxelMapperV3.exe --check-dependencies. Native PDF/vector operations use the
bundled Python runtime. The original source and physical geometry checks remain.

Diagnostics:
  VoxelMapperV3.exe --planning-collection-smoke-test PATH_TO_FRESH_COLLECTION_TEST_DIRECTORY
  VoxelMapperV3.exe --web-planning-smoke-test PATH_TO_FRESH_HANDOFF_TEST_DIRECTORY
  VoxelMapperV3.exe --web-smoke-test PATH_TO_FRESH_WEB_TEST_DIRECTORY
  VoxelMapperV3.exe --check-dependencies
  VoxelMapperV3.exe --self-test --data-dir PATH_TO_FRESH_TEST_DIRECTORY
  VoxelMapperV3.exe --ui-smoke-test PATH_TO_UI_TEST_RESULTS
  VoxelMapperV3.exe --review-smoke-test PATH_TO_FRESH_REVIEW_TEST_DIRECTORY
  VoxelMapperV3.exe --correction-smoke-test PATH_TO_FRESH_REGENERATION_TEST_DIRECTORY

This build is unsigned. The build receipt records the exact commit, executable
hashes, native dependency results, backend smoke test and UI smoke test. Full
park autonomy, generalized physical building identity and geographic placement
remain separate reconstruction work.

Web research: enter public search terms or URLs in the Web research tab. The
approved host list limits source reads; source citations and short observations
are retained in local memory. Leave the model blank for evidence-only gathering,
or separately install Ollama and a small model and enter its installed name.
No model weights are bundled. Cached-sources-only avoids website requests;
an enabled reasoning model still contacts its configured endpoint. Reads are
limited to six public sources, two model rounds and bounded text/bytes. Scanned
PDFs need the separate OCR/planning analysis. Web research does not verify
physical claims, generate training labels, update weights or modify a world.

Collect & analyse PDFs: enter the planning application reference and source URL
or search terms in Web research, then press Collect & analyse PDFs. Discovered
original PDF bytes are verified, exported and automatically analysed by page.
Open review.html in Results folder for drawing previews, classifications and
source gaps. Mixed states/roles and application membership stay unverified.
Roof plans and elevations do not enter ground-surface discovery. Scanned PDFs
retain an OCR gap. No per-file source manifest or view rectangles are needed.

Collection continues through unread document links in small saved batches.
Temporary network/server errors receive up to three attempts, with backoff.
Starting the same request resumes verified saved batches without repeating
finished analysis; offline misses can resume online. Source, time, byte and
disk limits preserve explicit gaps. Review ledger.json and each batch review
from the top-level review.html. Exhausted retries and analysis/OCR limits stay
visible. Collection does not establish exhaustive coverage or physical accuracy.

Planning source outlines: Collect & analyse PDFs now retains unclassified closed outlines and bounded view-region geometry. Open review.html in Results, then Inspect extracted source outlines. Cyan and orange inventories can overlap; nominal paper-scale measurements are not verified physical dimensions or geographic registration.

Source-label outline hints: green outlines in planning review.html show unique whole-label/source-enclosure associations. Shared Container labels identify one enclosure hint, not separate component footprints. Physical building/path identity, dimensions and geographic placement still require interpretation. No neural weights or reviewed training labels are created.

Fine component boundaries: purple outlines show individual closed source faces
around visible container labels on floor plans. The automatic bounded scan retains
short source segments omitted by coarse discovery, without snapping or repairing
gaps. Nested, shared, conflicting, hidden, obscured or holed boundaries remain
withheld. These hypotheses require physical exterior-wall, state, height, scale
and park-alignment checks before building reconstruction can accept them.

Nominal component plans: open the component measurement review from planning
review.html to inspect printed-scale trials and linked explicit size notes.
The default 0.25 m span-comparison policy is diagnostic, not physical accuracy.
Conflicting notes/scales, hidden text and frame/paper mismatches stay withheld.
Missing source height and cross-view scope prevent a 3D building preview; two
printed lengths are never treated as an automatic container height.

Section profile review:
Planning Results include section-profiles.html and section-profiles.json.
These retain nominal source-polygon spans and exact drawing evidence. Profiles
remain unassigned to floor-plan components; no physical building height or 3D
shell is accepted. Blue original-page overlays identify the retained profiles.

Planning review outputs include section-correspondence.html. This retains original
sheet-reference circles and competing section/plan component hypotheses across
automatic batches and restart. Similar widths and numeric view indices do not
assign physical component identity, height or a 3D building.

Planning Results can also include design-massing.html. Open it to rotate and
zoom actual conditional 3D row-group envelopes from visible design-statement
dimensions, and compare spacing alternatives. Each has a GLB model, source-linked
specification and static SVG view. Local ground zero is assumed. These are group
envelopes, not complete roofs, individually identified cabins or surveyed park
placements. Extract the whole review folder so linked models remain available.

Planning world downloads: select a completed planning source, web planning or
collection job, then choose Export preview worlds. When the new export completes,
select it and choose Open world. The page links both spacing alternatives as
separate .mcworld downloads. Open a downloaded file with Minecraft Bedrock.
These are Creative-mode surface-envelope prototypes on flat display terrain;
canopy, individual cabins, openings, paths and surveyed placement remain absent.
One block represents one source metre, with boundary rounding documented in the
audit. Each saved world is read back and its archive and outside spawn checked.
The target is Bedrock 1.21.130; Minecraft import and gameplay are not certified.
At most eight worlds may be exported per job. Larger reviews can use an advanced
planning_world_preview request selecting complete source-claim spacing pairs.

Shared plan layout: choose Export plan layout on a completed planning job.
The flat map retains all supported building-footprint and paving proposals in
one nominal source frame. Larger complete layouts use bounded sections in one
world, with a shared 100,000-write limit including foundations. Yellow markers
have no reconstructed building heights, roofs or openings. Saved ground, feature
cells, headroom, archive and spawn are checked; physical paths, park alignment
and Minecraft gameplay remain unverified.

Retained study image learning: extract the separate portable study dataset ZIP.
In Advanced jobs / learning choose Train study component recognizer, choose its
included training request JSON and start. Results contain open model.json weights
and report.json with source-group evaluation. Full original PDFs are unnecessary
for this portable training job. This is a research crop classifier, not automatic
object discovery or geometry generation. It never replaces the building ranker.
The first real 127-example run scored 9.4% on separate source groups; many test
classes are absent from their training folds. More independent examples are needed.
Frozen runtime check:
  VoxelMapperV3.exe --study-learning-smoke-test PATH_TO_FRESH_TEST_DIRECTORY

CPU component outline learning: in Advanced jobs / learning choose
Train component outlines (CPU), then select the separate vision training request.
This compact convolutional research model learns component types and drawing
masks from source crops, with separate-source evaluation and training-only
baselines. Its masks are proposed regions in an already supplied crop; full-sheet
object discovery, real-world dimensions, 3D reconstruction and park placement
remain separate work. It uses the existing CPU runtime and managed memory budget.
The existing component recognizer and active building ranker remain separate.
Frozen runtime check:
  VoxelMapperV3.exe --study-vision-smoke-test PATH_TO_FRESH_TEST_DIRECTORY

Whole-crop context and pretrained CPU features: the separate research bundle
contains two ready training requests. In Advanced jobs / learning select Train
context-aware outlines (CPU) or Train pretrained vision heads (CPU). Open the
result index.html for source-held-out comparisons and assumptions. Saved models
and history survive restart. In the current 148-example benchmark, context mask
IoU is 0.438 versus 0.265 for the older local CNN and 0.308 for the template;
the separate pretrained-feature classifier scores 15/148 versus 10/148. The
record-average mask gain is concentrated in the Prospect examples: with equal
source-group weighting both new models still trail the simple template. Path
targets remain weak. Open the detailed review before interpreting aggregate scores.

The CPU ONNX Runtime is bundled. The separate verified MobileNetV2 descriptor
weights and complete Apache license are in the offline research model bundle;
they are not downloaded automatically. The descriptor stays frozen while new
class/mask heads are fitted. These remain supplied-crop research proposals,
without full-page discovery, verified dimensions or autonomous 3D buildings.
Frozen runtime checks use small explicitly synthetic fixtures:
  VoxelMapperV3.exe --study-context-smoke-test PATH_TO_FRESH_TEST_DIRECTORY
  VoxelMapperV3.exe --study-transfer-smoke-test PATH_TO_FRESH_TEST_DIRECTORY
