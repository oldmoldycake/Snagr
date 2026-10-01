import { CircleHelp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import type { GlossaryTerm } from '@/components/ui/glossaryTerms'

/**
 * "What do these mean?": a small button that opens the page's terms in a
 * dialog, for the words that stay because no plainer one says the same.
 */
export function Glossary({ terms, className }: { terms: GlossaryTerm[]; className?: string }) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className={className}>
          <CircleHelp />
          What do these mean?
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Glossary</DialogTitle>
          <DialogDescription>The words and marks on this page.</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <dl className="grid gap-3.5">
            {terms.map(({ term, meaning }) => (
              <div key={term}>
                <dt className="font-mono text-[12px] text-ink">{term}</dt>
                <dd className="mt-0.5 text-[14px] leading-relaxed text-ink-2">{meaning}</dd>
              </div>
            ))}
          </dl>
        </DialogBody>
      </DialogContent>
    </Dialog>
  )
}
