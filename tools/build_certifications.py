#!/usr/bin/env python3
import argparse, datetime, html, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app", "resources", "certifications.json")
HOST = "https://www.databricks.com"
CATALOG = HOST + "/learn/certification"
CERT_PATH = "/learn/certification/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125 Safari/537.36")

CREDS = {
    "lakehouse-fundamentals": {"path": "/resources/learn/training/lakehouse-fundamentals", "kind": "Badge", "name": "card"},
    "analytics-fundamentals": {"path": "/resources/learn/training/analytics-fundamentals-accreditation", "kind": "Badge"},
    "generative-ai-fundamentals": {"path": "/resources/learn/training/generative-ai-fundamentals", "kind": "Badge", "name": "card"},
    "ai-agent-fundamentals": {"path": "/resources/training/level-your-ai-agent-skills", "kind": "Badge", "name": "card"},
    "data-analyst-associate": {"path": CERT_PATH + "data-analyst-associate", "kind": "Certification", "level": "Associate"},
    "data-engineer-associate": {"path": CERT_PATH + "data-engineer-associate", "kind": "Certification", "level": "Associate"},
    "data-engineer-professional": {"path": CERT_PATH + "data-engineer-professional", "kind": "Certification", "level": "Professional"},
    "machine-learning-associate": {"path": CERT_PATH + "machine-learning-associate", "kind": "Certification", "level": "Associate"},
    "machine-learning-professional": {"path": CERT_PATH + "machine-learning-professional", "kind": "Certification", "level": "Professional"},
    "genai-engineer-associate": {"path": CERT_PATH + "genai-engineer-associate", "kind": "Certification", "level": "Associate"},
    "context-engineer-associate": {"path": CERT_PATH + "context-engineer-associate", "kind": "Certification", "level": "Associate"},
    "apache-spark-developer-associate": {"path": CERT_PATH + "apache-spark-developer-associate", "kind": "Certification", "level": "Associate"},
    "platform-administrator-accreditation": {"path": CERT_PATH + "platform-administrator-accreditation", "kind": "Accreditation"},
    "platform-architect-aws": {"path": CERT_PATH + "databricks-on-aws", "kind": "Badge", "cloud": "aws"},
    "platform-architect-azure": {"path": CERT_PATH + "databricks-on-azure", "kind": "Badge", "cloud": "azure"},
    "platform-architect-gcp": {"path": CERT_PATH + "databricks-on-gcp", "kind": "Badge", "cloud": "gcp"},
}
IGNORE = {"data-engineering-associate-renewal", "faq", "terms-and-conditions"}
CLOUDS = ("aws", "azure", "gcp")
CARD_TAGS = {"Popular", "Associate", "Professional", "Renewal exam", "Learn more",
             "Start learning now", "Start free training"}

EVIDENCE = {
    "Lakeflow Connect": r"lakeflow connect",
    "Auto Loader": r"auto ?loader",
    "Streaming": r"streaming",
    "Lakeflow": r"lakeflow (jobs|pipelines|spark declarative|declarative)|declarative pipelines|delta live tables",
    "Apache Spark": r"apache spark|pyspark|spark sql|dataframe",
    "Delta Lake": r"delta lake|delta tables?",
    "Apache Iceberg": r"iceberg",
    "OpenSharing": r"opensharing|delta sharing",
    "Lakehouse": r"medallion|bronze|lakehouse",
    "Unity Catalog": r"unity catalog",
    "SQL Warehouses": r"sql warehouse",
    "AI/BI": r"ai/bi|dashboards?",
    "Genie Agents": r"genie",
    "MLflow": r"mlflow",
    "Model Serving": r"model serving|serving endpoints?",
    "AI Search": r"ai search|vector search",
    "Agent Bricks": r"agent bricks|agent framework",
    "Knowledge Assistant": r"knowledge assistant",
    "Unity Gateway": r"unity gateway|ai gateway",
    "Lakebase": r"lakebase",
    "Apps": r"databricks apps?",
    "Agentic Dev": r"automation bundles?|asset bundles?|ci/cd|git folders?",
}

