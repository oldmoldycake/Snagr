import { api } from './client'
import type { TimeRange } from '@/lib/time'
import type {
  AdminUser,
  AdminUserUpdateRequest,
  AgentRun,
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
  RunCreateRequest,
  RunEvent,
  RunListParams,
  Site,
  SiteCreateRequest,
  SiteUpdateRequest,
  User,
  Watch,
  WatchUpdateRequest,
} from './types'

// --- instance / auth -------------------------------------------------------

export const getInstance = () => api<InstanceInfo>('/api/instance')

export const login = (body: LoginRequest) =>
  api<{ user: User }>('/api/auth/login', { method: 'POST', body })

export const register = (body: RegisterRequest) =>
  api<{ user: User }>('/api/auth/register', { method: 'POST', body })

export const logout = () => api<void>('/api/auth/logout', { method: 'POST' })

export const getMe = () => api<User>('/api/auth/me')

export const validateInvite = (token: string) =>
  api<InviteValidation>(`/api/auth/invites/${token}`)

export const acceptInvite = (token: string, body: InviteAcceptRequest) =>
  api<{ user: User }>(`/api/auth/invites/${token}/accept`, { method: 'POST', body })

// --- me ---------------------------------------------------------------------

export const updateMe = (body: MeUpdateRequest) =>
  api<User>('/api/me', { method: 'PATCH', body })

export const changePassword = (body: PasswordChangeRequest) =>
  api<void>('/api/me/password', { method: 'POST', body })

export const listChannels = () => api<{ data: NotificationChannel[] }>('/api/me/channels')

export const createChannel = (body: NotificationChannelCreateRequest) =>
  api<NotificationChannelCreated>('/api/me/channels', { method: 'POST', body })

export const updateChannel = (id: number, body: NotificationChannelUpdateRequest) =>
  api<NotificationChannel>(`/api/me/channels/${id}`, { method: 'PATCH', body })

export const deleteChannel = (id: number) =>
  api<void>(`/api/me/channels/${id}`, { method: 'DELETE' })

export const testChannel = (id: number) =>
  api<void>(`/api/me/channels/${id}/test`, { method: 'POST' })

// --- categories -------------------------------------------------------------

export const listCategories = () => api<{ data: Category[] }>('/api/categories')

export const createCategory = (body: CategoryCreateRequest) =>
  api<Category>('/api/categories', { method: 'POST', body })

export const updateCategory = (id: number, body: CategoryUpdateRequest) =>
  api<Category>(`/api/categories/${id}`, { method: 'PATCH', body })

export const deleteCategory = (id: number) =>
  api<void>(`/api/categories/${id}`, { method: 'DELETE' })

export const setCategorySites = (id: number, siteIds: number[]) =>
  api<Category>(`/api/categories/${id}/sites`, { method: 'PUT', body: { site_ids: siteIds } })

// --- sites -------------------------------------------------------------------

export const listSites = () => api<{ data: Site[] }>('/api/sites')

export const createSite = (body: SiteCreateRequest) =>
  api<Site>('/api/sites', { method: 'POST', body })

export const updateSite = (id: number, body: SiteUpdateRequest) =>
  api<Site>(`/api/sites/${id}`, { method: 'PATCH', body })

export const deleteSite = (id: number) => api<void>(`/api/sites/${id}`, { method: 'DELETE' })

// --- items / listings / watches ----------------------------------------------

export const listItems = (params: ItemListParams = {}) =>
  api<Paginated<ItemSummary>>('/api/items', { params: { ...params } })

export const createItem = (body: ItemCreateRequest) =>
  api<ItemSummary>('/api/items', { method: 'POST', body })

export const getItem = (id: number) => api<ItemDetail>(`/api/items/${id}`)

export const updateItem = (id: number, body: ItemUpdateRequest) =>
  api<ItemDetail>(`/api/items/${id}`, { method: 'PATCH', body })

export const deleteItem = (id: number) => api<void>(`/api/items/${id}`, { method: 'DELETE' })

export const updateWatch = (itemId: number, body: WatchUpdateRequest) =>
  api<Watch>(`/api/items/${itemId}/watch`, { method: 'PATCH', body })

