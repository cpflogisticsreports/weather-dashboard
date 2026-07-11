# CPF Logistics Weather Monitoring Dashboard

Live weather & typhoon monitoring for CPF Logistics operations. **PAGASA is the single source of truth.**

## Files
- `index.html` — the dashboard (self-contained: HTML + CSS + JS).
- `latest_pagasa_weather.json` — the live data file the dashboard fetches. **Edit this daily.**

## Deploy on GitHub Pages
1. Put both files in the root of your repo (or a `/docs` folder).
2. Settings → Pages → deploy from branch → `main` (root or `/docs`).
3. Open the published URL. The page fetches `latest_pagasa_weather.json` automatically.

> Opening `index.html` directly from disk (file://) shows the **offline fallback**, because
> browsers block `fetch()` on the file protocol. That is expected — it works once hosted on Pages.

## Updating the weather (daily workflow)
Edit `latest_pagasa_weather.json` only. The dashboard derives everything else automatically:
- **Title** adjusts from `situation.mode`: `typhoon` → "Typhoon [NAME]", `tropical_depression`,
  `advisory` → "Weather Advisory", `clear` → "Daily Weather".
- **Headline banner**, **operational status**, **dispatch action**, and **colors** are computed from the
  PAGASA facts you enter. Override any of them via `cpf.operational_status`, `cpf.dispatch_action`,
  `situation.headline_override`, or `situation.severity`.
- Any field left blank shows **"Not specified in latest PAGASA bulletin"** — never invented.

Set `situation.mode` to `clear` and empty the hazard blocks when weather is fine.

## Data indicator
- Green **"Data: live JSON"** = the JSON file loaded successfully.
- Red **"Data: offline fallback"** = the file could not be fetched; verify with PAGASA directly.

## Notes
- Auto-refreshes every 10 minutes; manual ⟳ Refresh and 🖨 Print (management view) in the header.
- Secondary satellite links (Himawari, RAMMB/CIRA, NOAA, Windy, Zoom Earth) are **visual reference only**
  and open in a new tab. They never override PAGASA.
