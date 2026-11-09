"""Precompute local SVG paths from the documented Natural Earth 110m topology.

Usage: python scripts/build_discovery_map.py path/to/topology.json
The browser needs neither a map service nor a projection/topology dependency.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_app.countries import key, ENTRIES


def build(topology):
    scale, translate = topology['transform']['scale'], topology['transform']['translate']
    arcs = []
    for arc in topology['arcs']:
        x = y = 0
        points = []
        for dx, dy in arc:
            x, y = x + dx, y + dy
            points.append(((x*scale[0]+translate[0]+180)*2.5, (90-y*scale[1]-translate[1])*2.5))
        arcs.append(points)
    # Natural Earth identifiers that differ from the registered CLDR spellings.
    overrides = {'SAH':'EH', 'COD':'CD', 'COG':'CG', 'PSX':'PS', 'CYN':None,
                 'SOL':None, 'KOS':'XK', 'SDS':'SS', 'SWZ':'SZ', 'TWN':'TW',
                 'FLK':'FK', 'ATF':'TF', 'CIV':'CI', 'BIH':'BA', 'TTO':'TT'}
    result = []
    for geometry in topology['objects']['features']['geometries']:
        properties = geometry['properties']
        code = overrides.get(properties['id'], key(properties.get('name_long', properties['name'])))
        if code not in ENTRIES:
            code = key(properties['name'])
        if code not in ENTRIES or len(code) != 2:
            code = None
        polygons = geometry['arcs'] if geometry['type'] == 'MultiPolygon' else [geometry['arcs']]
        paths, bounds = [], []
        for polygon in polygons:
            for ring in polygon:
                points = []
                for index in ring:
                    arc = arcs[index] if index >= 0 else list(reversed(arcs[~index]))
                    points.extend(arc if not points else arc[1:])
                paths.append('M'+'L'.join(f'{x:.2f},{y:.2f}' for x,y in points)+'Z')
                bounds.append([round(min(x for x,y in points),2), round(min(y for x,y in points),2),
                               round(max(x for x,y in points),2), round(max(y for x,y in points),2)])
        result.append({'country':code, 'name':ENTRIES[code]['label'] if code else properties['name_long'], 'path':''.join(paths), 'bounds':bounds})
    return {'source':'Natural Earth 1:110m / @d3-maps/atlas 1.0.0', 'viewBox':'0 0 900 450', 'features':result}


if __name__ == '__main__':
    output = Path(__file__).resolve().parents[1]/'static/geo/material-world-110m.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))), ensure_ascii=False, separators=(',',':')), encoding='utf-8')
