import { api } from './client'
import type { TimeRange } from '@/lib/time'
import type {
  AdminUser,
  AdminUserUpdateRequest,
  ApiToken,
  ApiTokenCreated,
  ApiTokenCreateRequest,
  Category,
  CategoryCreateRequest,
  CategoryPriceChangeResponse,
  CategoryUpdateRequest,
  DashboardStats,
  InstanceInfo,
  Invite,
  InviteAcceptRequest,
  InviteCreateRequest,
  InviteValidation,
  ItemCreateRequest,
  ItemDetail,
  ItemListParams,
  ItemSummary,
  ItemUpdateRequest,
  Job,
  JobCreateRequest,
  JobEvent,
  JobListParams,
  JobsSummary,
  Listing,
  ListingUpdateRequest,
  LoginRequest,
  MeUpdateRequest,
  NotificationChannel,
  NotificationChannelCreateRequest,
  NotificationChannelCreated,
  NotificationChannelUpdateRequest,
  Paginated,
  PasswordChangeRequest,
  PriceCheck,
  PriceDrop,
  PriceHistoryResponse,
  PriceSummaryResponse,
  ReferenceImage,
  RegisterRequest,
  ReviewConfirmRequest,
  ReviewQueueEntry,
  Site,
  SiteCreateRequest,
  SiteUpdateRequest,
  User,
  Watch,
  WatchUpdateRequest,
} from './types'

/** Read the instance's feature flags and settings; public, so it works before login. */
export const getInstance = () => api<InstanceInfo>('/api/instance')

/** Sign in and start a cookie session; 401 invalid_credentials for a wrong email or password alike. */
export const login = (body: LoginRequest) =>
  api<{ user: User }>('/api/auth/login', { method: 'POST', body })

/** Self-signup while registration is open; the first user becomes admin. Starts a session. */
export const register = (body: RegisterRequest) =>
  api<{ user: User }>('/api/auth/register', { method: 'POST', body })

/** End the session: revoke its refresh token and clear both auth cookies. */
export const logout = () => api<void>('/api/auth/logout', { method: 'POST' })

/** The signed-in user; cookie sessions only, so an API token gets 403. */
export const getMe = () => api<User>('/api/auth/me')

/** Check an invite link before showing the signup form; 404 unknown, 410 used or expired. */
export const validateInvite = (token: string) =>
  api<InviteValidation>(`/api/auth/invites/${token}`)

/** Create an account from an invite and start a session; an email pinned to the invite wins. */
export const acceptInvite = (token: string, body: InviteAcceptRequest) =>
  api<{ user: User }>(`/api/auth/invites/${token}/accept`, { method: 'POST', body })

/** Change the caller's email or vision thresholds; only sent fields change. */
export const updateMe = (body: MeUpdateRequest) =>
  api<User>('/api/me', { method: 'PATCH', body })

/** Change the caller's password; 422 invalid_password for a wrong current one or an SSO account. */
export const changePassword = (body: PasswordChangeRequest) =>
  api<void>('/api/me/password', { method: 'POST', body })

/** The caller's notification channels. */
export const listChannels = () => api<{ data: NotificationChannel[] }>('/api/me/channels')

/** Add a notification channel; a webhook's signing secret comes back only in this response. */
export const createChannel = (body: NotificationChannelCreateRequest) =>
  api<NotificationChannelCreated>('/api/me/channels', { method: 'POST', body })

/** Edit one of the caller's channels; its kind cannot change. */
export const updateChannel = (id: number, body: NotificationChannelUpdateRequest) =>
  api<NotificationChannel>(`/api/me/channels/${id}`, { method: 'PATCH', body })

/** Delete one of the caller's channels along with its pending deliveries. */
export const deleteChannel = (id: number) =>
  api<void>(`/api/me/channels/${id}`, { method: 'DELETE' })

/** Send a test notification through a channel; 502 channel_failed when the destination is unreachable. */
export const testChannel = (id: number) =>
  api<void>(`/api/me/channels/${id}/test`, { method: 'POST' })

/** The caller's API tokens, without their raw values. */
export const listTokens = () => api<{ data: ApiToken[] }>('/api/me/tokens')

/** Mint an API token; the raw value comes back only in this response. */
export const createToken = (body: ApiTokenCreateRequest) =>
  api<ApiTokenCreated>('/api/me/tokens', { method: 'POST', body })

