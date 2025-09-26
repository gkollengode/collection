#!/usr/bin/env python3
import os, sys, csv, json, base64, pathlib, urllib.request, urllib.parse, ssl, time

OUT_DIR = pathlib.Path("out")
CSV_PATH = OUT_DIR / "sonar_loc.csv"
MD_PATH  = OUT_DIR / "Sonar_LOC_Report.md"

HOST   = os.environ.get("SONAR_HOST_URL", "").rstrip("/")
TOKEN  = os.environ.get("SONAR_TOKEN", "")
ORG    = os.environ.get("SONAR_ORGANIZATION", "")       # SonarCloud only
Q      = os.environ.get("SONAR_Q", "")
TAGS   = os.environ.get("SONAR_TAGS", "")
BRANCH = os.environ.get("SONAR_BRANCH", "")             # override branch; else main branch is detected
PS     = int(os.environ.get("SONAR_PAGE_SIZE", "500"))
INSECURE = os.environ.get("SONAR_INSECURE", "false").lower() in ("1","true","yes")

if not HOST or not TOKEN:
    print("ERROR: SONAR_HOST_URL and SONAR_TOKEN are required.", file=sys.stderr)
    sys.exit(1)

# HTTP setup
auth_header = "Basic " + base64.b64encode(f"{TOKEN}:".encode()).decode()
ctx = ssl._create_unverified_context() if INSECURE else None
def api_get(path, params=None, retries=3, sleep=1.0):
    params = params or {}
    url = f"{HOST}/api{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": auth_header,
        "User-Agent": "sonar-loc-report/1.0",
        "Accept": "application/json",
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if attempt == retries - 1:
                print(f"WARN: GET {url} failed: {e}", file=sys.stderr)
                return None
            time.sleep(sleep * (attempt + 1))
    return None

def list_projects():
    page = 1
    while True:
        params = {"qualifiers": "TRK", "ps": PS, "p": page}
        if ORG:  params["organization"] = ORG
        if Q:    params["q"] = Q
        if TAGS: params["tags"] = TAGS
        data = api_get("/projects/search", params)
        if not data or "components" not in data: break
        comps = data.get("components", [])
        if not comps: break
        for c in comps:
            yield {"key": c.get("key"), "name": c.get("name")}
        page += 1

def get_main_branch(project_key):
    d = api_get("/project_branches/list", {"project": project_key})
    if not d: return "main"
    for b in d.get("branches", []) or []:
        if b.get("isMain"):
            return b.get("name") or "main"
    return "main"

def get_ncloc(project_key, branch_name):
    params = {"component": project_key, "metricKeys": "ncloc"}
    if BRANCH:
        params["branch"] = BRANCH
    elif branch_name:
        params["branch"] = branch_name
    d = api_get("/measures/component", params)
    if not d: return 0
    try:
        measures = d["component"]["measures"]
        for m in measures:
            if m.get("metric") == "ncloc":
                return int(float(m.get("value", "0")))
    except Exception:
        pass
    return 0

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["project_key", "project_name", "branch", "ncloc"])
        total_loc = 0
        total_projects = 0
        rows_for_md = []
        for proj in list_projects():
            key = proj["key"]
            name = proj["name"]
            branch = get_main_branch(key)
            n = get_ncloc(key, branch)
            w.writerow([key, name, branch, n])
            rows_for_md.append((key, name, branch, n))
            total_loc += n
            total_projects += 1
        w.writerow(["TOTAL_PROJECTS", "", "", total_projects])
        w.writerow(["TOTAL_NCLOC", "", "", total_loc])

    # Markdown summary
    md = []
    md.append("# Sonar Projects LOC Report\n")
    md.append("| Project Key | Project Name | Branch | ncloc |")
    md.append("|---|---|---|---:|")
    for key, name, branch, n in rows_for_md:
        md.append(f"| `{key}` | {name} | {branch} | {n:,} |")
    md.append(f"| **Totals** |  |  | **{total_loc:,}** |")
    MD_PATH.write_text("\n".join(md))

    print(f"Wrote {CSV_PATH} and {MD_PATH}")
    print(f"Projects: {total_projects}  Total ncloc: {total_loc:,}")

if __name__ == "__main__":
    main()
