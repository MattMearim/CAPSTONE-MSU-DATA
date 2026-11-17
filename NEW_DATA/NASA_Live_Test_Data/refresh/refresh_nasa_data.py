#!/usr/bin/env python3
"""Re-pull the four NASA datasets with fresh (live) values, in the same CSV layout.

Usage (Mac Terminal, from this folder):
    python3 refresh_nasa_data.py              # writes into ../wiki_input/datasets/
    python3 refresh_nasa_data.py --out mydir  # writes somewhere else

Python 3.8+ standard library only - no pip installs.
After a refresh, the numeric answers in ../answer_key/ no longer apply to the
live datasets (the NTRS documents are not touched).
"""
import argparse, csv, datetime as dt, json, os, sys, urllib.parse, urllib.request

LAT, LON = 42.7245, -84.4746          # MSU / FRIB, East Lansing, Michigan
POWER = "https://power.larc.nasa.gov/api/temporal/{res}/point"
JPL_FIREBALL = "https://ssd-api.jpl.nasa.gov/fireball.api"
JPL_CAD = "https://ssd-api.jpl.nasa.gov/cad.api"


def get_json(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "frib-llm-wiki-test/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def js_num(v):
    """Format numbers the way the original files do (98.0 -> 98, 17.47 -> 17.47)."""
    if v is None or v == "":
        return ""
    f = float(v)
    return str(int(f)) if f == int(f) else repr(f)


POWER_PARAMS = {"hourly": "T2M,T2MDEW,RH2M,PS,WS10M,WD10M,PRECTOTCORR",
                "daily": "T2M,T2M_MAX,T2M_MIN,RH2M,PS,WS10M,PRECTOTCORR,ALLSKY_SFC_SW_DWN"}


def power_url(res, ymd):
    u = (f"https://power.larc.nasa.gov/api/temporal/{res}/point?parameters={POWER_PARAMS[res]}&community=RE"
         f"&longitude={LON}&latitude={LAT}&start={ymd}&end={ymd}&format=CSV")
    return u + ("&time-standard=UTC" if res == "hourly" else "")


def write_csv(path, header, rows, url=None):
    """Write rows; if url is given, append a source_url column computed from each row."""
    if url:
        header = header + ["source_url"]
        rows = [r + [url(r)] for r in rows]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    print(f"  wrote {len(rows):4d} rows -> {path}")


def power(res, params, start, end, header, key_fmt):
    data = get_json(POWER.format(res=res), {
        "parameters": ",".join(params), "community": "RE",
        "latitude": LAT, "longitude": LON,
        "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
        "format": "JSON", **({"time-standard": "UTC"} if res == "hourly" else {}),
    })["properties"]["parameter"]
    keys = sorted(data[params[0]].keys())
    return [[key_fmt(k)] + [js_num(data[p].get(k, -999)) for p in params] for k in keys]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wiki_input", "datasets"))
    ap.add_argument("--hourly-days", type=int, default=28)
    ap.add_argument("--daily-days", type=int, default=393)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    end = (now - dt.timedelta(days=2)).date()   # POWER lags ~1-2 days
    print(f"Refreshing NASA data at {now:%Y-%m-%d %H:%M} UTC")

    # 1. POWER hourly (UTC)
    rows = power("hourly", ["T2M", "T2MDEW", "RH2M", "PS", "WS10M", "WD10M", "PRECTOTCORR"],
                 end - dt.timedelta(days=a.hourly_days - 1), end, None,
                 lambda k: f"{k[:4]}-{k[4:6]}-{k[6:8]}T{k[8:10]}:00:00Z")
    write_csv(os.path.join(a.out, "power_frib_hourly.csv"),
              ["timestamp_utc", "air_temperature [C]", "dew_point [C]", "relative_humidity [%]", "surface_pressure [kPa]",
               "wind_speed_10m [m/s]", "wind_direction_10m_deg", "precipitation_mm_per_h"], rows,
              url=lambda r: power_url("hourly", r[0][:10].replace("-", "")))

    # 2. POWER daily (local solar time)
    rows = power("daily", ["T2M", "T2M_MAX", "T2M_MIN", "RH2M", "PS", "WS10M", "PRECTOTCORR", "ALLSKY_SFC_SW_DWN"],
                 end - dt.timedelta(days=a.daily_days - 1), end, None,
                 lambda k: f"{k[:4]}-{k[4:6]}-{k[6:8]}T00:00:00")
    write_csv(os.path.join(a.out, "power_frib_daily.csv"),
              ["timestamp_lst", "air_temperature_mean [C]", "air_temperature_max [C]", "air_temperature_min [C]",
               "relative_humidity [%]", "surface_pressure [kPa]", "wind_speed_10m [m/s]", "precipitation_mm_per_day",
               "solar_irradiance_kWh_per_m2_per_day"], rows,
              url=lambda r: power_url("daily", r[0][:10].replace("-", "")))

    # 3. JPL fireballs since 2024-01-01
    fb = get_json(JPL_FIREBALL, {"date-min": "2024-01-01"})
    i = {f: n for n, f in enumerate(fb["fields"])}
    rows = []
    for r in fb.get("data", []):
        lat = r[i["lat"]]; lon = r[i["lon"]]
        if lat and r[i["lat-dir"]] == "S": lat = "-" + lat
        if lon and r[i["lon-dir"]] == "W": lon = "-" + lon
        rows.append([r[i["date"]].replace(" ", "T") + "Z", lat or "", lon or "", r[i["alt"]] or "",
                     r[i["vel"]] or "", r[i["energy"]] or "", r[i["impact-e"]] or ""])
    rows.sort(key=lambda x: x[0])
    write_csv(os.path.join(a.out, "jpl_fireballs.csv"),
              ["timestamp_utc", "latitude_deg", "longitude_deg", "altitude_km", "velocity_km_per_s",
               "radiated_energy_1e10J", "impact_energy_kt"], rows,
              url=lambda r: f"https://ssd-api.jpl.nasa.gov/fireball.api?date-min={r[0][:10]}&date-max="
                            f"{(dt.date.fromisoformat(r[0][:10]) + dt.timedelta(days=1)).isoformat()}")

    # 4. JPL close approaches, current month-ish window (prev 2 months .. end of year)
    y = now.year; m0 = now.month - 1 or 12; y0 = y if now.month > 1 else y - 1
    cad = get_json(JPL_CAD, {"date-min": f"{y0}-{m0:02d}-01", "date-max": f"{y}-12-31",
                             "dist-max": "0.02", "diameter": "true", "fullname": "false"})
    i = {f: n for n, f in enumerate(cad["fields"])}
    rows = []
    for r in cad.get("data", []):
        t = dt.datetime.strptime(r[i["cd"]], "%Y-%b-%d %H:%M")
        rows.append([t.strftime("%Y-%m-%dT%H:%M:%S"), r[i["des"]],
                     f"{float(r[i['dist']]):.6f}", f"{float(r[i['dist_min']]):.6f}", f"{float(r[i['dist_max']]):.6f}",
                     f"{float(r[i['v_rel']]):.3f}", r[i["h"]] or "", (r[i["diameter"]] or "") if "diameter" in i else "",
                     r[i["t_sigma_f"]], "past" if t.replace(tzinfo=dt.timezone.utc) < now else "predicted"])
    write_csv(os.path.join(a.out, "jpl_close_approaches.csv"),
              ["time_tdb", "object", "distance_au", "distance_min_au", "distance_max_au",
               "relative_velocity_km_per_s", "absolute_magnitude_mag", "diameter_km", "time_uncertainty", "status"], rows,
              url=lambda r: "https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr=" + r[1].replace(" ", "%20"))
    print("Done. Note: answer_key/ numbers refer to the original snapshot, not this refresh.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # keep the message friendly for non-programmers
        sys.exit(f"Refresh failed: {e}\n(Check your internet connection; NASA services are sometimes down for a few hours.)")
