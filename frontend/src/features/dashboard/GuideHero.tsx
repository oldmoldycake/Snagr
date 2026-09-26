import type { Category, ItemSummary } from '@/api/types'
import { StepPips } from '@/components/ui/step-pips'
import { CreateCategoryDialog } from '@/features/categories/CreateCategoryDialog'
import { AddItemDialog } from '@/features/items/AddItemDialog'
import { siteList } from '@/features/sites/siteList'

/** Where a caller with no items stands: nothing on the instance, others' categories, or one just made. */
export type GuideState =
  | { kind: 'empty' }
  | { kind: 'shared'; categoryCount: number }
  | { kind: 'ready'; category: Category; siteNames: string[] }

const CTA = 'h-[38px] px-4 text-xs'

/**
 * The dashboard's hero until the caller has an item: it walks them through
 * ① a category → ② items in it. "Ready" is only known to the page that just ran
 * New category (categories have no owner), so after a reload it reads "shared".
 */
export function GuideHero({
  state,
  onCreated,
  onAdded,
}: {
  state: GuideState
  onCreated: (category: Category) => void
  onAdded: (item: ItemSummary) => void
}) {
  const eyebrow = `Getting started · ${new Date().toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })}`

  return (
    <div>
      <section className="max-w-[640px]">
        <p className="font-mono text-[10.5px] tracking-[0.16em] text-ink-3 uppercase">{eyebrow}</p>
        <h1 className="mt-2 font-display text-[38px] leading-[1.05] font-semibold tracking-[0.015em] text-ink text-balance">
          {state.kind === 'ready'
            ? `${state.category.name} is ready`
            : state.kind === 'shared'
              ? 'Pick a category, or make your own'
              : 'Nothing to hunt yet'}
        </h1>
        <p className="mt-2 max-w-[58ch] text-[15px] text-ink-2">
          {state.kind === 'ready' ? (
            <>
              Snagr will search <b className="font-semibold text-ink">{siteList(state.siteNames)}</b>. Now give it
              something to hunt: a name and a target price.
            </>
          ) : state.kind === 'shared' ? (
            <>
              Everything you track belongs to a category, which sets the sites Snagr searches. This server already
              has{' '}
              <b className="font-semibold text-ink">
                {state.categoryCount} {state.categoryCount === 1 ? 'category' : 'categories'}
              </b>
              . Add an item to one below, or create your own.
            </>
          ) : (
            <>
              Everything you track belongs to a category, which sets the sites Snagr searches, like eBay or
              Newegg. Create a category first, then add items to it.
            </>
          )}
        </p>
        <StepPips
          size="md"
          className="mt-4"
          steps={[state.kind === 'shared' ? 'Choose or create a category' : 'Create a category', 'Add items to it']}
          current={state.kind === 'ready' ? 2 : 1}
        />
        <div className="mt-[18px] flex flex-wrap items-center gap-x-3.5 gap-y-2.5">
          {state.kind === 'ready' ? (
            <AddItemDialog
              categoryId={state.category.id}
              categoryName={state.category.name}
              className={CTA}
              trigger={`＋ Add item to ${state.category.name}`}
              onAdded={onAdded}
            />
          ) : (
            <CreateCategoryDialog
              className={CTA}
              trigger={state.kind === 'shared' ? '＋ Create a category' : '＋ Create your first category'}
              onCreated={onCreated}
            />
          )}
          {state.kind === 'shared' ? (
            <span className="text-[12.5px] text-ink-3">or use Add item on a category below</span>
          ) : null}
        </div>
      </section>

      {state.kind === 'empty' ? (
        <div aria-hidden className="mt-[30px] rounded-md border border-dashed border-hairline-strong px-4 pt-3.5 pb-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
            <span className="font-display text-[19px] leading-none font-semibold tracking-[0.06em] text-ink-3 uppercase">
              Your first category
            </span>
            <span className="font-mono text-[11px] text-ink-3">searching eBay · Newegg</span>
          </div>
          <div className="mt-3.5 grid gap-2">
            <i className="block h-2.5 w-[92%] rounded-[3px] bg-raised" />
            <i className="block h-2.5 w-[78%] rounded-[3px] bg-raised" />
            <i className="block h-2.5 w-[85%] rounded-[3px] bg-raised" />
          </div>
          <p className="mt-3 text-[12.5px] text-ink-3">
            This is how a category looks on your dashboard. Items you add appear here, closest to target first.
          </p>
        </div>
      ) : null}
    </div>
  )
}
