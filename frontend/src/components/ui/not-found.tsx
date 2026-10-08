import { Link } from 'react-router-dom'
import { usePageTitle } from '@/lib/usePageTitle'
import { buttonVariants } from './button'
import { EmptyState } from './empty-state'

/**
 * A page whose subject doesn't exist, in the empty state's frame with a way
 * out: a deep link or a stale tab lands here with nothing else in the page to
 * click.
 */
export function NotFound({
  title,
  description,
  to = '/',
  label = 'Back to dashboard',
}: {
  title: string
  description?: string
  to?: string
  label?: string
}) {
  usePageTitle(title)
  return (
    <EmptyState
      title={title}
      description={description}
      action={
        <Link to={to} className={buttonVariants({ variant: 'default' })}>
          {label}
        </Link>
      }
    />
  )
}
