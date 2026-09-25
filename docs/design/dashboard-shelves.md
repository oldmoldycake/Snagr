# Dashboard shelves: the contract for the home-screen rework

Design-pass output for reworking the dashboard around categories. The prototype is the
artifact <https://claude.ai/artifact/GWqTnA6LGg3jGuhToScHXQ> (v4). A copy is in
`dashboard-shelves/prototype.html`: open it in a browser. The switches at the top pick the
scenario, shelf motion and dialog style, and the defaults are the approved options.
Screenshots are in `dashboard-shelves/`. **This file is the contract**: the components,
states, motion, copy and rules below are what the frontend builds. Where the prototype and
this file differ, this file wins. The known differences are called out inline.

Approved by the user on 2026-09-25: shelf motion **A · Drawer** and dialog style
**A · Field card** ("I like the A and A right now").

**Frontend only.** No backend, agent, API contract, `types.ts` or `handlers.ts` change is
needed. Every call used here already exists: `createCategory`, `setCategorySites`,
`createSite`, `createItem`, `listCategories`, `listSites`, `listItems`, and `enqueue` from
`useJobs`.

| Screenshot | What it shows |
|---|---|
| `home.png` | returning user: hero, one shared column-label strip, three open shelves (a no-sites shelf first), one-line rows for categories with none of your items |
| `home-many.png` | 10 shelves: the in-range and closest shelves start open, the rest collapsed with their one-line lead |
| `home-phone.png` | the same at 390 px |
| `first-run-empty.png` | fresh instance: the guide hero and the example shelf |
| `first-run-shared.png` | new user on an instance where others made categories |
| `first-run-ready.png` | right after creating the first category: step 2 of the guide |
| `new-category-name.png`, `new-category-sites.png` | the two-step New category dialog; the second shows the inline add-a-site form |
| `edit-sites.png` | the Sites dialog opened from a shelf |
| `add-item.png`, `add-item-phone.png` | the scoped Add item dialog with Tracking expanded; the phone bottom sheet |

---

## 1. Why

New users opened the dashboard, pressed **Add item**, and never made a category or linked a
site. The API already requires `category_id` on every item, but the home screen hides it:

- Add item is the amber primary button. "＋ category" is an 11 px ghost chip.
- The watch is one flat table. The category is small text under the item name.
- The "no linked sites" warning sits inside Add item's collapsed Tracking options.
- Linking sites takes three pages: Sites page → category page → pencil → dialog.
- The first-run empty state shows only when the **instance** has zero categories.
  Categories and sites are shared (`item_count` is instance-wide, see
  `backend/app/services/catalog.py`), so every user after the first skips it.

## 2. The shape, in one paragraph

The dashboard's flat watch table becomes one **shelf** per category that holds your items.
A shelf is a collapsible card: the header shows the name, your item count, "⌖ N in range",
and, when collapsed, one lead line that stands in for the hidden rows. It also has a site
count, one action (**＋ Add item**, or **Link sites** when the category has no sites) and a
⋯ menu. The open body shows the sites it searches (clicking them edits them), the existing
`WatchList` rows, and a footer that links to the category page. Categories holding none of
your items become one-line rows under the shelves. **＋ New category** is the only amber
button. It opens a two-step dialog: a name, then the sites, with an inline form to add a
site that isn't listed. **Items are only ever added from a shelf** (or a category page).
Until you have an item, the verdict hero becomes a **guide hero** that walks you through
① create a category → ② add items to it.

## 3. Decisions (settled; don't re-litigate)

1. **Shelves**, not a category rail or a flat table. They are ordered by urgency, with no
   manual reorder:
   - no-sites shelves that hold items come first;
   - then shelves with an item in range (more in range first);
   - then by the closest item's distance to target;
   - then shelves with no prices yet;
   - ties are broken alphabetically.
2. **Shelves collapse.** Collapse state is per browser in localStorage, keyed by user. A
   new strike reopens a collapsed shelf. Details in §6.3.
3. **Categories and items stay separate steps.** New category makes the category and its
   sites and nothing else. The prototype's v2 "first item" step is gone.
4. **No global Add item.** The dashboard's `AddItemDialog` without a `categoryId` (the one
   with a category picker) is removed. `categoryId` becomes required.
5. **A category with no sites can't take new items from the UI.** Its Add item is replaced
   by **Link sites**, on shelves, one-line rows and the category page. The API still
   accepts the item; this is a UI guard only.
6. **New category requires at least one site.** Picking an existing site, or adding one
   inline, satisfies it.
7. **The guide hero replaces the zero-categories `EmptyState`.** It appears whenever *you*
   have no items. "X is ready" (step 2) is client state from the dialog that just ran:
   categories have no owner column, and adding one is out of scope. After a reload it
   falls back to "Pick a category, or make your own".
8. **`CategoryChips` leaves the dashboard** and stays on category pages. The range selector
   stays in the dashboard bar.
9. **Motion A · Drawer** (§6.4). No Lock-on scan line or brackets.
10. **Dialogs A · Field card** (§4) for every dialog in the app. No side sheet or two-pane.
11. **One-line rows** show at most 5, then a "＋ N more categories" button that reveals the
    rest.
12. **Site names default to the host** (`facebook.com`), matching the existing naming
    (`fixtures.ts` uses `ebay.com`; the Sites page placeholder is `newegg.com`). *Differs
    from the prototype, which auto-fills "Facebook".*

## 4. Build order: three PRs, in this order

