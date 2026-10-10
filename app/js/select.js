// Which event leads (ADR 0024). Pure functions, mirrored in lookedup/og.py.
//   rank: multi-language events by total excess views, ties broken by breadth;
//   a hero must have >= 100,000 excess views OR be international/planetary;
//   if nothing in the last 24 h qualifies, widen to 48 h, then 7 days.

export const HERO_MIN_EXCESS = 100000;
const STRONG = new Set(['international', 'planetary']);
export const WINDOWS = [24, 48, 168];

export function rank(events) {
    return (events || [])
        .filter((e) => e.class !== 'single_language')
        .sort((a, b) => b.excess - a.excess || b.breadth - a.breadth || a.id.localeCompare(b.id));
}

export const qualifies = (e) => e.excess >= HERO_MIN_EXCESS || STRONG.has(e.tier);

/** Top-ranked qualifying event, or null. */
export function pick(events) {
    return rank(events).find(qualifies) || null;
}

/** The day view's default event: the hero rule, else the top-ranked event of the day. */
export function pickDay(events) {
    return pick(events) || rank(events)[0] || null;
}

/** Hero over widening windows. ``byWindow(hours)`` returns that window's events (may be async). */
export async function pickHero(byWindow, now) {
    for (const hours of WINDOWS) {
        const since = now - hours * 3600e3;
        const events = (await byWindow(hours)).filter((e) => Date.parse(e.start) >= since);
        const ev = pick(events);
        if (ev) return { event: ev, hours };
    }
    return { event: null, hours: 24 };
}
