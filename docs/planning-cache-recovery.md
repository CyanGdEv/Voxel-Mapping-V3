# Partial planning cache recovery

Supplying `--cache` previously prevented recovery of a catalogued PDF or
application page whose retained file was absent. A partial archive could leave
the drawing unavailable even when its official endpoint was working.

Alton acquisition now reads present retained files first and downloads missing
PDFs from their official HTTPS URLs. A recovered PDF must match its historical
SHA-256 before it is stored or inspected. A changed drawing needs recataloguing.
Corrupt, oversized, unreadable or escaped cache paths remain failures; they do
not trigger replacement downloads. Available cached PDFs retain priority over
downloads within the document budget.

Attachment discovery also fetches missing application pages. Current HTML can
change, so its observed hash and `official_download` provenance are retained
separately from the historical cached-page hash. Each validated page is saved
under `files/<observed-sha256>.html` in the output for audit. A present historical
page must still match its historical checksum. Neither path establishes complete
council coverage or verifies drawing geometry.

Both stages stop network attempts after three consecutive download failures
while continuing to inspect available cached evidence. Cached successes do not
reset the application download outage counter. Existing size, timeout, deadline,
redirect and document budgets still apply. Reports include missing download
attempts, deferred counts, acquisition methods and local source paths.

Inspect a retained directory, recovering missing files where possible:

```sh
python -m voxel_mapper.alton --cache retained-planning --output planning-check
```

For a checksum-pinned ZIP, first use the existing
[retained archive importer](anchor-audit.md). Its `--allow-partial` option keeps
absent PDF entries as metadata; it does not fabricate their bytes. Pass the
resulting corpus directory as the cache. Recovered PDFs are retained in the
inspection output's `planning-documents` directory. Wicker Man can reuse its
existing acquisition output with `--source-output`.

The 2026-10-12 real empty-cache Wicker Man acquisition exercised two application
requests and three pinned PDF requests, then deferred eight PDFs. All five
requests failed at the council TLS connection. No original PDF was recovered or
inspected, and no planning geometry was added. The earlier successful Alton
generation artifact (run `37678459391`) was also checked: its verified ZIP has no
PDF members. Original sources and independent survey controls remain necessary
for the real drawing qualification rerun.

Regression tests cover missing pinned PDFs, changed-download rejection, corrupt
and escaped cache rejection, current-page provenance, outage limits, and retained
evidence after an outage. Validation is recorded in
`docs/evidence/planning-cache-recovery-validation.json`.
