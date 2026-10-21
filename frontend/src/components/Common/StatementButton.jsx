import { useState } from 'react'

/**
 * "Download statement (PDF)". `getData` returns what the statement shows
 * ({ holderName, email, role, balance, transactions }); the PDF code is loaded
 * only when the button is pressed.
 */
function StatementButton({ getData, onError, label = 'Download statement (PDF)', className = '' }) {
  const [busy, setBusy] = useState(false)

  const download = async () => {
    setBusy(true)
    try {
      const { downloadStatementPdf } = await import('../../utils/statementPdf.js')
      await downloadStatementPdf(getData())
    } catch (error) {
      console.error('Statement download failed:', error)
      onError?.('Could not create the statement. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <button type="button" className={`tg-statement-btn ${className}`.trim()} onClick={download} disabled={busy}>
      <span className="material-symbols-outlined" aria-hidden="true">download</span>
      {busy ? 'Preparing statement…' : label}
    </button>
  )
}

export default StatementButton
