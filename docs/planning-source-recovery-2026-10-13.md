# Pinned source recovery — 13 October 2026

The official council HTTPS attachment route returned HTTP 503 from the managed
Linux workspace. The same official HTTP resource returned original bytes matching
historical SHA256 pins. Recovery retained eleven Wicker Man PDFs (58 pages) and
three historical application pages: SMD/2016/0315, SMD/2017/0111 and SMD/2007/0009.
No drawing pins, proposed/existing states or canonical HTTPS identities changed.

`alton.download_pdf` and application discovery now honour an explicitly recorded
`transport_url`. The transport must identify the same official host, path and
query, with no credentials, fragments or unexpected port. A valid historical
SHA256 is mandatory, responses remain bounded, redirects are refused and changed
bytes are rejected before retention or inspection. There is no automatic downgrade
for unpinned links. HTTPS-only entries continue using HTTPS. PDF outage counters
are separate by transport, so three failing HTTPS requests do not suppress an
explicit pinned HTTP resource. Both transports retain the three-failure limit.

The repository catalogues record transport URLs only for originals recovered and
hash-verified in this run. Application discovery can reuse the retained historical
snapshots; a changed HTTP page requires recataloguing rather than being accepted
as a new current snapshot.

Two Katanga PDFs (ImageName 12965 and 15348) timed out. The current SMD/2009/0125
application page differed from its historical checksum and was rejected. These
failures remain in the receipt. The retained pages expose 107 attachment links,
not 107 retained PDFs; offline replay reports 98 unique PDF URLs pending. Catalogue
and application scope do not establish complete park coverage.

Originals stay outside Git. The local retained pack contains `source-bundle.zip`,
its SHA256/report sidecars, and acquisition receipts. Its archive SHA256 is
`858121a1a410ea26647419def6fcb065ffbb6df1c408d2537d46cdb324460cd3`.
Use the [source bundle instructions](source-bundles.md) to verify, replay and
mirror it. Replay requires `--allow-partial` because two supplied catalogue PDFs
are absent. A clean offline replay inspected all 58 retained pages and parsed
three application pages, with zero live downloads, verified registrations or
world blocks. The pack is usable original evidence, not an accepted area model.

A scoped ordinary acquisition from this cache inspected all eleven original PDFs
and parsed both Wicker application pages without source-download requests or
failures. Its status remains partial because its eleven-document budget excludes
other discovered links. Geographic registration, view/state interpretation,
component identity and park insertion remain required. Machine-readable evidence:
[evidence/planning-source-recovery-2026-10-13.json](evidence/planning-source-recovery-2026-10-13.json).