export const updateListing = (id: number, body: ListingUpdateRequest) =>
  api<Listing>(`/api/listings/${id}`, { method: 'PATCH', body })

export const listPriceChecks = (itemId: number, limit = 50) =>
  api<{ data: PriceCheck[] }>(`/api/items/${itemId}/price-checks`, { params: { limit } })

// --- vision ----------------------------------------------------------------------
// GET /api/vision/images/{key} serves bytes straight to <img src> and is
// deliberately not listed here — same precedent as the SSE stream.

export const listReviewQueue = (params: { item_id?: number; page?: number; per_page?: number } = {}) =>
  api<Paginated<ReviewQueueEntry>>('/api/vision/review-queue', { params: { ...params } })

export const confirmReviewEntry = (id: number, body: ReviewConfirmRequest) =>
  api<ReferenceImage>(`/api/vision/review-queue/${id}/confirm`, { method: 'POST', body })

export const discardReviewEntry = (id: number) =>
  api<void>(`/api/vision/review-queue/${id}`, { method: 'DELETE' })

export const listReferences = (itemId: number) =>
  api<{ data: ReferenceImage[] }>(`/api/items/${itemId}/references`)

/** form fields: file, label ('real' | 'fake'), variant_tag? */
export const uploadReference = (itemId: number, form: FormData) =>
  api<ReferenceImage>(`/api/items/${itemId}/references`, { method: 'POST', body: form })

export const revokeReference = (id: number) =>
  api<void>(`/api/vision/references/${id}`, { method: 'DELETE' })

export const revokeAutoReferences = (itemId: number) =>
  api<{ revoked: number }>(`/api/items/${itemId}/references/revoke-auto`, { method: 'POST' })

// --- charts / aggregates -------------------------------------------------------

export const getPriceHistory = (itemId: number, range: TimeRange, points = 300) =>
  api<PriceHistoryResponse>(`/api/items/${itemId}/price-history`, { params: { range, points } })

export const getPriceSummary = (itemId: number, range: TimeRange, points = 300) =>
  api<PriceSummaryResponse>(`/api/items/${itemId}/price-summary`, { params: { range, points } })

export const getCategoryPriceChange = (categoryId: number, range: TimeRange) =>
  api<CategoryPriceChangeResponse>(`/api/categories/${categoryId}/price-change`, {
    params: { range },
  })

export const getDashboardStats = (range: TimeRange) =>
  api<DashboardStats>('/api/dashboard/stats', { params: { range } })

export const getPriceDrops = (range: TimeRange, limit = 10) =>
  api<{ data: PriceDrop[] }>('/api/dashboard/price-drops', { params: { range, limit } })

// --- runs ----------------------------------------------------------------------

export const triggerRun = (body: RunCreateRequest) =>
  api<{ run: AgentRun }>('/api/runs', { method: 'POST', body })

export const listRuns = (params: RunListParams = {}) =>
  api<Paginated<AgentRun>>('/api/runs', { params: { ...params } })

export const getRun = (id: number) => api<AgentRun>(`/api/runs/${id}`)

export const getRunEvents = (id: number, afterSeq = 0, limit = 500) =>
  api<{ data: RunEvent[] }>(`/api/runs/${id}/events`, { params: { after_seq: afterSeq, limit } })

export const cancelRun = (id: number) => api<AgentRun>(`/api/runs/${id}/cancel`, { method: 'POST' })

// --- admin -----------------------------------------------------------------------

export const listUsers = () => api<{ data: AdminUser[] }>('/api/admin/users')

export const updateUser = (id: number, body: AdminUserUpdateRequest) =>
  api<AdminUser>(`/api/admin/users/${id}`, { method: 'PATCH', body })

export const deleteUser = (id: number) => api<void>(`/api/admin/users/${id}`, { method: 'DELETE' })

export const listInvites = () => api<{ data: Invite[] }>('/api/admin/invites')

export const createInvite = (body: InviteCreateRequest = {}) =>
  api<Invite>('/api/admin/invites', { method: 'POST', body })

export const revokeInvite = (id: number) =>
  api<void>(`/api/admin/invites/${id}`, { method: 'DELETE' })
