// Generate src/rules.json (from config/live.yml) and src/languages.json (from the Python live package), so the
// Worker and the reference implementation share one set of rules (ADR 0032).
import { readFileSync, writeFileSync } from 'node:fs';
import { parse } from 'yaml';

const root = new URL('../../', import.meta.url);
const rules = parse(readFileSync(new URL('config/live.yml', root), 'utf8'));
writeFileSync(new URL('../src/rules.json', import.meta.url), JSON.stringify(rules, null, 1) + '\n');
const langs = JSON.parse(readFileSync(new URL('live/lookedup_live/languages.json', root), 'utf8'));
writeFileSync(new URL('../src/languages.json', import.meta.url), JSON.stringify(langs) + '\n');
console.log(`rules.json and languages.json written (${langs.length} languages)`);
