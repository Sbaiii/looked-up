// Looked Up: one page, vanilla JS. Data: data/app/ on the Hugging Face dataset (ADR 0022).

import * as i18n from './i18n.js';
import { t, label, langName, within, compact } from './i18n.js';
import * as data from './data.js';
import * as viz from './viz.js';
import { compose, excessPhrase } from './briefing.js';

const $ = (id) => document.getElementById(id);
const PAGE = 12;
const TIER_RANK = { noticed: 0, international: 1, planetary: 2 };

const state = {
    days: [],          // [{iso, count, today?}]
    index: 0,
    payload: null,     // the selected day's file (or today.json)
    today: null,
    stats: null,
    tier: 'noticed',
    shown: PAGE,
    selected: null,    // event id on the map
    lang: null,        // languages panel
};

const safeUrl = (u) => (typeof u === 'string' && u.startsWith('https://') ? u : '#');

function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === 'class') e.className = v;
        else if (k === 'text') e.textContent = v;
        else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? '' : v);
    }
    e.append(...children.filter((c) => c != null));
    return e;
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
    if (state.today) renderAll(false);
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

function card(ev) {
    const li = el('li', { class: `card${ev.id === state.selected ? ' is-selected' : ''}`, 'data-id': ev.id });
    const title = el('h3', { class: 'card__title' },
        el('button', { type: 'button', 'aria-label': `${label(ev)}: ${t('event.show')}`, onclick: () => select(ev, true), text: label(ev) }));
    li.append(
        title,
        sparkline(ev.spark),
        el('p', { class: 'card__meta' },
            badge(ev.tier),
            el('span', { text: t('event.languages', { n: ev.breadth }) }),
            el('span', { text: t('event.lead', { lang: langName(ev.lead) }) }),
            el('span', { text: t('event.first_spike', { time: i18n.hour(ev.start) }) }),
            el('span', { text: t(`event.category.${ev.category}`) })),
        el('p', { class: 'card__links' }, ...wikiLinks(ev)),
    );
    return li;
}

/* ---------------------------------------------------------------- hero */

function heroCounter(n, lag, ev) {
    if (ev.id !== state.today?.events?.[0]?.id) return;   // only the hero's own event drives its counter
    $('hero-counter').textContent = t('hero.counter', { n, within: within(lag) });
    if (n === ev.langs.length) $('hero-counter').textContent = t('hero.counter', { n: ev.breadth, within: within(ev.spread_h) });
}

function renderHero(animate) {
    const ev = state.today?.events?.[0];
    const lab = $('hero-label');
    lab.classList.remove('skeleton');
    $('replay').hidden = !ev;
    if (!ev) {
        lab.textContent = t('hero.empty');
        $('hero-counter').textContent = '';
        $('hero-sub').textContent = '';
        return;
    }
    const url = (ev.urls || {})[i18n.current()] || (ev.urls || {})[ev.lead];
    lab.replaceChildren(url ? el('a', { href: safeUrl(url), rel: 'noopener', text: label(ev) }) : label(ev));
    $('hero-counter').textContent = t('hero.counter', { n: ev.breadth, within: within(ev.spread_h) });
    $('hero-sub').textContent = `${t(`tier.${ev.tier}`)} · ${t('hero.led_by', { lang: langName(ev.lead) })} · ${excessPhrase(ev.excess)}`;
    if (state.today.generated_at) $('updated').textContent = t('ui.updated', { time: i18n.dateTime(state.today.generated_at) });
    if (animate) select(ev, false, true);
}

/* ---------------------------------------------------------------- map selection */

function reshow(animate) {
    const ev = findEvent(state.selected);
    if (ev) viz.show(ev, { animate });
}

function findEvent(id) {
    for (const src of [state.payload, state.today]) {
        const ev = src && [...(src.events || []), ...(src.single_language_events || [])].find((e) => e.id === id);
        if (ev) return ev;
    }
    return null;
}

