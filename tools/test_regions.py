#!/usr/bin/env python3
import contextlib, copy, importlib.util, io, json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = load("scrape_regions")
rg = load("regiongate")
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


AWS = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1"]
AZURE = ["eastus", "westeurope", "swedencentral", "uksouth"]
GCP = ["us-central1", "europe-west3"]

LAKEBASE_LIKE = """<html><head><script>var s = "<code>eu-west-1</code>";</script></head><body>
<h2>Limits<a href="#limits">#</a></h2><p><code>us-west-2</code></p>
<h3>Region availability<a href="#region-availability">\u200b</a></h3><p>Supported regions:</p>
<ul><li><code>us-east-1</code> (US East)</li><li><code>us-west-2</code> (US West)</li><li><code>eastus</code> (East US)</li></ul>
<h4>Postgres version support</h4><p><code>ap-south-1</code></p></body></html>"""
BOTH_CLOUDS = """<h2>Requirements and availability</h2><p>AWS: <code>us-east-1</code>, <code>eu-west-1</code>.
Azure: <code>eastus</code>, <code>uksouth\u2020</code>. GCP is not supported.</p><h2>Next steps</h2><p><code>westeurope</code></p>"""


def listed(col):
    return sorted(k for k, v in col.items() if v)


col = sr.parse_product_page(LAKEBASE_LIKE, AWS)
check("a product page yields exactly the codes under its region heading", listed(col) == ["us-east-1", "us-west-2"], listed(col))
check("every supported region gets a value, listed or not", sorted(col) == sorted(AWS), sorted(col))
check("codes inside scripts and in later sections are ignored", not col["eu-west-1"] and not col["ap-south-1"], col)
check("a heading with an anchor inside still matches", listed(sr.parse_product_page(LAKEBASE_LIKE, AZURE)) == ["eastus"])
check("one section listing two clouds splits by cloud (AWS)", listed(sr.parse_product_page(BOTH_CLOUDS, AWS)) == ["eu-west-1", "us-east-1"])
check("one section listing two clouds splits by cloud, footnote marks stripped (Azure)",
      listed(sr.parse_product_page(BOTH_CLOUDS, AZURE)) == ["eastus", "uksouth"])
check("a cloud the page does not list reads as not available", listed(sr.parse_product_page(BOTH_CLOUDS, GCP)) == [])
check("a page without a region heading lists nothing", listed(sr.parse_product_page("<h2>Overview</h2><code>us-east-1</code>", AWS)) == [])
check("a 'Supported regions' heading also counts", listed(sr.parse_product_page("<h3>Supported regions</h3><code>us-west-2</code>", AWS)) == ["us-west-2"])

SUPPORTED_PAGE = "<table><tr><th>Region</th><th>Location</th></tr>{}</table>"
FEATURE_PAGE = "<table><tr><th>Region</th><th>Location</th><th>AI Search</th></tr>{}</table>"


def site():
    pages, calls = {}, []
    for cloud, codes in (("aws", AWS), ("azure", AZURE), ("gcp", GCP)):
        pages[sr.SOURCES[cloud]["supported"]] = SUPPORTED_PAGE.format("".join(f"<tr><td>{c}</td><td>Place</td></tr>" for c in codes))
        pages[sr.SOURCES[cloud]["feature"]] = FEATURE_PAGE.format("".join(f"<tr><td>{c}</td><td>Place</td><td>{'✓' if i % 2 == 0 else ''}</td></tr>" for i, c in enumerate(codes)))
    pages["https://docs.example/lakebase-aws"] = LAKEBASE_LIKE
    pages["https://docs.example/both"] = BOTH_CLOUDS

    def fetch(u):
        calls.append(u)
        return pages[u]
    return fetch, calls


@contextlib.contextmanager
def patched(mod, **kw):
    saved = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)


fetch, calls = site()
pages = {"Lakebase": {"aws": "https://docs.example/lakebase-aws", "azure": "https://docs.example/both", "gcp": "https://docs.example/both"}}
with patched(sr, fetch=fetch, PRODUCT_PAGES=pages, ALIAS={"AI Search": "AI Search"}):
    data = sr.build()
