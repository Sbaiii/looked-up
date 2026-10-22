// The CSV download of the shown day, from fixtures.
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');
const day = (iso) => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'days', `${iso}.json`), 'utf8'));

async function download(page) {
  const [file] = await Promise.all([page.waitForEvent('download'), page.click('#download-day')]);
  return { name: file.suggestedFilename(), text: fs.readFileSync(await file.path(), 'utf8') };
}

test('a past day downloads as looked-up-<date>.csv with every event', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  const { name, text } = await download(page);
  const d = day('2026-08-17');
  expect(name).toBe('looked-up-2026-08-17.csv');
  const lines = text.replace(/^﻿/, '').trimEnd().split('\r\n');
  expect(lines[0]).toBe('date,qid,label,description,class,tier,breadth,lead_language,first_spike_utc,spread_hours,extra_views,category,languages,wikipedia_url');
  expect(lines).toHaveLength(1 + d.events.length + (d.single_language_events || []).length);
  expect(page.errors).toEqual([]);
});
