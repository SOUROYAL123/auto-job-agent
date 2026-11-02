"""
remote_feeds.py - worldwide REMOTE jobs from public JSON feeds that allow programmatic reading
(RemoteOK, Himalayas, plus optional Arbeitnow and Hacker News "Who is hiring"). No logins, no blocks to get around, one polite request per page.

Attribution: each job keeps its source link and a "Job via ..." line, as those boards ask.
Only jobs that look relevant, are not senior, are recent, and are open to candidates in India
(worldwide / anywhere / APAC / Asia / India, or no restriction listed) reach the scorer.

.env options (all optional):
  REMOTE_FEEDS=remoteok,himalayas     (set to blank to turn this stage off)
                                      add ",hackernews" and/or ",arbeitnow" to enable those (off by default)
  REMOTE_MAX_PER_SOURCE=40            (max new jobs kept per source per run)
  REMOTE_MAX_AGE_DAYS=14
"""
import html
import os
import re
import time
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "personal-job-agent/1.0"}
FEEDS = [f.strip().lower() for f in os.getenv("REMOTE_FEEDS", "amazon,keka,remoteok,himalayas").split(",") if f.strip()]
MAX_PER_SOURCE = int(os.getenv("REMOTE_MAX_PER_SOURCE", "40"))
MAX_AGE_DAYS = int(os.getenv("REMOTE_MAX_AGE_DAYS", "14"))
HIMALAYAS_PAGES = 3

RELEVANT = re.compile(
    r"cloud|aws|devops|sre\b|site reliability|infrastructure|platform|noc\b|operations|support|"
    r"implementation|solutions? engineer|sysadmin|system admin|linux|technical|customer success|"
    r"onboarding|integration", re.I)
IRRELEVANT = re.compile(r"sales|marketing|account executive|designer|copywriter|recruiter|attorney|accountant", re.I)
SENIOR = re.compile(r"\b(senior|sr\.?|lead|principal|staff|head|director|vp|manager|chief)\b", re.I)
OK_LOCATION = ("worldwide", "anywhere", "global", "any location", "apac", "asia", "india", "international")


def _get_json(url, params=None):
    import requests
    r = requests.get(url, headers=UA, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def parse_date(v):
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)) or str(v).replace(".", "", 1).isdigit():
            n = float(v)
            return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, tz=timezone.utc)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def strip_html(text, limit=6000):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def eligible_location(text) -> bool:
    t = (text or "").lower().strip()
    return (not t) or t in ("remote", "fully remote") or any(k in t for k in OK_LOCATION)


def fetch_remoteok():
    data = _get_json("https://remoteok.com/api")
    out = []
    for d in data:
        if not isinstance(d, dict) or not d.get("position"):
            continue  # first element is a legal notice
        url = d.get("url") or ("https://remoteok.com/remote-jobs/" + str(d.get("slug") or d.get("id") or ""))
        out.append(dict(title=d["position"], company=d.get("company", ""), location=d.get("location", ""),
                        url=url, apply_url=d.get("apply_url") or url, description=d.get("description", ""),
                        date=parse_date(d.get("epoch") or d.get("date")), source="remoteok",
                        attribution="Job via RemoteOK (https://remoteok.com)", tags=" ".join(d.get("tags") or [])))
    return out


def fetch_himalayas():
    out = []
    for page in range(HIMALAYAS_PAGES):
        data = _get_json("https://himalayas.app/jobs/api", params={"limit": 20, "offset": page * 20})
        jobs = data.get("jobs") or []
        for j in jobs:
            url = j.get("applicationLink") or j.get("guid") or j.get("url") or ""
            if not (j.get("title") and url):
                continue
            restr = j.get("locationRestrictions") or []
            loc = ", ".join(restr) if restr else "Worldwide (no restriction listed)"
            out.append(dict(title=j["title"], company=j.get("companyName", ""), location=loc, url=url,
                            apply_url=url, description=j.get("description") or j.get("excerpt", ""),
                            date=parse_date(j.get("pubDate")), source="himalayas",
                            attribution="Job via Himalayas (https://himalayas.app)",
                            tags=" ".join(j.get("categories") or [])))
        if len(jobs) < 20:
            break
        time.sleep(1)
    return out


