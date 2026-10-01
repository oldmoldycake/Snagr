/** One word or mark the page uses, and what it means there. */
export interface GlossaryTerm {
  term: string
  meaning: string
}

/**
 * Every term a page's glossary can explain. Each page picks the ones it
 * shows, so one word means the same thing everywhere it is explained.
 */
export const TERMS = {
  target: {
    term: '⌖ Target',
    meaning: 'The price you want to pay. Snagr tells you when a tracked listing is at or below it.',
  },
  vsTarget: {
    term: 'vs target',
    meaning: 'How far a listing’s price is above (+) or below (−) your target.',
  },
  change: {
    term: 'Change (7d, 30d, …)',
    meaning:
      'On each listing’s price line, a tick marks its price at the start of the chosen period and a bar runs to today’s price: green when it fell, red when it rose.',
  },
  match: {
    term: 'Match',
    meaning:
      'A 0–100 score for how well a listing fits your description, judged when Snagr saves it. Only Best match mode uses it to rank listings.',
  },
  mode: {
    term: 'Cheapest / Best match',
    meaning:
      'Cheapest tracks the lowest-priced listings that are the right item. Best match tracks the listings that fit your description best, with price breaking ties.',
  },
  tracked: {
    term: 'Tracked listings',
    meaning:
      'The listings Snagr re-checks for this item. There is a limit per item; when it is full, Snagr only looks for something better to swap in.',
  },
  hunt: {
    term: 'Hunt',
    meaning:
      'Snagr searching a site for new listings of an item. It runs on its own while an item has room for more listings.',
  },
  check: {
    term: 'Price check',
    meaning: 'Snagr re-reading the price of a listing it already tracks.',
  },
  market: {
    term: 'Market price',
    meaning: 'Snagr looking up what an item typically sells for, so it can spot prices that are too good to be true.',
  },
  pageData: {
    term: 'page data',
    meaning: 'The price came from details the site publishes for search engines. No AI was needed.',
  },
  learnedSpot: {
    term: 'learned spot',
    meaning: 'The price came from the place on the page where Snagr found it before. No AI was needed.',
  },
  unconfirmed: {
    term: 'unconfirmed',
    meaning:
      'A price that looked wrong (say $4.49 for a $449 item). It is shown but kept out of charts, averages and alerts until a second reading agrees.',
  },
  replicas: {
    term: 'Replicas',
    meaning: 'Whether reproductions, replicas and other unofficial copies count as this item.',
  },
  paused: {
    term: 'Paused site',
    meaning:
      'A site that kept blocking Snagr (for example with a “are you a robot?” page). Its checks and hunts wait, then resume on their own.',
  },
  tokens: {
    term: 'Tokens',
    meaning: 'How much AI text a job used. More tokens means a higher bill from your AI provider.',
  },
} satisfies Record<string, GlossaryTerm>
