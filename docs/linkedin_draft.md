I asked 14 questions of Wikipedia's reading data and wrote down my expected answers first. Two came back yes.

Looked Up reads the hourly pageview dumps of 30 Wikipedias, joins the same topic across languages through Wikidata, and turns sudden spikes into attention events. It runs on free tiers only: GitHub Actions, a Hugging Face dataset and a Cloudflare Worker. Every hypothesis was committed with its threshold before the code that tested it, so the misses count as much as the hits.

Three things the data said instead:

1. English Wikipedia leads only 26.6% of events.
2. A World Cup final reaches 29 languages in the same hour, while a death takes hours to spread. I had predicted the opposite.
3. Readers reach a story before editors do, by a median 106 minutes. Edits are still the earlier signal in practice: they are known 86 minutes before the reading numbers are published.

One honest limitation: it sees languages, not countries, and it favours the famous. It catches 23% of notable deaths for people with articles in 5 to 9 languages, and 54% for 20 or more.

The app, the scorecard and the method: https://sbaiii.com/projects/looked-up/
