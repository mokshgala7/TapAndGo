import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { APP_DOWNLOAD_FILE_NAME } from '../../config/appDownload.js'
import './AppDownloadModal.css'

/**
 * Dialog shown by the "Download the App" button.
 *  - no download link configured -> a friendly "App download coming soon" message (nothing is downloaded)
 *  - link configured             -> the download has started; installation guidance and a "Download again" link
 */
function AppDownloadModal({ url, onClose }) {
  const closeRef = useRef(null)
  const available = Boolean(url)

  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // Rendered on <body>: the sticky header's backdrop blur would otherwise trap a fixed-position dialog inside it.
  return createPortal(
    <div className="tapgo-dl-backdrop" role="presentation" onClick={onClose}>
      <div
        className="tapgo-dl-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tapgo-dl-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="tapgo-dl-head">
          <span className="material-symbols-outlined" aria-hidden="true">
            {available ? 'download_done' : 'schedule'}
          </span>
          <h2 id="tapgo-dl-title">{available ? 'Your Tap&Go download has started' : 'App download coming soon'}</h2>
        </div>

        {available ? (
          <div className="tapgo-dl-body">
            <p>Install the Tap&amp;Go Android app in a few steps:</p>
            <ol>
              <li>Open the downloaded <strong>{APP_DOWNLOAD_FILE_NAME}</strong> file from your notifications or Downloads folder.</li>
              <li>
                If Android asks, allow <strong>Install unknown apps</strong> for your browser (Settings &rarr; Apps &rarr; your browser
                &rarr; Install unknown apps), then go back and tap Install.
              </li>
              <li>Open Tap&amp;Go, then log in or register.</li>
            </ol>
            <p className="tapgo-dl-note">Only install the app from this website. Android phones only.</p>
            <a className="tapgo-dl-again" href={url} download={APP_DOWNLOAD_FILE_NAME} rel="noopener">
              Download again
            </a>
          </div>
        ) : (
          <div className="tapgo-dl-body">
            <p>
              The Tap&amp;Go Android app is almost ready. The download will be available here soon &mdash; please check back shortly.
            </p>
            <p className="tapgo-dl-note">Questions? Write to tapandgosupport@gmail.com.</p>
          </div>
        )}

        <button ref={closeRef} type="button" className="tapgo-dl-close" onClick={onClose}>
          Close
        </button>
      </div>
    </div>,
    document.body,
  )
}

export default AppDownloadModal
