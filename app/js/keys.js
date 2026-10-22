// Keyboard shortcuts as a pure mapping from a key press to an action, so the rules can be tested without a page.

const ACTIONS = { ArrowLeft: 'prev-day', ArrowRight: 'next-day', t: 'today', T: 'today', j: 'next-event', k: 'prev-event',
    '/': 'search' };

/**
 * The action for a key press, or null. ``inField``: focus is in an input, select, textarea or editable element;
 * ``inSearch``: focus is in the card search and it holds text. Escape there clears it; otherwise keys never act
 * while typing in a field or with a modifier held.
 */
export function keyAction({ key, altKey = false, ctrlKey = false, metaKey = false, inField = false, inSearch = false }) {
    if (altKey || ctrlKey || metaKey) return null;
    if (key === 'Escape' && inSearch) return 'clear-search';
    if (inField) return null;
    return ACTIONS[key] || null;
}
