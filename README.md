# SupJav resolver for gpt云播

This service resolves a SupJav detail page into a short-lived, clean HLS/MP4 URL for the private gpt云播 Site. It keeps the upstream player session, cookies, user agent and exact player Referer on the server, rewrites HLS playlists, and proxies segments without exposing the resolver API key.

## Behavior

- Tries `supjav.com`, `supjav.net`, and `supjav.org` for search.
- Prefers EVS, FST, VOE, VAS and LUC routes; skips the ST route because it requires robot verification.
- Resolves simple iframe chains with a Safari-compatible TLS fingerprint first.
- Falls back to a real mobile Chromium session and repeats play clicks while blocking popup navigation.
- Rewrites HLS master/media playlists, keys, maps and segments through an opaque 45-minute playback session.
- Rejects private/reserved upstream addresses and never exposes an open proxy.

## Local run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
export RESOLVER_API_KEY=local-test-key
uvicorn app.main:app --port 8788
```

## API

Authenticated endpoints require `X-Resolver-Key`.

```text
GET  /health
GET  /v1/search?q=JUR-583&page=1
POST /v1/resolve   {"url":"https://supjav.com/350766.html"}
GET  /v1/media/{opaque-session}/{opaque-resource}
```

Deploy using the included Render Blueprint. Set `PUBLIC_BASE_URL` to the deployed Render URL and use the generated `RESOLVER_API_KEY` as the matching secret in the Site worker.
