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
  /** vision thresholds as 0–1 decimal strings (always resolved) */
  vision_auto_reject_fake: string
  vision_auto_promote_real: string
  vision_auto_promote_fake: string
  created_at: number
}

/** Shipped vision-threshold defaults — spread into every new user. */
export const VISION_DEFAULTS = {
  vision_auto_reject_fake: '0.85',
  vision_auto_promote_real: '0.90',
  vision_auto_promote_fake: '0.90',
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
  /** set by the hunter's circuit breaker; null = not paused */
  paused_until: number | null
  paused_reason: string | null
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
  /** optional so existing fixtures follow the instance default (null) */
  recheck_interval_minutes?: number | null
  /** optional so existing fixtures hunt on their own (true) */
  hunt?: boolean
  site_ids: number[] | null
  created_at: number
}

export interface MockAuthenticity {
  verdict: 'leans_real' | 'leans_fake' | 'inconclusive'
  fake_confidence: string | null
  image_count: number
  checked_at: number
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
  /** optional so existing fixtures default to "never scanned" (null) */
  authenticity?: MockAuthenticity | null
  created_at: number
  discovered_by_job_id: number | null
}

export interface MockReference {
  id: number
  item_id: number
  label: 'real' | 'fake'
  variant_tag: string | null
  provenance: 'human' | 'upload' | 'auto'
  object_key: string
  source_listing_url: string | null
  captured_by: number | null
  revoked: boolean
  created_at: number
}

export interface MockQueueEntry {
  id: number
  item_id: number
  /** owner of the capturing watch — the ONLY user whose queue shows it (D-V11) */
  user_id: number
  object_key: string
  listing_url: string
  suggested_label: 'real' | 'fake'
  /** 0–1 decimal string backing the suggestion */
  confidence: string
  llm_authenticity_read: 'looks_authentic' | 'suspect' | 'unsure' | null
  /** confirmed entries stay for the 409 already_reviewed case; discards delete */
  review_state: 'suggested' | 'confirmed'
  created_at: number
}

export interface MockCheck {
  id: number
  listing_id: number
  ts: number
  price_cents: number | null
  in_stock: boolean
  status: string
  method: string
  confirmed: boolean
}

export interface MockWatch {
  id: number
  item_id: number
  user_id: number
  notify: boolean
  target_cents: number | null
}

export interface MockJobStats {
  listings_checked: number
  prices_found: number
  new_listings: number
  errors: number
  tokens_in: number
  tokens_out: number
  duration_ms: number | null
  method: string | null
  transport: 'static' | 'browser' | null
}

export interface MockJob {
  id: number
  kind: 'hunt' | 'recheck' | 'ground'
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
  /** null = the hunter queued it itself; shown as "system" */
  user_id: number | null
  watch_id: number | null
  item_id: number | null
  site_id: number | null
  listing_id: number | null
  priority: number
  run_after: number
  attempts: number
  started_at: number | null
  finished_at: number | null
  error: string | null
  stats: MockJobStats | null
  reason: 'user' | 'created' | 'slot_freed' | 'sweep' | 'paused' | 'backoff' | null
  /** a hunt chain's state: how long this hunt waited after the last came back empty */
  payload?: { backoff_minutes: number } | null
  last_seq: number
  created_at: number
}

