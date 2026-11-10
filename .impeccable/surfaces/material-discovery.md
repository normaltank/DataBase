# Material discovery

Mode: Operate / Read. Issue [#146](https://github.com/normaltank/DataBase/issues/146),
2026-11-10. User explicitly requested a minimal replacement of the cramped
exploration/sidebar composition. The parent supplied the visual direction and
authorized technical choices; this is a code-led build, without randomized
concept selection, a new questionnaire, image assets or extra motion libraries.

## Direction contract

THESIS: Make country/time exploration the primary work surface. Selecting a
record gives the saved text priority; returning restores the same exploration.

OWN-WORLD: Light neutral navigation and surfaces, graphite text, 14px minimum
interface text, one restrained blue accent. Existing business status colours
retain their meaning. Ordinary controls, thin separators and no decorative motion.

STORY: Start with the current authorized query, choose a country on the globe,
flat map or text list, then read a candidate. Clear only the intended dimension.
Applied query/URL and unapplied year inputs remain distinct. Slow and failed
reads retain the previous content with local status and recovery.

FIRST VIEWPORT: Desktop exploration/results use 3:2; textual country choices
precede the large globe. Scope and map provenance are disclosed. Reading uses
28:72 candidates/prose and hides, without detaching, exploration. A visible
return action restores it. At 1280×720 the country controls remain in view.
390/320 and native 200% use results-first responsive flow and explicit exploration.

FORM: The signature interaction is continuous country-to-query updating with a
stable canvas, camera and focus. Existing Three/ECharts engines update snapshots;
no added runtime. Scene changes release the hidden engine and restore its view.
Account/confirmed permission changes discard stale authorized content. Year brush
and time lens set a pending range before application. Browser history preserves
ordinary query semantics, and original archive/collection/favorite features remain.

FINISH: Developer evidence is the isolated public HTTP/real Chromium script
[scripts/check_minimal_research_browser.py](../../scripts/check_minimal_research_browser.py).
All fixture records are synthetic, the worker is off and the port is random.
The parent owns independent Standards/Spec and visual review. Developer checks
are not deployment or independent acceptance. No shipping raster assets.
