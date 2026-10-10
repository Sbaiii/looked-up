// All visible text goes through here: UI strings from i18n/<lang>.json, numbers, dates and language
// names through Intl in the same locale.

export const UI_LANGS = ['en', 'fr', 'es'];
let dict = {};
let lang = 'en';
let locale = 'en-GB';
let plural = new Intl.PluralRules(locale);

export function initialLang() {
    try {
        const stored = localStorage.getItem('lookedup_lang');
        if (UI_LANGS.includes(stored)) return stored;
    } catch { /* storage blocked */ }
    const nav = (navigator.languages || [navigator.language || 'en']).map((l) => l.slice(0, 2));
    return nav.find((l) => UI_LANGS.includes(l)) || 'en';
}

export async function load(code) {
    const res = await fetch(`i18n/${code}.json`);
    dict = await res.json();
    lang = code;
    locale = dict.locale;
    plural = new Intl.PluralRules(locale);
    try { localStorage.setItem('lookedup_lang', code); } catch { /* ignore */ }
    document.documentElement.lang = code;
    return dict;
}

export const current = () => lang;

/** Install a dictionary directly (unit tests run without fetch or a DOM). */
export function use(dictionary, code) {
    dict = dictionary;
    lang = code;
    locale = dictionary.locale;
    plural = new Intl.PluralRules(locale);
    cache.clear();
}

function lookup(key) {
    return key.split('.').reduce((o, k) => (o == null ? o : o[k]), dict);
}

/** t('event.languages', {n: 3}) picks the plural form; {placeholders} are filled from vars. */
export function t(key, vars = {}) {
    let s = lookup(key);
    if (s && typeof s === 'object' && !Array.isArray(s)) {
        const n = vars.n;
        s = (n === 0 && s.zero) || s[plural.select(n)] || s.other;
    }
    if (typeof s !== 'string') return Array.isArray(s) ? s : key;
    return s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
}

export function applyStatic(root = document) {
    root.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll('[data-i18n-aria]').forEach((el) => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
    document.title = t('meta.title');
    document.querySelector('meta[name="description"]').setAttribute('content', t('meta.description'));
}

const cache = new Map();
function intl(kind, opts) {
    const k = `${kind}|${locale}|${JSON.stringify(opts)}`;
    if (!cache.has(k)) cache.set(k, new Intl[kind](locale, opts));
    return cache.get(k);
}

export const num = (n) => intl('NumberFormat', {}).format(n);
export const pct = (p) => intl('NumberFormat', { style: 'percent', maximumFractionDigits: 0 }).format(p);
export const compact = (n) => intl('NumberFormat', { notation: 'compact', compactDisplay: 'long', maximumFractionDigits: 1 }).format(n);
export const day = (iso) => intl('DateTimeFormat', { day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(`${iso}T12:00:00Z`));
export const dayShort = (iso) => intl('DateTimeFormat', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${iso}T12:00:00Z`));
export const hour = (iso) => intl('DateTimeFormat', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'UTC' }).format(new Date(iso));
export const dateTime = (iso) => intl('DateTimeFormat', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'UTC', timeZoneName: 'short' }).format(new Date(iso));
export const langName = (code) => {
    try { return intl('DisplayNames', { type: 'language' }).of(code) || code; } catch { return code; }
};

/** "Japanese (日本語)"; just "English" when the native name adds nothing. */
export function langNative(code) {
    const name = langName(code);
    let native = code;
    try { native = new Intl.DisplayNames([code], { type: 'language' }).of(code) || code; } catch { /* keep code */ }
    return native.toLocaleLowerCase(code) === name.toLocaleLowerCase(locale) ? name : `${name} (${native})`;
}

/** Viewer's local clock time with zone, e.g. "15:58 CEST". */
export const localTime = (iso) => new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short' }).format(new Date(iso));

/** "under an hour" / "2 hours" */
export const within = (h) => t('within', { n: h });

/** Short Wikidata description in the UI language, then English (ADR 0026). */
export function desc(ev) {
    const d = ev.desc || {};
    return d[lang] || d.en || '';
}

/** The event's label in the viewer's UI language, then English, then the lead language. */
export function label(ev) {
    const l = ev.labels || {};
    return l[lang] || l.en || l[ev.lead] || Object.values(l)[0] || ev.qid;
}