Each PR is branched off `main` and squash-merged with a conventional title (AGENTS.md →
Workflow). Each is independently shippable.

| # | PR title | Scope |
|---|---|---|
| 1 | `feat(frontend): field-card dialogs with enter and exit motion` | `dialog.tsx` + motion tokens; migrate every dialog to the header/body/footer slots. No behaviour change. |
| 2 | `feat(frontend): pick or add sites while creating a category` | `SitePicker`, the two-step `CreateCategoryDialog`, `EditSitesDialog`, `EditCategoryDialog` using the picker, `AddItemDialog` scoped-only with the Tracking row, the category-page no-sites guard. |
| 3 | `feat(frontend): category shelves and a guided first run on the dashboard` | `DashboardPage` rewrite, `CategoryShelf`, the shelf-state logic and hook, `GuideHero`, shelf motion and the strike cue. |

PR 3 depends on PR 2 (`EditSitesDialog`, scoped `AddItemDialog`, `CreateCategoryDialog`'s
`onCreated`), and PR 2 depends on PR 1 (dialog slots).

---

## 5. PR 1: field-card dialogs

### 5.1 `styles/globals.css`

Add to the existing `@theme` block. Keyframes go at top level, next to `@keyframes sweep`,
which is the existing precedent.

```css
  --ease-shelf: cubic-bezier(0.2, 0, 0, 1);
  --ease-shelf-in: cubic-bezier(0.4, 0, 0.2, 1);
  --ease-panel: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-sheet: cubic-bezier(0.32, 0.72, 0, 1);

  --animate-overlay-in: overlay-in 200ms cubic-bezier(0.2, 0, 0, 1) both;
  --animate-overlay-out: overlay-out 150ms cubic-bezier(0.4, 0, 1, 1) both;
  --animate-dialog-in: dialog-in 220ms var(--ease-panel) both;
  --animate-dialog-out: dialog-out 150ms ease-in both;
  --animate-sheet-up: sheet-up 280ms var(--ease-sheet) both;
  --animate-sheet-down: sheet-down 200ms ease-in both;
  --animate-step-fwd: step-fwd 180ms ease-out both;
  --animate-step-back: step-back 180ms ease-out both;
```

```css
@keyframes overlay-in { from { opacity: 0; } }
@keyframes overlay-out { to { opacity: 0; } }
@keyframes dialog-in { from { opacity: 0; transform: translateY(-8px) scale(0.98); } }
@keyframes dialog-out { to { opacity: 0; transform: scale(0.98); } }
@keyframes sheet-up { from { transform: translateY(100%); } }
@keyframes sheet-down { to { transform: translateY(100%); } }
@keyframes step-fwd { from { opacity: 0; transform: translateX(12px); } }
@keyframes step-back { from { opacity: 0; transform: translateX(-12px); } }
```

The existing reduced-motion rule (animations and transitions at .01ms) already covers these.
Radix `Presence` waits for `animationend` before unmounting, which is why exits are
keyframe animations, not transitions. Tailwind v4's `-translate-x-1/2` uses the `translate`
property, so it doesn't clash with keyframes that animate `transform`.

### 5.2 `components/ui/dialog.tsx`

- **Overlay:** `fixed inset-0 z-50 bg-[rgb(5_8_6/0.72)] data-[state=open]:animate-overlay-in data-[state=closed]:animate-overlay-out`.
- **Content** is a three-row grid (header / body / footer), anchored near the top rather
  than centred, so it only grows downward and never runs off the top:
  ```
  fixed top-[max(8vh,2rem)] left-1/2 z-50 grid w-[calc(100%-2rem)] max-w-[480px]
  max-h-[min(720px,calc(100dvh-4rem))] -translate-x-1/2 grid-rows-[auto_minmax(0,1fr)_auto]
  overflow-hidden rounded-lg border border-hairline-strong bg-overlay
  shadow-[0_24px_64px_-16px_rgb(0_0_0/0.8)] origin-top focus:outline-none
  data-[state=open]:animate-dialog-in data-[state=closed]:animate-dialog-out
  max-sm:top-auto max-sm:bottom-0 max-sm:left-0 max-sm:w-full max-sm:max-w-none
  max-sm:max-h-[92dvh] max-sm:translate-x-0 max-sm:rounded-b-none max-sm:rounded-t-xl
  max-sm:grid-rows-[auto_auto_minmax(0,1fr)_auto]
  max-sm:data-[state=open]:animate-sheet-up max-sm:data-[state=closed]:animate-sheet-down
  ```
  On phones, a decorative grab bar is the first child:
  `<div aria-hidden className="mx-auto mt-2 h-1 w-8 rounded-full bg-hairline-strong sm:hidden" />`.
  A wider dialog passes `className="max-w-[520px]"`; `cn` merges it.
- **Close ×** stays inside Content at `absolute top-3.5 right-3.5`, 28 px hit area.
- **New slots** (each a thin wrapper, following the existing `DialogFooter` pattern):
  - `DialogHeader`: `relative border-b border-hairline px-5 pt-[18px] pb-3.5 pr-12`.
  - `DialogEyebrow` (new): `font-mono text-[10.5px] tracking-[0.16em] uppercase text-ink-3`.
    It holds a label ("Add item", "Sites") or the step pips (§5.3).
  - `DialogTitle`: 20 px instead of 17. Keep uppercase, `tracking-[0.08em]`, and the
    display face. Add `mt-2` when it follows an eyebrow.
  - `DialogDescription`: `mt-1.5 text-[13px] text-ink-2`.
  - `DialogBody` (new): `overflow-y-auto overscroll-contain px-5 py-4`. **Only the body
    scrolls**, so the footer is always visible without `position: sticky`.
  - `DialogFooter`: `flex items-center justify-end gap-2 border-t border-hairline bg-black/10 px-5 py-3 max-sm:pb-[calc(0.75rem+env(safe-area-inset-bottom))] max-sm:*:h-10 max-sm:*:flex-1`.
    The primary button gets `max-sm:flex-[2]` at the call site. A Back button takes `mr-auto`.
