#!/usr/bin/env python3
import os, sys, csv, json, base64, pathlib, urllib.request, urllib.parse, ssl, time, math, re
from datetime import datetime, timezone

OUT_DIR = pathlib.Path("out")
CSV_PATH = OUT_DIR / "sonar_loc.csv"
MD_TABLE = OUT_DIR / "Sonar_LOC_Report.md"
MD_CHART = OUT_DIR / "sonar_loc_chart.md"

HOST   = os.environ.get("SONAR_HOST_URL", "").rstrip("/")
TOKEN  = os.environ.get("SONAR_TOKEN", "")
ORG    = os.environ.get("SONAR_ORGANIZATION", "")
Q      = os.environ.get("SONAR_Q", "")
TAGS   = os.environ.get("SONAR_TAGS", "")
BRANCH = os.environ.get("SONAR_BRANCH", "")
PS     = int(os.environ.get("SONAR_PAGE_SIZE", "500"))
INSECURE = os.environ.get("SONAR_INSECURE", "false").lower() in ("1","true","yes")
TOP_N  = int(os.environ.get("TOP_N", "25"))
MERMAID_MODE = os.environ.get("MERMAID_MODE", "xy").lower()

if not HOST or not TOKEN:
    print("ERROR: SONAR_HOST_URL and SONAR_TOKEN are required.", file=sys.stderr)
    sys.exit(1)

auth_header = "Basic " + base64.b64encode(f"{TOKEN}:".encode()).decode()
ctx = ssl._create_unverified_context() if INSECURE else None

def api_get(path, params=None, retries=3, sleep=1.0):
    params = params or {}
    url = f"{HOST}/api{path}"
    if params: url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": auth_header,
        "User-Agent": "sonar-loc-report/1.2",
        "Accept": "application/json",
    })
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if i == retries - 1:
                print(f"WARN: GET {url} failed: {e}", file=sys.stderr)
                return None
            time.sleep(sleep * (i + 1))

def list_projects():
    page = 1
    while True:
        params = {"qualifiers": "TRK", "ps": PS, "p": page}
        if ORG:  params["organization"] = ORG
        if Q:    params["q"] = Q
        if TAGS: params["tags"] = TAGS
        data = api_get("/projects/search", params)
        comps = (data or {}).get("components", [])
        if not comps: break
        for c in comps:
            yield {"key": c.get("key"), "name": c.get("name")}
        page += 1

def get_main_branch(project_key):
    d = api_get("/project_branches/list", {"project": project_key})
    if not d: return "main"
    for b in d.get("branches", []) or []:
        if b.get("isMain"): return b.get("name") or "main"
    return "main"

def get_ncloc(project_key, branch_name):
    params = {"component": project_key, "metricKeys": "ncloc"}
    params["branch"] = BRANCH or branch_name
    d = api_get("/measures/component", params)
    if not d: return 0
    try:
        for m in d["component"]["measures"]:
            if m.get("metric") == "ncloc":
                return int(float(m.get("value", "0")))
    except Exception:
        pass
    return 0