def fetch_arbeitnow():
    """Arbeitnow board API. Mostly Europe-based, so only listings flagged remote are kept and
    the location is passed through; most will be filtered out unless they say worldwide/anywhere."""
    out = []
    for page in range(1, 3):
        data = _get_json("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
        rows = data.get("data") or []
        for d in rows:
            if not d.get("remote") or not d.get("title"):
                continue
            url = d.get("url") or ""
            if not url:
                continue
            loc = (d.get("location") or "").strip()
            out.append(dict(title=d["title"], company=d.get("company_name", ""),
                            location=("Remote" if not loc else f"Remote ({loc})"),
                            url=url, apply_url=url, description=d.get("description", ""),
                            date=parse_date(d.get("created_at")), source="arbeitnow",
                            attribution="Job via Arbeitnow (https://www.arbeitnow.com)",
                            tags=" ".join((d.get("tags") or []) + (d.get("job_types") or []))))
        if not rows:
            break
        time.sleep(1)
    return out


HN_OK = re.compile(r"worldwide|anywhere|global|apac|asia|india|international|any location", re.I)


def parse_hn_comment(text: str):
    """'Company | Role | Location | REMOTE | ...' first line -> (company, title, header) or None."""
    plain = html.unescape(re.sub(r"<[^>]+>", "\n", text or ""))
    lines = [l.strip() for l in plain.split("\n") if l.strip()]
    if not lines or "|" not in lines[0]:
        return None
    parts = [p.strip() for p in lines[0].split("|") if p.strip()]
    if len(parts) < 2:
        return None
    company = parts[0][:80]
    title = next((p for p in parts[1:] if RELEVANT.search(p)), parts[1])[:150]
    return company, title, " | ".join(parts), plain


def fetch_hackernews():
    """Latest monthly 'Ask HN: Who is hiring?' thread via the public Algolia HN API."""
    found = _get_json("https://hn.algolia.com/api/v1/search_by_date",
                      params={"tags": "story,author_whoishiring", "hitsPerPage": 5})
    story = next((h for h in found.get("hits", [])
                  if "who is hiring" in (h.get("title") or "").lower()), None)
    if not story:
        return []
    sid = story["objectID"]
    data = _get_json("https://hn.algolia.com/api/v1/search",
                     params={"tags": f"comment,story_{sid}", "hitsPerPage": 1000})
    out = []
    for h in data.get("hits", []):
        if str(h.get("parent_id")) != str(sid):
            continue  # top-level postings only, not replies
        parsed = parse_hn_comment(h.get("comment_text"))
        if not parsed:
            continue
        company, title, header, plain = parsed
        if "remote" not in header.lower() or not HN_OK.search(header):
            continue  # must be remote AND open to India/worldwide
        url = f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        out.append(dict(title=title, company=company, location="Worldwide (remote)", url=url,
                        apply_url=url, description=plain, date=parse_date(h.get("created_at_i")),
                        source="hackernews",
                        attribution="Job via Hacker News 'Who is hiring' (https://news.ycombinator.com)",
                        tags=header))
    return out



def fetch_remotive():
    """Remotive public API (DevOps/Sysadmin and Customer Support categories)."""
    out = []
    for cat in ("devops", "support"):
        try:
            data = _get_json("https://remotive.com/api/remote-jobs", params={"category": cat, "limit": 50})
        except Exception:
            continue
        for j in (data.get("jobs") or []):
            url = j.get("url") or ""
            if not (j.get("title") and url):
                continue
            loc = j.get("candidate_required_location") or "Worldwide"
            out.append(dict(
                title=j["title"],
                company=j.get("company_name", ""),
                location=loc,
                url=url,
                apply_url=url,
                description=j.get("description", ""),
                date=parse_date(j.get("publication_date")),
                source="remotive",
                attribution="Job via Remotive (https://remotive.com)",
                tags=" ".join(j.get("tags") or []),
            ))
        time.sleep(1)
    return out


def fetch_jobicy():
    """Jobicy public API v2 for remote cloud, sysadmin, and technical support jobs."""
    data = _get_json("https://jobicy.com/api/v2/remote-jobs", params={"count": 50})
    out = []
    for j in (data.get("jobs") or []):
        url = j.get("url") or ""
        if not (j.get("jobTitle") and url):
            continue
        loc = j.get("jobGeo") or "Worldwide"
        out.append(dict(
            title=html.unescape(j["jobTitle"]),
            company=html.unescape(j.get("companyName", "")),
            location=loc,
            url=url,
            apply_url=url,
            description=j.get("jobDescription") or j.get("jobExcerpt", ""),
            date=parse_date(j.get("pubDate")),
            source="jobicy",
            attribution="Job via Jobicy (https://jobicy.com)",
            tags=" ".join((j.get("jobIndustry") or []) + [j.get("jobType", "")]),
        ))
    return out

def fetch_amazon():
    """Public amazon.jobs JSON search endpoint for AWS Cloud Support & Associate roles in India."""
    out, seen = [], set()
    for q in ("Cloud Support Associate", "Cloud Support Engineer", "AWS Support"):
        data = _get_json(
            "https://www.amazon.jobs/en/search.json",
            params={"base_query": q, "loc_query": "India", "result_limit": 25, "sort": "recent"},
        )
        for j in (data or {}).get("jobs") or []:
            jid = j.get("id_icims") or j.get("id") or ""
            path = j.get("job_path") or (f"/en/jobs/{jid}" if jid else "")
            if not path or path in seen:
                continue
            seen.add(path)
            url = f"https://www.amazon.jobs{path}"
            loc = j.get("normalized_location") or j.get("location") or "India"
            desc = " ".join(filter(None, [j.get("description_short", ""), j.get("basic_qualifications", ""), j.get("preferred_qualifications", "")]))
            out.append(dict(
                title=j.get("title", "AWS Cloud Role"),
                company=j.get("company_name", "Amazon Web Services (AWS)"),
                location=loc,
                url=url,
                apply_url=url,
                description=desc,
                date=parse_date(j.get("posted_date")),
                source="amazon.jobs",
                attribution="Job via amazon.jobs (https://www.amazon.jobs)",
                tags="aws cloud support india",
            ))
    return out


def fetch_keka_and_recruitee():
    """Fetches openings from Indian Cloud MSPs on Keka (e.g. CloudThat) and Recruitee public APIs."""
    import os, re
    out = []
    # 1. Recruitee public JSON APIs (configurable via ATS_RECRUITEE in .env)
    rec_slugs = [s.strip() for s in os.getenv("ATS_RECRUITEE", "").split(",") if s.strip()]
    for slug in rec_slugs:
        data = _get_json(f"https://{slug}.recruitee.com/api/offers/")
        for o in (data or {}).get("offers") or []:
            title = (o.get("title") or "").strip()
            loc = o.get("location") or o.get("city") or "Remote"
            if o.get("remote"):
                loc = f"{loc} (Remote)".strip()
            url = o.get("careers_url") or f"https://{slug}.recruitee.com/o/{o.get('slug', '')}"
            out.append(dict(
                title=title,
                company=o.get("company_name") or slug.title(),
                location=loc,
                url=url,
                apply_url=o.get("careers_apply_url") or url,
                description=clean_html(o.get("description") or "") + " " + clean_html(o.get("requirements") or ""),
                date=parse_date(o.get("published_at") or o.get("created_at")),
                source=f"recruitee:{slug}",
                attribution=f"Direct ATS via Recruitee ({slug})",
                tags="cloud support devops",
            ))
    # 2. Keka public career boards (configurable via ATS_KEKA in .env, defaults to cloudthat)
    keka_slugs = [s.strip() for s in os.getenv("ATS_KEKA", "cloudthat").split(",") if s.strip()]
    for slug in keka_slugs:
        data = _get_json(f"https://{slug}.keka.com/careers/api/embedjobs/default")
        if not isinstance(data, list):
            data = (data or {}).get("data") if isinstance(data, dict) else []
        for j in (data or []):
            if not isinstance(j, dict):
                continue
            title = (j.get("title") or j.get("jobTitle") or "").strip()
            if not title:
                continue
            locs = j.get("jobLocations") or []
            loc_str = ", ".join(l.get("name", "") for l in locs if isinstance(l, dict)) or j.get("location") or "India"
            jid = j.get("id") or j.get("jobId") or ""
            url = f"https://{slug}.keka.com/careers/jobdetails/{jid}" if jid else f"https://{slug}.keka.com/careers"
            out.append(dict(
                title=title,
                company=slug.title(),
                location=loc_str,
                url=url,
                apply_url=url,
                description=clean_html(j.get("description") or j.get("jobDescription") or title),
                date=parse_date(j.get("publishedOn") or j.get("createdOn")),
                source=f"keka:{slug}",
                attribution=f"Direct ATS via Keka ({slug}.keka.com)",
                tags="aws cloud india",
            ))
    return out


FETCHERS = {"keka": fetch_keka_and_recruitee, "amazon": fetch_amazon, "remoteok": fetch_remoteok, "himalayas": fetch_himalayas, "arbeitnow": fetch_arbeitnow, "hackernews": fetch_hackernews, "remotive": fetch_remotive, "jobicy": fetch_jobicy}


def keep(job, senior_re=None) -> bool:
    title = job["title"]
    if not RELEVANT.search(title + " " + job.get("tags", "")) or IRRELEVANT.search(title):
        return False
    if (senior_re or SENIOR).search(title):
        return False
    if not eligible_location(job["location"]):
        return False
    d = job.get("date")
    if d:
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        if d < datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS):
            return False
    return True