label = "Lakebase" + sr.PAGE_SUFFIX
check("a product-page product is mapped to its own column", data["alias"].get("Lakebase") == label, data["alias"])
check("curated mappings are kept", data["alias"].get("AI Search") == "AI Search")
check("the product-page column lands on every cloud", all(label in data["clouds"][c]["features"] for c in ("aws", "azure", "gcp")))
check("each cloud records the page its column came from",
      data["clouds"]["aws"]["feature_sources"][label] == "https://docs.example/lakebase-aws" and data["clouds"]["gcp"]["feature_sources"][label] == "https://docs.example/both")
check("the column holds that cloud's listed regions", listed(data["clouds"]["azure"]["features"][label]) == ["eastus", "uksouth"])
check("a cloud the page does not list is not available there", listed(data["clouds"]["gcp"]["features"][label]) == [])
check("a page shared by two clouds is fetched once", calls.count("https://docs.example/both") == 1, calls)

fetch, _ = site()
with patched(sr, fetch=fetch, PRODUCT_PAGES=pages, ALIAS={"Lakebase": "Lakebase Autoscaling"}):
    try:
        sr.build()
        check("a product mapped both ways is refused", False)
    except SystemExit as e:
        check("a product mapped both ways is refused", "mapped twice" in str(e), str(e))

empty = copy.deepcopy(data)
for c in empty["clouds"].values():
    c["features"][label] = {k: False for k in c["features"][label]}
with tempfile.TemporaryDirectory() as tmp, patched(sr, build=lambda: empty, OUT=os.path.join(tmp, "regions.json"), PRODUCT_PAGES=pages):
    argv = sys.argv
    sys.argv = ["scrape_regions.py"]
    try:
        sr.main()
        check("a product page that lists no region anywhere stops the scrape", False)
    except SystemExit as e:
        check("a product page that lists no region anywhere stops the scrape", "list no region on any cloud" in str(e), str(e))
    finally:
        sys.argv = argv
    check("nothing is written when the scrape stops", not os.path.exists(os.path.join(tmp, "regions.json")))

committed = json.load(open(rg.REGIONS, encoding="utf-8"))
links = json.load(open(rg.LINKS, encoding="utf-8"))


def gate(regions, links_data=None):
    with tempfile.TemporaryDirectory() as tmp:
        rp, lp = os.path.join(tmp, "regions.json"), os.path.join(tmp, "links.json")
        json.dump(regions, open(rp, "w"))
        json.dump(links_data if links_data is not None else links, open(lp, "w"))
        out, code = io.StringIO(), 0
        argv = sys.argv
        sys.argv = ["regiongate.py"]
        with patched(rg, REGIONS=rp, LINKS=lp), contextlib.redirect_stdout(out):
            try:
                rg.main()
            except SystemExit as e:
                code = e.code
            finally:
                sys.argv = argv
        return code, out.getvalue()


code, out = gate(committed)
check("the committed region data passes the gate", code == 0 and "REGIONGATE OK" in out, out[-200:])
page_labels = [v for v in committed["alias"].values() if v.endswith(rg.PAGE_SUFFIX)]
check("the committed data maps Lakebase and Genie App Builder from their own pages",
      committed["alias"].get("Lakebase") == "Lakebase" + rg.PAGE_SUFFIX and committed["alias"].get("Genie App Builder") == "Genie App Builder" + rg.PAGE_SUFFIX, page_labels)

bad = copy.deepcopy(committed)
bad["clouds"]["aws"]["feature_sources"]["Ghost (product page)"] = "https://docs.databricks.com/aws/en/ghost"
code, out = gate(bad)
check("gate: a source for a column that does not exist fails", code == 1 and "names no feature column" in out, out[-200:])

bad = copy.deepcopy(committed)
bad["clouds"]["azure"]["feature_sources"]["Lakebase (product page)"] = "https://example.com/lakebase"
code, out = gate(bad)
check("gate: a source off the Databricks docs fails", code == 1 and "is not a Databricks docs page" in out, out[-200:])

bad = copy.deepcopy(committed)
del bad["clouds"]["gcp"]["feature_sources"]["Lakebase (product page)"]
code, out = gate(bad)
check("gate: a product-page column without its page fails", code == 1 and "has no source page" in out, out[-200:])