export interface MockJobEvent {
  job_id: number
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

export interface MockNotificationChannel {
  id: number
  user_id: number
  kind: 'ntfy' | 'webhook' | 'discord'
  name: string
  url: string | null
  topic: string | null
  /** webhook signing secret; serialized only as has_secret (echoed once at create) */
  secret: string | null
  events: ('target.hit' | 'listing.new')[] | null
  enabled: boolean
  created_at: number
}

/** The raw token is never stored — the mock, like the backend, only ever echoes
 *  it in the create response. */
export interface MockApiToken {
  id: number
  user_id: number
  name: string
  scopes: ('read' | 'write' | 'jobs')[]
  expires_at: number | null
  last_used_at: number | null
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
  jobs: [] as MockJob[],
  jobEvents: [] as MockJobEvent[],
  invites: [] as MockInvite[],
  notificationChannels: [] as MockNotificationChannel[],
  tokens: [] as MockApiToken[],
  references: [] as MockReference[],
  visionQueue: [] as MockQueueEntry[],
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
      // the listing's oldest check is the discovery read, which is always the
      // model; everything after it replays the locator that read taught us
      method: day === 365 ? 'llm' : day % 7 === 0 ? 'locator' : 'jsonld',
      confirmed: true,
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
      method: 'locator',
      confirmed: true,
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
    ...VISION_DEFAULTS,
    created_at: NOW - 200 * DAY,
  })
  // second, non-admin account for the runs-privacy surfaces (see seedGuestWatches)
  store.users.push({
    id: 2,
    email: 'guest@snagr.dev',
    password: 'snagr',
    role: 'user',
    is_active: true,
    ...VISION_DEFAULTS,
    created_at: NOW - 100 * DAY,
  })

  store.notificationChannels.push(
    {
      id: 1,
      user_id: 1,
      kind: 'ntfy',
      name: 'ntfy',
      url: null,
      topic: 'snagr-demo-8f3a',
      secret: null,
      events: null,
      enabled: true,
      created_at: NOW - 60 * DAY,
    },
    {
      id: 2,
      user_id: 1,
      kind: 'discord',
      name: 'deals channel',
      url: 'https://discord.com/api/webhooks/1234567890/mock-token',
      topic: null,
      secret: null,
      events: ['target.hit'],
      enabled: true,
      created_at: NOW - 30 * DAY,
    },
  )

  // and one agent already connected, so the MCP & API tab isn't empty
  store.tokens.push({
    id: 1,
    user_id: 1,
    name: 'claude code (laptop)',
    scopes: ['read', 'write'],
    expires_at: null,
    last_used_at: NOW - 2 * 3_600_000,
    created_at: NOW - 12 * DAY,
  })

  store.sites = SITES.map(([name, base_url], i) => ({
    id: i + 1,
    name,
    base_url,
    paused_until: null,
    paused_reason: null,
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
      store.watches.push({ id: newId(), item_id: itemId, user_id: 1, notify: rng() > 0.3, target_cents: null })

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
          // Items seeded past the 5-slot cap: cheapest mode keeps the cheapest
          // copies tracked, so the pricey Used ones sit inactive.
          active: seedItem.listings <= 5 || !(VARIANTS[l] ?? '').includes('Used'),
          match_score: null,
          match_summary: null,
          created_at: NOW - Math.floor(20 + rng() * 140) * DAY,
          discovered_by_job_id: null,
        })
        generateChecks(listingId, seedItem.base, 0xbeef + listingId * 7)
      }
    }
  }

  seedRetroGames(itemId, listingId)

  seedGuestWatches()

  seedJobs()

  seedVisionLibrary()
}

/**
 * The vision showcase: Pokemon Emerald gets a lived-in reference library
 * (mixed provenance, one variant tag, one revoked), pending review-queue
 * entries for the demo user, and authenticity reads on a couple of its
 * listings. The guest gets one queue entry of their own — invisible to the
 * demo user, proving the D-V11 scoping. Everything else stays unscanned.
 */
