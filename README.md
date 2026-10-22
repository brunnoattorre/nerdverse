# NerdVerse

Landing page for NerdScience, NerdHistory and NerdNature.

`build.py` fetches each channel's 3 newest uploads and renders `index.html`. A GitHub
Action (`.github/workflows/daily.yml`) runs it every day at 13:30 UTC and publishes to
GitHub Pages; use **Actions → Daily build → Run workflow** to refresh right after an upload.

- Videos: YouTube Data API (`YOUTUBE_API_KEY` repo secret), falling back to scraping.
- Store products and channel copy live at the top of `build.py`.
- Local preview: `python3 build.py --offline` and open `index.html`.
