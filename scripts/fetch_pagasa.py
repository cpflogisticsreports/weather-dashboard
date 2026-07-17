#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CPF Logistics — PAGASA auto-updater
===================================
Fetches PAGASA's live tropical-cyclone bulletin (and daily forecast when no
cyclone is active), maps it into the dashboard's JSON schema, and writes
`latest_pagasa_weather.json`. Meant to run on a schedule via GitHub Actions.

PAGASA has no public API, so this SCRAPES their public pages. That means:
  * It is best-effort and may need tuning when PAGASA changes their layout.
  * It FAILS SAFE — if it cannot read PAGASA confidently, it does NOT overwrite
    the last good JSON; it just exits so the dashboard keeps the last bulletin.
  * Every auto-write is stamped in the Change Log so it is clear the data was
    machine-parsed and should be confirmed against the official bulletin.

PAGASA data is public domain. This tool is not affiliated with PAGASA.
"""

import json, re, sys, os, datetime, html, math, urllib.request, urllib.error

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
OUT_FILE   = os.environ.get("OUT_FILE", "latest_pagasa_weather.json")
OVERLAY    = os.environ.get("CPF_OVERLAY", "cpf_overlay.json")  # optional
UA         = "CPF-Logistics-WeatherBot/1.0 (+logistics monitoring; contact: logistics@cpf)"
TIMEOUT    = 30
PH_TZ      = datetime.timezone(datetime.timedelta(hours=8))

# PAGASA public pages (scraped; no API exists)
BULLETIN_URLS = [
    "https://www.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin",
    "https://bagong.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin/1",
]
FORECAST_URLS = [
    "https://www.pagasa.dost.gov.ph/weather",
    "https://bagong.pagasa.dost.gov.ph/weather",
]

# CPF hub roster (mirrors the dashboard). `keys` = lowercase strings that may
# appear in PAGASA area text so we can flag a hub as affected.
HUBS = [
    {"name":"Gerona Feedmill","region":"Central Luzon (Tarlac)","type":"Feedmill","lat":15.6344949,"lon":120.5933201,"keys":["tarlac"]},
    {"name":"Ilagan Feedmill","region":"Cagayan Valley (Isabela)","type":"Feedmill","lat":17.1227406,"lon":121.851358,"keys":["isabela"]},
    {"name":"Samal Feedmill","region":"Central Luzon (Bataan)","type":"Feedmill","lat":14.7647281,"lon":120.4945722,"keys":["bataan"]},
    {"name":"Batangas Port Hub","region":"CALABARZON","type":"Port / RORO","lat":13.7557,"lon":121.0579,"keys":["batangas"]},
    {"name":"Cebu Hub","region":"Central Visayas","type":"Distribution","lat":10.2929,"lon":123.9016,"keys":["cebu"]},
    {"name":"CDO Hub","region":"Northern Mindanao (Cagayan de Oro)","type":"Distribution","lat":8.4765,"lon":124.6412,"keys":["misamis oriental"]},
    {"name":"Davao Hub","region":"Davao Region","type":"Distribution","lat":7.0646,"lon":125.6079,"keys":["davao del sur","davao del norte"]},
    {"name":"GenSan Hub","region":"SOCCSKSARGEN (General Santos)","type":"Distribution","lat":6.1129,"lon":125.1717,"keys":["south cotabato","sarangani"]},
]

# Province vocabulary used to pull area names out of signal blocks.
PROVINCES = [
    "batanes","cagayan","isabela","quirino","nueva vizcaya","apayao","kalinga","abra","mountain province",
    "ifugao","benguet","ilocos norte","ilocos sur","la union","pangasinan","zambales","tarlac","pampanga",
    "bataan","bulacan","nueva ecija","aurora","metro manila","rizal","cavite","laguna","batangas","quezon",
    "polillo","marinduque","occidental mindoro","oriental mindoro","romblon","palawan","camarines norte",
    "camarines sur","catanduanes","albay","sorsogon","masbate","northern samar","eastern samar","samar",
    "biliran","leyte","southern leyte","aklan","antique","capiz","iloilo","guimaras","negros occidental",
    "negros oriental","cebu","bohol","siquijor","zamboanga del norte","zamboanga del sur","zamboanga sibugay",
    "misamis occidental","misamis oriental","bukidnon","lanao del norte","lanao del sur","camiguin",
    "agusan del norte","agusan del sur","surigao del norte","surigao del sur","dinagat islands",
    "davao del norte","davao del sur","davao oriental","davao occidental","davao de oro","compostela valley",
    "cotabato","south cotabato","sultan kudarat","sarangani","general santos","maguindanao","basilan","sulu","tawi-tawi",
]

CENTROIDS = {
    "batanes":[20.45,121.97],"cagayan":[18.0,121.7],"isabela":[16.9,121.8],"quirino":[16.4,121.6],
    "nueva vizcaya":[16.4,121.15],"apayao":[18.0,121.2],"kalinga":[17.5,121.3],"abra":[17.6,120.75],
    "mountain province":[17.05,121.0],"ifugao":[16.85,121.15],"benguet":[16.5,120.7],"ilocos norte":[18.1,120.7],
    "ilocos sur":[17.3,120.5],"la union":[16.6,120.35],"pangasinan":[15.9,120.35],"zambales":[15.5,120.0],
    "tarlac":[15.48,120.6],"pampanga":[15.05,120.68],"bataan":[14.65,120.45],"bulacan":[14.9,120.95],
    "nueva ecija":[15.7,121.0],"aurora":[15.75,121.55],"metro manila":[14.6,121.0],"rizal":[14.6,121.25],
    "cavite":[14.28,120.87],"laguna":[14.2,121.35],"batangas":[13.9,121.05],"quezon":[14.0,122.1],
    "marinduque":[13.42,121.9],"occidental mindoro":[12.9,120.9],"oriental mindoro":[13.0,121.2],
    "romblon":[12.55,122.27],"palawan":[9.8,118.7],"camarines norte":[14.14,122.79],"camarines sur":[13.62,123.35],
    "catanduanes":[13.7,124.24],"albay":[13.28,123.55],"sorsogon":[12.87,124.0],"masbate":[12.37,123.62],
    "northern samar":[12.4,124.65],"eastern samar":[11.65,125.5],"samar":[11.8,125.0],"biliran":[11.55,124.45],
    "leyte":[10.8,124.85],"southern leyte":[10.35,125.0],"aklan":[11.7,122.35],"antique":[11.2,122.0],
    "capiz":[11.4,122.7],"iloilo":[10.9,122.55],"guimaras":[10.6,122.63],"negros occidental":[10.3,123.0],
    "negros oriental":[9.6,123.0],"cebu":[10.5,123.85],"bohol":[9.85,124.15],"siquijor":[9.2,123.5],
    "zamboanga del norte":[8.2,123.0],"zamboanga del sur":[7.85,123.4],"misamis occidental":[8.35,123.7],
    "misamis oriental":[8.5,124.9],"bukidnon":[8.05,125.05],"lanao del norte":[8.0,123.9],
    "camiguin":[9.17,124.73],"agusan del norte":[9.0,125.55],"agusan del sur":[8.45,125.75],
    "surigao del norte":[9.8,125.5],"surigao del sur":[8.8,126.1],"davao del norte":[7.55,125.7],
    "davao del sur":[6.75,125.35],"davao oriental":[7.3,126.35],"davao de oro":[7.9,126.1],
    "cotabato":[7.2,124.85],"south cotabato":[6.3,124.85],"sultan kudarat":[6.5,124.4],"sarangani":[5.9,125.15],
}

CATEGORY_WORDS = ["Super Typhoon","Severe Tropical Storm","Tropical Storm","Tropical Depression","Typhoon"]

# Matches "24.0 °N, 125.2 °E", "(13.6°N,128.6°E)", "14.5 N 121.0 E", etc.
COORD_RE = re.compile(r"([\d]{1,2}(?:\.\d+)?)\s*°?\s*N\s*[, ]\s*([\d]{2,3}(?:\.\d+)?)\s*°?\s*E", re.I)

def _valid_ph(lat, lon):
    return 3.0 <= lat <= 45.0 and 105.0 <= lon <= 175.0


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def now_iso():
    return datetime.datetime.now(PH_TZ).replace(microsecond=0).isoformat()

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August",
     "September","October","November","December"], 1)}

def _parse_ampm(tstr):
    """'11:00 am' -> (hour24, minute) or None."""
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*([AaPp])[Mm]", tstr or "")
    if not m:
        return None
    h = int(m.group(1)) % 12
    mi = int(m.group(2))
    if m.group(3).lower() == "p":
        h += 12
    return h, mi

def issued_to_iso(tstr, dstr):
    """('11:00 am', '14 July 2026') -> ISO8601 with +08:00, or '' on failure."""
    hm = _parse_ampm(tstr)
    dm = re.match(r"\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", dstr or "")
    if not hm or not dm:
        return ""
    mon = _MONTHS.get(dm.group(2).lower())
    if not mon:
        return ""
    try:
        return datetime.datetime(int(dm.group(3)), mon, int(dm.group(1)),
                                 hm[0], hm[1], tzinfo=PH_TZ).replace(microsecond=0).isoformat()
    except ValueError:
        return ""

def time_relative_iso(tstr, rel, base_iso):
    """('5:00 PM', 'today'|'tomorrow'|None, issued_iso) -> ISO on that date."""
    hm = _parse_ampm(tstr)
    if not hm:
        return ""
    try:
        base = datetime.datetime.fromisoformat(base_iso) if base_iso else datetime.datetime.now(PH_TZ)
    except ValueError:
        base = datetime.datetime.now(PH_TZ)
    if rel and rel.lower() == "tomorrow":
        base = base + datetime.timedelta(days=1)
    return base.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0).isoformat()

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")

def strip_tags(h):
    h = re.sub(r"(?is)<script.*?</script>", " ", h)
    h = re.sub(r"(?is)<style.*?</style>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = html.unescape(h)
    return re.sub(r"[ \t]+", " ", h)

def find_provinces(text):
    """Match known provinces, longest first, masking each hit so a shorter
    contained name (e.g. 'Samar' inside 'Northern Samar') can't re-match."""
    work = text.lower()
    hits = []
    for p in sorted(PROVINCES, key=len, reverse=True):
        for m in re.finditer(r"\b" + re.escape(p) + r"\b", work):
            hits.append((m.start(), p))
        work = re.sub(r"\b" + re.escape(p) + r"\b", lambda mm: " " * len(mm.group()), work)
    # order by first appearance, de-dup
    seen, res = set(), []
    for _, p in sorted(hits, key=lambda x: x[0]):
        if p not in seen:
            seen.add(p); res.append(p.title())
    return res