function seedVisionLibrary() {
  const emerald = store.items.find((i) => i.name === 'Pokemon Emerald (GBA)')!
  const gamecube = store.items.find((i) => i.name === 'GameCube Controller (OEM)')!
  const sony = store.items.find((i) => i.name === 'Sony WH-1000XM5')!
  const ebay = store.sites.find((s) => s.name === 'ebay.com')!

  const ref = (
    item_id: number,
    label: MockReference['label'],
    provenance: MockReference['provenance'],
    overrides: Partial<MockReference> = {},
  ) => {
    store.references.push({
      id: newId(),
      item_id,
      label,
      variant_tag: null,
      provenance,
      object_key: `k${(nextId * 2654435761) % 0xffffffff}`.padEnd(12, '0'),
      source_listing_url:
        provenance === 'upload' ? null : `${ebay.base_url}/itm/${170000000 + nextId * 91}`,
      captured_by: 1,
      revoked: false,
      created_at: NOW - Math.floor(5 + rng() * 40) * DAY,
      ...overrides,
    })
  }

  ref(emerald.id, 'real', 'human')
  ref(emerald.id, 'real', 'human', { variant_tag: "Player's Choice label" })
  ref(emerald.id, 'real', 'upload')
  ref(emerald.id, 'fake', 'human')
  ref(emerald.id, 'fake', 'human')
  ref(emerald.id, 'fake', 'auto')
  ref(emerald.id, 'real', 'auto', { revoked: true })
  ref(gamecube.id, 'real', 'upload')

  const queue = (
    item_id: number,
    user_id: number,
    suggested_label: MockQueueEntry['suggested_label'],
    confidence: string,
    llm: MockQueueEntry['llm_authenticity_read'],
  ) => {
    store.visionQueue.push({
      id: newId(),
      item_id,
      user_id,
      object_key: `q${(nextId * 2246822519) % 0xffffffff}`.padEnd(12, '0'),
      listing_url: `${ebay.base_url}/itm/${190000000 + nextId * 53}`,
      suggested_label,
      confidence,
      llm_authenticity_read: llm,
      review_state: 'suggested',
      created_at: NOW - Math.floor(rng() * 5) * DAY,
    })
  }

  queue(emerald.id, 1, 'fake', '0.82', 'suspect')
  queue(emerald.id, 1, 'real', '0.88', 'looks_authentic')
  queue(sony.id, 2, 'fake', '0.86', 'unsure') // the guest's — never in demo's queue

  // authenticity reads on the Emerald listings: the top match leans real,
  // the CIB one leans fake just under the 0.85 auto-reject default
  const emeraldListings = store.listings
    .filter((l) => l.item_id === emerald.id)
    .sort((a, b) => (b.match_score ?? 0) - (a.match_score ?? 0))
  emeraldListings[0].authenticity = {
    verdict: 'leans_real',
    fake_confidence: '0.08',
    image_count: 3,
    checked_at: NOW - 2 * DAY,
  }
  emeraldListings.at(-1)!.authenticity = {
    verdict: 'leans_fake',
    fake_confidence: '0.72',
    image_count: 2,
    checked_at: NOW - 1 * DAY,
  }
}

/**
 * The guest's watches, for the runs-privacy demo: one item of their own plus a
 * shared watch on an item the demo user also tracks. Only the runs/SSE
 * surfaces are per-user in this mock — items/watches endpoints stay
 * single-user, so the guest's items pages still show everything.
 */
function seedGuestWatches() {
  const own = store.items.find((i) => i.name === 'Sony WH-1000XM5')!
  store.watches.find((w) => w.item_id === own.id)!.user_id = 2

  const shared = store.items.find((i) => i.name === 'RTX 4070 Super')!
  store.watches.push({ id: newId(), item_id: shared.id, user_id: 2, notify: true, target_cents: null })
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
  store.watches.push({ id: newId(), item_id: emeraldId, user_id: 1, notify: true, target_cents: null })

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
      discovered_by_job_id: null,
    })
    generateChecks(listingId, spec.base, 0xeade + listingId * 11, spec.soldDaysAgo ?? 0, spec.soldDaysAgo != null ? 'sold' : undefined)
  }

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
  store.watches.push({ id: newId(), item_id: itemId, user_id: 1, notify: false, target_cents: null })

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
      discovered_by_job_id: null,
    })
    generateChecks(listingId, 3999 + i * 600, 0xcafe + listingId * 13)
  }
}

