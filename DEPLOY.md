# Deployment

This app is deployed as a read-only Streamlit market preview. The crawler runs in
GitHub Actions and publishes the latest compressed JSONL data to a GitHub
Release asset.

## GitHub Actions crawler

Create these repository secrets:

- `BMALL_COOKIE`: Cookie header copied from the Bilibili Mall market page.
- `BMALL_PROXY`: Optional explicit proxy for the crawler.
- `HTTP_PROXY` / `HTTPS_PROXY`: Optional environment proxies.

The workflow `.github/workflows/crawl-bmall-data.yml` runs every Monday at
`08:00 Asia/Shanghai`, and can also be started manually from the Actions tab.

The workflow:

1. Downloads the previous `data-latest` release asset if it exists.
2. Runs `scripts/crawl_bmall_data.py` with `BMALL_COOKIE`.
3. Rebuilds `Data/bmall_all_data.jsonl.gz`.
4. Uploads it to the `data-latest` GitHub Release with `--clobber`.

The stable data URL for a public repository is:

```text
https://github.com/2513502304/bilibili-mall/releases/download/data-latest/bmall_all_data.jsonl.gz
```

## Streamlit app

Deploy `streamlit_app.py` on Streamlit Community Cloud and set:

- Python version: `3.14`
- `BMALL_DATA_URL`: the release asset URL above
- `BMALL_ENABLE_CRAWLER_PANEL`: leave unset or set to `false`

The crawler panel is hidden by default for hosted preview deployments. Local
development can opt in by setting `BMALL_ENABLE_CRAWLER_PANEL=true`.
