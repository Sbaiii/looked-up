// Absolute colour scale (ADR 0025): per-language peak surprise on a fixed log scale from the spike threshold
// (8) to 5,000+, the same for every event, so a small event looks faint and a planetary one blazes.
// Mirrored in lookedup/og.py.

export const MIN = 8;
export const MAX = 5000;
export const TICKS = [8, 50, 500, 5000];

export function scale(surprise) {
    if (!(surprise > MIN)) return 0;
    return Math.min(1, Math.log(surprise / MIN) / Math.log(MAX / MIN));
}

export const tickLabel = (v) => (v >= MAX ? '5k+' : v >= 1000 ? `${v / 1000}k` : String(v));
