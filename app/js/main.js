// Looked Up: one page, vanilla JS. Data: data/app/ on the Hugging Face dataset (ADR 0022).
// URLs: #/today, #/day/YYYY-MM-DD, #/day/YYYY-MM-DD/event/Q123, #/lang/ja (history API, shareable).

import * as i18n from './i18n.js';
import { t, label, langNative, langName, within, compact, desc, pct } from './i18n.js';
import * as data from './data.js';
import * as viz from './viz.js';
import { compose, excessPhrase } from './briefing.js';
import { pickDay, pickHero, rank } from './select.js';

const $ = (id) => document.getElementById(id);
const PAGE = 12;
const TIER_RANK = { noticed: 0, international: 1, planetary: 2 };
const KICKER = { 24: 'hero.kicker', 48: 'hero.kicker_48h', 168: 'hero.kicker_week' };

const state = {
    days: [],          // [{iso, count, today?}]
    index: 0,
    payload: null,     // the selected day's file (or today.json)
    today: null,
    stats: null,
    hero: { event: null, hours: 24 },
    tier: 'noticed',
    shown: PAGE,
    selected: null,    // event id on the map
    lang: null,        // languages panel
};

const safeUrl = (u) => (typeof u === 'string' && u.startsWith('https://') ? u : '#');
const todayIso = () => state.today.generated_at.slice(0, 10);
const smooth = () => (matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth');

function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === 'class') e.className = v;
        else if (k === 'text') e.textContent = v;
        else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? '' : v);
    }
    e.append(...children.filter((c) => c != null && c !== ''));
    return e;
}

/* ---------------------------------------------------------------- URLs (F6) */

const dayHash = (d) => (d.today ? '#/today' : `#/day/${d.iso}`);
const eventHash = (d, ev) => `#/day/${d.iso}/event/${ev.qid}`;
const absolute = (hash) => `${location.origin}${location.pathname}${hash}`;

function setHash(hash, push = true) {
    if (location.hash === hash) return;
    history[push ? 'pushState' : 'replaceState'](null, '', hash);
    updateTitle();
}

async function copyLink(hash, button) {
    const url = absolute(hash);
    try {
        await navigator.clipboard.writeText(url);
    } catch {
        const tmp = el('input', { value: url });
        document.body.append(tmp);
        tmp.select();
        document.execCommand('copy');
        tmp.remove();
    }
    const old = button.textContent;
    button.textContent = t('ui.copied');
    setTimeout(() => { button.textContent = old; }, 1600);
}

