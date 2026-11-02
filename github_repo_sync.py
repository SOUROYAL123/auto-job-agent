import os, re, subprocess, sys
from datetime import datetime, timezone
try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import requests

STAMP_FILE = "github_sync_last_run.txt"
COMPANIES_FILE = "companies.txt"
ENV_FILE = ".env"
UA = {"User-Agent": "personal-job-agent/1.0", "Accept": "application/vnd.github+json"}

REPO_FEEDS = (
    ("remoteintech/remote-jobs", "https://raw.githubusercontent.com/remoteintech/remote-jobs/main/README.md", 35),
    ("lukasz-madon/awesome-remote-job", "https://raw.githubusercontent.com/lukasz-madon/awesome-remote-job/master/README.md", 25),
    ("poteto/hiring-without-whiteboards", "https://raw.githubusercontent.com/poteto/hiring-without-whiteboards/main/README.md", 35),
    ("yanirs/established-remote", "https://raw.githubusercontent.com/yanirs/established-remote/master/README.md", 25),
    ("dreamworkhq/Remote-Tech-Jobs", "https://raw.githubusercontent.com/dreamworkhq/Remote-Tech-Jobs/main/README.md", 25),
    ("SimplifyJobs/New-Grad-Positions", "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md", 25),
    ("tramcar/awesome-job-boards", "https://raw.githubusercontent.com/tramcar/awesome-job-boards/master/README.md", 20),
    ("jobs-jobr-pro/Cloud-Engineering-Jobs", "https://raw.githubusercontent.com/jobs-jobr-pro/Cloud-Engineering-Jobs/main/README.md", 25),
    ("jobs-jobr-pro/DevOps-Jobs", "https://raw.githubusercontent.com/jobs-jobr-pro/DevOps-Jobs/main/README.md", 25),
)

def gh_json(url):
    try:
        r = requests.get(url, headers=UA, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None

def gh_text(url):
    try:
        r = requests.get(url, headers=UA, timeout=20)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""

def sync_jobspy():
    data = gh_json("https://api.github.com/repos/speedyapply/JobSpy/releases/latest")
    tag = (data or {}).get("tag_name") or "latest"
    print(f"[repo-sync] speedyapply/JobSpy release: {tag} -> verifying python-jobspy...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-U", "python-jobspy", "-q"], check=False)

def extract_markdown_companies(url, label, limit=30):
    md = gh_text(url)
    if not md: return []
    names = []
    noise = ("awesome", "github", "board", "guide", "list", "apply", "link", "website", "remote", "here", "status", "badge", "simplify", "🔒", "🛂")
    for line in md.splitlines():
        for m in re.finditer(r"\[([A-Za-z0-9 .&\-\+]{2,28})\]\(https?://", line):
            n = m.group(1).strip()
            if not any(w in n.lower() for w in noise):
                names.append(n)
    print(f"[repo-sync] {label}: extracted {len(names[:limit])} companies")
    return names[:limit]

def extract_wfh_india():
    meta = gh_json("https://api.github.com/repos/abhagsain/WFH-Companies-India")
    if not meta or not meta.get("pushed_at"): return []
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(meta["pushed_at"].replace("Z", "+00:00"))).days
    if age > 730:
        print(f"[repo-sync] abhagsain/WFH-Companies-India: {age // 365}y old (> 2 yrs); skipping.")
        return []
    br = meta.get("default_branch", "master")
    return extract_markdown_companies(f"https://raw.githubusercontent.com/abhagsain/WFH-Companies-India/{br}/README.md", "abhagsain/WFH-Companies-India", 25)

def enable_remote_feeds():
    if not os.path.exists(ENV_FILE): return
    with open(ENV_FILE, encoding="utf-8", newline="") as f: raw = f.read()
    eol = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()
    target = "REMOTE_FEEDS=remoteok,himalayas,arbeitnow,hackernews"
    if not any(re.match(r"^\s*REMOTE_FEEDS\s*=", l) for l in lines):
        lines.append(target)
        with open(ENV_FILE, "w", encoding="utf-8", newline="") as f: f.write(eol.join(lines) + eol)

def update_companies(new_names):
    existing, lines = set(), []
    if os.path.exists(COMPANIES_FILE):
        with open(COMPANIES_FILE, encoding="utf-8") as f:
            for ln in f:
                s = ln.strip(); lines.append(s)
                if s and not s.startswith("#"): existing.add(s.lower())
    added = 0
    for n in new_names:
        if n.lower() not in existing:
            existing.add(n.lower()); lines.append(n); added += 1
    with open(COMPANIES_FILE, "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
    print(f"[repo-sync] Added {added} new companies to {COMPANIES_FILE} ({len(existing)} total)")

def main():
    if "--force" not in sys.argv and os.path.exists(STAMP_FILE):
        try:
            last = datetime.fromisoformat(open(STAMP_FILE).read().strip()).date()
            if (datetime.now(timezone.utc).date() - last).days < 7:
                print("[repo-sync] Already synced within 7 days; skipping.")
                return 0
        except Exception: pass
    print("=== Syncing World-Class GitHub Job Repositories ===")
    sync_jobspy()
    enable_remote_feeds()
    c = []
    for label, url, lim in REPO_FEEDS:
        c += extract_markdown_companies(url, label, lim)
    c += extract_wfh_india()
    c += [
        "CloudThat", "Cloud4C", "Minfy", "Searce", "MontyCloud", "Hasura",
        "BrowserStack", "Postman", "Razorpay", "Chargebee", "Freshworks",
        "Druva", "Icertis", "Innovaccer", "CleverTap", "MoEngage",
    ]
    if c: update_companies(c)
    with open(STAMP_FILE, "w", encoding="utf-8") as f: f.write(datetime.now(timezone.utc).date().isoformat())
    return 0

if __name__ == "__main__": raise SystemExit(main())