- **Footer order:** Back (ghost, far left, only on step 2 of a wizard), then Cancel (ghost),
  then the primary button, always rightmost.

### 5.3 Step pips

Wizards show `① NAME → ② SITES` in the eyebrow, using the same pip treatment as the guide
hero (§6.6):

- **Current step:** amber (lume) text with an amber ring.
- **Finished step:** ✓ in `ink-2` with a hairline ring. **Never drop-green**, because green
  means a good price.
- **Other steps:** `ink-3`.

Build one small `StepPips` component in `components/ui/` and use it in both places. It has
two real callers, so the house rule for extracting a shared helper is met.

### 5.4 Migrate every dialog

Each dialog becomes `DialogHeader` (eyebrow? + title + description) → `DialogBody` →
`DialogFooter`. Dialogs that wrap their fields in a `<form>` wrap body and footer in
`<form className="contents">`, so both stay direct grid children and Enter still submits.
The callers:

- `components/ui/confirm-dialog.tsx`
- `features/categories/CreateCategoryDialog.tsx`
- `features/categories/EditCategoryDialog.tsx`
- `features/sites/SitesPage.tsx` (`SiteDialog`)
- `features/items/EditItemDialog.tsx`
- `features/items/AddItemDialog.tsx`
- `features/settings/AdminUsersPage.tsx`
- `features/settings/ApiSettingsPage.tsx`
- `features/settings/ChannelsCard.tsx`
- `features/vision/UploadReferenceDialog.tsx`

`grep -rl DialogContent frontend/src` is the source of truth. **No behaviour change in
PR 1**: same fields, same buttons, same disabled rules. Fold `SheetContent`'s overlay onto
the same `overlay-in/out` fade while you're in the file. It has no fade today.

### 5.5 Done when

`npm run build`, `npm run lint` and `npm test` are green. Every dialog in the list opens,
animates in, scrolls only its body when tall, closes with the exit animation, and returns
focus to its trigger, at 1280 px and at 390 px (bottom sheet). No pure logic changes, so no
new vitest.

---

## 6. PR 2: site picker, New category, Edit sites, Add item

### 6.1 `features/sites/siteUrl.ts` (pure) and `siteUrl.test.ts`

- `normalizeBaseUrl(input)`: trim; prepend `https://` when there's no scheme; drop a
  trailing `/`. `facebook.com/marketplace` → `https://facebook.com/marketplace`.
- `hostOf(url)`: the hostname without a leading `www.`.
- `isPlausibleUrl(input)`: the host has a dot and no spaces. This check is client-side
  only, because the backend accepts any string (`SiteCreateRequest` has no validation).
- `findDuplicate(input, sites)`: the existing site whose `hostOf(base_url)` equals
  `hostOf(input)`, if any.
- `defaultSiteName(input)`: `hostOf(input)` (decision 12).

Test every function, including the edge cases: scheme present or missing, `www.`, a path,
trailing slashes, uppercase letters.

### 6.2 `features/sites/SitePicker.tsx` (new)

It's used by New category step 2, `EditSitesDialog` and `EditCategoryDialog`. Props:
`selected: number[]`, `onChange(ids)`. It reads `listSites` itself (`qk.sites`).

- **Header line:** `SITES` on the left, `N PICKED` on the right. Mono 10 px, `.14em`,
  `ink-3` (the count in `ink-2`).
- **List:** one bordered group (`rounded-md border-hairline-strong bg-well`) of divided
  rows, **no inner scroll**, because the dialog body scrolls. Each row is a 40 px
  `<button role="checkbox" aria-checked>` laid out as a grid:
  - a 16 px box (filled lume with a dark ✓ when picked);
  - a 20 px monogram square (`bg-raised`, mono 9.5 px, the first two letters of the name);
  - the name (13 px, ink);
  - `hostOf(base_url)` (mono 11 px, `ink-3`, truncated, hidden under `sm`);
  - on the right: `N tracked` (`listing_count`, mono `tnum`), or **`⚠ paused`** in warn when
    `paused_until` is in the future, or `new` in lume for a site added in this dialog.

  A picked row gets a 2 px lume bar inset on its left edge (`scaleY` 0→1, 150 ms
  `ease-shelf`) and **no row fill**. Hover: `bg-[rgb(193_255_208/0.03)]`.
- **Toggling updates in place.** Focus must stay on the row: never remount the list on
  toggle. The prototype's v3 mistake was dropping focus to `<body>` on every Space.
