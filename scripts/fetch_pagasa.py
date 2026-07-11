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

import json, re, sys, os, datetime, html, urllib.request, urllib.error

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
    {"name":"Gerona Feedmill","region":"Central Luzon (Tarlac)","type":"Feedmill","lat":15.61,"lon":120.60,"keys":["tarlac"]},
    {"name":"Isabela Hub","region":"Cagayan Valley (Isabela)","type":"Distribution","lat":16.93,"lon":121.77,"keys":["isabela"]},
    {"name":"Samal Hub","region":"Central Luzon (Bataan)","type":"Distribution","lat":14.77,"lon":120.54,"keys":["bataan"]},
    {"name":"Manila Distribution","region":"NCR","type":"Distribution","lat":14.60,"lon":120.98,"keys":["metro manila","ncr","manila","rizal"]},
    {"name":"Batangas Port Hub","region":"CALABARZON","type":"Port / RORO","lat":13.76,"lon":121.06,"keys":["batangas"]},
    {"name":"Cebu Hub","region":"Central Visayas","type":"Distribution","lat":10.32,"lon":123.90,"keys":["cebu"]},
    {"name":"CDO Hub","region":"Northern Mindanao (Cagayan de Oro)","type":"Distribution","lat":8.48,"lon":124.65,"keys":["misamis oriental","cagayan de oro"]},
    {"name":"Davao Hub","region":"Davao Region","type":"Distribution","lat":7.19,"lon":125.46,"keys":["davao del sur","davao city","davao occidental","davao de oro","davao"]},
    {"name":"GenSan Hub","region":"SOCCSKSARGEN (General Santos)","type":"Distribution","lat":6.11,"lon":125.17,"keys":["south cotabato","general santos","sarangani","cotabato"]},
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


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def now_iso():
    return datetime.datetime.now(PH_TZ).replace(microsecond=0).isoformat()

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
# Bulletin parsing (active tropical cyclone)
# --------------------------------------------------------------------------- #
def parse_bulletin(text):
    """Return a dict of PAGASA facts, or None if no active cyclone is detected."""
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

    # Wind signals: split the text at each "Signal No. X" / "TCWS No. X" marker.
    facts["signals"] = []
    markers = list(re.finditer(r"(?:Wind Signal|TCWS|Tropical Cyclone Wind Signal)\s*(?:No\.?|Number|#)?\s*([1-5])", text, re.I))
    # sections that mark the END of the wind-signal area lists
    STOP = re.compile(r"(heavy rainfall|rainfall outlook|rainfall warning|track and intensity|"
                      r"forecast position|hoisting|impacts of the wind|gale warning|"
                      r"southwest monsoon|the wind signals warn)", re.I)
    for i, mk in enumerate(markers):
        lvl = int(mk.group(1))
        end = markers[i+1].start() if i+1 < len(markers) else len(text)
        seg = text[mk.end(): min(end, mk.end()+900)]
        stop = STOP.search(seg)
        if stop: seg = seg[:stop.start()]
        areas = find_provinces(seg)
        if areas:
            facts["signals"].append({"signal": lvl, "areas": areas})
    # keep the highest entry per signal level
    best = {}
    for s in facts["signals"]:
        if s["signal"] not in best or len(s["areas"]) > len(best[s["signal"]]["areas"]):
            best[s["signal"]] = s
    facts["signals"] = [best[k] for k in sorted(best.keys(), reverse=True)]

    # Heavy rainfall outlook (best-effort)
    m = re.search(r"(heavy rainfall.{0,600}?)(?:\n\n|The wind signals|Hoisting|Track|$)", text, re.I|re.S)
    if m: facts["rain_text"] = re.sub(r"\s+", " ", m.group(1)).strip()[:600]

    return facts