PRODUCTS = {
    "Lakeflow Connect": ["data-engineer-associate", "data-engineer-professional"],
    "Auto Loader": ["data-analyst-associate", "data-engineer-associate", "data-engineer-professional"],
    "Streaming": ["data-engineer-associate", "apache-spark-developer-associate", "data-engineer-professional"],
    "Lakeflow": ["data-engineer-associate", "data-engineer-professional"],
    "Apache Spark": ["apache-spark-developer-associate", "data-engineer-associate", "data-engineer-professional"],
    "Delta Lake": ["data-analyst-associate", "data-engineer-associate", "data-engineer-professional"],
    "Apache Iceberg": ["data-engineer-professional"],
    "OpenSharing": ["data-analyst-associate", "data-engineer-professional"],
    "Lakehouse": ["data-analyst-associate", "data-engineer-associate", "data-engineer-professional"],
    "Unity Catalog": ["data-analyst-associate", "data-engineer-associate", "machine-learning-associate",
                      "context-engineer-associate", "data-engineer-professional", "platform-administrator-accreditation"],
    "SQL Warehouses": ["data-analyst-associate"],
    "AI/BI": ["data-analyst-associate"],
    "Genie Agents": ["data-analyst-associate", "genai-engineer-associate", "context-engineer-associate"],
    "MLflow": ["machine-learning-associate", "genai-engineer-associate", "context-engineer-associate", "machine-learning-professional"],
    "Model Serving": ["machine-learning-associate", "genai-engineer-associate", "machine-learning-professional"],
    "AI Search": ["genai-engineer-associate", "context-engineer-associate"],
    "Agent Bricks": ["genai-engineer-associate", "context-engineer-associate"],
    "Knowledge Assistant": ["genai-engineer-associate"],
    "Unity Gateway": ["genai-engineer-associate"],
    "Lakebase": ["context-engineer-associate"],
    "Apps": ["genai-engineer-associate"],
    "Agentic Dev": ["data-engineer-associate", "data-engineer-professional", "machine-learning-professional"],
}

PERSONAS = {
    "Executives": ["lakehouse-fundamentals", "generative-ai-fundamentals", "ai-agent-fundamentals"],
    "Business Teams": ["lakehouse-fundamentals", "analytics-fundamentals", "generative-ai-fundamentals", "ai-agent-fundamentals"],
    "Risk & Compliance": ["lakehouse-fundamentals", "generative-ai-fundamentals", "ai-agent-fundamentals"],
    "Data Engineers": ["data-engineer-associate", "apache-spark-developer-associate", "data-engineer-professional"],
    "Data Scientists": ["machine-learning-associate", "genai-engineer-associate", "machine-learning-professional"],
    "Data Analysts": ["analytics-fundamentals", "data-analyst-associate"],
    "Analytics Engineers": ["data-analyst-associate", "data-engineer-associate"],
    "App Developers": ["genai-engineer-associate", "context-engineer-associate"],
    "Platform Governance & Admin": ["platform-administrator-accreditation", "platform-architect-aws",
                                    "platform-architect-azure", "platform-architect-gcp"],
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1.5)


def page_text(page):
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)))


def local_path(href):
    u = urllib.parse.urlsplit(html.unescape(href))
    if u.netloc not in ("", "www.databricks.com", "databricks.com"):
        return None
    return u.path.rstrip("/") or "/"


def catalog_cards(page):
    cards = {}
    for m in re.finditer(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        path = local_path(m.group(1))
        if not path:
            continue
        body = re.sub(r"<(script|style)\b.*?</\1>", "", m.group(2), flags=re.S)
        parts = [html.unescape(re.sub(r"\s+", " ", p)).strip() for p in re.split(r"<[^>]+>", body)]
        cards.setdefault(path, []).append([p for p in parts if p])
    return cards


def card_name(card_list):
    for parts in card_list:
        for p in parts:
            if p not in CARD_TAGS:
                return p
    return None


def pdf_text(url, exe):
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "guide.pdf")
        with open(f, "wb") as fh:
            fh.write(get(url))
        return subprocess.run([exe, "-q", f, "-"], capture_output=True, text=True, check=True).stdout


def static_errors():
    errs = []
    if set(EVIDENCE) != set(PRODUCTS):
        errs.append("EVIDENCE and PRODUCTS name different products: %s"
                    % sorted(set(EVIDENCE) ^ set(PRODUCTS)))
    used = set()
    for where, table in (("PRODUCTS", PRODUCTS), ("PERSONAS", PERSONAS)):
        for key, ids in table.items():
            if not ids:
                errs.append("%s['%s'] is empty" % (where, key))
            if len(ids) != len(set(ids)):
                errs.append("%s['%s'] lists a credential twice" % (where, key))
            for cid in ids:
                if cid not in CREDS:
                    errs.append("%s['%s'] names unknown credential '%s'" % (where, key, cid))
                used.add(cid)
    for cid in sorted(set(CREDS) - used):
        errs.append("credential '%s' is attached to no product or team" % cid)
    for key, ids in PERSONAS.items():
        clouds = [CREDS[c]["cloud"] for c in ids if c in CREDS and CREDS[c].get("cloud")]
        if clouds and sorted(clouds) != sorted(CLOUDS):
            errs.append("PERSONAS['%s'] covers clouds %s, needs exactly one per cloud %s"
                        % (key, sorted(clouds), list(CLOUDS)))
    return errs


