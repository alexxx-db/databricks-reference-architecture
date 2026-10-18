#!/usr/bin/env python3
"""Scrape Databricks regional availability into app/resources/regions.json.

Databricks does NOT publish a single product x region matrix. It publishes two
things per cloud, both server-rendered HTML tables:

  * "Databricks clouds and regions"  -> the flat list of supported regions.
  * "Features with limited regional availability" -> the ONLY features that are
    NOT available in every supported region, one column per feature.

Everything absent from the second page is available in every supported region of
that cloud (the page states this itself: "If a feature is supported in all
regions, it is not included"). So the runtime materialises a full matrix from:

    region in regionsFor(product) iff
        product maps to a limited-availability feature column -> that cell's value
        otherwise                                             -> every supported region

This scraper emits the raw scraped truth (supported regions + the limited-feature
tables) plus the curated product->feature-column ALIAS so the runtime resolver has
one authoritative file to read. Re-run whenever the docs change; a companion gate
(regiongate.py) fails the build on drift.

A product whose own page publishes a region list (PRODUCT_PAGES) is read from that
page instead: the list becomes a "<product> (product page)" column, its page is
recorded in feature_sources so the board links to it, and a cloud the page does not
list reads as not available there.

Usage:  python3 tools/scrape_regions.py   [--check]
"""
import argparse, concurrent.futures, datetime, json, os, re, sys, urllib.request
from html import unescape
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app", "resources", "regions.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125 Safari/537.36")

# Doc pages per cloud. supported = the region list; feature = the limited table.
SOURCES = {
    "aws": {
        "supported": "https://docs.databricks.com/aws/en/resources/supported-regions",
        "feature":   "https://docs.databricks.com/aws/en/resources/feature-region-support",
    },
    "azure": {
        "supported": "https://learn.microsoft.com/en-us/azure/databricks/resources/supported-regions",
        "feature":   "https://learn.microsoft.com/en-us/azure/databricks/resources/feature-region-support",
    },
    "gcp": {
        "supported": "https://docs.databricks.com/gcp/en/resources/supported-regions",
        "feature":   "https://docs.databricks.com/gcp/en/resources/feature-region-support",
    },
}

# Curated product -> primary limited-availability feature column. The value is a
# case-insensitive substring matched against the scraped column labels of the
# active cloud. A product NOT listed here is treated as available in every
# supported region (the docs' own default). A product listed here but whose
# column is absent on a given cloud also falls back to all-supported for that
# cloud. One column per product keeps the truth defensible (no invented AND/OR).
ALIAS = {
    "AI Search": "AI Search",
    "Apps": "Databricks Apps",
    "Lakehouse//RT": "Lakehouse Real-Time",
    "Lakeflow Connect": "Managed connectors in Lakeflow Connect",
    "Zerobus": "Zerobus Ingest",
    "Unity Gateway": "Unity Gateway",
    "AI Functions": "Other AI functions",
    "Document Intelligence": "ai_parse_document",
    "Foundation Model APIs": "Foundation Model APIs (pay-per-token)",
    "Databricks Sandbox": "Databricks Sandbox",
    "Serverless Compute": "Serverless compute",
    "Model Serving": "Custom Model Serving capability (CPU serving)",
}

PART_OF = {
    "CMK": "customer-managed keys, an account setting with no box",
    "Custom Agents": "custom agents served on Model Serving, held by the Model Serving box",
    "Custom Model Serving capability (GPU serving)": "GPU serving inside Model Serving, whose box follows CPU serving",
    "Data Quality Monitoring": "a Unity Catalog capability",
    "Default storage": "a workspace storage option with no box",
    "Download visualizations API": "an AI/BI API",
    "External models": "models served through Model Serving",
    "Firewall enablement for serverless compute": "a Serverless Compute network option",
    "Foundation Model APIs (provisioned throughput)": "a Foundation Model APIs mode; the box follows pay-per-token",
    "Foundation Model Fine-tuning": "no box on the board",
    "Knowledge Assistant": "an Agent Bricks agent type",
    "Lakebase Autoscaling": "a Lakebase option; the box follows its product page",
    "MLflow traces in Unity Catalog": "an MLflow capability",
    "Managed disaster recovery": "no box on the board",
    "Model Training - forecasting": "no box on the board",
    "Predictive Optimization": "a Unity Catalog managed-table capability",
    "Private connectivity": "a network option for the compute planes",
    "PrivateLink (classic compute plane)": "a Classic Compute network option",
    "Serverless workspaces": "a Serverless Compute workspace option",
    "Supervisor Agent": "an Agent Bricks agent type",
    "System tables": "a Unity Catalog capability",
    "ai_": "an AI Functions function; the box follows the v1 functions",
}

