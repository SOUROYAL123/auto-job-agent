"""Job DIGEST tool. Searches job boards and emails YOU a list of new, filtered jobs.
It never emails employers, never applies, never guesses HR addresses. You review and apply yourself."""
import os, re, sqlite3, smtplib, hashlib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "souravrchowdhury2020@gmail.com").strip()
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD", "").replace(" ", "").strip()
DB_FILE = "ghost_memory.db"

ROLES = ["cloud support engineer", "AWS support associate", "cloud operations engineer",
         "technical support engineer cloud", "implementation engineer AWS", "junior devops engineer"]
LOCATIONS = ["Kolkata, West Bengal, India", "India"]   # "India" results are filtered to remote below
HOURS_OLD = 72
MAX_MIN_YEARS = 2          # skip jobs whose minimum required experience is above this
STRETCH_YEARS = 3          # shown separately as "stretch"

BAD_TITLE = re.compile(r"\b(senior|sr\.?|lead|principal|staff|architect|manager|director|head|vp)\b", re.I)
# Companies already applied to (skip) and possible duplicates (flag). Edit freely.
APPLIED = ["sprinto", "npst", "xploreteq"]
POSSIBLE_DUP = ["algosec", "niksun"]

def min_years(text: str):
    """Smallest 'N years' figure found, or None if no requirement stated."""
    vals = []
    for m in re.finditer(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|to|–)?\s*(\d{1,2})?\s*(?:\+)?\s*(?:years|yrs)", text or "", re.I):
        vals.append(int(m.group(1)))
    return min(vals) if vals else None

def classify(job: dict):
    """Return ('apply'|'stretch'|'skip', reason)."""
    title, company = job["title"] or "", (job["company"] or "").lower()
    if any(a in company for a in APPLIED): return "skip", "already applied"
    if BAD_TITLE.search(title): return "skip", "senior/lead title"
    desc = job["description"] or ""
    loc = (job["location"] or "").lower()
    if "kolkata" not in loc and "remote" not in loc and "remote" not in desc.lower()[:2000]:
        return "skip", "not Kolkata/remote"
    y = min_years(desc + " " + title)
    if y is not None and y > STRETCH_YEARS: return "skip", f"needs {y}+ yrs"
    if y is not None and y > MAX_MIN_YEARS: return "stretch", f"needs {y} yrs"
    return "apply", "no/low experience requirement" if y is None else f"needs {y} yrs"

def init_db():
    with sqlite3.connect(DB_FILE) as c:
        c.execute("CREATE TABLE IF NOT EXISTS seen (h TEXT PRIMARY KEY, first_seen TEXT)")

def is_new(job: dict) -> bool:
    h = hashlib.sha256(f"{job['company']}|{job['title']}|{job['url']}".lower().encode()).hexdigest()
    with sqlite3.connect(DB_FILE) as c:
        if c.execute("SELECT 1 FROM seen WHERE h=?", (h,)).fetchone(): return False
        c.execute("INSERT INTO seen VALUES (?,?)", (h, datetime.now(timezone.utc).isoformat()))
        return True

def scrape() -> list:
    from jobspy import scrape_jobs
    out, urls = [], set()
    for role in ROLES:
        for loc in LOCATIONS:
            try:
                df = scrape_jobs(site_name=["indeed", "naukri", "linkedin"], search_term=role, location=loc,
                                 results_wanted=10, hours_old=HOURS_OLD, country_indeed="india",
                                 linkedin_fetch_description=True)
            except Exception as e:
                print(f"[scrape notice] {role} / {loc}: {e}"); continue
            for _, r in df.iterrows():
                url = r.get("job_url_direct") or r.get("job_url")
                if not url or url in urls: continue
                urls.add(url)
                out.append({"title": str(r.get("title") or ""), "company": str(r.get("company") or ""),
                            "location": str(r.get("location") or ""), "url": str(url),
                            "description": str(r.get("description") or ""), "source": str(r.get("site") or ""),
                            "posted": str(r.get("date_posted") or "unverified")})
    return out

def send_digest(apply_, stretch, flagged, total):
    def rows(items):
        return "".join(f"<tr><td>{j['company']}</td><td><a href='{j['url']}'>{j['title']}</a></td>"
                       f"<td>{j['location']}</td><td>{j['posted']}</td><td>{j['source']}</td><td>{why}</td></tr>"
                       for j, why in items) or "<tr><td colspan=6>None today</td></tr>"
    head = "<tr><th>Company</th><th>Role</th><th>Location</th><th>Posted</th><th>Source</th><th>Experience</th></tr>"
    html = (f"<html><body style='font-family:Arial'><h3>Job digest: {len(apply_)} to review, {len(stretch)} stretch</h3>"
            f"<p>{total} scraped, only NEW matches shown. Dates and openings are unverified: open each link and "
            f"confirm the Apply button before applying. Nothing was sent to any employer.</p>"
            f"<h4>Review first</h4><table border=1 cellpadding=5>{head}{rows(apply_)}</table>"
            f"<h4>Stretch (3 yrs)</h4><table border=1 cellpadding=5>{head}{rows(stretch)}</table>"
            f"<h4>Possible duplicates (check before applying)</h4><table border=1 cellpadding=5>{head}{rows(flagged)}</table>"
            f"</body></html>")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Job digest: {len(apply_)} to review, {len(stretch)} stretch"
    msg["From"] = msg["To"] = EMAIL_SENDER
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
        s.sendmail(EMAIL_SENDER, EMAIL_SENDER, msg.as_string())

def main():
    init_db()
    jobs = scrape()
    apply_, stretch, flagged = [], [], []
    for j in jobs:
        verdict, why = classify(j)
        if verdict == "skip" or not is_new(j): continue
        if any(d in j["company"].lower() for d in POSSIBLE_DUP): flagged.append((j, why)); continue
        (apply_ if verdict == "apply" else stretch).append((j, why))
    print(f"scraped={len(jobs)} apply={len(apply_)} stretch={len(stretch)} flagged={len(flagged)}")
    if jobs: send_digest(apply_, stretch, flagged, len(jobs))

if __name__ == "__main__":
    main()
