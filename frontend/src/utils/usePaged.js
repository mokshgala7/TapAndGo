import { useId, useMemo, useState } from 'react'

export const PAGE_SIZE = 10

/**
 * Splits a long list into pages of `pageSize`. Changing `resetKey` (e.g. the
 * selected date range) goes back to the first page; a list that shrinks keeps
 * the page in range. Put `id={anchorId}` on the top of the list so changing
 * page scrolls back to it.
 */
export function usePaged(items, resetKey = '', pageSize = PAGE_SIZE) {
  const [state, setState] = useState({ key: resetKey, page: 0 })
  const anchorId = `paged-${useId().replace(/:/g, '')}`
  const list = useMemo(() => items || [], [items])
  const pageCount = Math.max(1, Math.ceil(list.length / pageSize))
  const page = Math.min(state.key === resetKey ? state.page : 0, pageCount - 1)
  const pageItems = useMemo(() => list.slice(page * pageSize, page * pageSize + pageSize), [list, page, pageSize])

  const goTo = (next) => {
    setState({ key: resetKey, page: next })
    document.getElementById(anchorId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return { pageItems, page, pageCount, total: list.length, pageSize, goTo, anchorId }
}
