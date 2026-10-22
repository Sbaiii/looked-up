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
