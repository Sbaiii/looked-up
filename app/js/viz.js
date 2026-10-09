// The map: countries coloured by attention in their languages for one event (ADR 0023: languages,
// not countries; a country takes the max over its languages). Flat SVG first; the WebGL globe is
// loaded lazily on capable devices after the first interaction, or on request.

import { createMap2D } from './map2d.js';
import { t, label, langName, within } from './i18n.js';

let geo = null;
let renderer = null;
let mode = '2d';
let currentEvent = null;
let stage;
let onCounter = () => {};

function loadScript(src) {
    return new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src; s.async = true; s.onload = resolve; s.onerror = reject;
        document.head.append(s);
    });
}

export function webglOK() {
    try {
        const c = document.createElement('canvas');
        return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl')));
    } catch { return false; }
}

export function capable() {
    const conn = navigator.connection || {};
    const lowEnd = (navigator.deviceMemory && navigator.deviceMemory < 4) || (navigator.hardwareConcurrency && navigator.hardwareConcurrency < 4);
    return webglOK() && !lowEnd && !conn.saveData;
}

const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

function largestRing(geom) {
    const polys = geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates;
    let best = null;
    let bestArea = -1;
    for (const poly of polys) {
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
    return best;
}

async function loadGeo() {
    const [topo, lg] = await Promise.all([
        fetch('data/countries-110m.json').then((r) => r.json()),
        fetch('data/language_geo.json').then((r) => r.json()),
        window.topojson ? null : loadScript('vendor/topojson-client.min.js'),
    ]);
    const fc = window.topojson.feature(topo, topo.objects.countries);
    const features = fc.features
        .filter((f) => f.id !== '010')                                        // Antarctica
        .map((f) => ({ ...f, key: f.id ?? (f.properties.name === 'Kosovo' ? 'XKS' : f.properties.name) }));
    const langOf = new Map();                                                  // country -> [languages]
    for (const [code, keys] of Object.entries(lg.languages)) {
        for (const k of keys) langOf.set(k, [...(langOf.get(k) || []), code]);
    }
    const byKey = new Map(features.map((f) => [f.key, f]));
    const anchors = {};
    for (const [code, key] of Object.entries(lg.anchors)) {
        const f = byKey.get(key);
        if (f) anchors[code] = largestRing(f.geometry);
    }
    return { features, langOf, languages: lg.languages, anchors };
}

function hexToRgb(h) {
    const v = h.trim().replace('#', '');
    return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16));
}

function ramp(x) {
    const cs = getComputedStyle(document.documentElement);
    const stops = ['--ramp-0', '--ramp-1', '--ramp-2'].map((v) => hexToRgb(cs.getPropertyValue(v)));
    const seg = x < 0.5 ? 0 : 1;
    const f = x < 0.5 ? x * 2 : (x - 0.5) * 2;
    const c = stops[seg].map((a, i) => Math.round(a + (stops[seg + 1][i] - a) * f));
    return `rgb(${c.join(',')})`;
}

/** Spread steps in lag order; each step colours only countries whose max rises (multi-language countries). */
export function steps(ev, { animate }) {
    const rows = [...ev.langs].sort((a, b) => a.lag - b.lag || a.lang.localeCompare(b.lang));
    const logs = rows.map((r) => Math.log10(1 + Math.max(r.excess, 0)));
    const lo = Math.min(...logs);
    const hi = Math.max(...logs);
    const best = new Map();
    const maxLag = Math.max(1, ...rows.map((r) => r.lag));
    return rows.map((r, i) => {
        const v = hi > lo ? 0.2 + (0.8 * (logs[i] - lo)) / (hi - lo) : 1;
        const countries = new Map();
        for (const key of geo.languages[r.lang] || []) {
            if (!best.has(key) || best.get(key) < v) { best.set(key, v); countries.set(key, ramp(v)); }
        }
        const delay = animate ? (i === 0 ? 150 : 400 + (rows.length > 1 ? (r.lag / maxLag) * 2400 : 0) + i * 60) : 0;
        return { lang: r.lang, lag: r.lag, delay, countries, anchor: geo.anchors[r.lang], value: v };
    });
}

function describe(ev) {
    stage.setAttribute('aria-label', t('map.label', { label: label(ev) }));
    const now = document.getElementById('viz-now');
    if (now) now.textContent = `${label(ev)} · ${t('event.languages', { n: ev.breadth })} · ${t('hero.led_by', { lang: langName(ev.lead) })}`;
}

export function show(ev, { animate = true } = {}) {
    currentEvent = ev;
    if (!geo || !renderer || !ev) return;
    const anim = animate && !reducedMotion();
    const st = steps(ev, { animate: anim });
    let shown = 0;
    st.forEach((s) => { s.onShow = () => { shown += 1; onCounter(shown, s.lag, ev); }; });
    renderer.play(st, { animate: anim });
    describe(ev);
}

async function useGlobe() {
    if (mode === 'globe') return;
    const { createGlobe } = await import('./globe.js');
    if (!window.Globe) await loadScript('vendor/globe.gl.min.js');
    renderer?.destroy();
    stage.classList.add('is-globe');
    renderer = createGlobe(stage, geo);
    mode = 'globe';
    if (currentEvent) show(currentEvent, { animate: false });
}

function useFlat() {
    renderer?.destroy();
    stage.classList.remove('is-globe');
    renderer = createMap2D(stage, geo);
    mode = '2d';
    if (currentEvent) show(currentEvent, { animate: false });
}

function savePref(m) { try { localStorage.setItem('lookedup_viz', m); } catch { /* ignore */ } }

export function refreshLabels() {
    const btn = document.getElementById('viz-mode');
    if (btn) btn.textContent = t(mode === 'globe' ? 'map.flat' : 'map.globe');
    if (currentEvent) describe(currentEvent);
    else if (stage) stage.setAttribute('aria-label', t('map.idle'));
}

export async function init(el, { counter } = {}) {
    stage = el;
    onCounter = counter || onCounter;
    geo = await loadGeo();
    renderer = createMap2D(stage, geo);
    const btn = document.getElementById('viz-mode');
    if (!capable()) { refreshLabels(); return; }                     // low-end or no WebGL: flat map only
    btn.hidden = false;
    btn.addEventListener('click', async () => {
        if (mode === 'globe') { useFlat(); savePref('2d'); } else { await useGlobe(); savePref('globe'); }
        refreshLabels();
    });
    let pref = null;
    try { pref = localStorage.getItem('lookedup_viz'); } catch { /* ignore */ }
    if (pref !== '2d') {
        // lazy: the 1.8 MB globe bundle loads only once the visitor interacts with the page
        const upgrade = () => {
            ['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach((e) => removeEventListener(e, upgrade));
            const go = () => useGlobe().then(refreshLabels).catch(() => {});
            ('requestIdleCallback' in window) ? requestIdleCallback(go, { timeout: 1500 }) : setTimeout(go, 300);
        };
        ['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach((e) => addEventListener(e, upgrade, { once: true, passive: true }));
    }
    refreshLabels();
}

export { within };