# --------------------------------------------------------------------------- #
# Geocoding for PAGASA forecast positions
# PAGASA writes forecast positions as "<km> km <direction> of <place>" (no
# lat/lon), so we project from a small gazetteer of the reference points they use.
# --------------------------------------------------------------------------- #
GAZETTEER = {
    "basco":[20.45,121.97],"itbayat":[20.78,121.85],"calayan":[19.26,121.47],
    "aparri":[18.36,121.64],"tuguegarao":[17.61,121.73],"santa ana":[18.47,122.14],
    "laoag":[18.20,120.59],"vigan":[17.57,120.39],"dagupan":[16.04,120.34],
    "san fernando, la union":[16.62,120.32],"iba":[15.33,119.98],"baler":[15.76,121.56],
    "casiguran":[16.28,122.12],"infanta":[14.75,121.65],"daet":[14.11,122.95],
    "virac":[13.58,124.23],"legazpi":[13.14,123.73],"juban":[12.85,123.99],
    "catbalogan":[11.78,124.88],"borongan":[11.61,125.43],"guiuan":[11.03,125.72],
    "surigao":[9.79,125.49],"catarman":[12.50,124.63],
    "extreme northern luzon":[18.60,121.50],"northern luzon":[17.50,121.20],
    "batanes":[20.45,121.97],"babuyan islands":[19.50,121.90],"mainland cagayan":[18.00,121.70],
    "cagayan":[18.00,121.70],"catanduanes":[13.70,124.24],"isabela":[16.90,121.80],
    "aurora":[15.75,121.55],"quezon":[14.00,122.10],"palanan":[17.06,122.43],
}

