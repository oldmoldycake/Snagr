/**
 * In-memory fixture store for MSW. Deterministic: a seeded RNG generates a
 * year of daily price walks per listing, so charts look the same on every
 * reload. Mutations (add item, run agent, toggle watch…) update this store,
 * so the app feels live; state resets on page reload (session survives via
 * localStorage).
 */

// --- seeded RNG --------------------------------------------------------------

function mulberry32(seed: number) {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const rng = mulberry32(0x5eed)

// --- internal shapes (prices in cents) ----------------------------------------

export interface MockUser {
  id: number
  email: string
  password: string
  role: 'admin' | 'user'
  is_active: boolean
  ntfy_topic: string | null
  created_at: number
}

export interface MockCategory {
  id: number
  name: string
  slug: string
  site_ids: number[]
}

export interface MockSite {
  id: number
  name: string
  base_url: string
  created_at: number
}

export interface MockItem {
  id: number
  category_id: number
  name: string
  target_cents: number | null
  criteria: string | null
  selection_mode: 'cheapest' | 'best_match'
  max_listings: number
  /** optional so existing fixtures default to false */
  allow_reproductions?: boolean
  site_ids: number[] | null
  created_at: number
}

export interface MockListing {
  id: number
  item_id: number
  site_id: number
  url: string
  title: string | null
  site_sku: string | null
  active: boolean
  match_score: number | null
  match_summary: string | null
  created_at: number
  discovered_by_run_id: number | null
}

export interface MockCheck {
  id: number
  listing_id: number
  ts: number
  price_cents: number | null
  in_stock: boolean
  status: string
}

export interface MockWatch {
  id: number
  item_id: number
  notify: boolean
  target_cents: number | null
}

export interface MockRun {
  id: number
  scope: 'global' | 'category' | 'site' | 'item'
  scope_id: number | null
  scope_label: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  started_at: number | null
  finished_at: number | null
  stats: { listings_checked: number; prices_found: number; new_listings: number; errors: number } | null
  error: string | null
  created_at: number
  last_seq: number
}

export interface MockRunEvent {
  run_id: number
  seq: number
  ts: number
  level: 'info' | 'success' | 'warn' | 'error'
  event_type: string
  message: string
  payload: Record<string, unknown> | null
}

export interface MockInvite {
  id: number
  token: string
  email: string | null
  expires_at: number
  accepted_at: number | null
  created_at: number
}

// --- store ---------------------------------------------------------------------

export const NOW = Date.now()
const DAY = 86_400_000

let nextId = 1000
export const newId = () => ++nextId

export const store = {
  users: [] as MockUser[],
  categories: [] as MockCategory[],
  sites: [] as MockSite[],
  items: [] as MockItem[],
  listings: [] as MockListing[],
  checks: [] as MockCheck[],
  watches: [] as MockWatch[],
  runs: [] as MockRun[],
  runEvents: [] as MockRunEvent[],
  invites: [] as MockInvite[],
}

// --- seed data -------------------------------------------------------------------

const SITES: [string, string][] = [
  ['newegg.com', 'https://www.newegg.com'],
  ['amazon.com', 'https://www.amazon.com'],
  ['bestbuy.com', 'https://www.bestbuy.com'],
  ['microcenter.com', 'https://www.microcenter.com'],
  ['bhphotovideo.com', 'https://www.bhphotovideo.com'],
  ['ebay.com', 'https://www.ebay.com'],
]

interface SeedItem {
  name: string
  base: number // cents
  target: number | null
  listings: number
}

const CATEGORIES: { name: string; slug: string; sites: number[]; items: SeedItem[] }[] = [
  {
    name: 'GPUs',
    slug: 'gpus',
    sites: [0, 1, 2, 3],
    items: [
      // 7 listings → exercises the "Others (n)" legend fold
      { name: 'RTX 4070 Super', base: 61900, target: 55000, listings: 7 },
      { name: 'RX 7800 XT', base: 51999, target: 45000, listings: 3 },
      // snagged: target above the walk's floor so best ≤ target
      { name: 'RTX 4060 Ti 16GB', base: 45999, target: 46500, listings: 4 },
      { name: 'Arc B580', base: 26999, target: 22000, listings: 2 },
    ],
  },
  {
    name: 'Handhelds',
    slug: 'handhelds',
    sites: [1, 2, 5],
    items: [
      { name: 'Steam Deck OLED 512GB', base: 54900, target: 47500, listings: 3 },
      { name: 'ROG Ally X', base: 79999, target: 65000, listings: 3 },
      { name: 'Legion Go S', base: 59999, target: 50000, listings: 2 },
      // no listings yet → exercises the "run the agent" empty state
      { name: 'Retroid Pocket 5', base: 21900, target: 18000, listings: 0 },
    ],
  },
  {
    name: 'Keyboards',
    slug: 'keyboards',
    sites: [1, 5],
    items: [
      { name: 'Keychron Q1 Pro', base: 19900, target: 15000, listings: 2 },
      { name: 'NuPhy Air75 V2', base: 12995, target: 10000, listings: 2 },
      // single listing → no legend on the history chart
      { name: 'HHKB Professional Hybrid Type-S', base: 38500, target: 32000, listings: 1 },
      { name: 'Wooting 80HE', base: 19999, target: 17500, listings: 2 },
    ],
  },
  {
    name: 'Home Lab',
    slug: 'home-lab',
    sites: [0, 1, 3, 5],
    items: [
      { name: 'Minisforum MS-01', base: 67900, target: 55000, listings: 3 },
      { name: 'UniFi Dream Machine Pro', base: 37900, target: 33000, listings: 2 },
      { name: 'Seagate Exos 16TB', base: 24999, target: 20000, listings: 4 },
      { name: 'Raspberry Pi 5 8GB', base: 7995, target: 7000, listings: 3 },
    ],
  },
  {
    name: 'Audio',
    slug: 'audio',
    sites: [1, 2, 4],
    items: [
      { name: 'Sennheiser HD 660S2', base: 49995, target: 40000, listings: 3 },
      { name: 'Sony WH-1000XM5', base: 39999, target: 30000, listings: 3 },
      { name: 'Schiit Modi+', base: 12900, target: 11000, listings: 1 },
      { name: 'Moondrop Blessing 3', base: 31999, target: 27000, listings: 2 },
    ],
  },
]

/**
 * Random-walk a year of daily prices with occasional multi-day sales.
 * `endDaysAgo` truncates history early (sold/ended listings) and finishes
 * with a terminal check of the given status.
 */
function generateChecks(
  listingId: number,
  baseCents: number,
  jitterSeed: number,
  endDaysAgo = 0,
  endStatus?: 'sold' | 'ended',
) {
  const walk = mulberry32(jitterSeed)
  // each listing sits at a slightly different price level than the item base
  let price = Math.round(baseCents * (0.96 + walk() * 0.1))
  let saleDaysLeft = 0
  let salePrice = 0

  for (let day = 365; day >= endDaysAgo; day--) {
    // drift ±0.8% a day, mean-reverting toward base
    const drift = (walk() - 0.5) * 0.016 + (baseCents - price) / baseCents / 220
    price = Math.max(Math.round(baseCents * 0.55), Math.round(price * (1 + drift)))

    if (saleDaysLeft === 0 && walk() < 0.025) {
      saleDaysLeft = 2 + Math.floor(walk() * 5)
      salePrice = Math.round(price * (0.8 + walk() * 0.12))
    }

    const effective = saleDaysLeft > 0 ? salePrice : price
    if (saleDaysLeft > 0) saleDaysLeft--

    const inStock = walk() > 0.04
    store.checks.push({
      id: newId(),
      listing_id: listingId,
      ts: NOW - day * DAY - Math.floor(walk() * 6 * 3_600_000),
      price_cents: inStock ? effective : walk() > 0.5 ? effective : null,
      in_stock: inStock,
      status: 'ok',
    })
  }

  if (endStatus) {
    store.checks.push({
      id: newId(),
      listing_id: listingId,
      ts: NOW - endDaysAgo * DAY + 3_600_000,
      price_cents: null,
      in_stock: false,
      status: endStatus,
    })
  }
}

function seed() {
  store.users.push({
    id: 1,
    email: 'demo@snagr.dev',
    password: 'snagr',
    role: 'admin',
    is_active: true,
    ntfy_topic: 'snagr-demo-8f3a',
    created_at: NOW - 200 * DAY,
  })

  store.sites = SITES.map(([name, base_url], i) => ({
    id: i + 1,
    name,
    base_url,
    created_at: NOW - 190 * DAY,
  }))

  let itemId = 0
  let listingId = 0
  for (const [ci, cat] of CATEGORIES.entries()) {
    const categoryId = ci + 1
    store.categories.push({
      id: categoryId,
      name: cat.name,
      slug: cat.slug,
      site_ids: cat.sites.map((s) => s + 1),
    })

    for (const seedItem of cat.items) {
      itemId++
      store.items.push({
        id: itemId,
        category_id: categoryId,
        name: seedItem.name,
        target_cents: seedItem.target,
        criteria: null,
        selection_mode: 'cheapest',
        max_listings: 5,
        site_ids: null,
        created_at: NOW - Math.floor(30 + rng() * 150) * DAY,
      })
      store.watches.push({ id: newId(), item_id: itemId, notify: rng() > 0.3, target_cents: null })

      // spread listings across the category's sites; >4 wraps with ebay dupes
      const VARIANTS = ['', ' (New)', ' (Open Box)', ' (Renewed)', ' — Used, Like New', ' — Used, Good', ' (Refurbished)']
      for (let l = 0; l < seedItem.listings; l++) {
        listingId++
        const siteIdx = cat.sites[l % cat.sites.length]
        const site = store.sites[siteIdx]
        const slug = seedItem.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')
        store.listings.push({
          id: listingId,
          item_id: itemId,
          site_id: site.id,
          url: `${site.base_url}/p/${slug}${l >= cat.sites.length ? `-${l}` : ''}`,
          title: `${seedItem.name}${VARIANTS[l] ?? ''}`,
          site_sku: `SKU-${String(listingId).padStart(5, '0')}`,
          active: true,
          match_score: null,
          match_summary: null,
          created_at: NOW - Math.floor(20 + rng() * 140) * DAY,
          discovered_by_run_id: null,
        })
        generateChecks(listingId, seedItem.base, 0xbeef + listingId * 7)
      }
    }
  }

  seedRetroGames(itemId, listingId)

  seedHistoricalRuns()
}

/**
 * The criteria-driven showcase: an item tracked by best_match with scored
 * eBay listings (one already sold), plus a plain cheapest-mode contrast item.
 */
function seedRetroGames(lastItemId: number, lastListingId: number) {
  const EBAY_ID = 6
  const AMAZON_ID = 2
  const categoryId = store.categories.length + 1
  store.categories.push({
    id: categoryId,
    name: 'Retro Games',
    slug: 'retro-games',
    site_ids: [AMAZON_ID, EBAY_ID],
  })

  let itemId = lastItemId
  let listingId = lastListingId

  // --- Pokemon Emerald: best_match, eBay only -------------------------------
  itemId++
  const emeraldId = itemId
  store.items.push({
    id: emeraldId,
    category_id: categoryId,
    name: 'Pokemon Emerald (GBA)',
    target_cents: 12000,
    criteria:
      'Dry battery and damaged case preferred but not required — must be an authentic cartridge, cart-only is fine',
    selection_mode: 'best_match',
    max_listings: 5,
    site_ids: [EBAY_ID],
    created_at: NOW - 45 * DAY,
  })
  store.watches.push({ id: newId(), item_id: emeraldId, notify: true, target_cents: null })

  const EMERALD_LISTINGS: {
    title: string
    base: number
    score: number
    summary: string
    soldDaysAgo?: number
  }[] = [
    {
      title: 'Pokemon Emerald Version (GBA) Authentic — Dry Battery, Damaged Label',
      base: 11800,
      score: 91,
      summary: 'dry battery ✓, damaged case ✓, authentic ✓ — cart only',
    },
    {
      title: 'Pokemon Emerald GBA Genuine Cartridge, Worn Shell, Saves OK',
      base: 12900,
      score: 84,
      summary: 'damaged case ✓, battery recently replaced ✗, authentic ✓',
    },
    {
      title: 'Pokemon Emerald — Authentic, Tested, Original Save Battery',
      base: 14500,
      score: 72,
      summary: 'dry battery likely ○, case near-mint ✗, authentic ✓',
    },
    {
      title: 'Pokemon Emerald Version Complete In Box, Authentic',
      base: 19900,
      score: 58,
      summary: 'CIB — mint case ✗, battery unknown ○, authentic ✓',
    },
    {
      title: 'Pokemon Emerald Cart Only — Dead Battery, Cracked Shell',
      base: 10900,
      score: 88,
      summary: 'dry battery ✓, damaged case ✓, authentic ✓',
      soldDaysAgo: 10,
    },
  ]

  const ebay = store.sites.find((s) => s.id === EBAY_ID)!
  for (const spec of EMERALD_LISTINGS) {
    listingId++
    store.listings.push({
      id: listingId,
      item_id: emeraldId,
      site_id: EBAY_ID,
      url: `${ebay.base_url}/itm/${180000000 + listingId * 137}`,
      title: spec.title,
      site_sku: null,
      active: spec.soldDaysAgo == null,
      match_score: spec.score,
      match_summary: spec.summary,
      created_at: NOW - Math.floor(15 + rng() * 30) * DAY,
      discovered_by_run_id: 901,
    })
    generateChecks(listingId, spec.base, 0xeade + listingId * 11, spec.soldDaysAgo ?? 0, spec.soldDaysAgo != null ? 'sold' : undefined)
  }

  // --- GameCube Controller: plain cheapest-mode contrast --------------------
  itemId++
  store.items.push({
    id: itemId,
    category_id: categoryId,
    name: 'GameCube Controller (OEM)',
    target_cents: 3000,
    criteria: null,
    selection_mode: 'cheapest',
    max_listings: 5,
    site_ids: null,
    created_at: NOW - 60 * DAY,
  })
  store.watches.push({ id: newId(), item_id: itemId, notify: false, target_cents: null })

  const gcSites = [EBAY_ID, AMAZON_ID]
  for (const [i, siteId] of gcSites.entries()) {
    listingId++
    const site = store.sites.find((s) => s.id === siteId)!
    store.listings.push({
      id: listingId,
      item_id: itemId,
      site_id: siteId,
      url: siteId === EBAY_ID ? `${site.base_url}/itm/${180000000 + listingId * 137}` : `${site.base_url}/p/gamecube-controller-oem`,
      title: i === 0 ? 'Nintendo GameCube Controller OEM Indigo — Tested' : 'GameCube Controller (Official Nintendo, Renewed)',
      site_sku: null,
      active: true,
      match_score: null,
      match_summary: null,
      created_at: NOW - Math.floor(20 + rng() * 40) * DAY,
      discovered_by_run_id: null,
    })
    generateChecks(listingId, 3999 + i * 600, 0xcafe + listingId * 13)
  }
}

function seedHistoricalRuns() {
  // a couple of finished historical runs for the runs page
  const historicalRun = (idOffset: number, daysAgo: number, scope_label: string): MockRun => ({
    id: 900 + idOffset,
    scope: idOffset % 2 === 0 ? 'global' : 'category',
    scope_id: idOffset % 2 === 0 ? null : 1,
    scope_label,
    status: 'succeeded',
    started_at: NOW - daysAgo * DAY,
    finished_at: NOW - daysAgo * DAY + 4 * 60_000,
    stats: {
      listings_checked: 40 + Math.floor(rng() * 20),
      prices_found: 38 + Math.floor(rng() * 18),
      new_listings: Math.floor(rng() * 3),
      errors: Math.floor(rng() * 2),
    },
    error: null,
    created_at: NOW - daysAgo * DAY,
    last_seq: 0,
  })
  store.runs.push(historicalRun(0, 1, 'Everything'), historicalRun(1, 2, 'Category: GPUs'), historicalRun(2, 4, 'Everything'))
}

seed()

// --- shared query helpers (used by handlers) --------------------------------------

export const cents = (c: number | null): string | null => (c == null ? null : (c / 100).toFixed(2))

export function checksFor(listingId: number): MockCheck[] {
  return store.checks
    .filter((c) => c.listing_id === listingId)
    .sort((a, b) => a.ts - b.ts)
}

export function latestCheck(listingId: number): MockCheck | null {
  let best: MockCheck | null = null
  for (const c of store.checks) {
    if (c.listing_id === listingId && c.price_cents != null && (!best || c.ts > best.ts)) best = c
  }
  return best
}

export function itemListings(itemId: number): MockListing[] {
  return store.listings.filter((l) => l.item_id === itemId)
}

export function activeListings(itemId: number): MockListing[] {
  return itemListings(itemId).filter((l) => l.active)
}

export function bestPriceCents(itemId: number): { cents: number; listing: MockListing } | null {
  let best: { cents: number; listing: MockListing } | null = null
  for (const l of activeListings(itemId)) {
    const check = latestCheck(l.id)
    if (check?.price_cents != null && (!best || check.price_cents < best.cents)) {
      best = { cents: check.price_cents, listing: l }
    }
  }
  return best
}

export function avgPriceCents(itemId: number): number | null {
  const prices = activeListings(itemId)
    .map((l) => latestCheck(l.id)?.price_cents)
    .filter((p): p is number => p != null)
  if (prices.length === 0) return null
  return Math.round(prices.reduce((a, b) => a + b, 0) / prices.length)
}

export function effectiveTargetCents(itemId: number): number | null {
  const watch = store.watches.find((w) => w.item_id === itemId)
  if (watch?.target_cents != null) return watch.target_cents
  return store.items.find((i) => i.id === itemId)?.target_cents ?? null
}

export function targetMet(itemId: number): boolean {
  const target = effectiveTargetCents(itemId)
  const best = bestPriceCents(itemId)
  return target != null && best != null && best.cents <= target
}

/**
 * Downsample checks to ≤ points, preserving first, last, and the range's
 * min/max (good enough for mocks; the real backend uses LTTB).
 */
export function downsample(checks: MockCheck[], points: number): MockCheck[] {
  const priced = checks.filter((c) => c.price_cents != null)
  if (priced.length <= points) return priced
  const keep = new Set<number>()
  keep.add(0)
  keep.add(priced.length - 1)
  let minIdx = 0
  let maxIdx = 0
  priced.forEach((c, i) => {
    if (c.price_cents! < priced[minIdx].price_cents!) minIdx = i
    if (c.price_cents! > priced[maxIdx].price_cents!) maxIdx = i
  })
  keep.add(minIdx)
  keep.add(maxIdx)
  const stride = priced.length / (points - keep.size)
  for (let i = 0; i < priced.length; i += stride) keep.add(Math.floor(i))
  return [...keep]
    .sort((a, b) => a - b)
    .slice(0, points)
    .map((i) => priced[i])
}

/** Best-price-per-bucket sparkline over a range (numbers = cents, null = no data). */
export function sparkline(itemId: number, rangeMs: number, buckets = 30): (number | null)[] {
  const listings = activeListings(itemId)
  if (listings.length === 0) return []
  const start = rangeMs === Number.POSITIVE_INFINITY ? NOW - 365 * DAY : NOW - rangeMs
  const width = (NOW - start) / buckets
  const out: (number | null)[] = new Array(buckets).fill(null)
  for (const l of listings) {
    for (const c of store.checks) {
      if (c.listing_id !== l.id || c.price_cents == null || c.ts < start) continue
      const b = Math.min(buckets - 1, Math.floor((c.ts - start) / width))
      if (out[b] == null || c.price_cents < out[b]!) out[b] = c.price_cents
    }
  }
  return out
}

/** Best price at-or-before a timestamp (for range pct-change). */
export function bestPriceAt(itemId: number, ts: number): number | null {
  let best: number | null = null
  for (const l of activeListings(itemId)) {
    let latest: MockCheck | null = null
    for (const c of store.checks) {
      if (c.listing_id === l.id && c.price_cents != null && c.ts <= ts && (!latest || c.ts > latest.ts)) {
        latest = c
      }
    }
    if (latest?.price_cents != null && (best == null || latest.price_cents < best)) best = latest.price_cents
  }
  return best
}