def run(db_path, get_conn, insert_job, job_hash, senior_re=None, fetchers=None) -> int:
    if not FEEDS:
        print("[remote] REMOTE_FEEDS is blank; skipping.")
        return 0
    fetchers = fetchers or FETCHERS
    conn = get_conn(db_path)
    cur = conn.cursor()
    added_total = 0
    for name in FEEDS:
        fetch = fetchers.get(name)
        if not fetch:
            print(f"[remote] unknown feed '{name}'; skipping.")
            continue
        try:
            jobs = fetch()
        except Exception as exc:
            print(f"[remote] WARNING {name}: {str(exc)[:120]}")
            continue
        kept = [j for j in jobs if keep(j, senior_re)]
        added = 0
        for j in kept:
            if added >= MAX_PER_SOURCE:
                break
            ok = insert_job(
                cur, job_hash=job_hash(j["url"]), title=j["title"][:200], company=j["company"], location=j["location"],
                experience="", job_type="remote", is_remote=1,
                date_posted=j["date"].date().isoformat() if j["date"] else "",
                description=j["attribution"] + "\n" + strip_html(j["description"]),
                job_url=j["url"], job_url_direct=j["apply_url"], company_url="",
                source_channel="Remote Feed", source_site=j["source"])
            added += 1 if ok else 0
        conn.commit()
        print(f"[remote] {name}: {len(jobs)} fetched, {len(kept)} relevant and open to India, {added} new")
        added_total += added
    conn.close()
    print(f"[remote] {added_total} new job(s)")
    return added_total