bad = copy.deepcopy(committed)
for c in bad["clouds"].values():
    col = c["features"]["Lakebase (product page)"]
    c["features"]["Lakebase (product page)"] = {k: False for k in col}
code, out = gate(bad)
check("gate: a product-page column listing no region anywhere fails", code == 1 and "lists no region on any cloud" in out, out[-200:])

bad_links = copy.deepcopy(links)
bad_links["Genie App Builder"] = {"note": "no doc, no site"}
code, out = gate(committed, bad_links)
check("gate: a mapped product that is neither documented nor a product page fails", code == 1 and "'Genie App Builder' is not a Databricks product tile" in out, out[-200:])

bad = copy.deepcopy(committed)
bad["clouds"]["azure"]["features"]["Brand new feature"] = {r["code"]: False for r in bad["clouds"]["azure"]["regions"]}
code, out = gate(bad)
check("gate: a limited column that belongs to no board product fails", code == 1 and "'Brand new feature' belongs to no board product" in out, out[-200:])

with patched(rg.scrape_regions, PART_OF=dict(sr.PART_OF, **{"Retired feature": "gone"})):
    code, out = gate(committed)
check("gate: a PART_OF entry that matches no column fails", code == 1 and "PART_OF['Retired feature'] matches no limited column" in out, out[-200:])

old = {k: v for k, v in committed["alias"].items() if k not in ("Serverless Compute", "Model Serving")}
gaps = rg.unowned(committed["clouds"]["azure"]["features"], old, {k: v for k, v in sr.PART_OF.items()})
check("without the Serverless Compute and Model Serving mappings their columns belong to no board product",
      any(g.startswith("Serverless compute") for g in gaps) and any(g.startswith("Custom Model Serving capability (CPU") for g in gaps), gaps)
check("every limited column on every cloud belongs to a board product or says why not",
      all(not rg.unowned(c["features"], committed["alias"], sr.PART_OF) for c in committed["clouds"].values()))
cols = {"Firewall enablement for serverless compute": {}, "Serverless compute (notebooks, jobs, pipelines, and SQL warehouses)": {}}
check("an alias resolves to the column that starts with it, whatever the order",
      rg.feature_label(cols, "Serverless compute") == "Serverless compute (notebooks, jobs, pipelines, and SQL warehouses)")
az = committed["clouds"]["azure"]["features"]
serverless, serving = rg.feature_label(az, committed["alias"]["Serverless Compute"]), rg.feature_label(az, committed["alias"]["Model Serving"])
check("Qatar Central has neither serverless compute nor Model Serving",
      az[serverless]["qatarcentral"] is False and az[serving]["qatarcentral"] is False, (serverless, serving))

check("a 'supported region' requirement on a product page is found",
      "supported region" in (sr.region_statement("<p>Your workspace must be in a supported region. See Geo availability.</p>") or ""))
check("a 'region availability' heading is found", sr.region_statement("<h2>Limitations and region availability</h2>"))
check("a link to the regional availability page is found",
      sr.region_statement('<p>See <a href="../resources/feature-region-support#x">limits</a>.</p>') == "links to the regional availability page")
check("a page with no region requirement is not flagged",
      sr.region_statement("<h1>Delta Lake</h1><p>Open table format, available everywhere you run Databricks.</p>") is None)
check("a link in the site navigation is ignored", sr.region_statement('<nav><a href="/resources/supported-regions">Regions</a></nav><p>Spark</p>') is None)
flags = {"Mapped": [("aws", "x")], "Paged": [("aws", "x")], "Known": [("gcp", "x")], "Missed": [("azure", "in a supported region")]}
probs = sr.page_problems(flags, {"Mapped": "m"}, {"Paged": {}}, {"Known": "why", "Gone": "why"})
check("a product page with a region requirement that is not mapped or reviewed is reported",
      any(p.startswith("Missed: its azure docs page states a region requirement") for p in probs), probs)
check("mapped, product-page and reviewed products are not reported", not any(p.startswith(("Mapped", "Paged", "Known")) for p in probs), probs)
check("a reviewed product whose page no longer states a requirement is reported", any("REVIEWED['Gone']" in p for p in probs), probs)

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    if not ok:
        print("FAIL  %s  %s" % (name, str(detail)[:300]))
print("%s %d/%d" % ("PASS" if not failed else "FAIL", len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
