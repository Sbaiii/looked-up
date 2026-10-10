// The map: countries coloured by attention in their languages for one event (ADR 0023: languages,
// not countries; a country takes the max over its languages). Flat SVG first; the WebGL globe is
// loaded lazily on capable devices after the first interaction, or on request.

import { createMap2D } from './map2d.js';
import { t, label, langNative, within } from './i18n.js';
import { scale, TICKS, tickLabel } from './scale.js';

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

async function loadGeo() {
    const [world, lg] = await Promise.all([
        fetch('data/world-2d.json').then((r) => r.json()),
        fetch('data/language_geo.json').then((r) => r.json()),
    ]);
    const langOf = new Map();                                                  // country -> [languages]
    for (const [code, keys] of Object.entries(lg.languages)) {
        for (const k of keys) langOf.set(k, [...(langOf.get(k) || []), code]);
    }
    const centroids = new Map(world.countries.map((c) => [c.k, c.c]));
    const anchors = {};
    for (const [code, key] of Object.entries(lg.anchors)) if (centroids.has(key)) anchors[code] = centroids.get(key);
    return { world, langOf, languages: lg.languages, anchors, features: null };
}

/** GeoJSON countries for the globe, converted only when the globe is requested. */
async function globeFeatures() {
    if (geo.features) return geo.features;
    const [topo] = await Promise.all([
        fetch('data/countries-110m.json').then((r) => r.json()),
        window.topojson ? null : loadScript('vendor/topojson-client.min.js'),
    ]);
    const { featureKey } = await import('./projection.js');
    geo.features = window.topojson.feature(topo, topo.objects.countries).features
        .filter((f) => f.id !== '010')
        .map((f) => ({ ...f, key: featureKey(f) }));
    return geo.features;
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

/** Spread steps in lag order. Colour = per-language peak surprise on the absolute scale (ADR 0025); each step
 * colours only countries whose max rises (multi-language countries take the max, ADR 0023). */
export function steps(ev, { animate }) {
    // the lead language always comes first (arcs start there), then lag order
    const rows = [...ev.langs].sort((a, b) => (b.lang === ev.lead) - (a.lang === ev.lead) || a.lag - b.lag || a.lang.localeCompare(b.lang));
    const best = new Map();
    const maxLag = Math.max(1, ...rows.map((r) => r.lag));
    return rows.map((r, i) => {
        const v = scale(r.surprise);
        const countries = new Map();
        for (const key of geo.languages[r.lang] || []) {
            if (!best.has(key) || best.get(key) < v) { best.set(key, v); countries.set(key, ramp(Math.max(v, 0.02))); }
        }
        // at least 140 ms between languages, so a replay is visible even when every language spiked in one hour
        const delay = animate ? 300 + Math.max(i * 140, (r.lag / maxLag) * 2400) : 0;
        return { lang: r.lang, lag: r.lag, delay, countries, anchor: geo.anchors[r.lang], value: v };
    });
}

function renderTicks() {
    const box = document.getElementById('legend-ticks');
    if (!box) return;
    box.replaceChildren(...TICKS.map((v) => {
        const s = document.createElement('span');
        s.style.left = `${scale(v) * 100}%`;
        s.textContent = tickLabel(v);
        return s;
    }));
}

function describe(ev) {
    stage.setAttribute('aria-label', t('map.label', { label: label(ev) }));
    const now = document.getElementById('viz-now');
    if (now) now.textContent = `${label(ev)} · ${t('event.languages', { n: ev.breadth })} · ${t('hero.led_by', { lang: langNative(ev.lead) })}`;
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

let globeLoading = null;
async function useGlobe() {
    if (mode === 'globe') return;
    globeLoading ||= Promise.all([import('./globe.js'), window.Globe ? null : loadScript('vendor/globe.gl.min.js'), globeFeatures()])
        .catch((e) => { globeLoading = null; throw e; });
    const [{ createGlobe }] = await globeLoading;
    if (mode === 'globe') return;
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
    renderTicks();
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
