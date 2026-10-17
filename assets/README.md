# VozAta assets

Derived from the exact SVG supplied by the project owner. The full logo is preserved; icon-only variants remove only the wordmark/tagline and retain the document + audio waveform, gradient (#38bdf8 to #a855f7), and dark background (#111827).

- `svg/logo-full.svg`: original full logo.
- `svg/logo-icon.svg`: icon-only logo.
- `web/`: favicon SVG/ICO/PNG, Apple touch icon, full logo PNG.
- `pwa/`: PWA icon sizes and manifest.
- `desktop/windows/`: Windows ICO and PNGs.
- `desktop/macos/`: ICNS if supported, plus iconset PNGs.

HTML: `<link rel="icon" href="/assets/web/favicon.ico">`, `<link rel="icon" type="image/svg+xml" href="/assets/web/favicon.svg">`, `<link rel="apple-touch-icon" href="/assets/web/apple-touch-icon.png">`, `<link rel="manifest" href="/assets/pwa/manifest.webmanifest">`.
