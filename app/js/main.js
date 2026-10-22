// Looked Up: one page, vanilla JS. Data: data/app/ on the Hugging Face dataset (ADR 0022).
// URLs: #/today, #/day/YYYY-MM-DD, #/day/YYYY-MM-DD/event/Q123, #/lang/ja (history API, shareable).

import * as i18n from './i18n.js';
import { t, label, langNative, langName, within, compact, desc, pct } from './i18n.js';
import * as data from './data.js';
import * as viz from './viz.js';
import { compose, excessPhrase } from './briefing.js';
import { pickDay, pickHero, rank } from './select.js';
import { renderLive, startLive } from './live.js';

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
    query: '',         // card search, folded (see fold)
    sort: 'widest',    // card order, a key of SORTS
};

/** Card orders. Day files list events widest first, so 'widest' keeps the file order; ties keep it too (stable sort). */
const SORTS = {
    widest: null,
    views: (a, b) => b.excess - a.excess,
    fastest: (a, b) => a.spread_h - b.spread_h || b.breadth - a.breadth,
    latest: (a, b) => Date.parse(b.start) - Date.parse(a.start),
    earliest: (a, b) => Date.parse(a.start) - Date.parse(b.start),
};

const safeUrl = (u) => (typeof u === 'string' && u.startsWith('https://') ? u : '#');
const todayIso = () => state.today.generated_at.slice(0, 10);
const smooth = () => (matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth');

/** A new element: ``class``, ``text`` and on* handlers are handled specially, other attributes set as given; children appended. */
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
/** The day on screen: an archive day (older than the slider's window) or the slider's day. */
const shownDay = () => state.archive || state.days[state.index];
const eventHash = (d, ev) => `#/day/${d.iso}/event/${ev.qid}`;
const absolute = (hash) => `${location.origin}${location.pathname}${hash}`;

/** Change the URL hash without scrolling, as a new history entry or in place, and retitle the page. */
function setHash(hash, push = true) {
    if (location.hash === hash) return;
    history[push ? 'pushState' : 'replaceState'](null, '', hash);
    updateTitle();
}

/** Copy the absolute URL for ``hash``, with a fallback for browsers without the clipboard API. */
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

/** The document title for the current URL: an event, a day, a language panel or the front page. */
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

/** Scroll a section into view, smoothly unless motion is reduced. */
function scrollTo(target) {
    target?.scrollIntoView({ behavior: smooth(), block: 'start' });
}

/** Apply the URL to the page: used on load and on back/forward. */
async function route({ scroll = true } = {}) {
    const h = location.hash;
    let m;
    if ((m = h.match(/^#\/day\/(\d{4}-\d{2}-\d{2})(?:\/event\/(Q\d+))?$/))) {
        const i = state.days.findIndex((d) => d.iso === m[1]);
        if (i >= 0) await selectDay(i, { qid: m[2], push: null });
        else if (m[1] < state.days[0].iso) await selectArchive(m[1], { qid: m[2] });
        else await selectDay(state.days.length - 1, { push: null });
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

/** Wire the theme button: toggle light and dark, remember it, update theme-color and redraw the map colours. */
function initTheme() {
    $('theme').addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', next);
        try { localStorage.setItem('lookedup_theme', next); } catch { /* ignore */ }
        document.querySelector('meta[name="theme-color"]').setAttribute('content', next === 'light' ? '#ffffff' : '#08090b');
        if (state.selected) reshow(false);
    });
}

/** Switch the interface language and redraw everything that holds text. */
async function setLang(code) {
    await i18n.load(code);
    i18n.applyStatic();
    document.querySelectorAll('[data-ui-lang]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.uiLang === code)));
    renderAbout();
    renderLive();
    viz.refreshLabels();
    if (state.today) { renderAll(false); updateTitle(); }
}

/* ---------------------------------------------------------------- pieces */

/** An event's views over 48 hours with its start marked in the middle; hours not known yet break the line. */
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

/** Links to the article in the lead language and, when different, in the interface language. */
function wikiLinks(ev) {
    const ui = i18n.current();
    const links = [];
    const urls = ev.urls || {};
    if (urls[ev.lead]) links.push(el('a', { href: safeUrl(urls[ev.lead]), rel: 'noopener', hreflang: ev.lead, text: t('event.wiki', { lang: langName(ev.lead) }) }));
    if (ui !== ev.lead && urls[ui]) links.push(el('a', { href: safeUrl(urls[ui]), rel: 'noopener', hreflang: ui, text: t('event.wiki', { lang: langName(ui) }) }));
    return links;
}

/** The tier badge, with the tier explained in its title. */
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

/** Top 3 open events by p_international, whatever the threshold, labelled as a forecast (Phase 5). */
function renderNext() {
    const now = Date.parse(state.today.generated_at);
    const open = (state.today.events || []).filter((e) => e.forecast?.p_international != null
        && now - Date.parse(e.start) < 24 * 3600e3)
        .sort((a, b) => b.forecast.p_international - a.forecast.p_international).slice(0, 3);
    $('next').hidden = !open.length;
    $('next-list').replaceChildren(...open.map((e) => el('li', {}, el('strong', { text: label(e) }), ' ',
        el('span', { text: t('next.item', { p: pct(e.forecast.p_international) }) }))));
}

/** Show the forecast note under the open events only when a forecast is shown, with the backtested AUC. */
function renderForecastNote(shown) {
    const note = $('forecast-note');
    const fc = state.stats?.forecast;
    note.hidden = !(shown && fc);
    if (fc) note.textContent = t('forecast.note', { auc: fmtAuc(fc.auc_international_t1) });
}

/** FIG. 05: the backtest numbers, the calibration chart and the summary; hidden without forecast data. */
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

/** One event card: title button, description, badges and facts, sparkline, Wikipedia links and a copy-link button. */
function card(ev) {
    const day = shownDay();
    const li = el('li', { class: `card${ev.id === state.selected ? ' is-selected' : ''}`, 'data-id': ev.id, 'data-qid': ev.qid });
    const title = el('h3', { class: 'card__title' },
        el('button', { type: 'button', 'aria-label': `${label(ev)}: ${t('event.show')}`, onclick: () => select(ev, { fromList: true, push: true }), text: label(ev) }));
    const copy = el('button', { type: 'button', class: 'linkbtn', text: t('ui.copy') });
    copy.addEventListener('click', () => copyLink(eventHash(day, ev), copy));
    li.append(...[
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
    ].filter((c) => c != null));   // append(null) would print "null" on cards without a description or forecast
    return li;
}

/* ---------------------------------------------------------------- hero (F1, F5) */

/** Pick the hero from the last 24 h, widening to 48 h and then 7 days on quiet days (ADR 0024). */
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

/** Count languages up under the hero as the spread plays, ending on the event's full breadth. */
function heroCounter(n, lag, ev) {
    if (ev.id !== state.hero.event?.id) return;   // only the hero's own event drives its counter
    $('hero-counter').textContent = n === ev.langs.length
        ? t('hero.counter', { n: ev.breadth, within: within(ev.spread_h) })
        : t('hero.counter', { n, within: within(lag) });
}

/** Draw the hero: kicker, label, description, counter, the update time and the briefing sentence. */
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

/** Replay the selected event on the map, for example after a theme change. */
function reshow(animate) {
    const ev = findEvent(state.selected);
    if (ev) viz.show(ev, { animate });
}

/** Multi-language and single-language events of a payload, in one list. */
function allEvents(src) {
    return src ? [...(src.events || []), ...(src.single_language_events || [])] : [];
}

/** An event by id in the shown day, then today, then the hero. */
function findEvent(id) {
    for (const src of [state.payload, state.today]) {
        const ev = allEvents(src).find((e) => e.id === id);
        if (ev) return ev;
    }
    return state.hero.event?.id === id ? state.hero.event : null;
}

/** The strongest event of a QID on the shown day, for /event/Q... links. */
function findByQid(qid) {
    const evs = allEvents(state.payload).filter((e) => e.qid === qid);
    return rank(evs)[0] || evs[0] || null;
}

/** Select an event: highlight its card, play it on the map, optionally update the URL and bring the map into view. */
function select(ev, { fromList = false, animate = true, push = false } = {}) {
    state.selected = ev.id;
    document.querySelectorAll('.card').forEach((c) => c.classList.toggle('is-selected', c.dataset.id === ev.id));
    viz.show(ev, { animate });
    if (push) setHash(eventHash(shownDay(), ev));
    if (fromList) {
        const stage = $('viz');
        const r = stage.getBoundingClientRect();
        if (r.bottom < 60 || r.top > innerHeight) stage.scrollIntoView({ behavior: smooth(), block: 'center' });
    }
}

/* ---------------------------------------------------------------- timeline */

/** The day bars above the slider, one per day, the shown day highlighted. */
function renderBars() {
    const svg = $('bars');
    const n = state.days.length;
    const max = Math.max(1, ...state.days.map((d) => d.count));
    svg.setAttribute('viewBox', `0 0 ${n * 10} 56`);
    svg.replaceChildren(...state.days.map((d, i) => {
        const h = Math.max(1.5, (d.count / max) * 54);
        const r = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        r.setAttribute('x', i * 10 + 1); r.setAttribute('width', 8); r.setAttribute('y', 56 - h); r.setAttribute('height', h);
        if (i === state.index && !state.archive) r.setAttribute('class', 'is-on');
        return r;
    }));
}

/** Short label of a day for the slider: "Today" or a localised date. */
function dayLabel(d) {
    return d.today ? t('timeline.today') : i18n.dayShort(d.iso);
}

/** push: true = new history entry, false = replace (slider drags), null = leave the URL alone (routing). */
async function selectDay(index, { qid = null, push = true } = {}) {
    state.archive = null;
    state.index = Math.max(0, Math.min(state.days.length - 1, index));
    const d = state.days[state.index];
    $('day-slider').value = state.index;
    if (push !== null) setHash(dayHash(d), push);
    let payload;
    try {
        payload = d.today ? state.today : await data.dayFile(d.iso);
    } catch {
        payload = { events: [], single_language_events: [], summary: { events: 0 } };
    }
    if (shownDay() !== d) return;  // a newer selection won
    showDay(d, payload, qid);
}

/**
 * A day older than the slider's 90 days, named by a URL. Day files stay on the Hub, so it is fetched directly and
 * shown with an "archive" tag; the slider keeps its window. A day with no file falls back to the latest day.
 */
async function selectArchive(iso, { qid = null } = {}) {
    const d = { iso, archive: true };
    state.archive = d;
    let payload;
    try {
        payload = await data.dayFile(iso);
    } catch {
        if (state.archive === d) await selectDay(state.days.length - 1, { push: null });
        return;
    }
    if (shownDay() !== d) return;
    showDay(d, payload, qid);
}

/** Show a loaded day (slider day or archive day): labels, the archive tag, the cards, and the event named by the URL or the day's lead. */
function showDay(d, payload, qid) {
    $('day-slider').setAttribute('aria-valuetext', dayLabel(d));
    $('day-out').textContent = dayLabel(d);
    $('day-archive').hidden = !d.archive;
    renderBars();
    state.payload = payload;
    state.shown = PAGE;
    const target = qid ? findByQid(qid) : null;
    if (target && target.class !== 'single_language') {
        const min = TIER_RANK[state.tier];
        if (TIER_RANK[target.tier] < min) setTier('noticed');
        const pos = visibleEvents().findIndex((e) => e.id === target.id);
        state.shown = Math.max(PAGE, Math.ceil((pos + 1) / PAGE) * PAGE);
    }
    renderDay();
    if (target) select(target, { animate: true });
    else if (!d.today) { const ev = pickDay(state.payload.events); if (ev) select(ev, { animate: false }); }
    else if (state.hero.event) select(state.hero.event, { animate: false });
}

/** Redraw everything that depends on the shown day: count, briefing line, cards, languages and the briefing panel. */
function renderDay() {
    const p = state.payload;
    const d = shownDay();
    $('day-count').textContent = t('timeline.count', { n: p.summary?.events ?? p.events.length });
    $('day-brief').textContent = compose(p, d.today ? todayIso() : d.iso).text;
    renderCards();
    renderLanguages();
    renderBriefing();
}

/** Set the tier filter and mark its button as checked. */
function setTier(tier) {
    state.tier = tier;
    document.querySelectorAll('.filters [data-tier]').forEach((x) => x.setAttribute('aria-checked', String(x.dataset.tier === tier)));
}

/** Lower-case text without accents, so that a search for "sao paulo" finds "São Paulo". */
const fold = (s) => String(s ?? '').normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();

/** Whether an event matches the card search: a label in any language, a description, or its QID. */
function matches(ev, q) {
    if (!q) return true;
    return [...Object.values(ev.labels || {}), ...Object.values(ev.desc || {}), ev.qid].some((s) => fold(s).includes(q));
}

/** The shown day's events at or above the tier filter and matching the search, in the chosen order. */
function visibleEvents() {
    const min = TIER_RANK[state.tier];
    const list = (state.payload.events || []).filter((e) => TIER_RANK[e.tier] >= min && matches(e, state.query));
    return SORTS[state.sort] ? list.sort(SORTS[state.sort]) : list;
}

/** The visible event cards, a page at a time. */
function renderCards() {
    const list = visibleEvents();
    const ol = $('cards');
    ol.replaceChildren(...list.slice(0, state.shown).map(card));
    renderForecastNote(!!ol.querySelector('.card__forecast'));
    if (!list.length) {
        const text = state.query ? t('timeline.no_match', { q: $('card-search').value.trim() }) : t('timeline.empty');
        ol.append(el('li', { class: 'empty', text }));
    }
    $('more').hidden = list.length <= state.shown;
}

/* ---------------------------------------------------------------- languages */

/** The language panel: the picker sorted by native name, and that language's top events of the day. */
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

/** The briefing panel for the shown day: date, lead sentence, about line and facts. */
function renderBriefing() {
    const d = shownDay();
    const iso = d.today ? todayIso() : d.iso;
    const b = compose(state.payload, iso);
    $('brief-date').textContent = d.today ? t('timeline.today') : i18n.day(iso);
    $('brief-text').textContent = b.text;
    $('brief-about').textContent = b.about;
    $('brief-facts').replaceChildren(...b.facts.map(([, text]) => el('li', { text })));
}

/** The About section, with its dataset and repository links filled into the translated text. */
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

/** The slider days: past days of the 90-day timeline, then today. */
function buildDays() {
    const days = (state.stats.timeline || [])
        .filter((r) => r.day < todayIso())
        .map((r) => ({ iso: r.day, count: (r.tiers.noticed || 0) + (r.tiers.international || 0) + (r.tiers.planetary || 0) }));
    days.push({ iso: todayIso(), count: state.today.summary?.events ?? state.today.events.length, today: true });
    state.days = days;
    $('day-slider').max = days.length - 1;
}

/** Redraw the whole page, for example after the language changes. */
function renderAll(animate) {
    renderHero(animate);
    renderNext();
    renderForecastSection();
    renderBars();
    $('day-slider').value = state.index;
    $('day-out').textContent = dayLabel(shownDay());
    $('day-slider').setAttribute('aria-valuetext', dayLabel(shownDay()));
    renderDay();
}

/** Attach every event handler: language buttons, slider, arrows, bars, copy, more, replay, filters and history. */
function wire() {
    document.querySelectorAll('[data-ui-lang]').forEach((b) => b.addEventListener('click', () => setLang(b.dataset.uiLang)));
    $('day-slider').addEventListener('input', (e) => selectDay(Number(e.target.value), { push: false }));
    $('day-slider').addEventListener('change', () => setHash(dayHash(state.days[state.index]), true));
    // From an archive day, either arrow returns to the oldest day of the slider's window.
    $('prev-day').addEventListener('click', () => selectDay(state.archive ? 0 : state.index - 1));
    $('next-day').addEventListener('click', () => selectDay(state.archive ? 0 : state.index + 1));
    $('bars').addEventListener('click', (e) => {
        const r = $('bars').getBoundingClientRect();
        selectDay(Math.floor(((e.clientX - r.left) / r.width) * state.days.length));
    });
    $('copy-day').addEventListener('click', (e) => copyLink(dayHash(shownDay()) === '#/today'
        ? `#/day/${todayIso()}` : dayHash(shownDay()), e.currentTarget));
    $('more').addEventListener('click', () => { state.shown += PAGE; renderCards(); });
    $('replay').addEventListener('click', () => { if (state.hero.event) select(state.hero.event, { animate: true }); });
    $('lang-select').addEventListener('change', (e) => { state.lang = e.target.value; renderLanguages(); setHash(`#/lang/${state.lang}`); });
    $('card-sort').addEventListener('change', (e) => { state.sort = e.target.value; state.shown = PAGE; renderCards(); });
    $('card-search').addEventListener('input', (e) => { state.query = fold(e.target.value.trim()); state.shown = PAGE; renderCards(); });
    document.querySelector('.filters').addEventListener('click', (e) => {
        const b = e.target.closest('[data-tier]');
        if (!b) return;
        setTier(b.dataset.tier);
        state.shown = PAGE;
        renderCards();
    });
    addEventListener('popstate', () => { if (state.today) route({ scroll: true }); });
    addEventListener('keydown', onKey);
}

/** Keyboard shortcuts: ← and → step through days, T returns to today, / jumps to the search (Escape clears it); never while typing in another field or with a modifier key. */
function onKey(e) {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || !state.today) return;
    if (e.key === 'Escape' && e.target.id === 'card-search' && e.target.value) {
        e.target.value = '';
        e.target.dispatchEvent(new Event('input'));
        return;
    }
    if (e.target.closest?.('input, select, textarea, [contenteditable="true"]')) return;
    const press = { ArrowLeft: 'prev-day', ArrowRight: 'next-day' }[e.key];
    if (press) { e.preventDefault(); $(press).click(); }
    else if (e.key === 't' || e.key === 'T') { e.preventDefault(); selectDay(state.days.length - 1); }
    else if (e.key === '/') { e.preventDefault(); $('card-search').focus(); }
}

/** Start the app: theme, language, live strip and map, then load today and stats, pick the hero and follow any deep link. */
async function boot() {
    initTheme();
    await setLang(i18n.initialLang());
    wire();
    startLive();
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
