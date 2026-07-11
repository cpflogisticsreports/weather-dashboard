CPF Logistics Weather Monitoring Dashboard
Live weather & typhoon monitoring for CPF Logistics operations. PAGASA is the single source of truth.
Files
`index.html` — the dashboard (self-contained: HTML + CSS + JS).
`latest_pagasa_weather.json` — the live data file the dashboard fetches. Edit this daily.
Deploy on GitHub Pages
Put both files in the root of your repo (or a `/docs` folder).
Settings → Pages → deploy from branch → `main` (root or `/docs`).
Open the published URL. The page fetches `latest_pagasa_weather.json` automatically.
> Opening `index.html` directly from disk (file://) shows the **offline fallback**, because
> browsers block `fetch()` on the file protocol. That is expected — it works once hosted on Pages.
Updating the weather (daily workflow)
Edit `latest_pagasa_weather.json` only. The dashboard derives everything else automatically:
Title adjusts from `situation.mode`: `typhoon` → "Typhoon [NAME]", `tropical_depression`,
`advisory` → "Weather Advisory", `clear` → "Daily Weather".
Headline banner, operational status, dispatch action, and colors are computed from the
PAGASA facts you enter. Override any of them via `cpf.operational_status`, `cpf.dispatch_action`,
`situation.headline_override`, or `situation.severity`.
Any field left blank shows "Not specified in latest PAGASA bulletin" — never invented.
Set `situation.mode` to `clear` and empty the hazard blocks when weather is fine.
Automatic updates (no daily editing)
The dashboard can update itself from PAGASA — you don't have to edit the JSON by hand.
How it works. A scheduled GitHub Action (`.github/workflows/update-weather.yml`) runs the
Python scraper (`scripts/fetch_pagasa.py`) twice an hour. The scraper reads PAGASA's public
tropical-cyclone bulletin (and the daily forecast when no storm is active), maps it into
`latest_pagasa_weather.json`, and commits the file. The dashboard already re-fetches that file
every 10 minutes, so the live link refreshes on its own.
Turn it on.
Repo → Settings → Actions → General → Allow all actions → Save. (Required for Pages too.)
The workflow is already in the repo. Open the Actions tab → Update PAGASA weather →
Run workflow once to test it now (don't wait for the schedule).
Open the workflow run logs. On the first run they print what was parsed — confirm the storm
name, signals, and areas match the official PAGASA bulletin.
Important, because this drives dispatch decisions:
PAGASA has no official API, so this scrapes their public pages. It is best-effort and may
need a small tweak if PAGASA changes their page layout. The parsing rules live at the top of
`fetch_pagasa.py` and are commented.
It fails safe: if it can't reach or read PAGASA, it leaves the last good JSON untouched
rather than writing garbage.
Every auto-write is stamped in the Change Log and labelled "Automated — verify against the
official PAGASA bulletin." Keep a human spot-check before holding or releasing trips.
It auto-covers active tropical cyclones in detail. On calm days it writes the clear /
daily-weather state. Rich thunderstorm/gale/marine advisories on non-cyclone days may still
need a manual touch.
GitHub's scheduler is best-effort (runs can be a few minutes late) and pauses after ~60 days
of no repo activity — a single manual "Run workflow" click resumes it.
Keep custom CPF text across auto-updates (optional). Add a `cpf_overlay.json` at the repo root
with a `"cpf"` object — any non-empty key (e.g. `contractor_advisory`, `priority_routes`,
`risk_matrix`) overrides the auto-generated one on every run. Hubs are built in to the scraper
(edit the `HUBS` list in `fetch_pagasa.py` to add/remove sites).
Data indicator
Green "Data: live JSON" = the JSON file loaded successfully.
Red "Data: offline fallback" = the file could not be fetched; verify with PAGASA directly.
Notes
Auto-refreshes every 10 minutes; manual ⟳ Refresh and 🖨 Print (management view) in the header.
Secondary satellite links (Himawari, RAMMB/CIRA, NOAA, Windy, Zoom Earth) are visual reference only
and open in a new tab. They never override PAGASA.
