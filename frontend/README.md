# Local visual modules

This folder builds local application assets; it does not run an application server.
Run `npm ci --ignore-scripts --no-audit --no-fund` here, then `node build.mjs`.
Run `node build.mjs --entry timeline` to build one entry. No command clears the
output directory or deletes a peer module. Full builds compile all existing named
entries and reproducibly copy shared styles, the worker and license files.

The fixed entry names are `globe`, `timeline`, `network`, `flow`, `diff`,
and `desk-motion`.
`desk-motion` also supplies the short shelf/list and book-to-detail transition;
the ordinary same-origin bookshelf adapter retains native content on load failure.
Their source is `frontend/<name>.js` and output is
`static/vendor/visual/<name>.js`. Missing entries are skipped by the full build;
a missing requested single entry is an error. Do not change the lock or loader
when adding these named modules. Avoid importing fixture or prototype HTML.
The adapted prototype geometry/picking MIT notice is preserved in
`prototype-LICENSE.txt` and copied with the generated licenses.
All runtime dependencies are exact versions in package-lock.json. Runtime needs
no Node or CDN. Static files already follow the application's portable packaging.

`window.visualLoader.load(name)` resolves a same-origin ESM module, loading its
external stylesheet first. Failed loads are evicted for retry. `mount(name,
container, options, {isCurrent})` checks the caller's account/page/selection guard
before and after `module.mount(container, options)`, disposing a late instance.
Every entry exports `mount(container, options)` and returns an instance exposing
`update(snapshot)`, `resize()` and idempotent `dispose()`. Page adapters own their
query/data/account generation; modules must not reach into global application
state. Dispose before replacing a slot, on route/identity changes, and disconnect
observers/listeners/workers/RAF/GPU resources. Do not render an animation loop
while hidden. Globe, timeline and network also expose `getViewState()`; globe
and timeline expose `restoreViewState(value)`. Their optional mount `viewState`
contains only camera/target, selection and chart zoom/brush state, never a copied
record window. The page adapter captures it before disposing on document hiding
and remounts only after a fresh authorized read. The page adapter resumes only after that authorized read; a standalone globe
can repaint its unchanged scene on visibility return. A rejected module leaves the caller's text/ordinary actions usable.
The loader caches code only, never account data or instances.

Globe options: `{geometry, snapshot:{countries:[{value,label,count}],selected:[]},
onSelect(value), onStatus(message)}`. `update(snapshot)` retains the camera;
`reset('europe'|'world')` and `zoom(step)` are globe-specific methods. The
focusable canvas supports arrows, plus/minus and Home; native country buttons
and the multi-country checkbox remain the selection entry. Selected countries
use curved radial relief with side walls; update retains the camera and accepts
multiple selected subject-country IDs. Country values are the existing
subject-country IDs, never institution locations. The map is the existing local Natural
Earth 1:110m asset under static/geo; attribution is preserved there.