REVIEWED = {
    "Genie Code": "only agent mode needs a supported Geo; without partner-powered AI features it runs everywhere on a Databricks-hosted model",
    "SQL Warehouses": "serverless warehouses follow Serverless Compute; classic and pro warehouses run in every supported region",
    "LTAP": "only the GCP page points to region availability, and LTAP is not available on GCP yet",
}
DOCS = {"aws": "https://docs.databricks.com/aws/en/",
        "azure": "https://learn.microsoft.com/en-us/azure/databricks/",
        "gcp": "https://docs.databricks.com/gcp/en/"}
REGION_REQ = re.compile(r"[^.\n]*(?:supported regions?\b|region availability|available in (?:these|the following) regions"
                        r"|not available in (?:all|every|some)? ?regions?)[^.\n]*", re.I)
REGION_LINK = re.compile(r'href="[^"]*(?:feature-region-support|supported-regions)[^"]*"')

PRODUCT_PAGES = {
    "Lakebase": {
        "aws": "https://docs.databricks.com/aws/en/oltp/projects/manage-projects",
        "azure": "https://learn.microsoft.com/en-us/azure/databricks/oltp/projects/manage-projects",
        "gcp": "https://docs.databricks.com/gcp/en/oltp/projects/manage-projects",
    },
    "Genie App Builder": {
        "aws": "https://docs.databricks.com/aws/en/dev-tools/databricks-apps/genie-app-builder",
        "azure": "https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/genie-app-builder",
        "gcp": "https://docs.databricks.com/aws/en/dev-tools/databricks-apps/genie-app-builder",
    },
}
PAGE_SUFFIX = " (product page)"
AVAIL_HEAD = re.compile(r"region availability|requirements and availability|supported regions", re.I)

CHECK = "✓"


class TableParser(HTMLParser):
    """Collect every <table> as a list of rows, each row a list of cell texts.
    Tolerant of the unclosed <td><p> markup docs.databricks.com emits and of the
    standard fully-closed markup learn.microsoft.com emits."""

    def __init__(self):
        super().__init__()
        self.tables, self._rows, self._cells, self._buf = [], None, None, []
        self._in_table = 0
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table += 1
            self._rows = []
        elif tag == "tr" and self._in_table:
            self._flush_row()
            self._cells = []
        elif tag in ("td", "th") and self._in_table:
            # a new cell starts: close the previous one, then begin capturing.
            # Text between <tr> and the first cell (whitespace on fully-closed
            # markup) is ignored because _in_cell is still False there.
            self._flush_cell()
            self._buf = []
            self._in_cell = True

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_table:
            self._flush_cell()
        elif tag == "table" and self._in_table:
            self._flush_row()
            if self._rows:
                self.tables.append(self._rows)
            self._rows, self._in_table = None, self._in_table - 1

    def handle_data(self, data):
        if self._in_cell:
            self._buf.append(data)

    def _flush_cell(self):
        if self._cells is not None and self._in_cell:
            self._cells.append("".join(self._buf).strip())
        self._buf = []
        self._in_cell = False

    def _flush_row(self):
        self._flush_cell()
        if self._cells:
            self._rows.append(self._cells)
        self._cells = None


class AvailabilityParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.codes, self._head, self._htext, self._capture, self._code, self._ctext, self._skip = [], None, [], False, False, [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("h1", "h2", "h3", "h4"):
            self._head, self._htext, self._capture = tag, [], False
        elif tag == "code":
            self._code, self._ctext = True, []

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag == self._head:
            self._capture = bool(AVAIL_HEAD.search("".join(self._htext)))
            self._head = None
        elif tag == "code" and self._code:
            self._code = False
            if self._capture:
                self.codes.append("".join(self._ctext).strip())

    def handle_data(self, data):
        if self._skip:
            return
        if self._head:
            self._htext.append(data)
        elif self._code:
            self._ctext.append(data)


def parse_product_page(html, supported):
    p = AvailabilityParser()
    p.feed(html)
    listed = {clean_code(c) for c in p.codes}
    return {code: code in listed for code in supported}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def tables_of(html):
    p = TableParser()
    p.feed(html)
    return p.tables


def clean_code(s):
    """Region codes carry footnote markers on the Azure docs (southcentralus*,
    uksouth†) that differ between the supported-regions and feature-region tables,
    so the same region reads as two different codes and a feature cell orphans off
    the region list. Strip every trailing non-alphanumeric so both tables agree."""
    return re.sub(r"[^a-z0-9]+$", "", (s or "").strip())


def is_region_row(cell):
    return bool(re.fullmatch(r"[a-z]{2}(-[a-z]+)?-[a-z0-9-]*\d", cell.strip())) \
        or bool(re.fullmatch(r"[a-z]+[a-z0-9]*", cell.strip())) and "-" not in cell


def parse_supported(html):
    """The region list: the table whose header is Region | Location and whose
    rows are region-code | location, with no extra feature columns."""
    out = {}
    for rows in tables_of(html):
        if not rows:
            continue
        head = [c.lower() for c in rows[0]]
        if len(head) == 2 and head[0].startswith("region") and "location" in head[1]:
            for r in rows[1:]:
                if len(r) >= 2 and r[0]:
                    out[clean_code(r[0])] = r[1].strip()
    return out


def parse_features(html):
    """Every limited-availability table: header Region|Location|<feat>|<feat>...
    Returns {feature_label: {region_code: bool}}. Later duplicate tables (the doc
    renders each twice) simply overwrite with identical data."""
    feats = {}
    for rows in tables_of(html):
        if len(rows) < 2:
            continue
        head = rows[0]
        low = [c.lower() for c in head]
        if not (low[0].startswith("region") and len(head) >= 3 and "location" in low[1]):
            continue
        cols = head[2:]
        for r in rows[1:]:
            if len(r) < 2 or not r[0]:
                continue
            code = clean_code(r[0])
            vals = r[2:]
            for i, label in enumerate(cols):
                lab = re.sub(r"\s+", " ", label).strip()
                if not lab:
                    continue
                has = i < len(vals) and CHECK in vals[i]
                feats.setdefault(lab, {})[code] = bool(has)
    return feats


def region_statement(html):
    body = re.sub(r"<(script|style|nav|header|footer|aside)\b.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", body)))
    m = REGION_REQ.search(text)
    if m:
        return m.group(0).strip()[:160]
    return "links to the regional availability page" if REGION_LINK.search(body) else None


def page_problems(flags, alias, product_pages, reviewed):
    out = []
    for name in sorted(flags):
        if name in alias or name in product_pages or name in reviewed:
            continue
        cloud, said = flags[name][0]
        out.append(f"{name}: its {cloud} docs page states a region requirement ('{said}'); "
                   f"map it in ALIAS or PRODUCT_PAGES, or record why not in REVIEWED")
    for name in sorted(set(reviewed) - set(flags)):
        out.append(f"REVIEWED[{name!r}] backs no region statement on any docs page any more; remove it")
    return out


def board_products():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from scrape_stages import board_arch
    arch, names = board_arch(), set()

    def walk(node, keep):
        if isinstance(node, list):
            for x in node:
                walk(x, keep)
        elif isinstance(node, dict):
            if isinstance(node.get("n"), str) and keep(node):
                names.add(node["n"])
            for v in node.values():
                walk(v, keep)

    walk(arch.get("bands"), lambda t: True)
    walk((arch.get("cloud") or {}).get("providers"), lambda t: t.get("role") == "network")
    return names