const HOUR = 3_600_000
const MINUTE = 60_000

function jobStats(over: Partial<MockJobStats> = {}): MockJobStats {
  return {
    listings_checked: 0,
    prices_found: 0,
    new_listings: 0,
    errors: 0,
    tokens_in: 0,
    tokens_out: 0,
    duration_ms: null,
    method: null,
    transport: null,
    ...over,
  }
}

/** Every (watch, site) pair the hunter could work — a watch with no pinned
 *  subset hunts every site its category is linked to. */
function huntPairs(): { watch: MockWatch; item: MockItem; siteId: number }[] {
  const pairs: { watch: MockWatch; item: MockItem; siteId: number }[] = []
  for (const watch of store.watches) {
    const item = store.items.find((i) => i.id === watch.item_id)!
    const category = store.categories.find((c) => c.id === item.category_id)!
    for (const siteId of item.site_ids ?? category.site_ids) pairs.push({ watch, item, siteId })
  }
  return pairs
}

/**
 * The hunter's ledger and its queue.
 *
 * Three days of finished work — ~20 hunts and ~200 rechecks — so History
 * paginates and the Checks filter has rows to debug a site with. Then the
 * queue the live page reads: one pending recheck per active listing spread
 * over the next half hour, a pending hunt for every watch with an open slot,
 * and a grounding job. One site is paused so the breaker's surfaces (banner,
 * ticker state, "waiting for eBay to resume") are reachable without waiting
 * for a demo hunt to trip it.
 */
function seedJobs() {
  const paused = store.sites.find((s) => s.name === 'ebay.com')!
  paused.paused_until = NOW + HOUR
  paused.paused_reason = '5 consecutive read errors: challenge page'

  const pairs = huntPairs()
  const pushJob = (job: MockJob): MockJob => {
    store.jobs.push(job)
    return job
  }

  const finishedHunt = (
    watch: MockWatch,
    item: MockItem,
    siteId: number,
    over: Partial<MockJob> = {},
  ): MockJob => {
    const startedAt = NOW - Math.floor(1 + rng() * 70) * HOUR
    const duration = 20_000 + Math.floor(rng() * 45_000)
    const seen = 3 + Math.floor(rng() * 4)
    const found = rng() < 0.3 ? 1 + Math.floor(rng() * 2) : 0
    return pushJob({
      id: newId(),
      kind: 'hunt',
      status: 'done',
      user_id: watch.user_id,
      watch_id: watch.id,
      item_id: item.id,
      site_id: siteId,
      listing_id: null,
      priority: 0,
      run_after: startedAt - MINUTE,
      attempts: 1,
      started_at: startedAt,
      finished_at: startedAt + duration,
      error: null,
      stats: jobStats({
        listings_checked: seen,
        prices_found: found,
        new_listings: found,
        tokens_in: 7000 + Math.floor(rng() * 8000),
        tokens_out: 400 + Math.floor(rng() * 900),
        duration_ms: duration,
      }),
      reason: 'sweep',
      last_seq: 0,
      created_at: startedAt - MINUTE,
      ...over,
    })
  }

  for (let i = 0; i < 18; i++) {
    const { watch, item, siteId } = pairs[(i * 5) % pairs.length]
    // one system hunt every few rows: nobody asked, the hunter queued itself
    finishedHunt(watch, item, siteId, i % 6 === 0 ? { user_id: null } : {})
  }

  // one hunt the breaker killed, and one the owner cancelled mid-flight
  const failedPair = pairs.find((pair) => pair.siteId === paused.id) ?? pairs[0]
  const failedAt = NOW - 75 * MINUTE
  pushJob({
    id: newId(),
    kind: 'hunt',
    status: 'failed',
    user_id: failedPair.watch.user_id,
    watch_id: failedPair.watch.id,
    item_id: failedPair.item.id,
    site_id: failedPair.siteId,
    listing_id: null,
    priority: 100,
    run_after: failedAt - MINUTE,
    attempts: 3,
    started_at: failedAt,
    finished_at: failedAt + 12_000,
    error: `${paused.name} answered a challenge page instead of the listing.`,
    stats: jobStats({ errors: 1, duration_ms: 12_000 }),
    reason: 'user',
    last_seq: 0,
    created_at: failedAt - MINUTE,
  })

  const cancelledPair = pairs[2]
  const cancelledAt = NOW - 100 * MINUTE
  pushJob({
    id: newId(),
    kind: 'hunt',
    status: 'cancelled',
    user_id: cancelledPair.watch.user_id,
    watch_id: cancelledPair.watch.id,
    item_id: cancelledPair.item.id,
    site_id: cancelledPair.siteId,
    listing_id: null,
    priority: 100,
    run_after: cancelledAt - MINUTE,
    attempts: 1,
    started_at: cancelledAt,
    finished_at: cancelledAt + 9_000,
    error: null,
    stats: jobStats({ listings_checked: 1, tokens_in: 1800, tokens_out: 200, duration_ms: 9_000 }),
    reason: 'user',
    last_seq: 0,
    created_at: cancelledAt - MINUTE,
  })

  seedShowcaseHunt()
  seedFinishedChecks()
  seedQueue()
}

