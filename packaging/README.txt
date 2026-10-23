Voxel Mapper V3 — CPU Windows desktop prototype

Extract the whole ZIP to a writable folder. Keep VoxelMapperV3.exe and its
_internal folder together. Double-click VoxelMapperV3.exe to open the desktop.
Python is included in the distribution; a separate Python installation is not
required. A console remains available for diagnostics and worker errors.

The default profile supports a 6 GB RAM PC without a GPU: two CPU workers, a
2048 MB observed worker-memory budget, and one heavy generation job at a time.
Memory is monitored and over-budget jobs are cancelled; this is not a hard OS
memory reservation. Large regions and local language models may need more RAM.

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
  VoxelMapperV3.exe --check-dependencies
  VoxelMapperV3.exe --self-test --data-dir PATH_TO_FRESH_TEST_DIRECTORY
  VoxelMapperV3.exe --ui-smoke-test PATH_TO_UI_TEST_RESULTS

This build is unsigned. The build receipt records the exact commit, executable
hashes, native dependency results, backend smoke test and UI smoke test. Full
park autonomy, generalized physical building identity and geographic placement
remain separate reconstruction work.
