// "Right now" strip (Phase 5): what editors are rushing to update, from the live layer (ADR 0030).
// Polled every 60 s; when the layer is resting (stale, asleep or unreachable) it shows one quiet line, never an error.

import { t, langName, label as eventLabel } from './i18n.js';

const DEFAULT = 'https://huggingface.co/datasets/Sbaiiiiii/looked-up/resolve/main/data/live/live.json';
const param = new URLSearchParams(location.search).get('live');
export const LIVE_URL = param && /^https:\/\/[a-z0-9-]+\.hf\.space\/live\.json$/.test(param) ? param : DEFAULT;
const STALE_MS = 15 * 60e3;
const POLL_MS = 60e3;
let last = null;
let failed = false;

const $ = (id) => document.getElementById(id);

function el(tag, text, cls) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
}

const list = (codes) => {
    const names = codes.map(langName);
    try { return new Intl.ListFormat(document.documentElement.lang, { type: 'conjunction' }).format(names); } catch { return names.join(', '); }
};

function resting(data) {
    if (failed || !data) return true;
    if (Date.now() - Date.parse(data.generated_at) > STALE_MS) return true;
    return (data.status?.gap_minutes ?? 0) >= 60;
}

export function renderLive() {
    const strip = $('right-now');
    if (!strip) return;
    const ul = $('live-list');
    const state = $('live-state');
    const rest = resting(last);
    strip.classList.toggle('is-resting', rest);
    ul.replaceChildren();
    state.textContent = '';
    if (rest) { state.textContent = last || failed ? t('live.resting') : ''; return; }
    const now = Date.now();
    const events = (last.events || []).slice(0, 4);
    for (const ev of events) {
        const li = el('li');
        const name = eventLabel({ labels: ev.labels, lead: ev.languages[0]?.lang, qid: ev.qid });
        const d = ev.desc?.[document.documentElement.lang] || ev.desc?.en;
        li.append(el('strong', name));
        if (d) li.append(el('span', d));
        li.append(el('span', `${t('live.languages', { langs: list(ev.languages.map((l) => l.lang)) })} · ${t('live.since', { n: Math.max(0, Math.round((now - Date.parse(ev.first_burst)) / 60e3)) })}`));
        ul.append(li);
    }
    if (!events.length) {
        state.textContent = t('live.quiet');
        for (const b of (last.single_language_bursts || []).slice(0, 3)) {
            const li = el('li');
            li.append(el('strong', b.title.replace(/_/g, ' ')),
                el('span', `${langName(b.lang)} · ${t('live.since', { n: Math.max(0, Math.round((now - Date.parse(b.first_burst)) / 60e3)) })}`));
            ul.append(li);
        }
    } else if ((last.status?.gap_minutes ?? 0) > 5) {
        state.textContent = t('live.gap', { n: last.status.gap_minutes });
    }
}

async function poll() {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 8000);
    try {
        const r = await fetch(LIVE_URL, { cache: 'no-store', signal: ctl.signal });
        if (!r.ok) throw new Error(String(r.status));
        last = await r.json();
        failed = false;
    } catch {
        failed = true;
    } finally {
        clearTimeout(timer);
    }
    renderLive();
}

export function startLive() {
    poll();
    setInterval(() => { if (!document.hidden) poll(); }, POLL_MS);
}