def build(evidence_exe):
    errs = static_errors()
    if errs:
        return None, errs
    catalog = get(CATALOG).decode("utf-8", "replace")
    cards = catalog_cards(catalog)
    linked = set(cards)
    known = {c["path"] for c in CREDS.values()}
    for cid, spec in CREDS.items():
        if spec["path"] not in linked:
            errs.append("'%s' (%s) is no longer on %s: retired or moved" % (cid, spec["path"], CATALOG))
    for path in sorted(linked):
        if path.startswith(CERT_PATH) and path not in known:
            slug = path[len(CERT_PATH):]
            if slug and "/" not in slug and slug not in IGNORE:
                errs.append("new credential on the catalog: %s; add it to CREDS and map it, or to IGNORE" % path)

    creds, proof = {}, {}
    for cid, spec in CREDS.items():
        url = HOST + spec["path"]
        try:
            page = get(url).decode("utf-8", "replace")
        except Exception as e:
            errs.append("'%s' page %s failed: %s" % (cid, url, str(e)[:80]))
            continue
        m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S)
        title = re.sub(r"\s*\|\s*Databricks\s*$", "", html.unescape(m.group(1)).strip()) if m else ""
        name = card_name(cards.get(spec["path"], [])) if spec.get("name") == "card" else title
        if not name:
            errs.append("'%s' has no name on %s" % (cid, url))
            continue
        if spec.get("level") and spec["level"] not in title:
            errs.append("'%s' is curated as %s but its page title reads '%s'" % (cid, spec["level"], title))
        rec = {"t": name, "kind": spec["kind"], "u": url}
        for k in ("level", "cloud"):
            if spec.get(k):
                rec[k] = spec[k]
        guide = None
        for href in re.findall(r'href="([^"]+\.pdf)"', page, re.I):
            if re.search(r"databricks-certified", href, re.I):
                guide = urllib.parse.urljoin(url, html.unescape(href))
                break
        if spec["kind"] == "Certification":
            if not guide:
                errs.append("'%s' links no exam guide PDF on %s" % (cid, url))
            else:
                rec["guide"] = guide
        creds[cid] = rec
        if evidence_exe:
            try:
                proof[cid] = (pdf_text(guide, evidence_exe) if guide else page_text(page), guide or url)
            except Exception as e:
                errs.append("'%s' evidence source %s unreadable: %s" % (cid, guide or url, str(e)[:80]))

    if evidence_exe:
        for prod, ids in PRODUCTS.items():
            for cid in ids:
                if cid in proof and not re.search(EVIDENCE[prod], proof[cid][0], re.I):
                    errs.append("'%s' no longer names %s in %s" % (cid, prod, proof[cid][1]))

    data = {
        "generated": datetime.date.today().isoformat(),
        "source": CATALOG,
        "creds": creds,
        "byProduct": PRODUCTS,
        "byPersona": PERSONAS,
    }
    return data, errs


def main():
    ap = argparse.ArgumentParser(description="Scrape the Databricks certification and badge catalog into "
                                             "app/resources/certifications.json, verifying each product "
                                             "pairing against the certification's current exam guide.")
    ap.add_argument("--check", action="store_true", help="scrape and diff vs committed file; exit 1 on drift")
    ap.add_argument("--no-evidence", action="store_true",
                    help="skip the exam-guide evidence check (it needs pdftotext from poppler)")
    args = ap.parse_args()
    exe = None
    if not args.no_evidence:
        exe = shutil.which("pdftotext")
        if not exe:
            raise SystemExit("pdftotext not found: install poppler (brew install poppler, apt install "
                             "poppler-utils) or pass --no-evidence")
    data, errs = build(exe)
    if errs:
        sys.stderr.write("certifications.json NOT written, %d problem(s):\n" % len(errs))
        for e in errs:
            sys.stderr.write("  - %s\n" % e)
        sys.exit(1)
    sys.stderr.write("credentials:%d  products:%d  teams:%d  evidence:%s\n" % (
        len(data["creds"]), len(data["byProduct"]), len(data["byPersona"]),
        "skipped" if args.no_evidence else "verified"))

    new = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    if args.check:
        old = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        strip = lambda s: re.sub(r'"generated":\s*"[^"]*"', '"generated":""', s)
        if strip(old) != strip(new):
            sys.stderr.write("certifications.json is stale; re-run tools/build_certifications.py\n")
            sys.exit(1)
        sys.stderr.write("certifications.json up to date\n")
        return
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(new)
    sys.stderr.write("wrote %s\n" % OUT)


if __name__ == "__main__":
    main()
