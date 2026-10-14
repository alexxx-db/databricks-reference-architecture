#!/usr/bin/env python3
import contextlib, copy, importlib.util, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bc = load("build_certifications")
lg = load("linkgate")

SAMPLE = {
    "Lakeflow Connect": "Lakeflow Connect", "Auto Loader": "Auto Loader", "Streaming": "Structured Streaming",
    "Lakeflow": "Lakeflow Jobs", "Apache Spark": "Apache Spark", "Delta Lake": "Delta Lake",
    "Apache Iceberg": "Iceberg", "OpenSharing": "Delta Sharing", "Lakehouse": "medallion architecture",
    "Unity Catalog": "Unity Catalog", "SQL Warehouses": "SQL warehouses", "AI/BI": "AI/BI dashboards",
    "Genie Agents": "Genie spaces", "MLflow": "MLflow", "Model Serving": "Model Serving",
    "AI Search": "Vector Search", "Agent Bricks": "Agent Bricks", "Document Intelligence": "Information Extraction",
    "Foundation Model APIs": "Foundation Model APIs", "Agent Runtime and Memory": "agent memory",
    "Unity Gateway": "AI Gateway", "Lakebase": "Lakebase", "Apps": "Databricks Apps",
    "Agentic Dev": "Declarative Automation Bundles",
}
CARD = {"lakehouse-fundamentals": "Databricks Fundamentals", "generative-ai-fundamentals": "Generative AI Fundamentals",
        "ai-agent-fundamentals": "AI Agent Fundamentals"}

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


def guide_url(cid):
    return bc.HOST + "/sites/default/files/2026-01/databricks-certified-%s-exam-guide.pdf" % cid


def evidence_for(cid):
    return " ".join(SAMPLE[p] for p, ids in bc.PRODUCTS.items() if cid in ids)


def site(drop=(), extra_links=(), titles=None, no_guide=(), guide_text=None, dead=()):
    titles = titles or {}
    links = []
    for cid, spec in bc.CREDS.items():
        if cid in drop:
            continue
        tag = "Popular" if spec.get("name") == "card" else (spec.get("level") or "Accreditation")
        head = CARD.get(cid, cid.replace("-", " ").title())
        links.append('<a href="%s?itm_source=www"><span>%s</span><h3>%s</h3><p>About it.</p><span>Learn more</span></a>'
                     % (spec["path"], tag, head))
    links.append('<a href="/learn/certification/data-engineering-associate-renewal"><span>Renewal exam</span><h3>Data Engineer Associate</h3></a>')
    links.append('<a href="https://www.databricks.com/learn/certification/faq">Learn more</a>')
    links.append('<a href="https://example.com/learn/certification/rival-associate">Rival</a>')
    for p in extra_links:
        links.append('<a href="%s"><h3>New</h3></a>' % p)
    pages = {bc.CATALOG: "<html><body>%s</body></html>" % "".join(links)}
    guides = {}
    for cid, spec in bc.CREDS.items():
        title = titles.get(cid, "Databricks Certified " + cid.replace("-", " ").title())
        body = ""
        if spec["kind"] == "Certification" and cid not in no_guide:
            body = ('<a href="/sites/default/files/2026-06/ai-prep-guide-any-databricks-certification.pdf">Prep</a>'
                    '<a href="/sites/default/files/2026-01/databricks-certified-%s-exam-guide.pdf">Exam guide</a>' % cid)
            guides[guide_url(cid)] = (guide_text or {}).get(cid, evidence_for(cid))
        page_text = "" if spec["kind"] == "Certification" else evidence_for(cid)
        if bc.HOST + spec["path"] not in dead:
            pages[bc.HOST + spec["path"]] = ("<html><head><title>%s | Databricks</title></head><body>%s<p>%s</p></body></html>"
                                             % (title, body, page_text))
    return pages, guides


@contextlib.contextmanager
def fake_web(pages, guides):
    real_get, real_pdf = bc.get, bc.pdf_text

    def get(url):
        if url not in pages:
            raise OSError("HTTP Error 404: Not Found")
        return pages[url].encode("utf-8")

    bc.get, bc.pdf_text = get, (lambda url, exe: guides[url])
    try:
        yield
    finally:
        bc.get, bc.pdf_text = real_get, real_pdf