DIR16 = {"n":0,"nne":22.5,"ne":45,"ene":67.5,"e":90,"ese":112.5,"se":135,"sse":157.5,
         "s":180,"ssw":202.5,"sw":225,"wsw":247.5,"w":270,"wnw":292.5,"nw":315,"nnw":337.5}
_WMAP = {"north":"n","south":"s","east":"e","west":"w",
         "northeast":"ne","northwest":"nw","southeast":"se","southwest":"sw"}

def dir_to_bearing(phrase):
    code = "".join(_WMAP.get(w, "") for w in phrase.lower().split())
    return DIR16.get(code)

def project(lat, lon, bearing_deg, dist_km, R=6371.0):
    br = math.radians(bearing_deg); d = dist_km / R
    la, lo = math.radians(lat), math.radians(lon)
    la2 = math.asin(math.sin(la)*math.cos(d) + math.cos(la)*math.sin(d)*math.cos(br))
    lo2 = lo + math.atan2(math.sin(br)*math.sin(d)*math.cos(la),
                          math.cos(d) - math.sin(la)*math.sin(la2))
    return round(math.degrees(la2), 2), round(math.degrees(lo2), 2)

def geocode_place(place):
    p = place.lower().strip()
    for k in sorted(GAZETTEER, key=len, reverse=True):
        if k in p:
            return GAZETTEER[k]
    return None

def short_when(s):
    m = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2}),.*?(\d{1,2}):(\d{2})\s*([AP]M)", s)
    if not m: return s.strip()[:14]
    hr = m.group(3).lstrip("0") or "0"
    return f"{m.group(1)} {m.group(2)} {hr}{m.group(5)}"

def parse_forecast_positions(text):
    """Extract PAGASA 'Forecast Position' lines and geocode them to lat/lon."""
    pts = []
    m = re.search(r"Forecast Position(.*?)(Wind Signal|Considering these|Tropical Cyclone Bulletin Archive|We always find|$)",
                  text, re.I | re.S)
    if not m: return pts
    block = m.group(1)
    line_re = re.compile(
        r"([A-Z][a-z]{2}\s+\d{1,2},\s*\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)\s*[-–]\s*"
        r"([\d]+)\s*km\s+([A-Za-z ]+?)\s+of\s+([A-Za-z .]+?)\s*(?:,|\(|$)", re.I)
    for lm in line_re.finditer(block):
        when, km, direction, place = lm.group(1), int(lm.group(2)), lm.group(3), lm.group(4)
        base = geocode_place(place)
        br = dir_to_bearing(direction)
        if base and br is not None:
            lat, lon = project(base[0], base[1], br, km)
            if _valid_ph(lat, lon):
                pts.append({"label": short_when(when), "lat": lat, "lon": lon})
    return pts

def parse_signals(raw):
    """Read TCWS levels from the tcwsN.png image markers in the raw HTML, then
    pull each signal's affected-area list and match known provinces."""
    marks = [(m.start(), int(m.group(1))) for m in re.finditer(r"tcws([1-5])\.png", raw, re.I)]
    sigs = []
    for i, (pos, lvl) in enumerate(marks):
        end = marks[i+1][0] if i+1 < len(marks) else pos + 6000
        chunk = strip_tags(raw[pos:end])
        am = re.search(r"Affected Areas(.*?)(Meteorological Condition|Impact of the Wind|$)", chunk, re.I | re.S)
        seg = am.group(1) if am else chunk
        areas = find_provinces(seg)
        if areas:
            sigs.append({"signal": lvl, "areas": areas})
    best = {}
    for s in sigs:
        if s["signal"] not in best or len(s["areas"]) > len(best[s["signal"]]["areas"]):
            best[s["signal"]] = s
    return [best[k] for k in sorted(best.keys(), reverse=True)]