/**
 * The hunt the job page is built to show: the criteria-driven item's eBay
 * hunt, with the listings it discovered pointing back at it and the event log
 * a reader actually learns something from.
 */
function seedShowcaseHunt() {
  const item = store.items.find((i) => i.name === 'Pokemon Emerald (GBA)')!
  const watch = store.watches.find((w) => w.item_id === item.id)!
  const site = store.sites.find((s) => s.name === 'ebay.com')!
  const startedAt = NOW - 4 * HOUR
  const duration = 48_000
  const listings = itemListings(item.id)

  const job: MockJob = {
    id: newId(),
    kind: 'hunt',
    status: 'done',
    user_id: watch.user_id,
    watch_id: watch.id,
    item_id: item.id,
    site_id: site.id,
    listing_id: null,
    priority: 100,
    run_after: startedAt - MINUTE,
    attempts: 1,
    started_at: startedAt,
    finished_at: startedAt + duration,
    error: null,
    stats: jobStats({
      listings_checked: 4,
      prices_found: 2,
      new_listings: 2,
      tokens_in: 11_400,
      tokens_out: 1_000,
      duration_ms: duration,
    }),
    reason: 'user',
    last_seq: 0,
    created_at: startedAt - MINUTE,
  }
  store.jobs.push(job)
  for (const listing of listings) listing.discovered_by_job_id = job.id

  const saved = listings.find((l) => l.active)!
  const price = latestCheck(saved.id)?.price_cents ?? 11800
  const push = (
    level: MockJobEvent['level'],
    event_type: string,
    message: string,
    payload: Record<string, unknown> | null = null,
  ) => {
    job.last_seq += 1
    store.jobEvents.push({
      job_id: job.id,
      seq: job.last_seq,
      ts: startedAt + job.last_seq * 6_000,
      level,
      event_type,
      message,
      payload,
    })
  }

  push('info', 'job_started', `Hunting ${site.name} for "${item.name}" — 3 open slots, best match mode`)
  push('info', 'listing_check', `Searched "${item.name.toLowerCase()}" · 6 results, 2 already tracked`)
  push('info', 'listing_evaluated', `Skipped "Pokemon Emerald repro cart" — reproduction, not authentic (match 12)`, {
    item_id: item.id,
    url: `${site.base_url}/itm/181000001`,
    title: 'Pokemon Emerald repro cart',
    match_score: 12,
    match_summary: 'reproduction, not authentic',
    tracked: false,
  })
  push('success', 'price_found', `Price read $${(price / 100).toFixed(2)} · in stock · "${saved.title}" (match ${saved.match_score})`, {
    listing_id: saved.id,
    item_id: item.id,
    price: (price / 100).toFixed(2),
  })
  push('success', 'listing_discovered', `Saved as listing #${saved.id} — 3 of 5 slots filled · locator learned (jsonld) · static ok`, {
    listing_id: saved.id,
    item_id: item.id,
  })
  push('success', 'job_finished', `Hunt complete — 2 new · 4 seen · 3 slots left · 11.4k tokens`)
}