function select(ev, fromList, animate = true) {
    state.selected = ev.id;
    document.querySelectorAll('.card').forEach((c) => c.classList.toggle('is-selected', c.dataset.id === ev.id));
    viz.show(ev, { animate });
    if (fromList) {
        const stage = $('viz');
        const r = stage.getBoundingClientRect();
        if (r.bottom < 60 || r.top > innerHeight) stage.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' });
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

async function selectDay(index, { animate = false } = {}) {
    state.index = Math.max(0, Math.min(state.days.length - 1, index));
    const d = state.days[state.index];
    $('day-slider').value = state.index;
    $('day-slider').setAttribute('aria-valuetext', dayLabel(d));
    $('day-out').textContent = dayLabel(d);
    renderBars();
    try {
        state.payload = d.today ? state.today : await data.dayFile(d.iso);
    } catch {
        state.payload = { events: [], single_language_events: [], summary: { events: 0 } };
    }
    if (state.days[state.index] !== d) return;  // a newer selection won
    state.shown = PAGE;
    renderDay();
    if (!d.today || !animate) {
        const first = state.payload.events?.[0];
        if (first && !d.today) select(first, false, false);
    }
}

function renderDay() {
    const p = state.payload;
    $('day-count').textContent = t('timeline.count', { n: p.summary?.events ?? p.events.length });
    renderCards();
    renderLanguages();
    renderBriefing();
}

function renderCards() {
    const min = TIER_RANK[state.tier];
    const list = (state.payload.events || []).filter((e) => TIER_RANK[e.tier] >= min);
    const ol = $('cards');
    ol.replaceChildren(...list.slice(0, state.shown).map(card));
    if (!list.length) ol.append(el('li', { class: 'empty', text: t('timeline.empty') }));
    $('more').hidden = list.length <= state.shown;
}

/* ---------------------------------------------------------------- languages */

function renderLanguages() {
    const p = state.payload;
    const langs = state.stats?.languages || [];
    const sel = $('lang-select');
    const names = langs.map((c) => [c, langName(c)]).sort((a, b) => a[1].localeCompare(b[1], i18n.current()));
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
    const iso = d.today ? state.today.generated_at.slice(0, 10) : d.iso;
    const b = compose(state.payload, iso);
    $('brief-date').textContent = d.today ? t('timeline.today') : i18n.day(iso);
    $('brief-text').textContent = b.text;
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
    const todayIso = state.today.generated_at.slice(0, 10);
    const days = (state.stats.timeline || [])
        .filter((r) => r.day < todayIso)
        .map((r) => ({ iso: r.day, count: (r.tiers.noticed || 0) + (r.tiers.international || 0) + (r.tiers.planetary || 0) }));
    days.push({ iso: todayIso, count: state.today.summary?.events ?? state.today.events.length, today: true });
    state.days = days;
    const slider = $('day-slider');
    slider.max = days.length - 1;
}

function renderAll(animate) {
    renderHero(animate);
    renderBars();
    $('day-out').textContent = dayLabel(state.days[state.index]);
    $('day-slider').setAttribute('aria-valuetext', dayLabel(state.days[state.index]));
    renderDay();
}

function wire() {
    document.querySelectorAll('[data-ui-lang]').forEach((b) => b.addEventListener('click', () => setLang(b.dataset.uiLang)));
    $('day-slider').addEventListener('input', (e) => selectDay(Number(e.target.value)));
    $('prev-day').addEventListener('click', () => selectDay(state.index - 1));
    $('next-day').addEventListener('click', () => selectDay(state.index + 1));
    $('bars').addEventListener('click', (e) => {
        const r = $('bars').getBoundingClientRect();
        selectDay(Math.floor(((e.clientX - r.left) / r.width) * state.days.length));
    });
    $('more').addEventListener('click', () => { state.shown += PAGE; renderCards(); });
    $('replay').addEventListener('click', () => { const ev = state.today?.events?.[0]; if (ev) select(ev, false, true); });
    $('lang-select').addEventListener('change', (e) => { state.lang = e.target.value; renderLanguages(); });
    document.querySelector('.filters').addEventListener('click', (e) => {
        const b = e.target.closest('[data-tier]');
        if (!b) return;
        state.tier = b.dataset.tier;
        document.querySelectorAll('.filters [data-tier]').forEach((x) => x.setAttribute('aria-checked', String(x === b)));
        state.shown = PAGE;
        renderCards();
    });
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
    renderAll(false);
    await vizReady;
    renderHero(true);
    document.documentElement.dataset.ready = 'true';
}

boot();
