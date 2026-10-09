// The daily briefing, written from templates in i18n/<lang>.json (no LLM): one paragraph about the day's
// biggest event plus three facts. Every number comes from the day file.

import { t, label, langName, within, compact, num, day } from './i18n.js';

export function excessPhrase(n) {
    return n >= 1e6 ? t('briefing.excess_big', { n: compact(n) }) : t('briefing.excess_small', { n: num(n) });
}

const by = (f) => (a, b) => f(b) - f(a);

/** The day's lead event: the most extra views among multi-language events. */
export function leadEvent(events) {
    return [...events].sort(by((e) => e.excess))[0] || null;
}

export function facts(events) {
    const out = [];
    const wide = events.filter((e) => e.breadth >= 5);
    const pool = wide.length ? wide : events.filter((e) => e.breadth >= 3);
    const fastest = [...pool].sort((a, b) => a.spread_h - b.spread_h || b.breadth - a.breadth || b.excess - a.excess)[0];
    if (fastest) out.push(['fastest', t('briefing.fastest', { label: label(fastest), breadth: t('event.languages', { n: fastest.breadth }), within: within(fastest.spread_h) }), fastest]);
    const widest = [...events].sort((a, b) => b.breadth - a.breadth || b.excess - a.excess)[0];
    if (widest) out.push(['widest', t('briefing.widest', { label: label(widest), breadth: t('event.languages', { n: widest.breadth }) }), widest]);
    const nonEn = leadEvent(events.filter((e) => e.lead !== 'en'));
    if (nonEn) out.push(['non_english', t('briefing.non_english', { label: label(nonEn), lang: langName(nonEn.lead), excess: excessPhrase(nonEn.excess) }), nonEn]);
    return out;
}

export function compose(payload, isoDate) {
    const events = payload.events || [];
    const top = leadEvent(events);
    if (!top) return { text: t('briefing.quiet'), facts: [], top: null };
    const text = t(top.category === 'death' ? 'briefing.lead_death' : 'briefing.lead', {
        date: day(isoDate), label: label(top), breadth: t('event.languages', { n: top.breadth }),
        within: within(top.spread_h), lang: langName(top.lead), excess: excessPhrase(top.excess),
    });
    return { text, facts: facts(events), top };
}
