// Flat SVG world map: the default view and the fallback without WebGL. Country paths are pre-projected
// (app/data/world-2d.json, built by scripts/vendor.mjs); only the arcs are projected here.

import { project, W, H } from './projection.js';

const NS = 'http://www.w3.org/2000/svg';

export function createMap2D(stage, geo) {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.setAttribute('aria-hidden', 'true');
    const gLand = document.createElementNS(NS, 'g');
    const gArcs = document.createElementNS(NS, 'g');
    svg.append(gLand, gArcs);
    const paths = new Map();
    for (const c of geo.world.countries) {
        const p = document.createElementNS(NS, 'path');
        p.setAttribute('d', c.d);
        p.setAttribute('class', `country${geo.langOf.has(c.k) ? ' is-lang' : ''}`);
        paths.set(c.k, p);
        gLand.append(p);
    }
    stage.replaceChildren(svg);
    let timers = [];

    function clear() {
        timers.forEach(clearTimeout);
        timers = [];
        gArcs.replaceChildren();
        svg.classList.add('is-reset');                // reset colours at once, so a replay starts from a blank map
        for (const p of paths.values()) p.style.fill = '';
        requestAnimationFrame(() => requestAnimationFrame(() => svg.classList.remove('is-reset')));
    }

    function arc(from, to) {
        const [x1, y1] = project(from);
        const [x2, y2] = project(to);
        const lift = Math.min(160, Math.hypot(x2 - x1, y2 - y1) * 0.35);
        const path = document.createElementNS(NS, 'path');
        path.setAttribute('d', `M${x1},${y1} Q${(x1 + x2) / 2},${(y1 + y2) / 2 - lift} ${x2},${y2}`);
        path.setAttribute('class', 'arc');
        return path;
    }

    function dot(lonlat, r = 3.5) {
        const [x, y] = project(lonlat);
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