# --------------------------------------------------------------------------- #
# Bulletin parsing (active tropical cyclone)
# --------------------------------------------------------------------------- #
def parse_bulletin(raw):
    """Return a dict of PAGASA facts, or None if nothing trackable is on the page.
    Handles active tropical cyclones AND a Low Pressure Area (formerly a TC) that
    PAGASA is still bulletining on the tropical-cyclone page. `raw` is the raw HTML
    (needed to read signal levels from image filenames)."""
    text = strip_tags(raw)

    # ---- Low Pressure Area path -------------------------------------------- #
    # When a storm weakens, PAGASA keeps publishing it here as an LPA (e.g.
    # 'LPA "Josie"' / 'Low Pressure Area (formerly "JOSIE")'). Capture it as a
    # Low Pressure Area system so the dashboard reflects the latest bulletin,
    # rather than silently dropping to the daily forecast or showing a stale TC.
    is_lpa = bool(re.search(r"low\s*pressure\s*area|(?<![A-Za-z])LPA(?![A-Za-z])"
                            r"|(?:weakened|degenerated)\s+into\s+a\s+(?:remnant\s+)?low", text, re.I))
    has_tc_cat = any(re.search(c + r"\s+[\"“']?[A-Z][A-Za-z]+", text) for c in CATEGORY_WORDS)
    if is_lpa and not has_tc_cat:
        # A genuinely final bulletin with no center/track left is not useful.
        lpa_name = None
        m = re.search(r'(?:low\s*pressure\s*area|LPA)[^"“\'A-Za-z]*(?:\(?\s*formerly\s*)?["“\']([A-Za-z]+)', text, re.I)
        if not m:
            m = re.search(r'formerly\s+["“\']([A-Za-z]+)', text, re.I)
        if m: lpa_name = m.group(1).upper()
        facts = {"category": "Low Pressure Area", "name": lpa_name, "intl": None, "is_lpa": True, "signals": []}
        mm = re.search(r"\(\s*([\d.]+)\s*°?\s*N\s*,\s*([\d.]+)\s*°?\s*E", text)
        if mm:
            facts["lat"] = float(mm.group(1)); facts["lon"] = float(mm.group(2))
        m = re.search(r"moving\s+([A-Za-z ]+?)\s+at\s+([\d]+)\s*(?:km/?h|kph)", text, re.I)
        if m: facts["movement"] = f"{m.group(1).strip().title()} at {m.group(2)} km/h"
        mc = re.search(r"(?:estimated .{0,80}?at\s+)(.*?)\(\s*[\d.]+\s*°?\s*N", text, re.I|re.S)
        if mc: facts["center_text"] = re.sub(r"\s+", " ", mc.group(1)).strip(" ,")
        m = re.search(r"(?:Bulletin|SWB)\s*(?:No\.|#)\s*([0-9]+[A-Z]?)", text, re.I)
        if m: facts["bulletin_no"] = m.group(1)
        m = re.search(r"Issued at[:\s]+(\d{1,2}:\d{2}\s*[AaPp][Mm])\s*,?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text)
        facts["issued_at_iso"] = issued_to_iso(m.group(1), m.group(2)) if m else ""
        m = re.search(r"next advisory to be issued at\s+(\d{1,2}:\d{2}\s*[AaPp][Mm])\s*(today|tomorrow)?", text, re.I)
        if m: facts["next_advisory_iso"] = time_relative_iso(m.group(1), m.group(2), facts["issued_at_iso"])
        m = re.search(r"(heavy rainfall.{0,600}?)(?:\n\n|The wind signals|Hoisting|Track|$)", text, re.I|re.S)
        if m: facts["rain_text"] = re.sub(r"\s+", " ", m.group(1)).strip()[:600]
        track = []
        if facts.get("lat") is not None and facts.get("lon") is not None and _valid_ph(facts["lat"], facts["lon"]):
            track.append({"label": "Now", "lat": facts["lat"], "lon": facts["lon"]})
        for p in parse_forecast_positions(text):
            track.append(p)
        facts["track"] = track[:9]
        facts["affected_areas"] = parse_affected_areas(text)
        return facts

    # A truly final bulletin with no LPA/center → let the daily forecast take over.
    if re.search(r"final tropical cyclone bulletin|last tropical cyclone bulletin|no longer a tropical cyclone", text, re.I) and not is_lpa:
        return None
    # Storm category + local name, e.g. "Typhoon INDAY", "Tropical Depression AghON"
    cat, name = None, None
    for c in CATEGORY_WORDS:  # ordered so 'Typhoon' doesn't shadow 'Super Typhoon'
        m = re.search(c + r"\s+[\"“']?([A-Z][A-Za-z]+)", text)
        if m:
            cat, name = c, m.group(1).upper()
            break
    if not cat:
        return None  # no active TC found in this text

    intl = None
    m = re.search(r"\(international name[:\s]+([A-Za-z\- ]+?)\)", text, re.I)
    if m: intl = m.group(1).strip().upper()

    facts = {"category": cat, "name": name, "intl": intl}

    # Center description + coordinates
    m = re.search(r"center of .{0,60}?\bat\b\s+(.*?)\(\s*([\d.]+)\s*°?\s*N\s*,\s*([\d.]+)\s*°?\s*E", text, re.I|re.S)
    if m:
        facts["center_text"] = re.sub(r"\s+", " ", m.group(1)).strip(" ,")
        facts["lat"] = float(m.group(2)); facts["lon"] = float(m.group(3))
    else:
        m = re.search(r"\(\s*([\d.]+)\s*°?\s*N\s*,\s*([\d.]+)\s*°?\s*E", text)
        if m:
            facts["lat"] = float(m.group(1)); facts["lon"] = float(m.group(2))

    m = re.search(r"maximum sustained winds of\s+([\d]+)\s*(?:km/?h|kph)", text, re.I)
    if m: facts["winds"] = int(m.group(1))
    m = re.search(r"gustiness of up to\s+([\d]+)\s*(?:km/?h|kph)", text, re.I)
    if m: facts["gust"] = int(m.group(1))
    m = re.search(r"central pressure of\s+([\d]+)\s*hpa", text, re.I)
    if m: facts["pressure"] = int(m.group(1))
    m = re.search(r"moving\s+([A-Za-z ]+?)\s+at\s+([\d]+)\s*(?:km/?h|kph)", text, re.I)
    if m: facts["movement"] = f"{m.group(1).strip().title()} at {m.group(2)} km/h"
    m = re.search(r"(?:Bulletin|SWB)\s*(?:No\.|#)\s*([0-9]+[A-Z]?)", text, re.I)
    if m: facts["bulletin_no"] = m.group(1)

    # Official issued time, e.g. "Issued at 11:00 am, 14 July 2026"
    m = re.search(r"Issued at[:\s]+(\d{1,2}:\d{2}\s*[AaPp][Mm])\s*,?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text)
    issued_iso = issued_to_iso(m.group(1), m.group(2)) if m else ""
    facts["issued_at_iso"] = issued_iso
    # Next advisory / validity, e.g. "the next advisory to be issued at 5:00 PM today"
    m = re.search(r"next advisory to be issued at\s+(\d{1,2}:\d{2}\s*[AaPp][Mm])\s*(today|tomorrow)?", text, re.I)
    if m: facts["next_advisory_iso"] = time_relative_iso(m.group(1), m.group(2), issued_iso)

    # Wind signals: levels come from tcwsN.png image markers in the raw HTML.
    facts["signals"] = parse_signals(raw)

    # Heavy rainfall outlook (best-effort)
    m = re.search(r"(heavy rainfall.{0,600}?)(?:\n\n|The wind signals|Hoisting|Track|$)", text, re.I|re.S)
    if m: facts["rain_text"] = re.sub(r"\s+", " ", m.group(1)).strip()[:600]

    # Wind extent (radius of strong/gale winds), if stated
    m = re.search(r"extend(?:ing|s)?\s+outward\s+up\s+to\s+([\d]+)\s*km", text, re.I)
    if m: facts["wind_extent"] = int(m.group(1))

    # Forecast track: current center (has lat/lon) + geocoded forecast positions
    track = []
    if facts.get("lat") is not None and facts.get("lon") is not None and _valid_ph(facts["lat"], facts["lon"]):
        track.append({"label": "Now", "lat": facts["lat"], "lon": facts["lon"]})
    for p in parse_forecast_positions(text):
        if track and abs(track[-1]["lat"]-p["lat"]) < 0.05 and abs(track[-1]["lon"]-p["lon"]) < 0.05:
            continue
        track.append(p)
    facts["track"] = track[:9]
    facts["affected_areas"] = parse_affected_areas(text)

    return facts


# --------------------------------------------------------------------------- #
# CPF derivation (deterministic — maps PAGASA facts to hub/route/risk output)
# --------------------------------------------------------------------------- #
def affected_level(hub, signals, rain_provs):
    """Return a hub status string based on PAGASA affected areas.
    Matches on exact province equality (areas come from the province vocabulary)
    so e.g. 'Cagayan' province never falsely matches 'Cagayan de Oro'."""
    hub_keys = set(k.lower() for k in hub["keys"])
    max_sig = 0
    for s in signals:
        for a in s["areas"]:
            if a.lower() in hub_keys:
                max_sig = max(max_sig, s["signal"])
    in_rain = any(p.lower() in hub_keys for p in rain_provs)
    if max_sig >= 2: return "Dispatch Hold"
    if max_sig == 1: return "Route Validation"
    if in_rain:      return "Heightened"
    return "Normal"

def build_hubs(signals, rain_provs):
    out = []
    for h in HUBS:
        out.append({"name":h["name"],"region":h["region"],"type":h["type"],
                    "lat":h["lat"],"lon":h["lon"],
                    "status": affected_level(h, signals, rain_provs)})
    return out

def build_risk_matrix(hubs):
    order = {"Normal":0,"Heightened":1,"Route Validation":2,"Dispatch Hold":3}
    rows = []
    for h in sorted(hubs, key=lambda x: order.get(x["status"],0), reverse=True):
        st = h["status"]
        if st == "Normal": continue
        level  = {"Heightened":"Caution","Route Validation":"High","Dispatch Hold":"Critical"}[st]
        hazard = {"Heightened":"Rainfall in area","Route Validation":"Wind Signal / heavy rain","Dispatch Hold":"Wind Signal (severe)"}[st]
        action = {"Heightened":"Dispatch with caution","Route Validation":"Require route validation before dispatch","Dispatch Hold":"Hold dispatch"}[st]
        rows.append({"area":h["region"],"hazard":hazard,"likelihood":"High" if level!="Caution" else "Medium",
                     "impact":"High" if level=="Critical" else "Medium","level":level,"action":action})
    return rows


# --------------------------------------------------------------------------- #
# Assemble dashboard JSON
# --------------------------------------------------------------------------- #
def assemble(facts, source_url):
    stamp = now_iso()
    signals = facts.get("signals", [])
    rain_provs = find_provinces(facts.get("rain_text","")) if facts.get("rain_text") else []
    hubs = build_hubs(signals, rain_provs)

    cl = facts["category"].lower()
    is_lpa = facts.get("is_lpa", False)
    if is_lpa:
        mode = "lpa"
    elif "depression" in cl:
        mode = "tropical_depression"
    elif "storm" in cl:          # Tropical Storm & Severe Tropical Storm
        mode = "tropical_storm"
    else:                        # Typhoon & Super Typhoon
        mode = "typhoon"

    issued = facts.get("issued_at_iso") or stamp
    nxt = facts.get("next_advisory_iso", "")

    data = {
        "meta": {
            "source": "PAGASA (auto-parsed)",
            "bulletin_title": (f"Tropical Cyclone Bulletin No. {facts['bulletin_no']}"
                               if facts.get("bulletin_no") else
                               ("PAGASA Low Pressure Area Bulletin" if is_lpa else "PAGASA Tropical Cyclone Bulletin")),
            "issued_at": issued, "valid_until": nxt, "next_update": nxt, "generated_at": stamp,
            "prepared_by": "Automated (fetch_pagasa.py) — verify against official PAGASA bulletin",
            "bulletin_url": source_url,
        },
        "situation": {
            "mode": mode, "has_active_tc": (not is_lpa),
            "storm_name_local": facts.get("name",""),
            "storm_name_intl": facts.get("intl",""),
            "category": facts["category"], "severity": "", "headline_override": "",
        },
        "cyclone": {
            "center_text": facts.get("center_text",""),
            "lat": facts.get("lat",""), "lon": facts.get("lon",""),
            "max_sustained_winds_kph": facts.get("winds",""),
            "gustiness_kph": facts.get("gust",""),
            "central_pressure_hpa": facts.get("pressure",""),
            "movement": facts.get("movement",""),
            "wind_extent_km": facts.get("wind_extent",""),
            "forecast_track": [
                {"label": p["label"], "lat": p["lat"], "lon": p["lon"],
                 "category": facts["category"], "winds_kph": facts.get("winds","")}
                for p in facts.get("track", [])
            ],
        },
        "tcws": [{"signal": s["signal"], "wind_range": "", "lead_time": "", "areas": s["areas"]} for s in signals],
        "rainfall": {
            "outlook": facts.get("rain_text",""),
            "warning_level": "Heavy" if facts.get("rain_text") and re.search(r"intense|heavy", facts["rain_text"], re.I) else "",
            "habagat_affected": [], "areas": [
                {"name": p, "lat": CENTROIDS.get(p.lower(),[None,None])[0], "lon": CENTROIDS.get(p.lower(),[None,None])[1], "level": "Heavy"}
                for p in rain_provs if p.lower() in CENTROIDS
            ],
        },
        "thunderstorm": {"active": False, "advisory": "", "areas": []},
        "gale_warning": {"active": False, "seaboards": [], "areas": []},
        "marine": {"hazards": "", "affected_waters": [], "risk_level": ""},
        "forecast": {"synopsis": "", "regions": _flatten_regions(facts.get("affected_areas")),
                     "wind_outlook": (facts.get("affected_areas") or {}).get("days", []),
                     "wind_hazard": (facts.get("affected_areas") or {}).get("hazard", ""),
                     "conditions": []},
        "cpf": {
            "operational_status": "", "dispatch_action": "",
            "executive_summary": auto_summary(facts, signals, hubs),
            "priority_routes": [
                {"route": f"Trips to {h['region']}", "risk": {"Heightened":"Moderate","Route Validation":"High","Dispatch Hold":"Critical"}[h["status"]],
                 "note": "Auto-flagged from PAGASA affected areas"}
                for h in hubs if h["status"] != "Normal"
            ],
            "risk_matrix": build_risk_matrix(hubs),
            "contractor_advisory": auto_contractor(hubs),
            "affected_deliveries_note": "",
            "hubs": hubs,
            "change_log": [{"time": stamp,
                            "entry": f"Auto-updated from PAGASA bulletin at {stamp}. Machine-parsed — confirm against the official PAGASA bulletin before dispatch."}],
        },
    }
    return merge_overlay(data)

def auto_summary(facts, signals, hubs):
    parts = [f"{facts['category']} “{facts.get('name','')}” is being tracked by PAGASA."]
    if facts.get("center_text"): parts.append(f"Center: {facts['center_text']}.")
    holds = [h["region"] for h in hubs if h["status"] == "Dispatch Hold"]
    valid = [h["region"] for h in hubs if h["status"] == "Route Validation"]
    if holds: parts.append("Dispatch HOLD for: " + ", ".join(holds) + ".")
    if valid: parts.append("Route validation required for: " + ", ".join(valid) + ".")
    if not holds and not valid: parts.append("No CPF hub currently under a wind signal; continue monitoring.")
    return " ".join(parts)

def auto_contractor(hubs):
    holds = [h["region"] for h in hubs if h["status"] == "Dispatch Hold"]
    valid = [h["region"] for h in hubs if h["status"] == "Route Validation"]
    msg = []
    if holds: msg.append("Trips to " + ", ".join(holds) + " are on HOLD until wind signals are lowered and passability is confirmed.")
    if valid: msg.append("Validate route passability and receiving-site readiness before releasing trips to " + ", ".join(valid) + ".")
    msg.append("Report driver location and any road closures to Logistics Control immediately.")
    return " ".join(msg)


# --------------------------------------------------------------------------- #
# Clear / advisory state (no active cyclone)
# --------------------------------------------------------------------------- #
def _flatten_regions(affected):
    """Distinct region names across the day-by-day outlook (for quick chips)."""
    if not affected:
        return []
    seen, out = set(), []
    for d in affected.get("days", []):
        for part in re.split(r",|\band\b", d.get("areas", "")):
            r = part.strip(" .;·")
            if r and r.lower() not in seen and len(r) < 60:
                seen.add(r.lower()); out.append(r)
    return out[:24]

def parse_affected_areas(text):
    """From a TC/LPA bulletin, extract the day-by-day wind/monsoon outlook, e.g.
    'Today: Ilocos Region, CAR, Cagayan Valley, and Central Luzon'."""
    m = re.search(r"over the following areas.*?:(.*?)(?:HAZARDS AFFECTING COASTAL|24-Hour|Up to\s*\d|Mariners|$)",
                  text, re.I | re.S)
    block = m.group(1) if m else text
    day_re = re.compile(
        r"\b(Today|Tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b"
        r"\s*(\([^)]*\))?\s*:\s*(.+?)"
        r"(?=\b(?:Today|Tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b\s*(?:\([^)]*\))?\s*:|$)",
        re.I | re.S)
    out = []
    for mm in day_re.finditer(block):
        when = (mm.group(1) + (" " + mm.group(2) if mm.group(2) else "")).strip()
        areas = re.sub(r"\s+", " ", mm.group(3)).strip(" .;·")
        if areas and len(areas) < 300:
            out.append({"when": when, "areas": areas})
    hazard = ""
    mh = re.search(r"(strong to gale[- ]force gusts|gale[- ]force gusts|strong winds)", text, re.I)
    if not mh:
        mh = re.search(r"(heavy rainfall)", text, re.I)
    if mh: hazard = mh.group(1)[0].upper() + mh.group(1)[1:]
    return {"hazard": hazard, "days": out[:6]}

def _html_tables(raw):
    tables = []
    for tb in re.findall(r"<table[^>]*>(.*?)</table>", raw, re.I | re.S):
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.I | re.S):
            cells = [re.sub(r"\s+", " ", strip_tags(c)).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.I | re.S)]
            if any(cells): rows.append(cells)
        if rows: tables.append(rows)
    return tables

