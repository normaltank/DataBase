# Material discovery

Mode: Operate / Read. Primary target: static/material-discovery.js. Related:
static/library.js, static/desk.css. Issue #146, current rework 2026-11-10.

## Direction contract

THESIS: Supporting country/time exploration is a workface with candidates below;
opening a record gives saved text a centered reading surface.

OWN-WORLD: Follow [DESIGN](../../DESIGN.md): cool white/pale indigo, dark graphite,
15px UI and at least14px metadata. Real status words retain domain meanings.

STORY: Apply country or time to the authorized query, select a candidate, read,
and return to the same canvas, camera, filters and unapplied year draft.

FIRST VIEWPORT: Desktop chart/map is above a bottom candidate tray. Search and
extra filters are disclosed. Reading hides the attached exploration and results
without destroying them; the article is centered. Mobile starts with results,
opens exploration explicitly and keeps one task in a single-column flow.

FORM: Code-led structural replacement under the user's direction; no new map
library or raster assets. Existing Three/ECharts stable snapshots, text/flat map,
brush and lens keep their real selection semantics. The global bounded object-
to-workface transition is documented in the collaboration desk surface.

FINISH: Developer evidence is not independent acceptance or deployment. Parent
owns Standards/Spec/visual review. No shipping raster assets.

## Verification boundary

[scripts/check_minimal_research_browser.py](../../scripts/check_minimal_research_browser.py)
uses public HTTP, isolated synthetic records, real Chromium, random port and no
worker/AI. It checks rapid countries, slow/late reads, retained DOM/camera/input,
saved query/history, failure retry, batches, permission/account boundaries,
320/390/1280/1440 and native200% browser zoom.
