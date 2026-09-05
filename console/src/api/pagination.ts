// Pure pagination math -- 1-indexed pages, clamps out-of-range requests
// rather than returning an empty page or throwing.

export interface Page<T> {
  items: T[]
  page: number
  totalPages: number
  total: number
  from: number
  to: number
}

export function paginate<T>(items: T[], page: number, pageSize: number): Page<T> {
  const total = items.length
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const clampedPage = Math.min(Math.max(1, page), totalPages)
  const start = (clampedPage - 1) * pageSize
  const pageItems = items.slice(start, start + pageSize)
  const from = total === 0 ? 0 : start + 1
  const to = start + pageItems.length

  return { items: pageItems, page: clampedPage, totalPages, total, from, to }
}