def parse_daily_conditions(raw):
    """From the Daily Weather Forecast page, extract the 'Forecast Weather
    Conditions' table -> [{place, condition, cause, impact}]."""
    for rows in _html_tables(raw):
        hdr = " ".join(rows[0]).lower()
        if "place" in hdr and ("weather" in hdr or "condition" in hdr):
            out = []
            for r in rows[1:]:
                if len(r) >= 4 and r[0]:
                    out.append({"place": r[0], "condition": r[1], "cause": r[2], "impact": r[3]})
            if out: return out
    return []


def parse_tc_information(text):
    """From the Daily Forecast 'TC Information' block, capture a tropical cyclone
    OUTSIDE (or entering) PAR. PAGASA notes these even when nothing is inside PAR."""
    m = re.search(r"TC Information(.*?)(Forecast Weather|Forecast Wind|Temperature and|$)", text, re.I | re.S)
    block = m.group(1) if m else ""
    if not block or re.search(r"no tropical cyclone", block, re.I):
        return {"present": False}
    cat = ""
    for c in ["Super Typhoon", "Severe Tropical Storm", "Tropical Storm", "Tropical Depression", "Typhoon"]:
        if re.search(c, block, re.I): cat = c; break
    hd = re.search(r"(Tropical Cyclone\s+(?:Outside|Inside)\s+PAR[^\n.]*?Today)", block, re.I)
    if not cat:
        return {"present": False}
    out = {"present": True, "headline": (hd.group(1).strip() if hd else ""), "category": cat}
    mm = re.search(r"LOCATION:\s*(.*?)\(\s*([\d.]+)\s*°?\s*N\s*,\s*([\d.]+)\s*°?\s*E", block, re.I | re.S)
    if mm:
        out["location"] = re.sub(r"\s+", " ", mm.group(1)).strip(" ,")
        try: out["lat"] = float(mm.group(2)); out["lon"] = float(mm.group(3))
        except ValueError: pass
    mw = re.search(r"MAXIMUM SUSTAINED WINDS:\s*([\d]+)\s*KM/?H", block, re.I)
    if mw: out["winds_kph"] = mw.group(1)
    mg = re.search(r"GUSTINESS:\s*(?:UP TO\s*)?([\d]+)\s*KM/?H", block, re.I)
    if mg: out["gustiness_kph"] = mg.group(1)
    mv = re.search(r"MOVEMENT:\s*([A-Za-z][A-Za-z ]+?)(?:\s*(?:LOCATION|MAXIMUM|GUSTINESS|$))", block, re.I)
    if mv: out["movement"] = re.sub(r"\s+", " ", mv.group(1)).strip().title()
    return out