def review_pages(links):
    names = sorted(n for n in board_products() if (links.get(n) or {}).get("doc"))
    jobs = [(n, c) for n in names for c in (links[n].get("docClouds") or list(DOCS))]

    def one(job):
        n, c = job
        try:
            return n, c, region_statement(fetch(DOCS[c] + links[n]["doc"].lstrip("/")))
        except Exception:
            return n, c, None

    flags = {}
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        for n, c, said in ex.map(one, jobs):
            if said:
                flags.setdefault(n, []).append((c, said))
    return flags


def build():
    clouds = {}
    for cloud, urls in SOURCES.items():
        sup_html = fetch(urls["supported"])
        feat_html = fetch(urls["feature"])
        supported = parse_supported(sup_html)
        features = parse_features(feat_html)
        clouds[cloud] = {
            "regions": [{"code": k, "loc": v} for k, v in supported.items()],
            "features": features,
        }
        sys.stderr.write(
            f"{cloud}: {len(supported)} regions, {len(features)} limited features\n")
    overlap = sorted(set(ALIAS) & set(PRODUCT_PAGES))
    if overlap:
        raise SystemExit(f"mapped twice (ALIAS and PRODUCT_PAGES): {overlap}")
    alias, pages = dict(ALIAS), {}
    for prod, by_cloud in PRODUCT_PAGES.items():
        label = prod + PAGE_SUFFIX
        alias[prod] = label
        for cloud, url in by_cloud.items():
            if url not in pages:
                pages[url] = fetch(url)
            codes = [r["code"] for r in clouds[cloud]["regions"]]
            col = parse_product_page(pages[url], codes)
            clouds[cloud]["features"][label] = col
            clouds[cloud].setdefault("feature_sources", {})[label] = url
            sys.stderr.write(f"{cloud}: {prod} product page lists {sum(col.values())} of {len(codes)} regions\n")
    return {
        "generated": datetime.date.today().isoformat(),
        "sources": SOURCES,
        "alias": alias,
        "clouds": clouds,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="scrape and diff against the committed file; exit 1 on drift")
    args = ap.parse_args()
    data = build()

    # every cloud must have yielded regions and at least one limited feature, or
    # the doc layout moved and a silent empty file would poison the runtime.
    for cloud, c in data["clouds"].items():
        if not c["regions"]:
            raise SystemExit(f"{cloud}: 0 regions scraped — doc layout changed")
        if not c["features"]:
            raise SystemExit(f"{cloud}: 0 limited features scraped — doc layout changed")
    for prod in PRODUCT_PAGES:
        label = prod + PAGE_SUFFIX
        if not any(any((c["features"].get(label) or {}).values()) for c in data["clouds"].values()):
            raise SystemExit(f"{prod}: its product pages list no region on any cloud — doc layout changed")
    links = json.load(open(os.path.join(ROOT, "app", "resources", "links.json"), encoding="utf-8"))
    flags = review_pages(links)
    problems = page_problems(flags, ALIAS, PRODUCT_PAGES, REVIEWED)
    if problems:
        raise SystemExit("product pages state region requirements the data does not carry:\n  " + "\n  ".join(problems))
    sys.stderr.write(f"product pages: {len(flags)} board products state a region requirement, every one mapped or reviewed\n")

    new = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    if args.check:
        old = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        # compare on everything but the generated date
        def strip_date(s):
            return re.sub(r'"generated":\s*"[^"]*"', '"generated":""', s)
        if strip_date(old) != strip_date(new):
            sys.stderr.write("regions.json is stale — re-run tools/scrape_regions.py\n")
            sys.exit(1)
        sys.stderr.write("regions.json up to date\n")
        return
    open(OUT, "w", encoding="utf-8").write(new)
    sys.stderr.write(f"wrote {OUT}\n")


if __name__ == "__main__":
    main()
