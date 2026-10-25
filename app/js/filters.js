// The day's card list: search, tier, category and language filters, and the orders. Pure, so it runs in node too.

export const TIER_RANK = { noticed: 0, international: 1, planetary: 2 };

/** Card orders. Day files list events widest first, so 'widest' keeps the file order; ties keep it too (stable sort). */
export const SORTS = {
    widest: null,
    views: (a, b) => b.excess - a.excess,
    fastest: (a, b) => a.spread_h - b.spread_h || b.breadth - a.breadth,
    latest: (a, b) => Date.parse(b.start) - Date.parse(a.start),
    earliest: (a, b) => Date.parse(a.start) - Date.parse(b.start),
};

// Letters that carry no separable accent, written as their plain Latin forms (Łódź, Øresund, Đà Nẵng, Straße).
const PLAIN = { ł: 'l', ø: 'o', æ: 'ae', œ: 'oe', đ: 'd', ð: 'd', þ: 'th', ß: 'ss', ı: 'i' };

/** Lower-case text without accents, so that a search for "sao paulo" finds "São Paulo" and "lodz" finds "Łódź". */
export const fold = (s) => String(s ?? '').normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
    .replace(/[łøæœđðþßı]/g, (c) => PLAIN[c]);

/** Whether an event matches a folded search: a label in any language, a description, or its QID. */
export function matches(ev, q) {
    if (!q) return true;
    return [...Object.values(ev.labels || {}), ...Object.values(ev.desc || {}), ev.qid].some((s) => fold(s).includes(q));
}

/** The events left by ``f`` = {tier, query, category, lang, sort}, in the chosen order (a new array). */
export function visible(events, f) {
    const min = TIER_RANK[f.tier] ?? 0;
    const list = (events || []).filter((e) => TIER_RANK[e.tier] >= min && matches(e, f.query)
        && (!f.category || e.category === f.category)
        && (!f.lang || (e.langs || []).some((r) => r.lang === f.lang)));
    return SORTS[f.sort] ? list.sort(SORTS[f.sort]) : list;
}

/** Events per category, for the category chips. */
export function categoryCounts(events) {
    const counts = {};
    for (const e of events || []) counts[e.category || 'other'] = (counts[e.category || 'other'] || 0) + 1;
    return counts;
}

/** Spread table columns that can be sorted, each with its natural first direction. */
export const SPREAD_KEYS = { name: 'asc', lang: 'asc', first: 'asc', lag: 'asc', surprise: 'desc', excess: 'desc' };

/** An event's language rows sorted by ``key`` ('asc' or 'desc'); ties fall back to lag, then language code. */
export function sortSpread(rows, key = 'lag', dir = SPREAD_KEYS[key] || 'asc') {
    const sign = dir === 'desc' ? -1 : 1;
    const val = (r) => (key === 'first' ? Date.parse(r.first) : r[key]);
    const cmp = (a, b) => {
        const x = val(a), y = val(b);
        return typeof x === 'string' ? x.localeCompare(y) : x - y;
    };
    return [...(rows || [])].sort((a, b) => sign * cmp(a, b) || a.lag - b.lag || a.lang.localeCompare(b.lang));
}
