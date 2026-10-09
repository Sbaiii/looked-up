// Flat SVG world map: the default view and the fallback without WebGL. Equirectangular, Antarctica cropped.

const W = 1000;
const LAT_TOP = 84;
const LAT_BOTTOM = -57;
const H = Math.round((W * (LAT_TOP - LAT_BOTTOM)) / 360);
const NS = 'http://www.w3.org/2000/svg';

const project = ([lon, lat]) => [((lon + 180) / 360) * W, ((LAT_TOP - Math.max(LAT_BOTTOM, Math.min(LAT_TOP, lat))) / (LAT_TOP - LAT_BOTTOM)) * H];

function ringPath(ring) {
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

function polygons(geom) {
    if (!geom) return [];
    return geom.type === 'Polygon' ? [geom.coordinates] : geom.type === 'MultiPolygon' ? geom.coordinates : [];
}

export function createMap2D(stage, geo) {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.setAttribute('aria-hidden', 'true');
    const gLand = document.createElementNS(NS, 'g');
    const gArcs = document.createElementNS(NS, 'g');
    svg.append(gLand, gArcs);
    const paths = new Map();
    for (const f of geo.features) {
        const p = document.createElementNS(NS, 'path');
        p.setAttribute('d', polygons(f.geometry).map((poly) => poly.map(ringPath).join('')).join(''));
        p.setAttribute('class', `country${geo.langOf.has(f.key) ? ' is-lang' : ''}`);
        paths.set(f.key, p);
        gLand.append(p);
    }
    stage.replaceChildren(svg);
    let timers = [];

    function clear() {
        timers.forEach(clearTimeout);
        timers = [];
        gArcs.replaceChildren();
        for (const p of paths.values()) p.style.fill = '';
    }

    function arc(from, to) {
        const [x1, y1] = project(from);
        const [x2, y2] = project(to);
        const dx = x2 - x1;
        const dy = y2 - y1;
        const lift = Math.min(160, Math.hypot(dx, dy) * 0.35);
        const path = document.createElementNS(NS, 'path');
        path.setAttribute('d', `M${x1},${y1} Q${(x1 + x2) / 2},${(y1 + y2) / 2 - lift} ${x2},${y2}`);
        path.setAttribute('class', 'arc');
        return path;
    }

    function dot([lon, lat], r = 3.5) {
        const [x, y] = project([lon, lat]);
        const c = document.createElementNS(NS, 'circle');
        c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', r); c.setAttribute('class', 'anchor');
        return c;
    }

    /** steps: [{lang, delay, countries: Map(key -> colour), anchor: [lon, lat]}], first step = lead language. */
    function play(steps, { animate }) {
        clear();
        const lead = steps[0];
        steps.forEach((s, i) => {
            const show = () => {
                for (const [key, colour] of s.countries) {
                    const p = paths.get(key);
                    if (p) p.style.fill = colour;
                }
                if (s.anchor && lead.anchor) {
                    if (i === 0) {
                        gArcs.append(dot(s.anchor, 5));
                    } else {
                        const a = arc(lead.anchor, s.anchor);
                        gArcs.append(a, dot(s.anchor));
                        if (animate && a.getTotalLength) {
                            const len = a.getTotalLength();
                            a.style.strokeDasharray = `${len}`;
                            a.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }],
                                { duration: 700, easing: 'ease-out', fill: 'forwards' });
                        }
                    }
                }
                s.onShow?.();
            };
            if (animate) timers.push(setTimeout(show, s.delay)); else show();
        });
    }

    return { play, clear, destroy: () => { clear(); svg.remove(); } };
}