/** ~200 finished rechecks over three days — the Checks filter's rows. */
function seedFinishedChecks() {
  const METHODS: [string, 'static' | 'browser'][] = [
    ['jsonld', 'static'],
    ['jsonld', 'browser'],
    ['locator', 'browser'],
    ['meta', 'static'],
    ['llm', 'browser'],
  ]
  const tracked = store.listings.filter((l) => l.active)
  for (let i = 0; i < 200; i++) {
    const listing = tracked[i % tracked.length]
    const watch = store.watches.find((w) => w.item_id === listing.item_id)!
    const [method, transport] = METHODS[i % METHODS.length]
    const startedAt = NOW - Math.floor(1 + rng() * 71) * HOUR
    const duration = transport === 'static' ? 300 + Math.floor(rng() * 900) : 1_200 + Math.floor(rng() * 2_500)
    store.jobs.push({
      id: newId(),
      kind: 'recheck',
      status: 'done',
      user_id: null,
      watch_id: watch.id,
      item_id: listing.item_id,
      site_id: listing.site_id,
      listing_id: listing.id,
      priority: 0,
      run_after: startedAt,
      attempts: 1,
      started_at: startedAt,
      finished_at: startedAt + duration,
      error: null,
      stats: jobStats({
        listings_checked: 1,
        prices_found: 1,
        tokens_in: method === 'llm' ? 3_200 : 0,
        tokens_out: method === 'llm' ? 180 : 0,
        duration_ms: duration,
        method,
        transport,
      }),
      reason: null,
      last_seq: 0,
      created_at: startedAt,
    })
  }
}

/** What the hunter will do next: the pending rows the live page reads. */
function seedQueue() {
  const paused = store.sites.find((s) => s.name === 'ebay.com')!

  // one pending recheck per active listing, spread over the next half hour —
  // a site that is paused waits for its pause to lift instead
  for (const [i, listing] of store.listings.filter((l) => l.active).entries()) {
    const watch = store.watches.find((w) => w.item_id === listing.item_id)!
    const due =
      listing.site_id === paused.id ? paused.paused_until! : NOW + 42_000 + i * 28_000
    store.jobs.push({
      id: newId(),
      kind: 'recheck',
      status: 'pending',
      user_id: null,
      watch_id: watch.id,
      item_id: listing.item_id,
      site_id: listing.site_id,
      listing_id: listing.id,
      priority: 0,
      run_after: due,
      attempts: 0,
      started_at: null,
      finished_at: null,
      error: null,
      stats: null,
      reason: listing.site_id === paused.id ? 'paused' : null,
      last_seq: 0,
      created_at: NOW - 28 * MINUTE,
    })
  }

  // one watch hunted only when asked — the item page's "hunting off" state
  store.items.find((i) => i.name === 'Retroid Pocket 5')!.hunt = false

  // a hunt waiting for every watch that still has room for another listing
  // and hunts on its own; the first to come back empty is backing off
  let backingOff = false
  for (const { watch, item, siteId } of huntPairs()) {
    if (activeListings(item.id).length >= item.max_listings) continue
    if (item.hunt === false) continue
    if (store.jobs.some((j) => j.kind === 'hunt' && j.watch_id === watch.id && j.status === 'pending')) {
      continue
    }
    const onPaused = siteId === paused.id
    const backoff: boolean = !onPaused && !backingOff
    backingOff ||= backoff
    store.jobs.push({
      id: newId(),
      kind: 'hunt',
      status: 'pending',
      user_id: null,
      watch_id: watch.id,
      item_id: item.id,
      site_id: siteId,
      listing_id: null,
      priority: 0,
      run_after: onPaused
        ? paused.paused_until!
        : backoff
          ? NOW + 5 * MINUTE // queued an hour out, 55 minutes ago
          : NOW + 10 * MINUTE + item.id * MINUTE,
      attempts: 0,
      started_at: null,
      finished_at: null,
      error: null,
      stats: null,
      reason: onPaused ? 'paused' : backoff ? 'backoff' : 'sweep',
      payload: backoff ? { backoff_minutes: 60 } : null,
      last_seq: 0,
      created_at: NOW - 40 * MINUTE,
    })
  }

  // market stats go stale on their own; one refresh is always due next
  const grounded = store.items[0]
  store.jobs.push({
    id: newId(),
    kind: 'ground',
    status: 'pending',
    user_id: null,
    watch_id: null,
    item_id: grounded.id,
    site_id: null,
    listing_id: null,
    priority: 0,
    run_after: NOW + 2 * HOUR,
    attempts: 0,
    started_at: null,
    finished_at: null,
    error: null,
    stats: null,
    reason: 'sweep',
    last_seq: 0,
    created_at: NOW - 10 * MINUTE,
  })

  seedDisbelievedCheck()
}