@contextlib.contextmanager
def patched(**tables):
    saved = {k: getattr(bc, k) for k in tables}
    for k, v in tables.items():
        setattr(bc, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(bc, k, v)


def run(exe="pdftotext", **kw):
    pages, guides = site(**kw)
    with fake_web(pages, guides):
        return bc.build(exe)


def has(errs, pattern):
    return any(re.search(pattern, e) for e in errs)


check("SAMPLE covers exactly the mapped products", set(SAMPLE) == set(bc.PRODUCTS), sorted(set(SAMPLE) ^ set(bc.PRODUCTS)))
for prod, phrase in SAMPLE.items():
    check("evidence pattern for %s matches real exam phrasing" % prod, re.search(bc.EVIDENCE[prod], phrase, re.I), phrase)
check("curated tables are consistent", not bc.static_errors(), bc.static_errors())

data, errs = run()
check("happy path builds without problems", data and not errs, errs)
creds = (data or {}).get("creds", {})
check("every curated credential is emitted", set(creds) == set(bc.CREDS), sorted(set(bc.CREDS) ^ set(creds)))
check("card-named badge takes the catalog heading, skipping the Popular tag",
      creds.get("lakehouse-fundamentals", {}).get("t") == "Databricks Fundamentals", creds.get("lakehouse-fundamentals"))
check("title-named credential drops the ' | Databricks' suffix",
      creds.get("data-engineer-professional", {}).get("t") == "Databricks Certified Data Engineer Professional", creds.get("data-engineer-professional"))
check("exam guide is the databricks-certified PDF, not the generic prep guide",
      creds.get("genai-engineer-associate", {}).get("guide") == guide_url("genai-engineer-associate"), creds.get("genai-engineer-associate"))
check("non-certifications carry no guide", "guide" not in creds.get("platform-administrator-accreditation", {"guide": 1}))
check("cloud badges keep their cloud", creds.get("platform-architect-gcp", {}).get("cloud") == "gcp")
check("links are absolute databricks.com URLs", all(c["u"].startswith(bc.HOST + "/") for c in creds.values()))

_, errs = run(drop={"context-engineer-associate"})
check("a curated credential missing from the catalog is reported as retired", has(errs, r"context-engineer-associate.*no longer on"), errs)

_, errs = run(extra_links=["/learn/certification/data-steward-associate"])
check("an unmapped credential on the catalog is reported as new", has(errs, r"new credential on the catalog: /learn/certification/data-steward-associate"), errs)
check("renewal, faq and other hosts are not reported as new", not has(errs, r"renewal|faq|rival"), errs)

_, errs = run(extra_links=["/learn/certification/data-steward-associate/details", "/learn/certification/"])
check("sub-pages and the bare catalog path are not credentials", not has(errs, r"new credential"), errs)

text = {"context-engineer-associate": evidence_for("context-engineer-associate").replace("Lakebase", "a database")}
_, errs = run(guide_text=text)
check("a product the exam guide no longer names fails the evidence check", has(errs, r"context-engineer-associate' no longer names Lakebase"), errs)
_, errs = run(exe=None, guide_text=text)
check("--no-evidence skips the exam-guide check", not has(errs, r"no longer names"), errs)

text = {"platform-administrator-accreditation": ""}
pages, guides = site()
pages[bc.HOST + bc.CREDS["platform-administrator-accreditation"]["path"]] = "<html><head><title>Admin | Databricks</title></head><body></body></html>"
with fake_web(pages, guides):
    _, errs = bc.build("pdftotext")
check("credentials without a guide are checked against their page text", has(errs, r"platform-administrator-accreditation' no longer names Unity Catalog"), errs)

_, errs = run(titles={"data-engineer-professional": "Databricks Certified Data Engineer Associate"})
check("a level that drifts from the page title is reported", has(errs, r"data-engineer-professional' is curated as Professional"), errs)

_, errs = run(no_guide={"genai-engineer-associate"})
check("a certification without an exam guide is reported", has(errs, r"genai-engineer-associate' links no exam guide"), errs)

_, errs = run(dead={bc.HOST + bc.CREDS["machine-learning-associate"]["path"]})
check("a credential page that fails to load is reported", has(errs, r"machine-learning-associate' page .* failed"), errs)

pages, guides = site()
cat = pages[bc.CATALOG].replace("<span>Popular</span><h3>AI Agent Fundamentals</h3><p>About it.</p><span>Learn more</span>", "<img alt=''>")
pages[bc.CATALOG] = cat
with fake_web(pages, guides):
    _, errs = bc.build("pdftotext")
check("a card-named badge with no heading is reported", has(errs, r"ai-agent-fundamentals' has no name"), errs)

prods = copy.deepcopy(bc.PRODUCTS)
prods["Lakebase"] = ["context-engineer-associate", "no-such-cert"]
with patched(PRODUCTS=prods):
    errs = bc.static_errors()
check("an unknown credential id in PRODUCTS is reported", has(errs, r"unknown credential 'no-such-cert'"), errs)

prods = copy.deepcopy(bc.PRODUCTS)
prods["Lakebase"] = ["context-engineer-associate", "context-engineer-associate"]
with patched(PRODUCTS=prods):
    errs = bc.static_errors()
check("a credential listed twice for one product is reported", has(errs, r"lists a credential twice"), errs)

prods = copy.deepcopy(bc.PRODUCTS)
prods["Lakebase"] = []
with patched(PRODUCTS=prods):
    errs = bc.static_errors()
check("an empty product list is reported", has(errs, r"PRODUCTS\['Lakebase'\] is empty"), errs)

pers = copy.deepcopy(bc.PERSONAS)
pers["App Developers"] = ["genai-engineer-associate"]
with patched(PERSONAS=pers):
    errs = bc.static_errors()
check("dropping a credential from one team keeps it if a product still uses it", not has(errs, r"context-engineer-associate"), errs)

extra = dict(bc.CREDS, **{"data-steward-associate": {"path": bc.CERT_PATH + "data-steward-associate", "kind": "Certification", "level": "Associate"}})
with patched(CREDS=extra):
    errs = bc.static_errors()
check("a curated credential attached to nothing is reported", has(errs, r"'data-steward-associate' is attached to no product or team"), errs)

pers = copy.deepcopy(bc.PERSONAS)
pers["Platform Governance & Admin"] = ["platform-administrator-accreditation", "platform-architect-aws", "platform-architect-azure"]
creds_no_gcp = {k: v for k, v in bc.CREDS.items() if k != "platform-architect-gcp"}
with patched(PERSONAS=pers, CREDS=creds_no_gcp):
    errs = bc.static_errors()
check("a team missing one cloud's badge is reported", has(errs, r"covers clouds \['aws', 'azure'\]"), errs)

ev = dict(bc.EVIDENCE)
ev.pop("Apps")
with patched(EVIDENCE=ev):
    errs = bc.static_errors()
check("a product without an evidence pattern is reported", has(errs, r"EVIDENCE and PRODUCTS name different products: \['Apps'\]"), errs)

check("local_path ignores other hosts", bc.local_path("https://example.com/learn/certification/x") is None)
check("local_path keeps relative and absolute databricks.com paths",
      bc.local_path("/learn/certification/x?itm=1") == bc.local_path("https://www.databricks.com/learn/certification/x/") == "/learn/certification/x")

certs = json.load(open(lg.CERT_FILE, encoding="utf-8"))
dump = {"prodNames": list(certs["byProduct"]) + ["Zerobus"], "personas": list(certs["byPersona"]) + ["Executive Board"]}
check("the committed certifications.json passes the gate", lg.cert_checks(dump, certs) == [], lg.cert_checks(dump, certs))

bad = copy.deepcopy(certs)
bad["byProduct"]["Unity AI Gateway"] = bad["byProduct"].pop("Unity Gateway")
check("gate: a product that is not a platform box fails", has(lg.cert_checks(dump, bad), r"product 'Unity AI Gateway' is not a platform box"))

bad = copy.deepcopy(certs)
bad["byPersona"]["Data Wranglers"] = ["data-analyst-associate"]
check("gate: a team that is not a Teams box fails", has(lg.cert_checks(dump, bad), r"team 'Data Wranglers' is not a Teams box"))

bad = copy.deepcopy(certs)
bad["creds"]["data-analyst-associate"]["u"] = "https://www.example.com/certs/data-analyst"
check("gate: a credential linking off Databricks fails", has(lg.cert_checks(dump, bad), r"'data-analyst-associate' links off Databricks"))

bad = copy.deepcopy(certs)
bad["creds"]["data-analyst-associate"]["u"] = "https://databricks.com.example.org/x"
check("gate: a look-alike host fails", has(lg.cert_checks(dump, bad), r"links off Databricks"))

bad = copy.deepcopy(certs)
bad["byProduct"]["Lakebase"].append("ghost-cert")
check("gate: an unknown credential id fails", has(lg.cert_checks(dump, bad), r"names unknown credential 'ghost-cert'"))

bad = copy.deepcopy(certs)
bad["creds"]["orphan-badge"] = {"t": "Orphan", "kind": "Badge", "u": "https://www.databricks.com/x"}
check("gate: a credential attached to nothing fails", has(lg.cert_checks(dump, bad), r"'orphan-badge' is attached to nothing"))

bad = copy.deepcopy(certs)
bad["byPersona"]["Platform Governance & Admin"].remove("platform-architect-gcp")
bad["creds"].pop("platform-architect-gcp")
check("gate: a team missing a cloud badge fails", has(lg.cert_checks(dump, bad), r"needs one cloud badge per cloud"))

bad = copy.deepcopy(certs)
bad["creds"]["data-analyst-associate"].update(kind="Diploma", level="Expert", cloud="oci")
fails = lg.cert_checks(dump, bad)
check("gate: unknown kind, level and cloud each fail",
      has(fails, r"unknown kind 'Diploma'") and has(fails, r"unknown level 'Expert'") and has(fails, r"unknown cloud 'oci'"), fails)

check("gate: an empty dump of Teams boxes fails", has(lg.cert_checks({"prodNames": dump["prodNames"]}, certs), r"no Teams boxes"))
check("gate: an empty certifications file fails", has(lg.cert_checks(dump, {}), r"no credentials, products or teams"))

urls = lg.collect_urls({"LINKS": {}, "inds": {}}, certs)
check("gate --urls live-checks every credential page and exam guide",
      all(c["u"] in urls for c in certs["creds"].values()) and all(c["guide"] in urls for c in certs["creds"].values() if c.get("guide")))

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    if not ok:
        print("FAIL  %s  %s" % (name, str(detail)[:300]))
print("%s %d/%d" % ("PASS" if not failed else "FAIL", len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
