#!/usr/bin/env python3
"""
Generates a Markdown snippet with SonarQube license info:
- Edition
- Licensed LOC (limit)
- LOC used (if monitoring metrics available)
- Expiry date
- Time to renew from today
Optional Mermaid pie chart of Used vs Free.

Env:
  SONAR_HOST_URL   required
  SONAR_TOKEN      required  (user with Administer System for /api/editions/show_license)
  SONAR_SYS_PASS   optional  (sonar.web.systemPasscode to read /api/monitoring/metrics)
  WARN_DAYS        optional  default 45
  CRIT_DAYS        optional  default 14
  MERMAID          optional  "true" to include pie chart when data available

Outputs:
  out/sonar_license_section.md
"""
import os, sys, json, base64, re, urllib.request, urllib.parse
import datetime, pathlib

HOST   = os.environ.get("SONAR_HOST_URL", "").rstrip("/")
TOKEN  = os.environ.get("SONAR_TOKEN", "")
PASS   = os.environ.get("SONAR_SYS_PASS", "")
WARN   = int(os.environ.get("WARN_DAYS", "45"))
CRIT   = int(os.environ.get("CRIT_DAYS", "14"))
MERMAID = os.environ.get("MERMAID", "true").lower() in ("1","true","yes")

OUT_DIR = pathlib.Path("out")
OUT_FILE = OUT_DIR / "sonar_license_section.md"

def _auth_header():
    return {"Authorization": "Basic " + base64.b64encode(f"{TOKEN}:".encode()).decode(),
            "Accept": "application/json", "User-Agent": "sonar-license-section/1.0"}

def api_json(path, params=None, headers=None):
    url = f"{HOST}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    h = _auth_header()
    if headers: h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))

def parse_iso_or_epoch(value):
    if not value:
        return None
    s = str(value)
    # try ISO
    try:
        # handle trailing Z
        s_iso = s.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(s_iso).date()
    except Exception:
        pass
    # try epoch millis
    try:
        ms = int(s)
        return datetime.datetime.utcfromtimestamp(ms/1000).date()
    except Exception:
        return None

def fetch_license_info():
    # /api/editions/show_license requires licensed editions
    data = api_json("/api/editions/show_license")
    edition = data.get("editionKey") or data.get("edition") or data.get("type") or "unknown"
    expires = parse_iso_or_epoch(data.get("expirationDate") or data.get("expiresAt") or data.get("validUntil"))
    lic_limit = data.get("licensedLines") or data.get("ncloc") or data.get("loc")
    try:
        lic_limit = int(lic_limit) if lic_limit is not None else None
    except Exception:
        lic_limit = None
    return edition, expires, lic_limit

def fetch_usage_metrics():
    if not PASS:
        return None, None
    req = urllib.request.Request(f"{HOST}/api/monitoring/metrics",
                                 headers={"X-Sonar-Passcode": PASS, "User-Agent": "sonar-license-section/1.0"})
    txt = urllib.request.urlopen(req).read().decode("utf-8", "replace")
    def metric(name):
        m = re.search(rf"^{re.escape(name)}\s+([0-9.]+)", txt, flags=re.M)
        return int(float(m.group(1))) if m else None
    limit = metric("sonarqube_license_number_of_lines_analyzed_limit")
    used  = metric("sonarqube_license_number_of_lines_analyzed_total")
    return used, limit

def fmt(n):
    return f"{n:,}" if isinstance(n, (int, float)) else "unknown"

def main():
    if not HOST or not TOKEN:
        print("ERROR: SONAR_HOST_URL and SONAR_TOKEN are required", file=sys.stderr)
        sys.exit(1)

    # license info
    try:
        edition, expires, lic_limit = fetch_license_info()
    except Exception as e:
        print(f"ERROR: failed to read license: {e}", file=sys.stderr)
        sys.exit(2)

    # usage info
    used, prom_limit = None, None
    if PASS:
        try:
            used, prom_limit = fetch_usage_metrics()
        except Exception as e:
            print(f"WARN: failed to read monitoring metrics: {e}", file=sys.stderr)

    # prefer license limit from editions API, else monitoring metric
    limit = lic_limit if isinstance(lic_limit, int) else prom_limit

    today = datetime.date.today()
    days_left = (expires - today).days if isinstance(expires, datetime.date) else None
    status = "unknown"; emoji = "ℹ️"
    if days_left is not None:
        if days_left < 0:
            status, emoji = "expired", "🛑"
        elif days_left <= CRIT:
            status, emoji = "critical", "🟥"
        elif days_left <= WARN:
            status, emoji = "warning", "🟧"
        else:
            status, emoji = "ok", "🟩"

    lines = []
    lines.append("### SonarQube License")
    lines.append("")
    lines.append(f"- Edition: **{edition}**")
    lines.append(f"- Licensed LOC: **{fmt(limit)}**")
    lines.append(f"- LOC used: **{fmt(used)}**")
    if expires:
        lines.append(f"- Expires on: **{expires.isoformat()}**")
    if days_left is not None:
        lines.append(f"- Time to renew: **{days_left} days** {emoji} _{status}_")
    lines.append("")

    # optional Mermaid pie chart
    if MERMAID and isinstance(limit, int) and isinstance(used, int) and limit > 0:
        free = max(limit - used, 0)
        lines += [
            "```mermaid",
            "pie showData",
            '    title Licensed LOC usage',
            f'    "Used" : {used}',
            f'    "Free" : {free}',
            "```",
            ""
        ]

    lines.append(f"_Last updated: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_FILE}")

if __name__ == "__main__":
    main()