Globe borders use square-capped, screen-space triangle quads with CSS-pixel
widths and deduplicated shared edges. The small ShaderMaterial handles only the
globe's bounded camera domain, not generic near-plane crossing lines. It avoids
the measured software-rendering cost of the initial general LineSegments2 path.
`python scripts/check_globe_feedback_browser.py --evidence <new-directory>` from
the repository root checks real Chromium/WebGL feedback and input with synthetic
HTTP data. `python scripts/measure_globe_feedback_browser.py --evidence
<new-directory>` compares the fixed #149 baseline bundle with the working bundle;
its laboratory timings are not field INP. See [the #149 evidence notes](../work/globe-feedback-149.md).

CSS is `/static/vendor/visual/flow.css`, `diff.css`, `cytoscape-csp.css`.
Network style is installed using the exact Cytoscape 3.34.4 stylesheet ID
`__________cytoscape_stylesheet` before importing the module, avoiding its inline
style injection. Upgrades must recheck that internal compatibility contract.
Create ELK with `elkjs/lib/elk-api.js` and `workerFactory: () => new
Worker('/static/vendor/visual/elk-worker.min.js')` (classic worker, not module or
Blob). Always terminate it. ELK API and worker are version 0.12.1. Shared license
files and the ELK upstream source-distribution pointer are shipped in `licenses/`.
No CSP relaxation is permitted. React owns only a local flow root and must unmount.

Timeline options: `{snapshot:{years:[{year,count}],items:[{id,title,kind,date,
year,precision}],lens:boolean,kindLabels},onRange(start,end),onSelect(recordID),
onStatus(message)}`. ECharts brush and dataZoom report an unapplied range; the page
adapter applies it through the existing query. Optional Three lens picking uses
the same authorized record window and precision, and opens the ordinary reader.
`reset()` resets its lens camera. Lens year/type labels use projected DOM text
at 14 CSS pixels, independent of camera fit; the geometry and text share the
authorized date domain. There is no invented date for unknown items.
`GET /api/material-discovery?visual_window=1&...` adds `time_context` with
`scope=query_without_time`, `total` and all three date distributions; it also adds
`timeline_window` with `date_field`, `items`, `total`, `loaded`, `limit=300` and
`has_more`. Without the flag the existing distribution representation is retained.

Network options: `{snapshot:{center:'record:'+id,nodes:[{key:'type:'+id,type,id,
name}],edges:[{key:stableRelationID,from:nodeKey,to:nodeKey}],selected:nodeKey},
onSelect(nodeKey),onStatus(message),mode:'plane'|'space'}`. Cytoscape plane and
Three space share the identical authorized one-hop snapshot and selected object.
`getViewState()` retains the plane and space cameras for authorized remounts.
`setMode(mode)` changes the view; `reset()` resets its camera. The caller retains
the semantic relationship direction, basis, AI/human provenance and real profile
destinations in ordinary text. The local Cytoscape stylesheet compatibility rule
above is part of this exact locked version, including the external stylesheet ID.

Flow options: `{snapshot:{nodes:[{id,label,actions?:[{id,label,primary?,disabled?}]}],edges:[{id,source,target,label,description?,relation?:'sequence'|'review',parallel?:boolean}],
selected:[id],layout?:'lineage'|'material-lineage',groups?:[{id,version,nodes:[id]}],legend?:string},viewport?,onSelect(id),onAction(id, action),onStatus(message)}`. IDs and labelled edges
must come from the authorized version/review or step/evidence projection. The
module uses ELK for general maintenance layout, reading selection and adapter-provided node actions. Material-lineage uses explicit version groups rather than DAG layering; it does not start an unused ELK worker. The adapter alone checks permissions and owns HTTP requests, forms, tokens, request identity and File objects; these remain outside the React root. `update` preserves the
viewport for general graphs and selection changes with unchanged topology. Material topology replacement resets the readable origin to x0/y0/zoom1; `zoomIn()`, `zoomOut()`, `fit()`, `focusSelected()` and `getViewport()`
support the caller's explicit controls and visibility lifecycle. Initial maintenance view
centres the first node at zoom 1. Material-lineage places version columns left to right, with submission and actual reviews in that column; compact widths stack version groups. Material text starts at zoom1 and fits by page height rather than automatic shrinking. Only selected-adjacent edges
show short labels; their full description remains accessible and in the text legend. `fit` is the user's optional whole-graph overview for general graphs; in material-lineage it restores the readable group origin at zoom1.
For general ELK graphs, topology replacement, timeout and dispose terminate the true classic Worker;
late layouts are ignored. React Flow's transient zero-size measurement while a
disclosure is hidden is left to its ResizeObserver, not reported as data loss.
Application forms, file inputs, tokens and write targets stay outside this root.

Diff options: `{snapshot:{before:string,after:string}}`. The module uses jsdiff
and diff2html's default precompiled templates for actual long recorded text. It
escapes HTML-like text and never enables raw templates, eval, editing or a claimed
Word/PDF body comparison. Callers retain full old/new values and semantic short
field/relation comparisons. Both entries use the common update/resize/dispose
contract; failed modules leave those ordinary reading controls available.

Whole-application acceptance is `python scripts/check_visual_workspace_journey_browser.py
--evidence tests/artifacts/<new-directory>` from the repository root. It serves one
isolated app and one synthetic library, uses both researcher and admin roles, and
loads all five normal modules through the actual application routes. Other focused
browser checks are `check_live_globe_browser.py`, `check_live_timeline_browser.py`,
`check_network_browser.py`, `check_collaboration_lineage_browser.py`,
`check_maintenance_trace_browser.py` and `check_live_flow_failures_browser.py`.
Their screenshots and JSON outputs stay in ignored local artifacts. Runtime strict
CSP sentinels deliberately exercise denied inline styles/eval; those expected
denials are recorded separately from library violations. Test suppliers are
synthetic and test servers use isolated data and ports.

Refresh/lifecycle regression is `python scripts/check_discovery_refresh_browser.py
--evidence-dir tests/artifacts/<new-directory>`. It checks ordinary authorized
HTTP reads, failed-read mouse interaction, focus/drafts/zoom, actor changes,
and explicitly labelled controlled-DOM visibility with real WebGL context-loss
observation. This is not native OS visibility evidence. The single-year visual
review scene can be recaptured with `python scripts/capture_time_review_browser.py
--evidence-dir tests/artifacts/<new-directory>`; it writes new screenshots and
metadata without modifying prior review evidence.

`desk-motion` is a bounded interaction helper rather than a chart adapter. It
exports `transition(target)` and `cancel()` using exact Anime.js 4.5.0. The
application imports its same-origin revisioned bundle; its scope is reverted
on another transition, route composition, document hiding or reduced-motion
changes. Reduced motion takes the visible final state. No runtime CDN, Node
service, inline stylesheet or CSP exception is needed. Native Popover provides
top-layer menus, light dismissal and Escape/focus restoration; the public
Chromium desk check exercises those behaviors. No duplicate write-form component
is mounted: native form/File nodes stay owned by the existing handoff module.

The build copies the Anime.js MIT notice into `static/vendor/visual/licenses/`.
`npm ci --ignore-scripts --no-audit --no-fund` followed by `node build.mjs`
reproduces the six same-origin bundles from the lockfile.