def parse_daily(text):
    """Parse PAGASA's daily weather forecast page for synopsis + advisory signals."""
    d = {"synopsis":"","issued":"","advisory":False,"rain_level":"","thunderstorm":False,"monsoon":False}
    m = re.search(r"Synopsis\b[\s:·|>-]*(.*?)(Forecast Weather|Forecast Wind|TC Information|Tropical Cyclone"
                  r"|Temperature and|Extremes for the 24|Satellite Image|Surface Map|Predicted|We always find|$)",
                  text, re.I|re.S)
    if m:
        d["synopsis"] = re.sub(r"\s+"," ", m.group(1)).strip(" ·|-:>")[:320]
    m = re.search(r"Issued at[:\s]*([0-9:]+\s*[AP]M,?\s*\d{1,2}\s+\w+\s+\d{4})", text, re.I)
    if m: d["issued"] = m.group(1)
    # Advisory signals come from the FULL forecast text (synopsis + conditions),
    # not just the short synopsis line, so rain/thunderstorm flags stay accurate.
    s = text.lower()
    if any(k in s for k in ["southwest monsoon","habagat","northeast monsoon","amihan"]): d["monsoon"]=True
    if "thunderstorm" in s: d["thunderstorm"]=True
    if any(k in s for k in ["scattered rain","occasional rain","monsoon rain","rains and thunderstorm","rainshower","cloudy with rain"]):
        d["rain_level"]="Moderate"
    if "heavy rain" in s: d["rain_level"]="Heavy"
    d["advisory"] = bool(d["monsoon"] or d["thunderstorm"] or d["rain_level"] or
                         any(k in s for k in ["itcz","intertropical","low pressure","lpa","trough",
                                              "easterlies","tail-end","shear line","cold front"]))
    return d


