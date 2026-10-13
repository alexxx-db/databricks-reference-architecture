#!/usr/bin/env python3
"""Completeness + live-URL gate for every clickable entity in the board.

Dumps the app's in-memory ARCH / LINKS / INDUSTRIES with tools/pw_dump.js (served
over HTTP, every industry loaded), then:
  * every Databricks product (a band tile whose LINKS entry has a `doc` path)
    must also carry `site` and `blog` (Bronze/Silver/Gold exempt from `site`,
    they are medallion concepts); the four late-added products must exist.
  * every Source tile, generic and per industry, must carry what / users /
    dataOut(+vol); data-format tiles (standards, not systems) are exempt.
  * every industry use case must carry at least one customer story.
With --urls it HEAD-checks every outbound URL (YouTube via oEmbed) in parallel
and fails on any dead link. Exit non-zero on any failure so it gates a push.
"""
import argparse, concurrent.futures as cf, json, os, re, shutil, subprocess, tempfile, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Official Databricks YouTube channel author_name as reported by oEmbed. A video
# in LINKS[name].videos is only legitimate if oEmbed says it lives here AND its
# title carries the feature name (there is no human review step, so the gate is
# the review). Anything else is a third-party upload and must be rejected.
OFFICIAL_YT = {"Databricks"}

# Medallion tiers are architecture concepts, not products with a landing page.
SITE_EXEMPT = {"Bronze", "Silver", "Gold"}
# Platform tiles that MUST carry a full LINKS entry (doc/site/blog). These are
# real product tiles in ARCH.bands; "Omnigent" is intentionally NOT here because
# it is an Apache-2.0 OSS project with a GitHub home and no Databricks doc path.
REQUIRED_PRODUCTS = ["Streaming", "Knowledge Assistant", "Document Parsing", "Text Classification"]
DOC_HOSTS = {"aws": "https://docs.databricks.com/aws/en/",
             "azure": "https://learn.microsoft.com/azure/databricks/",
             "gcp": "https://docs.databricks.com/gcp/en/"}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