function updateTitle() {
    const h = location.hash;
    let m;
    if ((m = h.match(/^#\/day\/(\d{4}-\d{2}-\d{2})\/event\/(Q\d+)$/))) {
        const ev = findByQid(m[2]);
        document.title = t('titles.event', { label: ev ? label(ev) : m[2], date: i18n.day(m[1]) });
    } else if ((m = h.match(/^#\/day\/(\d{4}-\d{2}-\d{2})$/))) {
        document.title = t('titles.day', { date: i18n.day(m[1]) });
    } else if ((m = h.match(/^#\/lang\/([a-z-]+)$/))) {
        document.title = t('titles.lang', { lang: langName(m[1]) });
    } else {
        document.title = h === '#/today' ? t('titles.today') : t('meta.title');
    }
}

function scrollTo(target) {
    target?.scrollIntoView({ behavior: smooth(), block: 'start' });
}

/** Apply the URL to the page: used on load and on back/forward. */
async function route({ scroll = true } = {}) {
    const h = location.hash;
    let m;
    if ((m = h.match(/^#\/day\/(\d{4}-\d{2}-\d{2})(?:\/event\/(Q\d+))?$/))) {
        let i = state.days.findIndex((d) => d.iso === m[1]);
        if (i < 0) i = state.days.length - 1;
        await selectDay(i, { qid: m[2], push: null });
        if (scroll) scrollTo(m[2] ? document.querySelector('.card.is-selected') || $('days') : $('days'));
    } else if ((m = h.match(/^#\/lang\/([a-z-]+)$/)) && (state.stats.languages || []).includes(m[1])) {
        state.lang = m[1];
        renderLanguages();
        if (scroll) scrollTo($('languages'));
    } else if (h === '#/today' || h === '' || h === '#') {
        if (state.index !== state.days.length - 1) await selectDay(state.days.length - 1, { push: null });
        if (h === '#/today' && scroll) scrollTo($('today'));
    }
    updateTitle();
}

/* ---------------------------------------------------------------- theme and language */

function initTheme() {
    $('theme').addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', next);
        try { localStorage.setItem('lookedup_theme', next); } catch { /* ignore */ }
        document.querySelector('meta[name="theme-color"]').setAttribute('content', next === 'light' ? '#ffffff' : '#08090b');
        if (state.selected) reshow(false);
    });
}

async function setLang(code) {
    await i18n.load(code);
    i18n.applyStatic();
    document.querySelectorAll('[data-ui-lang]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.uiLang === code)));
    renderAbout();
    viz.refreshLabels();
    if (state.today) { renderAll(false); updateTitle(); }
}

/* ---------------------------------------------------------------- pieces */

function sparkline(values) {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'spark');
    svg.setAttribute('viewBox', '0 0 47 20');
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', t('event.spark'));
    const vals = (values || []).filter((v) => v != null);
    const max = Math.max(1, ...vals);
    const line = document.createElementNS(NS, 'line');
    line.setAttribute('x1', 24); line.setAttribute('x2', 24); line.setAttribute('y1', 0); line.setAttribute('y2', 20);
    svg.append(line);
    let pts = [];
    const flush = () => {
        if (pts.length > 1) {
            const p = document.createElementNS(NS, 'polyline');
            p.setAttribute('points', pts.join(' '));
            svg.append(p);
        }
        pts = [];
    };
    (values || []).forEach((v, i) => {
        if (v == null) { flush(); return; }
        pts.push(`${i},${(19 - (v / max) * 18).toFixed(1)}`);
    });
    flush();
    return svg;
}

function wikiLinks(ev) {
    const ui = i18n.current();
    const links = [];
    const urls = ev.urls || {};
    if (urls[ev.lead]) links.push(el('a', { href: safeUrl(urls[ev.lead]), rel: 'noopener', hreflang: ev.lead, text: t('event.wiki', { lang: langName(ev.lead) }) }));
    if (ui !== ev.lead && urls[ui]) links.push(el('a', { href: safeUrl(urls[ui]), rel: 'noopener', hreflang: ui, text: t('event.wiki', { lang: langName(ui) }) }));
    return links;
}

function badge(tier) {
    return el('span', { class: `badge badge--${tier}`, title: t(`tier_help.${tier}`), text: t(`tier.${tier}`) });
}

/* ---------------------------------------------------------------- forecasts (Phase 4) */

const fmtAuc = (v) => new Intl.NumberFormat(i18n.current(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);

/** Forecast lines for an event still open (< 24 h old) at the time of the latest export; null otherwise. */
function forecastLine(ev) {
    const f = ev.forecast;
    if (!f || !state.today) return null;
    const now = Date.parse(state.today.generated_at);
    if (now - Date.parse(ev.start) >= 24 * 3600e3) return null;          // stale: no longer an open event
    const bits = [];
    const note = state.stats?.forecast ? t('forecast.note', { auc: fmtAuc(state.stats.forecast.auc_international_t1) }) : '';
    if (f.p_international != null && f.p_international >= 0.5) {
        bits.push(el('span', { class: 'badge badge--spreading', title: note, text: t('forecast.spreading') }));
        bits.push(el('span', { text: t('forecast.p_international', { p: pct(f.p_international) }) }));
    }
    if (f.p_planetary != null && f.p_planetary >= 0.3) bits.push(el('span', { text: t('forecast.p_planetary', { p: pct(f.p_planetary) }) }));
    if (f.fade_eta && Date.parse(f.fade_eta) > now) {
        bits.push(el('span', { class: 'fade', text: t('forecast.fade', { time: i18n.hour(f.fade_eta) }) }));
    }
    return bits.length ? el('p', { class: 'card__forecast' }, ...bits) : null;
}

function renderForecastNote(shown) {
    const note = $('forecast-note');
    const fc = state.stats?.forecast;
    note.hidden = !(shown && fc);
    if (fc) note.textContent = t('forecast.note', { auc: fmtAuc(fc.auc_international_t1) });
}

function renderForecastSection() {
    const fc = state.stats?.forecast;
    const sec = $('forecast');
    if (!fc) { sec.hidden = true; return; }
    sec.hidden = false;
    const stat = (value, text) => el('div', {}, el('dt', { text: value }), el('dd', { text }));
    $('forecast-stats').replaceChildren(
        stat(fmtAuc(fc.auc_international_t1), t('forecast.auc')),
        stat(`${new Intl.NumberFormat(i18n.current(), { maximumFractionDigits: 1 }).format(fc.lift_top10_international_t1)}×`, t('forecast.lift')),
        stat(pct(fc.m2_improvement_over_category_decay), t('forecast.gain')),
    );
    $('forecast-summary').textContent = t('forecast.summary', { auc: fmtAuc(fc.auc_international_t1) });
    // calibration chart: inline SVG from stats.json
    const NS = 'http://www.w3.org/2000/svg';
    const svg = $('forecast-chart');
    svg.setAttribute('aria-label', t('forecast.chart'));
    const L = 34, B = 206, W = 270, H = 190;
    const x = (v) => L + v * W;
    const y = (v) => B - v * H;
    const node = (tag, attrs, text) => {
        const n = document.createElementNS(NS, tag);
        for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
        if (text) n.textContent = text;
        return n;
    };
    const kids = [node('line', { class: 'axis', x1: L, y1: B, x2: L + W, y2: B }), node('line', { class: 'axis', x1: L, y1: B, x2: L, y2: B - H }),
        node('line', { class: 'diag', x1: x(0), y1: y(0), x2: x(1), y2: y(1) })];
    for (const v of [0, 0.5, 1]) {
        kids.push(node('text', { x: x(v), y: B + 14, 'text-anchor': 'middle' }, pct(v)));
        kids.push(node('text', { x: L - 6, y: y(v) + 3, 'text-anchor': 'end' }, pct(v)));
    }
    const pts = fc.calibration_curve || [];
    const maxN = Math.max(1, ...pts.map((p) => p.n));
    kids.push(node('polyline', { class: 'line', points: pts.map((p) => `${x(p.mean_p)},${y(p.observed)}`).join(' ') }));
    for (const p of pts) kids.push(node('circle', { class: 'pt', cx: x(p.mean_p), cy: y(p.observed), r: 2.5 + 6 * Math.sqrt(p.n / maxN) }));
    svg.replaceChildren(...kids);
}

function card(ev) {
    const day = state.days[state.index];
    const li = el('li', { class: `card${ev.id === state.selected ? ' is-selected' : ''}`, 'data-id': ev.id, 'data-qid': ev.qid });
    const title = el('h3', { class: 'card__title' },
        el('button', { type: 'button', 'aria-label': `${label(ev)}: ${t('event.show')}`, onclick: () => select(ev, { fromList: true, push: true }), text: label(ev) }));
    const copy = el('button', { type: 'button', class: 'linkbtn', text: t('ui.copy') });
    copy.addEventListener('click', () => copyLink(eventHash(day, ev), copy));
    li.append(
        title,
        sparkline(ev.spark),
        desc(ev) ? el('p', { class: 'card__desc', text: desc(ev) }) : null,
        el('p', { class: 'card__meta' },
            badge(ev.tier),
            el('span', { text: t('event.languages', { n: ev.breadth }) }),
            el('span', { text: t('event.lead', { lang: langNative(ev.lead) }) }),
            el('span', { text: t('event.first_spike', { time: i18n.hour(ev.start) }) }),
            el('span', { text: t(`event.category.${ev.category}`) })),
        forecastLine(ev),
        el('p', { class: 'card__links' }, ...wikiLinks(ev), copy),
    );
    return li;
}

/* ---------------------------------------------------------------- hero (F1, F5) */

async function chooseHero() {
    const now = Date.parse(state.today.generated_at);
    const base = new Date(`${todayIso()}T00:00:00Z`);
    const dayIso = (k) => new Date(base.getTime() - k * 86400e3).toISOString().slice(0, 10);
    const daysBack = async (n) => (await Promise.all(Array.from({ length: n }, (_, k) => data.dayFile(dayIso(k + 1)).catch(() => null))))
        .flatMap((p) => (p ? p.events : []));
    state.hero = await pickHero(async (hours) => {
        if (hours === 24) return state.today.events;
        return [...state.today.events, ...(await daysBack(hours === 48 ? 2 : 7))];
    }, now);
}

function heroCounter(n, lag, ev) {
    if (ev.id !== state.hero.event?.id) return;   // only the hero's own event drives its counter
    $('hero-counter').textContent = n === ev.langs.length
        ? t('hero.counter', { n: ev.breadth, within: within(ev.spread_h) })
        : t('hero.counter', { n, within: within(lag) });
}

function renderHero(animate) {
    const ev = state.hero.event;
    const lab = $('hero-label');
    lab.classList.remove('skeleton');
    $('hero-kicker').textContent = t(KICKER[state.hero.hours] || KICKER[24]);
    $('replay').hidden = !ev;
    const gen = state.today.generated_at;
    $('updated').textContent = t('ui.updated', { utc: i18n.dateTime(gen), local: i18n.localTime(gen) });
    $('hero-brief').textContent = compose(state.today, todayIso()).text;
    if (!ev) {
        lab.textContent = t('hero.empty');
        $('hero-desc').textContent = '';
        $('hero-counter').textContent = '';
        $('hero-sub').textContent = '';
        return;
    }
    const url = (ev.urls || {})[i18n.current()] || (ev.urls || {})[ev.lead];
    lab.replaceChildren(url ? el('a', { href: safeUrl(url), rel: 'noopener', text: label(ev) }) : label(ev));
    $('hero-desc').textContent = desc(ev);
    $('hero-counter').textContent = t('hero.counter', { n: ev.breadth, within: within(ev.spread_h) });
    $('hero-sub').textContent = `${t(`tier.${ev.tier}`)} · ${t('hero.led_by', { lang: langNative(ev.lead) })} · ${excessPhrase(ev.excess)}`;
    if (animate) select(ev, { animate: true });
}

/* ---------------------------------------------------------------- map selection */

function reshow(animate) {
    const ev = findEvent(state.selected);
    if (ev) viz.show(ev, { animate });
}

function allEvents(src) {
    return src ? [...(src.events || []), ...(src.single_language_events || [])] : [];
}

function findEvent(id) {
    for (const src of [state.payload, state.today]) {
        const ev = allEvents(src).find((e) => e.id === id);
        if (ev) return ev;
    }
    return state.hero.event?.id === id ? state.hero.event : null;
}

function findByQid(qid) {
    const evs = allEvents(state.payload).filter((e) => e.qid === qid);
    return rank(evs)[0] || evs[0] || null;
}

function select(ev, { fromList = false, animate = true, push = false } = {}) {
    state.selected = ev.id;
    document.querySelectorAll('.card').forEach((c) => c.classList.toggle('is-selected', c.dataset.id === ev.id));
    viz.show(ev, { animate });
    if (push) setHash(eventHash(state.days[state.index], ev));
    if (fromList) {
        const stage = $('viz');
        const r = stage.getBoundingClientRect();
        if (r.bottom < 60 || r.top > innerHeight) stage.scrollIntoView({ behavior: smooth(), block: 'center' });
    }
}

/* ---------------------------------------------------------------- timeline */

function renderBars() {
    const svg = $('bars');
    const n = state.days.length;
    const max = Math.max(1, ...state.days.map((d) => d.count));
    svg.setAttribute('viewBox', `0 0 ${n * 10} 56`);
    svg.replaceChildren(...state.days.map((d, i) => {
        const h = Math.max(1.5, (d.count / max) * 54);
        const r = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        r.setAttribute('x', i * 10 + 1); r.setAttribute('width', 8); r.setAttribute('y', 56 - h); r.setAttribute('height', h);
        if (i === state.index) r.setAttribute('class', 'is-on');
        return r;
    }));
}

function dayLabel(d) {
    return d.today ? t('timeline.today') : i18n.dayShort(d.iso);
}

/** push: true = new history entry, false = replace (slider drags), null = leave the URL alone (routing). */
async function selectDay(index, { qid = null, push = true } = {}) {
    state.index = Math.max(0, Math.min(state.days.length - 1, index));
    const d = state.days[state.index];
    $('day-slider').value = state.index;
    $('day-slider').setAttribute('aria-valuetext', dayLabel(d));
    $('day-out').textContent = dayLabel(d);
    renderBars();
    if (push !== null) setHash(dayHash(d), push);
    try {
        state.payload = d.today ? state.today : await data.dayFile(d.iso);
    } catch {
        state.payload = { events: [], single_language_events: [], summary: { events: 0 } };
    }
    if (state.days[state.index] !== d) return;  // a newer selection won
    state.shown = PAGE;
    const target = qid ? findByQid(qid) : null;
    if (target && target.class !== 'single_language') {
        const min = TIER_RANK[state.tier];
        if (TIER_RANK[target.tier] < min) setTier('noticed');
        const pos = state.payload.events.filter((e) => TIER_RANK[e.tier] >= TIER_RANK[state.tier]).findIndex((e) => e.id === target.id);
        state.shown = Math.max(PAGE, Math.ceil((pos + 1) / PAGE) * PAGE);
    }
    renderDay();
    if (target) select(target, { animate: true });
    else if (!d.today) { const ev = pickDay(state.payload.events); if (ev) select(ev, { animate: false }); }
    else if (state.hero.event) select(state.hero.event, { animate: false });
}

function renderDay() {
    const p = state.payload;
    const d = state.days[state.index];
    $('day-count').textContent = t('timeline.count', { n: p.summary?.events ?? p.events.length });
    $('day-brief').textContent = compose(p, d.today ? todayIso() : d.iso).text;
    renderCards();
    renderLanguages();
    renderBriefing();
}

function setTier(tier) {
    state.tier = tier;
    document.querySelectorAll('.filters [data-tier]').forEach((x) => x.setAttribute('aria-checked', String(x.dataset.tier === tier)));
}

function renderCards() {
    const min = TIER_RANK[state.tier];
    const list = (state.payload.events || []).filter((e) => TIER_RANK[e.tier] >= min);
    const ol = $('cards');
    ol.replaceChildren(...list.slice(0, state.shown).map(card));
    renderForecastNote(!!ol.querySelector('.card__forecast'));
    if (!list.length) ol.append(el('li', { class: 'empty', text: t('timeline.empty') }));
    $('more').hidden = list.length <= state.shown;
}

/* ---------------------------------------------------------------- languages */

function renderLanguages() {
    const p = state.payload;
    const langs = state.stats?.languages || [];
    const sel = $('lang-select');
    const names = langs.map((c) => [c, langNative(c)]).sort((a, b) => a[1].localeCompare(b[1], i18n.current()));
    if (!state.lang) state.lang = langs.includes(i18n.current()) ? i18n.current() : 'en';
    sel.replaceChildren(...names.map(([c, n]) => el('option', { value: c, selected: c === state.lang, text: n })));
    const L = state.lang;
    const mini = (ev, extra) => el('li', {},
        el('a', { href: safeUrl((ev.urls || {})[L] || (ev.urls || {})[ev.lead]), rel: 'noopener', text: (ev.labels || {})[L] || label(ev) }),
        el('small', { text: extra }));
    const top = (p.events || [])
        .map((e) => [e, e.langs.find((r) => r.lang === L)])
        .filter(([, r]) => r)
        .sort((a, b) => b[1].excess - a[1].excess)
        .slice(0, 5);
    $('lang-top').replaceChildren(...(top.length
        ? top.map(([e, r]) => mini(e, `${t(`tier.${e.tier}`)} · ${t('event.languages', { n: e.breadth })} · +${compact(r.excess)}`))
        : [el('li', { class: 'empty', text: t('languages.none') })]));
    const only = (p.single_language_events || []).filter((e) => e.lead === L).slice(0, 5);
    $('lang-only').replaceChildren(...(only.length
        ? only.map((e) => mini(e, `+${compact(e.excess)} · ${t('event.first_spike', { time: i18n.hour(e.start) })}`))
        : [el('li', { class: 'empty', text: t('languages.none') })]));
}

/* ---------------------------------------------------------------- briefing and about */

function renderBriefing() {
    const d = state.days[state.index];
    const iso = d.today ? todayIso() : d.iso;
    const b = compose(state.payload, iso);
    $('brief-date').textContent = d.today ? t('timeline.today') : i18n.day(iso);
    $('brief-text').textContent = b.text;
    $('brief-about').textContent = b.about;
    $('brief-facts').replaceChildren(...b.facts.map(([, text]) => el('li', { text })));
}

function renderAbout() {
    $('about-lines').replaceChildren(...t('about.lines').map((s) => el('li', { text: s })));
    $('about-limits').replaceChildren(...t('about.limits').map((s) => el('li', { text: s })));
    const tpl = t('about.links');
    const parts = tpl.split(/(\{dataset\}|\{repo\})/);
    $('about-links').replaceChildren(...parts.map((part) => {
        if (part === '{dataset}') return el('a', { href: 'https://huggingface.co/datasets/Sbaiiiiii/looked-up', text: t('about.dataset') });
        if (part === '{repo}') return el('a', { href: 'https://github.com/Sbaiii/looked-up', text: t('about.repo') });
        return part;
    }));
}

/* ---------------------------------------------------------------- boot */

function buildDays() {
    const days = (state.stats.timeline || [])
        .filter((r) => r.day < todayIso())
        .map((r) => ({ iso: r.day, count: (r.tiers.noticed || 0) + (r.tiers.international || 0) + (r.tiers.planetary || 0) }));
    days.push({ iso: todayIso(), count: state.today.summary?.events ?? state.today.events.length, today: true });
    state.days = days;
    $('day-slider').max = days.length - 1;
}

function renderAll(animate) {
    renderHero(animate);
    renderForecastSection();
    renderBars();
    $('day-slider').value = state.index;
    $('day-out').textContent = dayLabel(state.days[state.index]);
    $('day-slider').setAttribute('aria-valuetext', dayLabel(state.days[state.index]));
    renderDay();
}

function wire() {
    document.querySelectorAll('[data-ui-lang]').forEach((b) => b.addEventListener('click', () => setLang(b.dataset.uiLang)));
    $('day-slider').addEventListener('input', (e) => selectDay(Number(e.target.value), { push: false }));
    $('day-slider').addEventListener('change', () => setHash(dayHash(state.days[state.index]), true));
    $('prev-day').addEventListener('click', () => selectDay(state.index - 1));
    $('next-day').addEventListener('click', () => selectDay(state.index + 1));
    $('bars').addEventListener('click', (e) => {
        const r = $('bars').getBoundingClientRect();
        selectDay(Math.floor(((e.clientX - r.left) / r.width) * state.days.length));
    });
    $('copy-day').addEventListener('click', (e) => copyLink(dayHash(state.days[state.index]) === '#/today'
        ? `#/day/${todayIso()}` : dayHash(state.days[state.index]), e.currentTarget));
    $('more').addEventListener('click', () => { state.shown += PAGE; renderCards(); });
    $('replay').addEventListener('click', () => { if (state.hero.event) select(state.hero.event, { animate: true }); });
    $('lang-select').addEventListener('change', (e) => { state.lang = e.target.value; renderLanguages(); setHash(`#/lang/${state.lang}`); });
    document.querySelector('.filters').addEventListener('click', (e) => {
        const b = e.target.closest('[data-tier]');
        if (!b) return;
        setTier(b.dataset.tier);
        state.shown = PAGE;
        renderCards();
    });
    addEventListener('popstate', () => { if (state.today) route({ scroll: true }); });
}

async function boot() {
    initTheme();
    await setLang(i18n.initialLang());
    wire();
    const vizReady = viz.init($('viz'), { counter: heroCounter }).catch(() => {});
    try {
        [state.today, state.stats] = await Promise.all([data.today(), data.stats()]);
    } catch {
        $('hero-label').classList.remove('skeleton');
        $('hero-label').textContent = t('ui.error');
        return;
    }
    buildDays();
    state.index = state.days.length - 1;
    state.payload = state.today;
    await chooseHero();
    renderAll(false);
    await vizReady;
    const deepLink = /^#\/(day|lang)\//.test(location.hash);
    if (deepLink) await route({ scroll: true });
    else { renderHero(true); updateTitle(); if (location.hash === '#/today') scrollTo($('today')); }
    document.documentElement.dataset.ready = 'true';
}

boot();