- **Add a site:** the last row is `＋ Add a site that isn't listed` (ink-3, lume on hover,
  `aria-expanded`). Clicking it expands a form in place (grid rows 0fr → 1fr, 180 ms
  `ease-shelf`) and hides the row itself.
  - **Fields:** Site URL first (1.4fr, mono) and Name second (1fr), then an **Add** button
    (secondary) and a ghost × that cancels. Collapsed form content is `inert`.
  - **While typing the URL:** Name auto-fills with `defaultSiteName` until the user edits
    Name.
  - **Enter** in either field submits.
  - **Implausible URL:** `⚠ That doesn't look like a URL.` in rise under the fields,
    `aria-invalid` on the URL input, focus stays there.
  - **Duplicate host:** don't create anything. Pick that site and show
    `⚠ eBay is already listed. Picked it for you.` in warn.
  - **Otherwise:** `createSite({ name, base_url: normalizeBaseUrl(url) })`, then invalidate
    `['sites']`. Append the returned site already picked and flash it once (`lume-glow`
    background fading over 600 ms). Collapse the form, focus the new row, and announce
    `"<name> added and picked."` in a polite live region.
  - **Always visible under the fields:** "Added sites are shared with everyone on this
    instance." This is needed because `POST /api/sites` is instance-wide and immediate.
  - **API failure:** show the error message under the fields and keep the form open.

### 6.3 `features/categories/CreateCategoryDialog.tsx`: two steps

