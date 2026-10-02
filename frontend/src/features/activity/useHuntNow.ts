import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { enqueueJobs } from '@/api/endpoints'
import type { JobCreateRequest } from '@/api/types'
import { huntReceipt } from './lines'

/**
 * Hunt now, for whichever scope the caller names. Each caller holds its own
 * request, so only the control that was pressed shows it waiting. Most of
 * what it queues waits its turn rather than starting, and a button that just
 * stops spinning says nothing, so a toast says what was queued.
 */
export function useHuntNow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (target: Omit<JobCreateRequest, 'kind'>) => enqueueJobs({ kind: 'hunt', ...target }),
    onSuccess: (res) => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      if (res.data.length === 0) toast.warning(huntReceipt(res.data))
      else toast.success(huntReceipt(res.data))
    },
  })
}