/** Delete one of the caller's API tokens so it stops authenticating. */
export const revokeToken = (id: number) =>
  api<void>(`/api/me/tokens/${id}`, { method: 'DELETE' })

/** Every category, with counts read through the caller's watches. */
export const listCategories = () => api<{ data: Category[] }>('/api/categories')

/** Create a category; 422 duplicate when the name exists (case-insensitive). */
export const createCategory = (body: CategoryCreateRequest) =>
  api<Category>('/api/categories', { method: 'POST', body })

/** Rename a category; its slug stays the same. */
export const updateCategory = (id: number, body: CategoryUpdateRequest) =>
  api<Category>(`/api/categories/${id}`, { method: 'PATCH', body })

/** Delete a category and everything under it, including every user's watches on its items. */
export const deleteCategory = (id: number) =>
  api<void>(`/api/categories/${id}`, { method: 'DELETE' })

/** Replace the sites a category is searched on; unknown site ids are dropped. */
export const setCategorySites = (id: number, siteIds: number[]) =>
  api<Category>(`/api/categories/${id}/sites`, { method: 'PUT', body: { site_ids: siteIds } })

/** Every site, with its counts and any circuit-breaker pause. */
export const listSites = () => api<{ data: Site[] }>('/api/sites')

/** Add a site for the hunter to search. */
export const createSite = (body: SiteCreateRequest) =>
  api<Site>('/api/sites', { method: 'POST', body })

/** Rename a site, change its base URL, or lift a breaker pause (`paused_until: null`). */
export const updateSite = (id: number, body: SiteUpdateRequest) =>
  api<Site>(`/api/sites/${id}`, { method: 'PATCH', body })

/** Delete a site; one that listings still reference fails with 503 db_unavailable. */
export const deleteSite = (id: number) => api<void>(`/api/sites/${id}`, { method: 'DELETE' })

/** The caller's watched items, filtered and paged, each with its price rollup. */
export const listItems = (params: ItemListParams = {}) =>
  api<Paginated<ItemSummary>>('/api/items', { params: { ...params } })

/** Watch an item: finds or creates the shared item, then adds the caller's watch and site subset. */
export const createItem = (body: ItemCreateRequest) =>
  api<ItemSummary>('/api/items', { method: 'POST', body })

/** One watched item with its listings and what the hunter does next; 404 when unwatched. */
export const getItem = (id: number) => api<ItemDetail>(`/api/items/${id}`)

/** Edit an item's and the caller's watch fields; only sent fields change. */
export const updateItem = (id: number, body: ItemUpdateRequest) =>
  api<ItemDetail>(`/api/items/${id}`, { method: 'PATCH', body })

/** Stop watching an item and drop the caller's listings and checks; the shared item stays. */
export const deleteItem = (id: number) => api<void>(`/api/items/${id}`, { method: 'DELETE' })

/** Set the caller's notify flag or personal target price on an item. */
export const updateWatch = (itemId: number, body: WatchUpdateRequest) =>
  api<Watch>(`/api/items/${itemId}/watch`, { method: 'PATCH', body })

/** Stop or resume tracking one of the caller's listings. */
export const updateListing = (id: number, body: ListingUpdateRequest) =>
  api<Listing>(`/api/listings/${id}`, { method: 'PATCH', body })

/** Recent raw price checks across an item's listings, newest first, unconfirmed readings included. */
export const listPriceChecks = (itemId: number, limit = 50) =>
  api<{ data: PriceCheck[] }>(`/api/items/${itemId}/price-checks`, { params: { limit } })

// GET /api/vision/images/{key} serves bytes straight to <img src> and is
// deliberately not listed here — same precedent as the SSE stream.

/** Captured photos awaiting the caller's confirm or discard, newest first. */
export const listReviewQueue = (params: { item_id?: number; page?: number; per_page?: number } = {}) =>
  api<Paginated<ReviewQueueEntry>>('/api/vision/review-queue', { params: { ...params } })

/** Keep a captured photo as a real/fake reference and rescore the item; 409 already_reviewed. */
export const confirmReviewEntry = (id: number, body: ReviewConfirmRequest) =>
  api<ReferenceImage>(`/api/vision/review-queue/${id}/confirm`, { method: 'POST', body })

/** Drop a captured photo without keeping it as a reference, then rescore the item. */
export const discardReviewEntry = (id: number) =>
  api<void>(`/api/vision/review-queue/${id}`, { method: 'DELETE' })

