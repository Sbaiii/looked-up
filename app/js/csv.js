// CSV downloads (RFC 4180): the shown day's events as a table anyone can open in a spreadsheet.

/** One CSV field: quoted when it holds a comma, a quote or a line break, with inner quotes doubled. */
export function field(v) {
    const s = v == null ? '' : String(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** CSV text for ``rows`` (objects) under ``columns``, CRLF line ends as RFC 4180 asks. */
export function toCsv(rows, columns) {
    return [columns.map(field).join(','), ...rows.map((r) => columns.map((c) => field(r[c])).join(','))].join('\r\n') + '\r\n';
}

export const DAY_COLUMNS = ['date', 'qid', 'label', 'description', 'class', 'tier', 'breadth', 'lead_language',
    'first_spike_utc', 'spread_hours', 'extra_views', 'category', 'languages', 'wikipedia_url'];

/** The rows of a day file for the CSV: multi-language events, then single-language ones. ``label`` and ``desc``
 * give the names in the interface language, so the file matches the page. */
export function dayRows(payload, iso, { label, desc }) {
    const events = [...(payload.events || []), ...(payload.single_language_events || [])];
    return events.map((e) => ({
        date: iso, qid: e.qid, label: label(e), description: desc(e), class: e.class, tier: e.tier,
        breadth: e.breadth, lead_language: e.lead, first_spike_utc: e.start, spread_hours: e.spread_h,
        extra_views: e.excess, category: e.category,
        languages: (e.langs || []).map((r) => r.lang).join(' '), wikipedia_url: (e.urls || {})[e.lead] || '',
    }));
}
