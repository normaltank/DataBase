# Local visual modules

This folder builds local application assets; it does not run an application server.
Run `npm ci --ignore-scripts --no-audit --no-fund` here, then `node build.mjs`.
Run `node build.mjs --entry timeline` to build one entry. No command clears the
output directory or deletes a peer module. Full builds compile all existing named
entries and reproducibly copy shared styles, the worker and license files.

The five fixed entry names are `globe`, `timeline`, `network`, `flow`, `diff`.
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
while hidden. A rejected module leaves the caller's text/ordinary actions usable.
The loader caches code only, never account data or instances.

Globe options: `{geometry, snapshot:{countries:[{value,label,count}],selected:[]},
onSelect(value), onStatus(message)}`. `update(snapshot)` retains the camera;
`reset('europe'|'world')` is an optional globe-specific method. Country values
are the existing subject-country IDs. Representative positions are geometric
selection aids, not institution locations. The map is the existing local Natural
Earth 1:110m asset under static/geo; attribution is preserved there.

CSS is `/static/vendor/visual/flow.css`, `diff.css`, `cytoscape-csp.css`.
Network style is installed using the exact Cytoscape 3.34.4 stylesheet ID
`__________cytoscape_stylesheet` before importing the module, avoiding its inline
style injection. Upgrades must recheck that internal compatibility contract.
Create ELK with `elkjs/lib/elk-api.js` and `workerFactory: () => new
Worker('/static/vendor/visual/elk-worker.min.js')` (classic worker, not module or
Blob). Always terminate it. ELK API and worker are version 0.12.1. Shared license
files and the ELK upstream source-distribution pointer are shipped in `licenses/`.
No CSP relaxation is permitted. React owns only a local flow root and must unmount.

Flow options: `{snapshot:{nodes:[{id,label}],edges:[{id,source,target,label,description?}],
selected:[id],layout?:'lineage',legend?:string},viewport?,onSelect(id),onStatus(message)}`. IDs and labelled edges
must come from the authorized version/review or step/evidence projection. The
module performs only ELK layout and reading selection. `update` preserves the
viewport; `zoomIn()`, `zoomOut()`, `fit()`, `focusSelected()` and `getViewport()`
support the caller's explicit controls and visibility lifecycle. Initial maintenance view
centres the first node at zoom 1; short material graphs use the compact lineage
layout and initially fit desktop at approximately 1:1. Only selected-adjacent edges
show short labels; their full description remains accessible and in the text legend. `fit` is the user's optional whole-graph overview.
Topology replacement, timeout and dispose terminate the true classic Worker;
late layouts are ignored. React Flow's transient zero-size measurement while a
disclosure is hidden is left to its ResizeObserver, not reported as data loss.
Application forms, file inputs, tokens and write targets stay outside this root.

Diff options: `{snapshot:{before:string,after:string}}`. The module uses jsdiff
and diff2html's default precompiled templates for actual long recorded text. It
escapes HTML-like text and never enables raw templates, eval, editing or a claimed
Word/PDF body comparison. Callers retain full old/new values and semantic short
field/relation comparisons. Both entries use the common update/resize/dispose
contract; failed modules leave those ordinary reading controls available.
