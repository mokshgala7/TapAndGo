/** "‹  Page 2 of 7  ›" under a paged list; hidden when everything fits on one page. */
function Pager({ paged }) {
  const { page, pageCount, total, pageSize, goTo } = paged
  if (pageCount <= 1) return null
  const from = page * pageSize + 1
  const to = Math.min((page + 1) * pageSize, total)
  return (
    // Not a <nav>: the dashboards style every <nav> as their fixed bottom tab bar.
    <div className="tg-pager" role="navigation" aria-label="Pages">
      <button type="button" className="tg-pager-btn" onClick={() => goTo(page - 1)} disabled={page === 0} aria-label="Previous page">
        <span className="material-symbols-outlined" aria-hidden="true">chevron_left</span>
      </button>
      <div className="tg-pager-label" aria-live="polite">
        <strong>
          Page {page + 1} of {pageCount}
        </strong>
        <span>
          {from}–{to} of {total}
        </span>
      </div>
      <button
        type="button"
        className="tg-pager-btn"
        onClick={() => goTo(page + 1)}
        disabled={page >= pageCount - 1}
        aria-label="Next page"
      >
        <span className="material-symbols-outlined" aria-hidden="true">chevron_right</span>
      </button>
    </div>
  )
}

export default Pager