def parse_sonar_datetime(s):
    # Accept '2023-06-01T12:34:56+0000', '2023-06-01T12:34:56Z', with or without .sss
    s2 = re.sub(r"\.(\d+)", "", s)
    fmts = ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"]
    for fmt in fmts:
        try:
            if fmt.endswith("Z") and s2.endswith("Z"):
                return datetime.strptime(s2, fmt).replace(tzinfo=timezone.utc)
            return datetime.strptime(s2, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            continue
    raise ValueError(f"Unrecognized Sonar datetime: {s}")

def get_last_analysis(project_key, branch_name):
    # Iterate pages to be robust, though Sonar returns newest first
    newest_dt = None
    newest_raw = None
    page = 1
    while True:
        params = {"project": project_key, "p": page, "ps": 100}
        b = BRANCH or branch_name
        if b:
            params["branch"] = b
        d = api_get("/project_analyses/search", params)
        analyses = (d or {}).get("analyses", [])
        if not analyses: break
        for a in analyses:
            raw = a.get("date") or a.get("createdAt")
            if not raw:
                continue
            try:
                adt = parse_sonar_datetime(raw)
            except Exception:
                continue
            if newest_dt is None or adt > newest_dt:
                newest_dt, newest_raw = adt, raw
        paging = (d or {}).get("paging", {})
        total = int(paging.get("total", len(analyses)))
        size = int(paging.get("pageSize", 100))
        if page * size >= total:
            break
        page += 1
    if newest_dt:
        return newest_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ""

def round_up(n):
    if n <= 0: return 0
    return int(math.ceil(n * 1.1))

def sanitize_label(s, maxlen=24):
    s = s.replace("|"," ").replace("\n"," ").strip()
    return (s[:maxlen-1] + "…") if len(s) > maxlen else s

def write_mermaid_chart(rows):
    # rows: (key, name, branch, ncloc, last_utc)
    rows_sorted = sorted(rows, key=lambda r: r[3], reverse=True)
    top = rows_sorted[:TOP_N]
    others = rows_sorted[TOP_N:]
    other_sum = sum(r[3] for r in others)
    if other_sum > 0:
        top.append(("other", "Other", "", other_sum, ""))

    labels = [sanitize_label(r[1] or r[0]) for r in top]
    values = [r[3] for r in top]
    ymax = round_up(max(values) if values else 0)

    out = []
    out.append("# Sonar LOC by Project")
    out.append("")
    if MERMAID_MODE == "pie":
        out.append("```mermaid")
        out.append("pie showData")
        out.append('    title LOC distribution by project')
        for lab, val in zip(labels, values):
            out.append(f'    "{lab}" : {val}')
        out.append("```")
    else:
        out.append("```mermaid")
        out.append("xychart-beta")
        out.append('    title "LOC by Project"')
        xlabels = ", ".join(f'"{lab}"' for lab in labels)
        out.append(f"    x-axis [{xlabels}]")
        out.append('    y-axis "LOC" 0 --> ' + str(ymax))
        out.append("    bar [" + ", ".join(str(v) for v in values) + "]")
        out.append("```")

    out.append("")
    out.append(f"_Projects shown: {min(len(rows_sorted), TOP_N)} of {len(rows_sorted)}" + (" plus Other" if other_sum > 0 else "") + "_")
    out.append("")
    out.append("## Last analysis for shown projects")
    out.append("")
    out.append("| Project | Branch | Last analysis (UTC) | LOC |")
    out.append("|---|---|---:|---:|")
    for r in top:
        if r[0] == "other":
            continue
        out.append(f"| {r[1] or r[0]} | {r[2]} | {r[4] or 'n/a'} | {r[3]} |")
    MD_CHART.write_text("\n".join(out), encoding="utf-8")

def write_md_table(rows):
    # Full table for all projects
    out = []
    out.append("# Sonar Projects LOC Report")
    out.append("")
    out.append("| Project key | Project name | Branch | Last analysis (UTC) | ncloc |")
    out.append("|---|---|---|---|---:|")
    for key, name, branch, ncloc, last_utc in sorted(rows, key=lambda r: (r[1] or r[0]).lower()):
        out.append(f"| {key} | {name} | {branch} | {last_utc or 'n/a'} | {ncloc} |")
    MD_TABLE.write_text("\n".join(out), encoding="utf-8")

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    total_loc = 0
    total_projects = 0

    with CSV_PATH.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["project_key", "project_name", "branch", "ncloc", "last_analysis_utc"])
        for proj in list_projects():
            key = proj["key"]
            name = proj["name"]
            branch = get_main_branch(key)
            n = get_ncloc(key, branch)
            last_utc = get_last_analysis(key, branch)
            rows.append((key, name, branch, n, last_utc))
            w.writerow([key, name, branch, n, last_utc])
            total_loc += n
            total_projects += 1
        w.writerow(["TOTAL_PROJECTS", "", "", total_projects, ""])
        w.writerow(["TOTAL_NCLOC", "", "", total_loc, ""])

    write_md_table(rows)
    write_mermaid_chart(rows)

    print(f"Wrote {CSV_PATH} and {MD_CHART} and {MD_TABLE}")
    print(f"Projects: {total_projects}  Total ncloc: {total_loc:,}")

if __name__ == "__main__":
    main()