# --------------------------------------------------------------------------- #
# CPF derivation (deterministic — maps PAGASA facts to hub/route/risk output)
# --------------------------------------------------------------------------- #
def affected_level(hub, signals, rain_provs):
    """Return a hub status string based on PAGASA affected areas."""
    hub_keys = [k.lower() for k in hub["keys"]]
    max_sig = 0
    for s in signals:
        for a in s["areas"]:
            al = a.lower()
            if any(k in al or al in k for k in hub_keys):
                max_sig = max(max_sig, s["signal"])
    in_rain = any(any(k in p.lower() for k in hub_keys) for p in rain_provs)
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

    mode = "typhoon" if "typhoon" in facts["category"].lower() else \
           "tropical_depression" if "depression" in facts["category"].lower() else "typhoon"

    data = {
        "meta": {
            "source": "PAGASA (auto-parsed)",
            "bulletin_title": (f"Tropical Cyclone Bulletin No. {facts['bulletin_no']}"
                               if facts.get("bulletin_no") else "PAGASA Tropical Cyclone Bulletin"),
            "issued_at": stamp, "valid_until": "", "next_update": "",
            "prepared_by": "Automated (fetch_pagasa.py) — verify against official PAGASA bulletin",
            "bulletin_url": source_url,
        },
        "situation": {
            "mode": mode, "has_active_tc": True,
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
            "wind_extent_km": "", "forecast_track": [],
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
        "forecast": {"synopsis": "", "regions": []},
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
def assemble_clear(synopsis, source_url):
    stamp = now_iso()
    return {
        "meta": {"source":"PAGASA (auto-parsed)","bulletin_title":"No active tropical cyclone",
                 "issued_at":stamp,"valid_until":"","next_update":"",
                 "prepared_by":"Automated (fetch_pagasa.py) — verify against official PAGASA forecast",
                 "bulletin_url":source_url},
        "situation": {"mode":"clear","has_active_tc":False,"storm_name_local":"",
                      "storm_name_intl":"","category":"","severity":"","headline_override":""},
        "cyclone": {}, "tcws": [],
        "rainfall": {"outlook":"","warning_level":"","habagat_affected":[],"areas":[]},
        "thunderstorm": {"active":False,"advisory":"","areas":[]},
        "gale_warning": {"active":False,"seaboards":[],"areas":[]},
        "marine": {"hazards":"","affected_waters":[],"risk_level":""},
        "forecast": {"synopsis":synopsis or "No active tropical cyclone inside PAR. Monitor PAGASA daily forecast.","regions":[]},
        "cpf": {"operational_status":"","dispatch_action":"",
                "executive_summary":"No active tropical cyclone. Deliveries may proceed under normal monitoring; verify local road/weather conditions before dispatch.",
                "priority_routes":[],"risk_matrix":[],"contractor_advisory":"",
                "affected_deliveries_note":"","hubs":[{"name":h["name"],"region":h["region"],"type":h["type"],
                    "lat":h["lat"],"lon":h["lon"],"status":"Normal"} for h in HUBS],
                "change_log":[{"time":stamp,"entry":f"Auto-check at {stamp}: no active tropical cyclone found on PAGASA. Showing daily-weather mode."}]},
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
    bulletin_text, bulletin_src = None, None
    for url in BULLETIN_URLS:
        try:
            bulletin_text = strip_tags(fetch(url)); bulletin_src = url
            print(f"[ok] fetched bulletin page: {url}")
            break
        except Exception as e:
            print(f"[warn] bulletin fetch failed ({url}): {e}", file=sys.stderr)

    if bulletin_text is None:
        # Could not reach PAGASA at all -> FAIL SAFE, keep last known JSON.
        print("[fail-safe] Could not reach PAGASA. Keeping existing JSON untouched.", file=sys.stderr)
        return 0

    facts = parse_bulletin(bulletin_text)

    if facts and facts.get("signals") is not None:
        print(f"[ok] active cyclone: {facts['category']} {facts.get('name')} "
              f"({len(facts.get('signals',[]))} signal levels)")
        data = assemble(facts, bulletin_src)
    else:
        # No active cyclone -> try the daily forecast for a synopsis, write clear state.
        synopsis = ""
        for url in FORECAST_URLS:
            try:
                ftxt = strip_tags(fetch(url))
                m = re.search(r"(synopsis|forecast weather condition).{0,600}", ftxt, re.I|re.S)
                if m: synopsis = re.sub(r"\s+", " ", m.group(0)).strip()[:500]
                break
            except Exception:
                continue
        print("[ok] no active cyclone; writing daily-weather (clear) state.")
        data = assemble_clear(synopsis, bulletin_src)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[done] wrote {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