RETIRED_NAME = "Data Intelligence Platform"
ARCHIVED_REPO = "interactive-databricks-enterprise-architecture"
ARCHIVED_REPO_OK = {"CLAUDE.md"}
STORY_EXEMPT_REASONS = {"outcome map", "no public story"}
STORY_EXEMPT = {
    "advertising": {"Agency Reconciliation": "no public story", "Brand Lift Measurement": "outcome map"},
    "airlines": {"Passenger 360": "outcome map"},
    "apparel_fashion": {"3D Sample Reduction": "no public story", "Factory Risk Monitoring": "no public story", "Sustainable Sourcing": "no public story", "Wholesale Chargebacks": "no public story"},
    "banking": {"Contact-Center AI": "outcome map", "FP&A & Financial Close": "outcome map", "Perpetual KYC/KYB": "outcome map"},
    "capital_markets_sellside": {"Pricing & Spreads": "outcome map"},
    "clinical_trials": {"Clinical Data Repository": "outcome map", "HEOR Acceleration": "outcome map", "OMOP Standardisation": "outcome map"},
    "consumer_goods": {"Identity Resolution & CDP": "outcome map", "Joint Demand Planning": "outcome map", "New Product Intro": "outcome map", "Shopper Segmentation": "outcome map"},
    "crypto_digital_assets": {"Proof of Reserves": "no public story", "Treasury & Settlement": "no public story"},
    "data_analytics_providers": {"Client Intelligence & Churn": "outcome map"},
    "data_centers": {"Field Ops Assistant": "outcome map", "Financial Analytics": "no public story"},
    "digital_health": {"Contact Center Sentiment": "outcome map", "Digital Patient 360": "outcome map"},
    "ecommerce": {"Agent-to-Agent Transactions": "outcome map", "Conversational Shopping": "outcome map", "Demand Forecasting": "outcome map", "Identity Resolution & CDP": "outcome map", "Product Discovery & Search": "outcome map"},
    "edtech": {"Exam Integrity": "no public story"},
    "education": {"Research Compliance": "no public story", "Space & Scheduling": "no public story"},
    "exchanges": {"Member Credit Monitoring": "outcome map"},
    "gaming": {"Anti-Cheat & Toxicity": "outcome map", "Game Health & Stability": "outcome map", "In-Game Purchase Optimization": "outcome map", "Player Journey Analytics": "outcome map", "UA & Ad Attribution": "outcome map"},
    "genomics_biotech": {"Lab Turnaround Optimisation": "no public story", "Multi-Omics Integration": "outcome map", "Polygenic Risk Scoring": "outcome map"},
    "grocery": {"E-commerce Substitution": "no public story", "Labor Scheduling": "no public story", "Shrink Attribution": "no public story"},
    "health_insurance": {"Auto-Adjudication Rate": "outcome map", "Member Call Sentiment": "outcome map", "Utilization Forecasting": "outcome map"},
    "healthcare": {"Care Gap Closure": "outcome map", "Contact Center Sentiment": "outcome map", "Denial Management": "outcome map", "FHIR Data Pipelines": "outcome map", "OR Utilisation": "outcome map", "Patient Services": "outcome map", "eCQM Quality Measures": "outcome map"},
    "insurance_pandc": {"Contact-Center AI": "outcome map", "Distribution & Producer Analytics": "outcome map", "Subrogation Recovery": "no public story"},
    "legal": {"Conflicts Screening": "no public story", "Docket Monitoring": "no public story", "Legal Research Analytics": "no public story", "Outside Counsel Spend": "no public story", "Time Entry Compliance": "no public story"},
    "life_insurance": {"Contact-Center AI": "outcome map", "Embedded Value": "no public story", "New Business Strain": "no public story", "Statutory & NAIC Reporting": "outcome map"},
    "media_broadcasting": {"Audience Segmentation": "outcome map", "Content & Licensing Monetization": "outcome map", "Content Localization": "outcome map", "Subscription Pricing & Packaging": "outcome map"},
    "medical_devices": {"Device & Consumable Demand Forecasting": "outcome map", "Device Digital Twin & Simulation": "outcome map", "Surgical Video & Image Analytics": "outcome map"},
    "mortgage_lending": {"Lead & Pull-Through": "no public story", "Pipeline Hedging": "no public story"},
    "ngo": {"Grant Compliance": "no public story", "Sanctions Screening": "no public story"},
    "paper_packaging": {"Reel & Order Genealogy": "outcome map", "Reel & Roll Inventory": "outcome map"},
    "payments_fintech": {"Agentic Commerce": "outcome map", "Interchange Optimisation": "no public story", "Payment Routing": "no public story", "Transaction Enrichment": "outcome map"},
    "pharmaceuticals": {"Assay & Screening Analytics": "no public story", "Lead Optimization / QSAR": "outcome map"},
    "professional_services": {"Proposal Analytics": "no public story"},
    "real_estate": {"CAM Reconciliation": "no public story", "Capex Planning": "no public story"},
    "restaurants": {"Franchise Compliance": "no public story", "New Store Analytics": "no public story", "Shrink & Void Control": "no public story"},
    "retail": {"Agentic Commerce": "outcome map", "Household Identity Resolution": "outcome map", "Store Performance & Workforce": "outcome map"},
    "sports_entertainment": {"Broadcast Highlights": "no public story", "Crowd Safety Analytics": "no public story", "Fan Cross-Sell & Upsell": "outcome map", "Merchandise Forecast": "outcome map"},
    "staffing_hr": {"Client Profitability": "no public story", "Overtime Control": "no public story"},
    "telecommunication": {"Care Transcript Analysis": "outcome map", "Field Dispatch Optimization": "outcome map", "Location Data Monetization": "outcome map", "Next Best Offer": "outcome map", "Revenue Assurance & Leakage": "outcome map"},
    "travel_hospitality": {"24/7 AI Concierge": "outcome map", "Conversational Booking": "outcome map", "Disruption Response": "outcome map", "Labour Scheduling": "outcome map", "Next Best Offer": "outcome map", "Predictive Maintenance": "outcome map"},
    "waste_management": {"Compliance & Franchise Reporting": "outcome map", "Customer 360 & Churn": "outcome map", "Disposal & Transfer Logistics": "no public story", "Driver & Workforce Safety": "outcome map", "Dynamic Pricing & Working Capital": "no public story"},
    "water_utilities": {"Field Crew Assistant": "outcome map", "Pressure Management": "no public story"},
    "wealth_management": {"Practice FP&A": "outcome map"},
}