/**
 * One reading the plausibility bands rejected, so the disbelieved row is
 * reachable in mock mode. Deliberately absurd — a tenth of the listing's real
 * price, the "$4.49 for a $449 item" case the confirm rule exists for. It
 * shows in the checks log and in nothing else: no chart, no average, no best
 * price, and in the real system no notification.
 */
function seedDisbelievedCheck() {
  const item = store.items.find((i) => i.name === 'RTX 4070 Super')!
  const listing = store.listings.find((l) => l.item_id === item.id)!
  const last = latestCheck(listing.id)
  store.checks.push({
    id: newId(),
    listing_id: listing.id,
    ts: NOW - 3 * 3_600_000,
    price_cents: Math.round((last?.price_cents ?? 59999) / 10),
    in_stock: true,
    status: 'ok',
    method: 'llm',
    confirmed: false,
  })
}

seed()

// --- per-user job visibility (jobs/SSE surfaces only) -----------------------------

/**
 * A viewer sees jobs for their own watches, `ground` jobs for items they
 * watch, and — as admin — everything. A hidden job must behave exactly like a
 * nonexistent one (404, absent from lists) so its existence never leaks.
 *
 * Unlike a run, a job belongs to one watch, so there is no event-level rule:
 * seeing the job is seeing its events.
 */
export function jobVisible(job: MockJob, user: MockUser): boolean {
  if (user.role === 'admin') return true
  if (job.watch_id != null) {
    return store.watches.some((w) => w.id === job.watch_id && w.user_id === user.id)
  }
  if (job.item_id != null) {
    return store.watches.some((w) => w.item_id === job.item_id && w.user_id === user.id)
  }
  return false
}

// --- shared query helpers (used by handlers) --------------------------------------

export const cents = (c: number | null): string | null => (c == null ? null : (c / 100).toFixed(2))

/**
 * Every BELIEVED check for a listing, oldest first. Unconfirmed readings are
 * excluded here and in latestCheck, matching the backend: a price the
 * plausibility bands rejected is shown in the checks log but never counted in
 * a chart, an average or a "best price". The log reads store.checks directly.
 */
export function checksFor(listingId: number): MockCheck[] {
  return store.checks
    .filter((c) => c.listing_id === listingId && c.confirmed)
    .sort((a, b) => a.ts - b.ts)
}

export function latestCheck(listingId: number): MockCheck | null {
  let best: MockCheck | null = null
  for (const c of store.checks) {
    if (
      c.listing_id === listingId &&
      c.confirmed &&
      c.price_cents != null &&
      (!best || c.ts > best.ts)
    )
      best = c
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