def assemble_clear(daily, source_url):
    """Daily / advisory state (no active cyclone). Uses PAGASA's daily synopsis
    so the dashboard is useful for planning even with no storm."""
    stamp = now_iso()
    daily = daily or {}
    synopsis = daily.get("synopsis","")
    advisory = daily.get("advisory", False)
    rain_level = daily.get("rain_level","")
    tstorm = daily.get("thunderstorm", False)
    mode = "advisory" if advisory else "clear"

    # Official daily issued time, e.g. "4:00 PM, 14 July 2026"
    issued = stamp
    if daily.get("issued"):
        m = re.match(r"(\d{1,2}:\d{2}\s*[AaPp][Mm])\s*,?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", daily["issued"])
        if m:
            iso = issued_to_iso(m.group(1), m.group(2))
            if iso:
                issued = iso

    exec_summary = (("Weather advisory in effect. " if advisory else "No active tropical cyclone. ")
        + (synopsis + " " if synopsis else "")
        + ("Plan deliveries with normal caution; validate road conditions in rain-prone corridors before dispatch."
           if advisory else
           "Deliveries may proceed under normal monitoring; verify local road/weather conditions before dispatch."))

    return {
        "meta": {"source":"PAGASA (auto-parsed)",
                 "bulletin_title": "PAGASA Daily Weather Forecast" if advisory else "No active tropical cyclone",
                 "issued_at":issued,"valid_until":"","next_update":"","generated_at":stamp,
                 "prepared_by":"Automated (fetch_pagasa.py) — verify against official PAGASA daily forecast",
                 "bulletin_url":source_url},
        "situation": {"mode":mode,"has_active_tc":False,"storm_name_local":"",
                      "storm_name_intl":"","category":"","severity":"","headline_override":""},
        "cyclone": {}, "tcws": [],
        "rainfall": {"outlook": (synopsis if rain_level else ""), "warning_level": rain_level,
                     "habagat_affected": (["Southwest Monsoon areas"] if daily.get("monsoon") else []), "areas": []},
        "thunderstorm": {"active": tstorm, "advisory": (synopsis if tstorm else ""), "areas": []},
        "gale_warning": {"active":False,"seaboards":[],"areas":[]},
        "marine": {"hazards":"","affected_waters":[],"risk_level":""},
        "forecast": {"synopsis": synopsis or "No active tropical cyclone inside PAR. Monitor PAGASA daily forecast.",
                     "regions": [c["place"] for c in daily.get("conditions", []) if c.get("place")],
                     "wind_outlook": [], "wind_hazard": "",
                     "conditions": daily.get("conditions", [])},
        "tc_outside_par": daily.get("tc_information") or {"present": False},
        "cpf": {"operational_status":"","dispatch_action":"",
                "executive_summary": exec_summary,
                "priority_routes":[],"risk_matrix":[],"contractor_advisory":"",
                "affected_deliveries_note":"","hubs":[{"name":h["name"],"region":h["region"],"type":h["type"],
                    "lat":h["lat"],"lon":h["lon"],"status":"Normal"} for h in HUBS],
                "change_log":[{"time":stamp,
                    "entry":f"Auto-check at {stamp}: no active tropical cyclone. Daily forecast ingested "
                            f"({'advisory' if advisory else 'fair weather'}). Verify against official PAGASA daily forecast."}]},
    }