/** An item's shared reference library, newest first. */
export const listReferences = (itemId: number) =>
  api<{ data: ReferenceImage[] }>(`/api/items/${itemId}/references`)

/** form fields: file, label ('real' | 'fake'), variant_tag? */
export const uploadReference = (itemId: number, form: FormData) =>
  api<ReferenceImage>(`/api/items/${itemId}/references`, { method: 'POST', body: form })

/** Revoke a reference so scoring stops using it; revoking twice is a no-op. */
export const revokeReference = (id: number) =>
  api<void>(`/api/vision/references/${id}`, { method: 'DELETE' })

/** Revoke every live auto-promoted reference of an item, for when the library has drifted. */
export const revokeAutoReferences = (itemId: number) =>
  api<{ revoked: number }>(`/api/items/${itemId}/references/revoke-auto`, { method: 'POST' })

/** One price line per live listing of an item over the range, each thinned to at most `points`. */
export const getPriceHistory = (itemId: number, range: TimeRange, points = 300) =>
  api<PriceHistoryResponse>(`/api/items/${itemId}/price-history`, { params: { range, points } })

/** Average and best price over the range, pooled across the item's listings. */
export const getPriceSummary = (itemId: number, range: TimeRange, points = 300) =>
  api<PriceSummaryResponse>(`/api/items/${itemId}/price-summary`, { params: { range, points } })

/** Best-price movement over the range for each of the caller's items in a category. */
export const getCategoryPriceChange = (categoryId: number, range: TimeRange) =>
  api<CategoryPriceChangeResponse>(`/api/categories/${categoryId}/price-change`, {
    params: { range },
  })

/** The four dashboard tiles for the caller over the range. */
export const getDashboardStats = (range: TimeRange) =>
  api<DashboardStats>('/api/dashboard/stats', { params: { range } })

/** The caller's recent price drops, at most one row per listing, newest first. */
export const getPriceDrops = (range: TimeRange, limit = 10) =>
  api<{ data: PriceDrop[] }>('/api/dashboard/price-drops', { params: { range, limit } })

/**
 * Queue hunts or rechecks for a scope; asking again brings a queued job forward
 * instead of adding a second one. 409 hunting_disabled for a hunt while hunting is off.
 */
export const enqueueJobs = (body: JobCreateRequest) =>
  api<{ data: Job[] }>('/api/jobs', { method: 'POST', body })

/** The jobs the caller may see, filtered and paged. */
export const listJobs = (params: JobListParams = {}) =>
  api<Paginated<Job>>('/api/jobs', { params: { ...params } })

/** The queue at a glance: running and pending counts, the next check and hunt, paused sites. */
export const getJobsSummary = () => api<JobsSummary>('/api/jobs/summary')

/** One job; a job the caller may not see 404s like a missing one. */
export const getJob = (id: number) => api<Job>(`/api/jobs/${id}`)

/** A job's events after `afterSeq` — the backfill after an SSE reconnect. */
export const getJobEvents = (id: number, afterSeq = 0, limit = 200) =>
  api<{ data: JobEvent[] }>(`/api/jobs/${id}/events`, { params: { after_seq: afterSeq, limit } })

/** Cancel a pending or running hunt; 422 for a recheck, 409 job_finished once it has ended. */
export const cancelJob = (id: number) => api<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' })

/** Every user on the instance (admin only). */
export const listUsers = () => api<{ data: AdminUser[] }>('/api/admin/users')

/** Activate or deactivate a user, or change their role (admin only). */
export const updateUser = (id: number, body: AdminUserUpdateRequest) =>
  api<AdminUser>(`/api/admin/users/${id}`, { method: 'PATCH', body })

/**
 * Delete a user (admin only); 409 user_has_items while they still watch anything,
 * 422 cannot_delete_self for the caller.
 */
export const deleteUser = (id: number) => api<void>(`/api/admin/users/${id}`, { method: 'DELETE' })

/** Pending invites — unused and not yet expired (admin only). */
export const listInvites = () => api<{ data: Invite[] }>('/api/admin/invites')

/** Issue a single-use invite link, optionally pinned to an email (admin only). */
export const createInvite = (body: InviteCreateRequest = {}) =>
  api<Invite>('/api/admin/invites', { method: 'POST', body })

/** Delete an invite so its link stops working (admin only). */
export const revokeInvite = (id: number) =>
  api<void>(`/api/admin/invites/${id}`, { method: 'DELETE' })
