// The ONE place that decides where the "Download the App" button gets the Android app from.
//
// To publish the app: put the link of the final, signed RELEASE APK below (or set the build-time
// variable VITE_APP_DOWNLOAD_URL; it wins over the value below), then rebuild/redeploy the website.
// Leave it empty until that APK exists: the button then shows an "App download coming soon" message
// and never downloads anything.
//
// Accepted: an https:// link, or a path on this website that ends in .apk (e.g. '/downloads/TapAndGo.apk').
// Refused on purpose (treated as "not configured"): http:// links, other schemes (javascript:, data: ...),
// anything that is not an .apk file, and any file name containing "debug" (a debug build must never be public).
// Change ONLY this line when a new build is published.
export const APP_DOWNLOAD_URL = 'https://github.com/mokshgala7/tapandgo-android-releases/releases/download/v1.0.0-build8/TapAndGo-1.0.0-build8.apk'

export const APP_DOWNLOAD_FILE_NAME = 'TapAndGo.apk'

export function resolveAppDownloadUrl(raw = import.meta.env.VITE_APP_DOWNLOAD_URL || APP_DOWNLOAD_URL) {
  const value = String(raw ?? '').trim()
  if (!value) return ''
  const isHttps = /^https:\/\//i.test(value)
  const isSitePath = /^\/(?!\/)/.test(value)
  if (!isHttps && !isSitePath) return ''
  let pathname
  if (isHttps) {
    try {
      pathname = new URL(value).pathname
    } catch {
      return ''
    }
  } else {
    pathname = value.split(/[?#]/)[0]
  }
  if (!/\.apk$/i.test(pathname)) return ''
  if (/debug/i.test(value)) return ''
  return value
}
