// Flat-map projection, shared by the browser (arcs) and scripts/vendor.mjs (pre-projected country paths).
// Equirectangular, Antarctica cropped.

export const W = 1000;
export const LAT_TOP = 84;
export const LAT_BOTTOM = -57;
export const H = Math.round((W * (LAT_TOP - LAT_BOTTOM)) / 360);

export const project = ([lon, lat]) => [((lon + 180) / 360) * W,
    ((LAT_TOP - Math.max(LAT_BOTTOM, Math.min(LAT_TOP, lat))) / (LAT_TOP - LAT_BOTTOM)) * H];

export function polygons(geom) {
    if (!geom) return [];
    return geom.type === 'Polygon' ? [geom.coordinates] : geom.type === 'MultiPolygon' ? geom.coordinates : [];
}

export function ringPath(ring) {
    // Rings crossing the antimeridian (Russia, Fiji) are unwrapped to the east: their far part is
    // drawn just past the right edge instead of as a stripe across the whole map.
    let wraps = false;
    for (let i = 1; i < ring.length; i++) if (Math.abs(ring[i][0] - ring[i - 1][0]) > 180) { wraps = true; break; }
    let d = '';
    for (let i = 0; i < ring.length; i++) {
        const [lon, lat] = ring[i];
        const [x, y] = project([wraps && lon < 0 ? lon + 360 : lon, lat]);
        d += `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
    }
    return `${d}Z`;
}

export const geomPath = (geom) => polygons(geom).map((poly) => poly.map(ringPath).join('')).join('');

/** [lon, lat] centroid of the largest outer ring. */
export function centroid(geom) {
    let best = null;
    let bestArea = -1;
    for (const poly of polygons(geom)) {
        const ring = poly[0];
        let a = 0;
        let cx = 0;
        let cy = 0;
        for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
            const f = ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
            a += f; cx += (ring[j][0] + ring[i][0]) * f; cy += (ring[j][1] + ring[i][1]) * f;
        }
        if (Math.abs(a) > bestArea) { bestArea = Math.abs(a); best = a ? [cx / (3 * a), cy / (3 * a)] : ring[0]; }
    }
    return best && best.map((v) => Math.round(v * 100) / 100);
}

/** Feature key: ISO numeric id; Kosovo has none in world-atlas. */
export const featureKey = (f) => f.id ?? (f.properties.name === 'Kosovo' ? 'XKS' : f.properties.name);
