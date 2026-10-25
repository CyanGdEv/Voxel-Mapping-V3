# Regional recovery of planning surfaces

The surface-boundary stage now scans a bounded native window around each
supported label, instead of the rectangle spanning every label on a sheet.
Original page paint and fill visibility data are read once and reused. Each
window selects complete original primitives; crossing primitives are withheld,
never clipped, joined or repaired into invented boundaries.

All regions share the existing 10,000-candidate and 200,000-point limits.
Duplicates still consume extraction work, so overlapping windows cannot evade
the work budget. Defaults allow at most 32 windows and 3,200,000 raw-path visits.
Overrides are lower-only. Any incomplete region, exceeded quota or failure
withholds the complete fine result; cancellation propagates.

The stage combines whole source boundaries from completed regions, deduplicates
identical geometry, and binds labels against the combined inventory. Nested or
competing enclosures remain ambiguous. A complete coarse boundary can extend
beyond all regional windows: its unchanged original geometry is retained only
when no fine enclosure contains the label and exactly one coarse enclosure
exists. This does not select among competing boundaries. Every such fallback
retains its original record hash and an explicit reason.

Region receipts retain bounds, extraction options, source-inventory hashes,
record pins and budget outcomes. Cached paint data is bound to the original
page and its unchanged content stream. Later fill/occlusion checks continue to
use the entire page, including paint outside the focused region.

The surface contract is now `planning-surface-boundaries-v2`. Planning jobs and
collections invalidate old analyses through their implementation contracts.
Source-local layout evidence records the boundary version explicitly; previously
exported v1 standalone layouts remain reloadable.

## Wicker development result

On the same pinned proposed woodland-path site plan, the previous encompassing
scan stopped at 10,000 native candidates and published zero fine-stage surface
boundaries. The regional replay completes nine windows, charging 2,733 native
candidates and 8,362 points, with 66 unique source enclosures.

Two unregistered boundary hypotheses are retained: `ground` from fine source
linework and `COURTYARD` from a complete original coarse boundary. These are the
same two kinds of source hints already seen by the ordinary coarse adapter,
not two newly verified physical paths. The nine supported labels out of 134 are
unchanged by this recovery step.

The area stage still requires an unambiguous horizontal drawing context and
supported scale. No real area layout, building, registered path network,
reviewed training label or neural-weight update is produced. This previously
inspected drawing is a development replay, not an independent accuracy test.
See the [source-pinned receipt](evidence/regional-surface-recovery/validation.json).

Synthetic tests cover distant labelled regions with intervening clutter under
the same candidate limit, overlapping windows, later-region failures, shared
budgets, cancellation, original holes, preserved coarse ambiguity and unchanged
large source boundaries. The managed full-plan/native-world smoke also exercises
multiple regional windows and retains its existing block, spacing and restart
checks. Native export success does not establish physical accuracy or gameplay.
