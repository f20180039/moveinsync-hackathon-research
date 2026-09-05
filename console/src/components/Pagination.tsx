import type { Page } from '../api/pagination.ts'
import { Button } from './Button.tsx'

export interface PaginationProps<T> {
  page: Page<T>
  onPageChange: (page: number) => void
}

// "Showing 26–50 of 208" + Previous/Next. Page numbers are 1-indexed
// throughout, matching `paginate()`.
export function Pagination<T>({ page, onPageChange }: PaginationProps<T>) {
  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="pagination__summary">
        {page.total === 0 ? 'No results' : `Showing ${page.from}–${page.to} of ${page.total}`}
      </span>
      <div className="pagination__controls">
        <Button
          size="sm"
          variant="ghost"
          disabled={page.page <= 1}
          onClick={() => onPageChange(page.page - 1)}
        >
          Previous
        </Button>
        <span className="pagination__page">
          Page {page.page} of {page.totalPages}
        </span>
        <Button
          size="sm"
          variant="ghost"
          disabled={page.page >= page.totalPages}
          onClick={() => onPageChange(page.page + 1)}
        >
          Next
        </Button>
      </div>
    </nav>
  )
}