def merge_overlay(data):
    """Merge an optional cpf_overlay.json so you can keep custom routes / advisory
    text that survives auto-updates. Any key present in the overlay's 'cpf'
    object overrides the auto-generated one."""
    if os.path.exists(OVERLAY):
        try:
            ov = json.load(open(OVERLAY, encoding="utf-8"))
            for k, v in (ov.get("cpf") or {}).items():
                if v not in (None, "", [], {}):
                    data["cpf"][k] = v
        except Exception as e:
            print(f"[warn] overlay ignored: {e}", file=sys.stderr)
    return data


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    bulletin_raw, bulletin_src = None, None
    for url in BULLETIN_URLS:
        try:
            bulletin_raw = fetch(url); bulletin_src = url
            print(f"[ok] fetched bulletin page: {url}")
            break
        except Exception as e:
            print(f"[warn] bulletin fetch failed ({url}): {e}", file=sys.stderr)

    if bulletin_raw is None:
        # Could not reach PAGASA at all -> FAIL SAFE, keep last known JSON.
        print("[fail-safe] Could not reach PAGASA. Keeping existing JSON untouched.", file=sys.stderr)
        return 0

    facts = parse_bulletin(bulletin_raw)

    if facts and facts.get("signals") is not None:
        print(f"[ok] active cyclone: {facts['category']} {facts.get('name')} "
              f"({len(facts.get('signals',[]))} signal levels)")
        data = assemble(facts, bulletin_src)
    else:
        # No active cyclone -> parse the daily forecast so calm days are still useful.
        daily = {}
        for url in FORECAST_URLS:
            try:
                raw_daily = fetch(url)
                daily = parse_daily(strip_tags(raw_daily))
                daily["conditions"] = parse_daily_conditions(raw_daily)
                daily["tc_information"] = parse_tc_information(strip_tags(raw_daily))
                if daily.get("synopsis"): break
            except Exception:
                continue
        print(f"[ok] no active cyclone; daily forecast ({'advisory' if daily.get('advisory') else 'fair'}).")
        data = assemble_clear(daily, bulletin_src)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[done] wrote {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
