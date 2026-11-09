# Material discovery map

`material-world-110m.json` contains precomputed equirectangular SVG paths from
Natural Earth 1:110m country geometry, distributed by `@d3-maps/atlas` 1.0.0:

- [Topology package](https://esm.sh/@d3-maps/atlas@1.0.0/world/countries/countries-110m)
- [Natural Earth source repository](https://github.com/nvkelso/natural-earth-vector)
- [Public domain license](https://github.com/nvkelso/natural-earth-vector/blob/master/LICENSE.md)
- [Natural Earth terms](https://www.naturalearthdata.com/about/terms-of-use/)

Natural Earth map data is public domain. Its authors permit modification,
redistribution and use for personal, educational and commercial purposes.
License text was verified from the source repository on 2026-11-08, blob
`9dfbc3d55a4ab1dd758c253b2ee339888f632889`.
No map service, location API or third-party runtime is used by the browser.

The topology was taken from the authorized local discovery concept and converted
with `scripts/build_discovery_map.py`. Paths retain the source's generalized
boundaries; country lookup uses this platform's country identities. Shapes that
have no equivalent current identity remain background geometry. Small countries,
historical values, regions and unknown values remain available in the complete
textual distribution. The map serves discovery; it is not a boundary assertion.