def dump():
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "dump.json")
    try:
        res = subprocess.run(["node", os.path.join(ROOT, "tools", "pw_dump.js"), out],
                             capture_output=True, text=True, timeout=300)
        try:
            return json.load(open(out, encoding="utf-8"))
        except (OSError, ValueError):
            raise SystemExit("dump failed; pw_dump.js stderr tail:\n" + res.stderr[-800:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def retired_refs(root=ROOT):
    listed = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    fails = []
    for rel in filter(None, listed.split("\0")):
        if os.path.abspath(os.path.join(root, rel)) == os.path.abspath(__file__):
            continue
        try:
            text = open(os.path.join(root, rel), encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        if rel == "app/resources/links.json":
            links = json.loads(text)
            for L in links.values():
                for v in (L.get("videos") or []) if isinstance(L, dict) else []:
                    if isinstance(v, dict):
                        v.pop("t", None)
                        v.pop("a", None)
            text = json.dumps(links)
        if RETIRED_NAME in text:
            fails.append(f"retired product name '{RETIRED_NAME}' in {rel}")
        if ARCHIVED_REPO in text and rel not in ARCHIVED_REPO_OK:
            fails.append(f"archived repo or site '{ARCHIVED_REPO}' in {rel}")
    return fails


def collect_urls(d):
    """Every outbound URL a click can reach, tagged with where it came from."""
    urls = {}
    def add(u, where):
        if u and isinstance(u, str) and u.startswith("http"):
            urls.setdefault(u, set()).add(where)
    LINKS = d["LINKS"]
    for name, L in LINKS.items():
        if not isinstance(L, dict):
            continue
        if L.get("doc"):
            for cl, hostp in DOC_HOSTS.items():
                add(hostp + str(L["doc"]).lstrip("/"), f"LINKS[{name}].doc/{cl}")
        if L.get("dbx"):
            add(DOC_HOSTS["aws"] + str(L["dbx"]).lstrip("/"), f"LINKS[{name}].dbx")
        for k in ("site", "blog", "url", "video"):
            if L.get(k):
                add(L[k], f"LINKS[{name}].{k}")
        # `videos` list is verified separately (check_video) for channel + title,
        # not just liveness, so it is intentionally not added to the plain pool.
        for pair in (L.get("also") or []):
            if isinstance(pair, list) and len(pair) == 2:
                add(pair[1], f"LINKS[{name}].also")
        # Product tours and hands-on tutorials shown in the drawer (build_demos.py).
        for dm in (L.get("demos") or []):
            if isinstance(dm, dict) and dm.get("u"):
                add(dm["u"], f"LINKS[{name}].demos/{dm.get('kind', '?')}")
    for iid, o in d["inds"].items():
        for uc in o["uc"]:
            for u in uc["stories"]:
                add(u, f"{iid}:uc:{uc['n']}")
        for u in o["cites"]:
            add(u, f"{iid}:cite")
    return urls


def _norm(s):
    """Lowercase, strip everything but alphanumerics to single spaces, so
    'AI/BI' matches 'AI BI' and 'Unity Catalog' matches 'unity  catalog'."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def check_video(vid, feature, alias=None):
    """oEmbed check for a LINKS videos entry: exists, lives on the official
    Databricks channel, and its title carries the feature name OR a declared
    alias (a renamed / prior product name, e.g. AI Search's 'Vector Search').
    The alias is verified the same way (whole-phrase, official channel), so a
    rename never opens the gate to an unrelated video. Returns (ok, detail):
    detail is the real title on success or the reason on failure."""
    url = "https://www.youtube.com/watch?v=" + vid
    oe = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url, safe="")
    try:
        req = urllib.request.Request(oe, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.status != 200:
                return (False, f"oembed http {r.status}")
            meta = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return (False, f"oembed error {str(e)[:50]}")
    author = (meta.get("author_name") or "").strip()
    title = meta.get("title") or ""
    if author not in OFFICIAL_YT:
        return (False, f"channel '{author}' not official Databricks")
    hay = " " + _norm(title) + " "
    terms = [feature] + ([alias] if alias else [])
    if not any((" " + _norm(t) + " ") in hay for t in terms if _norm(t)):
        want = "' / '".join(terms)
        return (False, f"title lacks feature/alias '{want}': '{title}'")
    return (True, title)


def check_url(u):
    """Return (ok, code). YouTube via oEmbed existence check; others HEAD->GET."""
    try:
        if "youtube.com/watch" in u or "youtu.be/" in u:
            oe = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(u, safe="")
            req = urllib.request.Request(oe, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                return (r.status == 200, r.status)
        for method in ("HEAD", "GET"):
            req = urllib.request.Request(u, method=method, headers={"User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    return (200 <= r.status < 400, r.status)
            except urllib.error.HTTPError as e:
                if e.code in (403, 405, 429) and method == "HEAD":
                    continue  # some hosts block HEAD; retry GET
                return (e.code in (403, 429), e.code)  # 403/429 = bot-blocked, treat as WARN-ok
        return (False, 0)
    except Exception as e:
        return (False, str(e)[:60])


import urllib.parse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", action="store_true", help="live-check every outbound URL")
    ap.add_argument("--dump-file", help="read a pre-dumped ARCH/LINKS JSON (from tools/pw_dump.js) "
                    "instead of launching Chrome; use when the default Chrome profile is locked")
    args = ap.parse_args()
    d = json.load(open(args.dump_file)) if args.dump_file else dump()
    fails = retired_refs()
    print(f"retired names / archived repo references: {len(fails)}")
    if not d.get("LINKS"):
        fails.append("LINKS did not load, so no product, see-also or video check ran")
    if not d.get("inds"):
        fails.append("no industry board loaded, so no industry check ran")
    for iid in d.get("load_failed") or []:
        fails.append(f"industry '{iid}' failed to load")

    # ---- Products ----
    LINKS = d["LINKS"]
    prod = [n for n in d["prodNames"] if isinstance(LINKS.get(n), dict) and LINKS[n].get("doc")]
    for n in prod:
        L = LINKS[n]
        if n not in SITE_EXEMPT and not L.get("site"):
            fails.append(f"product '{n}' missing site (landing)")
        if not L.get("blog"):
            fails.append(f"product '{n}' missing blog")
    for n in REQUIRED_PRODUCTS:
        L = LINKS.get(n)
        if not isinstance(L, dict) or not L.get("doc") or not L.get("site") or not L.get("blog"):
            fails.append(f"required product '{n}' missing LINKS doc/site/blog")
    print(f"products checked: {len(prod)} (doc-bearing) + {len(REQUIRED_PRODUCTS)} required")

    # ---- See-also references must resolve to a real, linkable feature ----
    sa_refs = 0
    for name, L in LINKS.items():
        if not isinstance(L, dict):
            continue
        for ref in (L.get("seealso") or []):
            sa_refs += 1
            tgt = LINKS.get(ref)
            if not isinstance(tgt, dict):
                fails.append(f"seealso '{ref}' (from '{name}') is not a LINKS feature")
            elif not (tgt.get("doc") or tgt.get("dbx") or tgt.get("site") or tgt.get("url")):
                fails.append(f"seealso '{ref}' (from '{name}') has no linkable URL")
            elif ref == name:
                fails.append(f"seealso '{ref}' points at itself")
    print(f"see-also references checked: {sa_refs}")

    # ---- Generic sources ----
    gbad = [r["n"] for r in d["genSrc"] if not r.get("fmt") and not (r["what"] and r["users"] and r["dataOut"] and r["vol"])]
    if gbad:
        fails.append(f"generic sources missing what/users/dataOut+vol: {gbad}")
    print(f"generic sources: {len(d['genSrc'])} tiles, incomplete: {len(gbad)}")

    # ---- Industry sources + use-case stories ----
    src_bad = uc_bad = 0
    for iid, o in d["inds"].items():
        for r in o["src"]:
            if not r.get("fmt") and not (r["what"] and r["users"] and r["dataOut"] and r["vol"]):
                src_bad += 1; fails.append(f"{iid}: source '{r['n']}' incomplete")
        exempt = STORY_EXEMPT.get(iid, {})
        by_name = {uc["n"]: uc for uc in o["uc"]}
        for uc in o["uc"]:
            if not uc["stories"] and uc["n"] not in exempt:
                uc_bad += 1; fails.append(f"{iid}: use case '{uc['n']}' has no story")
        for n, why in exempt.items():
            if why not in STORY_EXEMPT_REASONS:
                fails.append(f"{iid}: story exemption for '{n}' has an unknown reason '{why}'")
            elif n not in by_name:
                fails.append(f"{iid}: story exemption for '{n}' matches no use case")
            elif by_name[n]["stories"]:
                fails.append(f"{iid}: story exemption for '{n}' is stale, it now has a story")
    if d["inds"]:
        for iid in STORY_EXEMPT:
            if iid not in d["inds"]:
                fails.append(f"story exemptions name '{iid}', which is not an industry board")
    n_exempt = sum(len(v) for v in STORY_EXEMPT.values())
    print(f"industry sources incomplete: {src_bad}")
    print(f"industry use cases without a story: {uc_bad} (exempt by list: {n_exempt})")

    # ---- Live URL check ----
    if args.urls:
        urls = collect_urls(d)
        print(f"\nlive-checking {len(urls)} unique URLs ...")
        bad = []
        with cf.ThreadPoolExecutor(max_workers=24) as ex:
            futs = {ex.submit(check_url, u): u for u in urls}
            for fut in cf.as_completed(futs):
                u = futs[fut]; ok, code = fut.result()
                if not ok:
                    bad.append((u, code, sorted(urls[u])[:3]))
        for u, code, where in sorted(bad):
            fails.append(f"DEAD [{code}] {u}  <- {where}")
        print(f"dead URLs: {len(bad)}")

        # ---- Databricks YouTube videos (channel + title, not just liveness) ----
        vids = []  # (feature, id, title-as-declared, alias)
        for name, L in LINKS.items():
            if isinstance(L, dict):
                for v in (L.get("videos") or []):
                    if isinstance(v, dict) and v.get("id"):
                        vids.append((name, v["id"], v.get("t", ""), v.get("a")))
        vbad = 0
        if vids:
            print(f"verifying {len(vids)} Databricks YouTube videos ...")
            with cf.ThreadPoolExecutor(max_workers=12) as ex:
                futs = {ex.submit(check_video, vid, feat, alias): (feat, vid, decl) for feat, vid, decl, alias in vids}
                for fut in cf.as_completed(futs):
                    feat, vid, decl = futs[fut]
                    ok, detail = fut.result()
                    if not ok:
                        vbad += 1
                        fails.append(f"BAD VIDEO {vid} (LINKS[{feat}].videos): {detail}")
                    elif decl and _norm(decl) != _norm(detail):
                        vbad += 1
                        fails.append(f"VIDEO TITLE DRIFT {vid} (LINKS[{feat}]): declared '{decl}' != oembed '{detail}'")
        print(f"bad videos: {vbad}")

    print("\n" + "=" * 72)
    if fails:
        print(f"FAIL ({len(fails)} issues)")
        for f in fails:
            print("  -", f)
        raise SystemExit(1)
    print("PASS — every clickable entity is complete" + (" and every URL is live" if args.urls else ""))


if __name__ == "__main__":
    main()