- **Props:** keep `trigger`, `variant` and `className`. Add optional
  `onCreated?: (category: Category) => void`. **Without it, the dialog keeps today's
  behaviour** and navigates to `/categories/:slug`, which the Masthead's `MobileNav` and
  `CategoryChips` rely on. With it, it calls `onCreated` and stays on the page (the
  dashboard's use).
- **Step 1 · Name**
  - Eyebrow shows the pips (step 1). Title `New category`. Description (step 1 only):
    "A category is a shelf: things you want, plus the sites the hunter searches for them."
  - Name input, placeholder `e.g. Keyboards`, autofocused.
  - Suggestion chips `Try: Keyboards · Retro games · Camera lenses · Home lab`. Clicking a
    chip fills the name and refocuses the input.
  - **Next: sites →** submits step 1. An empty name shows `⚠ Give it a name.` (rise,
    `role="alert"`) and doesn't advance. The button is **not** disabled.
- **Step 2 · Sites**
  - Lead line: "Where should the hunter look for **Keyboards**?"
  - Then `SitePicker`, then a neutral hint: "Pick one or more. You can change them any time
    from the shelf."
  - **Create category** with nothing picked shows
    `⚠ Pick at least one site. The hunter needs somewhere to look.` (rise, `role="alert"`)
    and hides the hint. No warning before the first click.
  - On success: `createCategory({ name })` then `setCategorySites(id, ids)`. Invalidate
    `['categories']` and `['sites']`, then close.
  - While pending: the only time the primary is disabled, with the existing `Loader2`
    spinner.
  - **If `setCategorySites` fails after `createCategory` succeeded:** keep the dialog open
    on step 2 and show the error. Retrying calls only `setCategorySites` on the category
    already created; never create a second one.
- **Between steps:** the incoming step's content (not the header) animates with
  `animate-step-fwd` going forward or `animate-step-back` on Back. Key the content by step.
  The panel height snaps. Focus moves to the new step's first control with
  `preventScroll`.
- **Unsaved work:** with a name typed or a site picked, an outside click does nothing
  (`onInteractOutside={(e) => dirty && e.preventDefault()}`). Escape and × still close.

### 6.4 `features/categories/EditSitesDialog.tsx` (new)

- **Header:** eyebrow `Sites`, title = the category name, description "The hunter searches
  these for every item on <name>."
- **Body:** `SitePicker`. Footer: Cancel, **Save sites**.
- **Validation:** saving with zero sites shows the same "Pick at least one site" error.
- **On save:** `setCategorySites`, invalidate `['categories']` and `['items']`, close.
- **Unsaved work:** the same outside-click guard when the selection changed.

It's opened from a shelf's **Link sites**, the shelf's `Searching …` chips, the ⋯ menu's
**Edit sites**, one-line rows, and the category page's no-sites state.

### 6.5 `EditCategoryDialog.tsx`

Replace its inline site toggle buttons with `SitePicker`. Rename and delete are unchanged.
The empty-list copy ("No sites yet — add sites on the Sites page first") goes away, because
the picker's add row covers it.

### 6.6 `features/items/AddItemDialog.tsx`: always scoped

- **Props:** `categoryId: number` and `categoryName: string` are **required**. Delete the
  category picker and the `categories` query. Add optional `onAdded?: (item) => void`.
- **Header:** eyebrow `Add item`, title = the category name.
- **Description:** "The hunter searches **eBay, Newegg and Amazon** on its next sweep. No
  URLs needed." With more than 3 sites: "eBay, Newegg and 2 more". This fixes the existing
  "The agent searches the category's sites…", which now reads "hunter".
- **Body, in order:**
  1. Item name (autofocus). Empty on submit shows `⚠ Give it a name.`
  2. Target price with the existing `$` adornment. Hint: "You'll see **⌖ Snagged** when the
     best price hits this."
  3. The criteria textarea (3 rows).
  4. Tracking options.
- **Tracking options:** restyle `TrackingFields`' `CollapsibleTrigger` as a full-width
  bordered summary row: `TRACKING · Cheapest · up to 5 · every 30m · all sites ▸`, with an
  SVG chevron that turns 90° over 180 ms. It expands in place inside the scrolling body.
  Change only the trigger and container. The fields inside, and `EditItemDialog`'s use of
  them, stay as they are.
- **Primary:** never disabled except while pending. `max-w-[520px]`.

### 6.7 Category page no-sites guard (`CategoryPage.tsx`)

When `linkedSites.length === 0`, the header's `AddItemDialog` and the empty state's
`AddItemDialog` become a warn **Link sites** button that opens `EditSitesDialog`. The
existing "No sites linked…" line stays.

### 6.8 Done when

- `siteUrl.test.ts` is green; build, lint and test are green.
- Driven in mock mode:
  - create a category from each entry point (Masthead mobile nav still navigates);
  - add an inline site, including the duplicate and bad-URL cases;
  - toggle sites by keyboard, with focus kept;
  - edit sites; add an item;
  - the category page with no sites offers only Link sites.

---

## 7. PR 3: the dashboard

### 7.1 Files

| File | Job |
|---|---|
| `features/dashboard/shelves.ts` (pure) + `shelves.test.ts` | Grouping, ordering, open defaults, the reopen rule, the lead line, strike detection. All the logic, none of the React. |
| `features/dashboard/useShelfState.ts` | localStorage read/write around `shelves.ts`. |
| `features/dashboard/CategoryShelf.tsx` | One shelf: header, collapsible body, motion. |
| `features/dashboard/CategoryRow.tsx` | The one-line row for a category with none of your items. |
| `features/dashboard/GuideHero.tsx` | The first-run hero (§7.6). |
| `features/dashboard/DashboardPage.tsx` | Composes it all. Drops `CategoryChips`, the global `AddItemDialog` and the bootstrap `EmptyState`. |
| `features/items/WatchList.tsx` | Fixed column widths (§7.4); export the column-label row. |
| `frontend/README.md` | The design-system bullets: shelves and the guide hero replace the flat watch table. |

### 7.2 `shelves.ts`

- **`groupShelves(items, categories)`** → `{ shelves, rows }`.
  - `shelves`: categories that hold ≥1 of the caller's items. Each carries its
    `sortByDistanceToTarget` items, `hits` (count of `target_met`), `lead` and `sites`
    (from `category.site_ids`).
  - `rows`: the other categories, `justCreatedId` first, then alphabetical.
  - **Count items from the grouped `ItemSummary[]`, never from `Category.item_count`**,
    which is instance-wide.
- **`orderShelves`**: decision 1.
- **`lead(shelf)`**:
  - the first in-range item → `⌖ RX 7800 XT at $409.00`;
  - otherwise the closest priced item → `RTX 4070 Super · $49.99 from striking`;
  - otherwise `hunting · no prices yet`.
  - Money goes through `lib/money` (`formatMoney`, `toCents`), never floats.
- **`defaultOpen(shelves)`**:
  - with ≤ 4 shelves, all open;
  - otherwise, open those with `hits > 0` plus the one shelf holding the single closest
    priced item overall.
- **`resolveOpen(stored, shelf, defaults)`**. `stored` is `{ collapsed: boolean, snaggedAt: number } | undefined`.
  - No entry → the default.
  - `collapsed && shelf.hits > snaggedAt` → **open**, and the caller rewrites the entry
    as open. Collapsing must never hide a new strike.
  - Otherwise → `!collapsed`.
- **`newlyStruck(previousInRangeIds, items)`**: ids whose `target_met` is true now and wasn't
  in the previous set. On first load there is no previous set, so it returns nothing.

`shelves.test.ts` covers each: the ordering tiers, both default-open branches, reopen on a
higher hit count, no reopen on an equal count, the three lead variants, and the first-load
case of `newlyStruck`.

### 7.3 `useShelfState`

- **Key:** `snagr:shelves:<user.id>`, from `useSession`. It holds a map of category id →
  `{ collapsed, snaggedAt }`.
- **Storage:** wrap every read and write in try/catch. Ignore ids that no longer exist.
  Follow `HistoryTable.tsx`'s `REMEMBERED` pattern.
- **Writes:** a toggle writes `{ collapsed, snaggedAt: shelf.hits }`. Collapse all and
  Expand all write every shelf.
- **Search:** while `?search=` is set, nothing is read or written. All matching shelves are
  forced open.

### 7.4 `WatchList` fixed columns and the shared label strip

- **Fixed layout:** give the table `table-layout: fixed` and fixed widths on the non-name
  columns, so columns line up across shelves:
  - Trend 96 px, Best 96 px, Site 88 px, Target 92 px, To target 150 px, Checked 84 px;
  - under `sm`: To target 104 px, Best 80 px.
- **Hidden header, kept in the layout:** on a shelf, keep the `<thead>` but render it with
  `h-0 py-0 text-[0px] leading-[0]` (px unchanged). Screen readers still get headers and the
  fixed layout keeps its widths. **Don't** use `sr-only`: `position:absolute` takes the row
  out of the table layout, and every column collapses (the prototype hit this).
- **Label strip:** export the column-label row. The dashboard renders it once, `sticky top-0`
  under the bar, and hides it while no shelf is open.
- **Dashboard shelves use** `showSite`, not `showCategory`. The shelf already names the
  category.

### 7.5 `CategoryShelf`

**Markup:**

```
<section data-state={open ? 'open' : 'closed'} className="rounded-md border border-hairline bg-surface overflow-clip">
  <div class="header row">
    <h3><button aria-expanded aria-controls="shelf-<id>-body">chevron · NAME · count · ⌖ hits · lead · spacer · N sites</button></h3>
    action (＋ Add item | Link sites) · ⋯ DropdownMenu
  </div>
  <div id="shelf-<id>-body" role="region" aria-labelledby=… class="grid transition-[grid-template-rows]">
    <div class="min-h-0 overflow-hidden">  sites button · (no-sites strip) · WatchList · footer  </div>
  </div>
</section>
```

- **The header toggle** is the whole left side: chevron, name, counts, lead and site count.
  - The action and ⋯ are siblings of the toggle, not inside it.
  - The name is not a link. The page link is the footer's `Open <name> →` and the ⋯ menu.
  - `min-h-12`.
- **Header content:**
  - Chevron: an SVG (`M3.5 1.5 7 5l-3.5 3.5`, stroke 1.5, `origin-center`), `ink-3`, lume
    on hover or focus. Not the `▶` glyph, which sits off-centre.
  - Name: display 19 px, `.06em`, uppercase, **the same size open and closed**.
  - Count: mono 11 `ink-3`, from the grouped items. Hits: `⌖ N in range` in drop, shown only
    when above 0.
  - Lead: 12.5 px `ink-2`, the amount mono lume. In-range lead in drop mono. The
    no-prices-yet lead in `ink-3` mono.
  - Site count: `N sites` mono `ink-3`, or `⚠ no sites` in warn. Hidden under `sm`.
- **Actions:**
  - `＋ Add item` is a secondary `AddItemDialog` trigger. Under `sm` it's a 36 px `＋` icon
    button with `aria-label="Add item to <name>"`. With no sites, a warn `Link sites` opens
    `EditSitesDialog`.
  - **⋯ menu** (existing `DropdownMenu`):
    - `Hunt now`: `enqueue({ kind: 'hunt', scope: 'category', scope_id })`, disabled with no
      sites;
    - `Edit sites`;
    - `Rename`: opens `EditCategoryDialog`;
    - a separator;
    - `Open category page`.
- **Body:**
  - **Sites line:** `SEARCHING [eBay] [Newegg] [Amazon] EDIT` as **one** button,
    `aria-label="Edit sites for <name>"`. It opens `EditSitesDialog`.
  - **No-sites strip**, only when the shelf holds items but no sites:
    `⚠ No sites linked. The hunter can't search for these 2 items.` in warn, on `bg-warn/10`.
  - **Then the `WatchList`.**
  - **Footer:** `N items · closest first` on the left and `Open <name> →` on the right, in
    `bg-well` mono 11.
- **Collapsed body:** `hidden="until-found"`, so Ctrl-F still finds collapsed rows, and a
  `beforematch` listener opens the shelf.
  - Set the attribute and the listener through a ref, not JSX. React's handling of the
    `until-found` string and `onBeforeMatch` isn't something to rely on.
  - Add `[hidden="until-found"] { display: grid !important }` scoped to the shelf body, so
    Tailwind's `[hidden]{display:none}` doesn't turn it into plain `display:none`.
- **Don't use Radix Collapsible here.** It has no until-found support, and its presence
  logic fights the grid-rows transition. A button with `aria-expanded` and a region is
  enough.

### 7.6 `GuideHero` (replaces `VerdictHero` while you have no items)

It shows when `items.isSuccess`, `rows.length === 0` and there is no search. While it's up,
the `HunterTicker` is hidden. Eyebrow: `Getting started · <weekday, month day>`. Title:
display 38 px, ink.

| State | When | Title | Body | Pips | Button (amber, `h-[38px]`) |
|---|---|---|---|---|---|
| Empty instance | no categories | Nothing to hunt yet | Everything you track sits in a category: a shelf, plus the sites the hunter searches, like eBay or Newegg. Create one first, then add items to it. | ①on Create a category → ② Add items to it | ＋ Create your first category (`CreateCategoryDialog` with `onCreated`) |
| Shared instance | categories exist, none just created | Pick a category, or make your own | Everything you track sits in a category: a shelf, plus the sites the hunter searches. People here already hunt **N categories**. Add an item to one below, or create one of your own. | ①on Choose or create a category → ② Add items to it | ＋ Create a category, then the muted aside "or use Add item on a category below" |
| Just created | `justCreatedId` set | <Name> is ready | The hunter will search **eBay and Amazon**. Now give it something to hunt: a name and a target price. | ✓ Create a category → ②on Add items to it | ＋ Add item to <Name> (scoped `AddItemDialog`) |

- **Empty instance:** under the hero, a dashed "example shelf". Title `YOUR FIRST CATEGORY`
  in ink-3, beside it `searching eBay · Newegg`, then three 10 px `bg-raised` bars and
  "This is what a shelf looks like. Items you add show up here, closest to target first."
  It's decorative: `aria-hidden`.
- **Otherwise:** under the hero, the bar reads `CATEGORIES · N on this instance`, followed by
  the category rows. A secondary `＋ New category` appears in the bar once `justCreatedId`
  is set.
- **`justCreatedId`** is `DashboardPage` state, set by `CreateCategoryDialog`'s `onCreated`.
  That category's row reads `new · searching …` in lume, with a lume/40 border.

### 7.7 Returning-user layout (`home.png`)

- **Hero:** `VerdictHero`, with its `h1` reduced from 42 px to **30 px**. Put
  `HunterTicker` directly under the PulseLine (`mt-2` instead of `mt-9`) so hero and ticker
  read as one block.
- **Bar:**
  - left: `THE WATCH` and `N shelves · M items`;
  - a spacer;
  - `Collapse all` / `Expand all` (ghost). It reads "Collapse all" while any shelf is
    open, and shows only when there are 2 or more shelves;
  - the `RangeSelector`;
  - `＋ New category` (primary, `onCreated` → reveal §7.8).
- **Then:** the label strip (§7.4), then the shelves, with a 10 px gap.
- **Then:** `NO ITEMS OF YOURS YET` (mono 10 `.14em` `ink-3`) and up to 5 `CategoryRow`s.
  After them, a `＋ N more categories` ghost button that reveals the rest.
- **`CategoryRow` content:**
  - with sites: `NAME` (display 17, ink-2), then
    `none of yours · searching eBay, Mercari`, then `＋ Add item` (secondary);
  - with none: `NAME`, then `⚠ no sites. The hunter can't search here.` in warn, then
    `Link sites` (warn).
- **Search** (`?search=`):
  - the bar reads `SEARCH · matching "x" · clear`;
  - only shelves with a match render, forced open, with `2 of 5 match` as the count;
  - no hero, ticker, rows or Collapse all;
  - with no matches at all: `Nothing on any shelf matches "x". · clear`.
- **Loading:** reuse the existing skeletons: the hero skeleton, then three `h-12` shelf
  skeletons.

### 7.8 Motion: A · Drawer (exact values)

| Moment | Spec |
|---|---|
| **Open** | Body `grid-template-rows` 0fr → 1fr over **200 ms `ease-shelf`**. The inner wrapper's opacity goes 0 → 1 over 140 ms, starting 40 ms in. |
| **Close** | 1fr → 0fr over **160 ms `ease-shelf-in`**. Opacity → 0 over 90 ms, no delay, no stagger. |
| **Chevron** | `rotate(90deg)` when open, with the same duration and easing as the height. On `:active` it nudges 2 px in its direction of travel (`translate` x when closed, y when open) over 80 ms. |
| **Rows** | Only on a **user-initiated open**; not on first render, not during Expand all. Add a class to the section for 460 ms. The sites line (`--i:0`), each row (`--i:1…5`, capped) and the footer (`--i:5`) run `shelf-row` 140 ms `ease-shelf`, delayed `calc(40ms + var(--i) * 20ms)`. |
| **Lead and site count** | These fade out (90 ms, then `visibility:hidden`) when opening and back in (140 ms, 60 ms delay) when closing. They keep their space, so the header never reflows. Under `sm` the lead wraps to its own line and also animates `max-height` on the 200/160 ms timing. |
| **Hover** | The header row's background goes to `rgb(193 255 208/.03)` and the chevron turns lume, 120 ms ease-out. No scaling. |
| **Collapse all** | Every open shelf together, 160 ms. |
| **Expand all** | Cascades top-down: shelf *i* starts at `min(i, 4) × 40 ms`. No row stagger. |
| **Strike** (§7.9) | The struck row runs `strike-row`: background from `rgb(66 208 124/.22)` fading over 1200 ms ease-out. If the shelf was collapsed, it opens as usual and its border runs `strike-edge` (lume/60 → hairline over 1200 ms). |
| **Newly created or revealed** | The row or shelf runs `strike-edge` once. It scrolls into view with `block: 'nearest'` (smooth, or `auto` under reduced motion) because the user just asked for it. **Never auto-scroll for a strike**, since that would yank the page from under the reader. |
| **Reduced motion** | Everything is instant; the global rule handles it. The struck row gets a static `inset 2px 0 0 var(--color-lume)` for 8 s, then it's removed with no transition. Use `useMediaQuery('(prefers-reduced-motion: reduce)')`. |

Add to `globals.css` in PR 3:

```css
  --animate-shelf-row: shelf-row 140ms var(--ease-shelf) both;
  --animate-strike-row: strike-row 1200ms ease-out;
  --animate-strike-edge: strike-edge 1200ms ease-out;
```
```css
@keyframes shelf-row { from { opacity: 0; transform: translateY(-4px); } }
@keyframes strike-row { from { background-color: rgb(66 208 124 / 0.22); } }
@keyframes strike-edge { 0%, 25% { border-color: rgb(255 180 84 / 0.6); } }
```

`strike-row` animates `background-color`, which shows through the transparent end of the
in-range row's gradient (`WatchList` sets it as a background image).

**Getting the order right in React.** Drive `hidden` and `data-state` from a
`useLayoutEffect` on `open`, through a ref, rather than straight from JSX:

- **Opening:** remove `hidden`, read `offsetHeight` to force a reflow, then set
  `data-state="open"`.
- **Closing:** set `data-state="closed"`. On `transitionend` for `grid-template-rows`, and
  only if the shelf is still closed, set `hidden="until-found"`. Add a 260 ms timeout as a
  fallback for interrupted transitions.
- **Why not start with `hidden`:** it can't be set at the start of a close. It applies
  `content-visibility:hidden`, which collapses the height to zero at once and snaps the
  animation.
- **First mount:** render in the final state with no transition.
- **A shelf that mounts because it was just revealed** (first item added, or a new strike
  on a stored-collapsed shelf) mounts closed, then opens on the next frame.

### 7.9 Strikes

- **Detecting one:** `DashboardPage` keeps a ref of the in-range item ids from the previous
  items response. Each new response runs `newlyStruck`, which gives the struck ids.
  - A strike arrives through the existing SSE path: `JobsProvider` invalidates `['items']`
    on `job.finished`.
  - `resolveOpen` reopens the shelf of a struck item if it was collapsed.
- **Showing it:** each struck row gets `data-strike` for 1300 ms (8 s under reduced motion),
  which drives `animate-strike-row` or the static edge.
- **In mock mode:** raise an item's target above its best price in `EditItemDialog`. That
  flips `target_met` through the same data path.

### 7.10 Done when

- `shelves.test.ts` is green; build, lint and test are green.
- `frontend:verify` in mock mode, at 1280 px and 390 px:
  - [ ] returning layout matches `home.png`;
  - [ ] toggle a shelf by mouse and keyboard; the chevron animates and focus stays;
  - [ ] Collapse all / Expand all, including the cascade;
  - [ ] reload and collapse state persists;
  - [ ] a second account on the same browser has its own state;
  - [ ] collapse a shelf, then trigger a strike on it: it reopens, and the row flashes;
  - [ ] Ctrl-F finds an item inside a collapsed shelf and opens it;
  - [ ] `?search=` behaviour;
  - [ ] all three guide-hero states:
    - delete the demo's items, or sign up a second account, to see them;
    - after **＋ Create your first category**, the hero moves to step 2;
    - after adding the item, the normal hero returns and the new shelf opens with the edge;
  - [ ] reduced motion (emulated) gives instant toggles and the static strike edge.

---

## 8. Copy

All strings are verbatim. Button labels render uppercase through `buttonVariants`, so write
them in sentence case.

| Where | String |
|---|---|
| Dashboard bar | `The Watch` · `N shelves · M items` · `Collapse all` / `Expand all` · `＋ New category` |
| Shelf count / hits | `N items` / `1 item` · `⌖ N in range` · search: `2 of 5 match` |
| Shelf lead | `⌖ <item> at <price>` · `<item> · <gap> from striking` · `hunting · no prices yet` |
| Shelf site count | `N sites` / `1 site` · `⚠ no sites` |
| Shelf sites button | `Searching` + chips + `edit` · aria `Edit sites for <name>` |
| No-sites strip | `⚠ No sites linked. The hunter can't search for this item.` / `…for these N items.` |
| Shelf footer | `N items · closest first` · `Open <name> →` |
| ⋯ menu | `Hunt now` · `Edit sites` · `Rename` · `Open category page` |
| Rows heading | `No items of yours yet` · `＋ N more categories` |
| Row | `none of yours · searching <sites>` · `new · searching <sites>` · `⚠ no sites. The hunter can't search here.` · `＋ Add item` / `Link sites` |
| Search | `Search` · `matching "x" · clear` · `Nothing on any shelf matches "x". · clear` |
| Guide hero | §7.6 table |
| New category | pips `Name` → `Sites` · `New category` · the step-1 description · `e.g. Keyboards` · `Try:` · `Next: sites →` · `⚠ Give it a name.` · `Where should the hunter look for <name>?` · `Pick one or more. You can change them any time from the shelf.` · `⚠ Pick at least one site. The hunter needs somewhere to look.` · `← Back` · `Cancel` · `Create category` |
| Site picker | `Sites` · `N picked` · `N tracked` · `⚠ paused` · `new` · `＋ Add a site that isn't listed` · `Site URL` · `Name` · `Add` · `Added sites are shared with everyone on this instance.` · `⚠ That doesn't look like a URL.` · `⚠ <name> is already listed. Picked it for you.` · live region `<name> added and picked.` |
| Sites dialog | eyebrow `Sites` · title `<name>` · `The hunter searches these for every item on <name>.` · `Save sites` |
| Add item | eyebrow `Add item` · title `<name>` · `The hunter searches <sites> on its next sweep. No URLs needed.` · `Item name` · `e.g. Pokémon Sapphire (GBA)` · `⚠ Give it a name.` · `Target price (optional)` · `You'll see ⌖ Snagged when the best price hits this.` · `What are you looking for? (optional)` · the Tracking summary row · `Add item` |

## 9. Rules the build must keep

- **The frontend is the contract**, and it doesn't change here. If a step seems to need a
  new endpoint or field, stop and raise it. Don't add one.
- **Prices stay decimal strings.** Every money display and comparison goes through
  `lib/money`.
- **Every semantic colour ships with its glyph:** ⌖ ✓ ⚠ ▼ ▲. Lume is identity and never
  semantic. The finished step pip is `ink-2`, not green.
- **Match the neighbours:**
  - new components copy the idioms of the file next to them;
  - comments explain *why* (CONTRIBUTING.md → Comments & docstrings);
  - no new dependencies (Radix, `tw-animate-css` and `lucide` are already there);
  - thin logic stays in components, but anything a test should pin down goes in a pure
    module (`shelves.ts`, `siteUrl.ts`).
- **No quiet fallbacks:**
  - API errors from `createCategory`, `setCategorySites`, `createSite` and `createItem`
    show `ApiError.message` or `fields` in the dialog;
  - localStorage failures are the one deliberate exception. They are caught and ignored,
    because collapse state is a convenience.
- **Accessibility:**
  - shelf toggles are real `<button aria-expanded aria-controls>`;
  - site rows are `role="checkbox" aria-checked`;
  - errors use `role="alert"`;
  - focus returns to the trigger when a dialog closes (Radix does this; don't break it by
    unmounting the trigger);
  - every icon-only button has an `aria-label`.
- **After each PR, update the docs it touches:** `frontend/README.md` (design-system bullets,
  structure). Neither STRUCTURE doc should need changes, since there's no backend or agent
  change.

## 10. Out of scope

- Remembering who created a category, which would let "X is ready" survive a reload. That
  needs a backend column; it's a separate proposal if wanted.
- Manual shelf ordering or pinning.
- The prototype's Lock-on motion (scan line, ⌖ brackets), the side-sheet dialogs and the
  two-pane New category. They were considered and not chosen.
- Any change to the category page beyond the no-sites guard (§6.7).
