#!/usr/bin/env python3
import argparse, concurrent.futures, datetime, glob, html, json, os, re, subprocess, sys, time, urllib.error
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scrape_regions as sr

ROOT = sr.ROOT
RES = os.path.join(ROOT, "app", "resources")
OUT = os.path.join(RES, "stages.json")
LINKS = os.path.join(RES, "links.json")
PLATDOCS = os.path.join(RES, "platform_docs.json")
ARCHITECTURES = os.path.join(ROOT, "app", "architectures")

DOCS = {
    "aws": "https://docs.databricks.com/aws/en/",
    "azure": "https://learn.microsoft.com/en-us/azure/databricks/",
    "gcp": "https://docs.databricks.com/gcp/en/",
}
CLOUDS = list(DOCS)
API = "https://docs.databricks.com/api/"
SOURCE = DOCS["aws"] + "release-notes/release-types"
LADDER = ["Coming soon", "Private Preview", "Beta", "Public Preview", "GA"]
CANON = {"ga": "GA", "generally available": "GA", "general availability": "GA",
         "public preview": "Public Preview", "beta": "Beta", "private preview": "Private Preview",
         "coming soon": "Coming soon"}
NOTICE = re.compile(r"\b(?:is|are)\s+(?:now\s+)?(?:available\s+)?in\s+(public preview|private preview|beta)\b", re.I)
API_MARK = re.compile(r'__stage--([a-z-]+)"')
LEARN_BOXES = {"NOTE", "IMPORTANT", "CAUTION", "WARNING", "TIP"}
CAPABILITY_TABLES = {"LTAP"}
LC = "ingestion/lakeflow-connect/"
CONNECTOR_INDEXES = ["saas-overview", "cdc-overview", "query-based-overview",
                     "file-connectors-overview", "streaming-overview"]
INDEX_LINK = re.compile(r'<a [^>]*href="?/aws/en/(' + re.escape(LC) + r'[a-z0-9-]+)/?(?=["\s>])[^>]*>(.*?)</a>', re.S)
PROSE_WORD = re.compile(r"\b(private preview|public preview|beta|generally available|coming soon)\b|\b(GA)\b", re.I)
PROSE_SKIP = {"n", "name", "st", "stByCloud", "t", "title", "url", "u", "href", "id", "ic", "icon", "brand",
              "tag", "doc", "docClouds", "site", "blog", "dbx", "spec_url", "slug", "videos"}

RUNTIME = ["agents/deploy/agent-runtime"]
MEMORY = ["agents/agent-memory/managed-memory", "agents/agent-memory/managed-sessions"]
REAL_TIME_MODE = ["structured-streaming/real-time/"]
IDP = ["agents/agent-bricks/intelligent-document-processing"]
AI_DECIDE = ["sql/language-manual/functions/ai_decide"]
APP_SPACES = ["dev-tools/databricks-apps/app-spaces"]
GENIE_VOLUMES = ["genie-agents/volumes"]
CLAIMS = {
    "Agent Bricks": [
        ("Agent Bricks CLI (Beta)", "Beta", ["agents/custom-agents/agent-bricks-cli"]),
        ("Agent Runtime, MCP tools and tracing are generally available", "GA",
         RUNTIME + ["agents/mcp-tools/", "mlflow3/genai/tracing/"]),
        ("the Agent Bricks CLI, managed memory and sessions and Databricks Sandbox are in Beta", "Beta",
         ["agents/custom-agents/agent-bricks-cli"] + MEMORY + ["compute/serverless/sandbox"]),
    ],
    "Agent Mode": [
        ("Generally available since July 2026", "GA", ["genie-agents/concepts"]),
        ("The mode itself is GA", "GA", ["genie-agents/concepts"]),
        ("the Agent mode APIs are still Beta", "Beta", ["api:genie/v1/agent-mode-create-response"]),
    ],
    "Agent Runtime and Memory": [
        ("Managed sessions and long-term memory, stored in Lakebase and usable from any framework, are in Beta",
         "Beta", MEMORY),
        ("Memory and sessions (Beta)", "Beta", MEMORY),
        ("Managed memory and sessions are in Beta", "Beta", MEMORY),
    ],
    "Apache Iceberg": [("Managed Iceberg tables went GA", "GA", ["iceberg/"])],
    "Apps": [
        ("App Spaces for enterprise app governance (Beta)", "Beta", APP_SPACES),
        ("Serverless Micro Apps for lightweight, scale-to-zero deployment (Private Preview)", "Private Preview", None),
        ("App Spaces (Beta)", "Beta", APP_SPACES),
        ("Serverless Micro Apps (Private Preview)", "Private Preview", None),
    ],
    "Document Intelligence": [
        ("ai_decide (Beta)", "Beta", AI_DECIDE),
        ("ai_decide is in Beta", "Beta", AI_DECIDE),
        ("call the generally available REST APIs", "GA", IDP),
        ("The REST APIs for parsing, extraction and classification are generally available", "GA", IDP),
    ],
    "Genie Agents": [
        ("files in Unity Catalog volumes (Beta)", "Beta", GENIE_VOLUMES),
        ("Files in volumes (Beta)", "Beta", GENIE_VOLUMES),
        ("Analyzing files in volumes is in Beta", "Beta", GENIE_VOLUMES),
    ],
    "Lakebase": [("generally available on AWS and Azure", "GA", ["oltp/projects/lakebase-search"])],
    "Lakehouse": [("powered by the new Reyden engine (Beta)", "Beta", ["compute/sql-warehouse/real-time/"])],
    "Omnigent OSS": [("A managed Beta is available", "Beta", ["omnigent/"])],
    "Streaming": [
        ("Real-Time Mode, generally available", "GA", REAL_TIME_MODE),
        ("Real-Time Mode is generally available", "GA", REAL_TIME_MODE),
    ],
    "Teams & M365 Copilot": [("The Genie app for Teams is in Public Preview", "Public Preview",
                              ["integrations/msft-teams"])],
    "Unity Gateway": [("service policies and other beta capabilities", "Beta",
                       ["data-governance/unity-catalog/service-policies/"])],
}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.h1, self.crumbs, self.notices = "", [], []
        self._state, self._skip, self._in_h1 = "pre", 0, False
        self._box, self._depth, self._crumb = None, 0, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag in ("script", "style", "svg"):
            self._skip += 1
            return
        if "breadcrumbs__link" in cls and self._crumb is None:
            self._crumb = [a.get("href") or "", []]
        if tag == "h1" and self._state == "pre":
            self._state, self._in_h1 = "top", True
            return
        if self._state != "top":
            return
        if tag == "h2" and "ms--in-this-article" not in (a.get("id") or ""):
            self._state = "body"
            return
        if tag == "div":
            if self._box is not None:
                self._depth += 1
            elif "theme-admonition" in cls or set(cls.split()) & LEARN_BOXES:
                self._box, self._depth = [], 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg"):
            self._skip = max(0, self._skip - 1)
            return
        if tag == "h1":
            self._in_h1 = False
        if self._crumb is not None and tag in ("a", "span"):
            self.crumbs.append((squash(" ".join(self._crumb[1])), self._crumb[0]))
            self._crumb = None
        if tag == "div" and self._box is not None:
            self._depth -= 1
            if not self._depth:
                self.notices.append(squash(" ".join(self._box)))
                self._box = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_h1:
            self.h1 += data
        if self._crumb is not None:
            self._crumb[1].append(data)
        if self._box is not None:
            self._box.append(data)


def squash(s):
    return re.sub(r"\s+", " ", s or "").strip()


def parse(page_html):
    p = Page()
    p.feed(page_html)
    p.close()
    return p


def notice_stage(page):
    for text in page.notices:
        m = NOTICE.search(text)
        if m:
            return CANON[m.group(1).lower()]
    return "GA"


def status_of(cell):
    c = squash(cell)
    if c.lower().startswith("not available"):
        return "Coming soon"
    s = CANON.get(c.lower())
    if not s:
        raise ValueError(f"unknown capability status {c!r}")
    return s


def capability_stage(page_html):
    for rows in sr.tables_of(page_html):
        head = [squash(c).lower() for c in rows[0]]
        if "capability" in head and "status" in head:
            i = head.index("status")
            found = [status_of(r[i]) for r in rows[1:] if len(r) > i and squash(r[i])]
            if found:
                return min(found, key=LADDER.index)
    raise ValueError("no Capability | Status table on the page")


def api_stage(page_html):
    marks = [CANON.get(m.replace("-", " ")) for m in API_MARK.findall(page_html)]
    marks = [m for m in marks if m]
    return min(marks, key=LADDER.index) if marks else "GA"


def landing_crumb(page):
    for i in range(1, len(page.crumbs)):
        if page.crumbs[i - 1][0].lower().endswith("connectors"):
            return page.crumbs[i]
    return None


def is_connector_landing(page):
    crumb = landing_crumb(page)
    return bool(crumb) and not crumb[1] and bool(re.search(r"\bconnector\b", page.h1, re.I))


def index_links(page_html):
    i = page_html.find("<h1")
    out = []
    for path, text in INDEX_LINK.findall(page_html[i if i >= 0 else 0:]):
        out.append((path, squash(html.unescape(re.sub(r"<[^>]+>", " ", text)))))
    return out


_PAGES = {}


def get(url):
    if url in _PAGES:
        return _PAGES[url]
    body = None
    for attempt in range(3):
        try:
            body = sr.fetch(url)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            if attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
        time.sleep(2 * (attempt + 1))
    _PAGES[url] = body
    return body


def prefetch(urls):
    with concurrent.futures.ThreadPoolExecutor(12) as ex:
        list(ex.map(get, sorted(set(urls))))


def node_json(script):
    r = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("node failed: " + r.stderr.strip()[-400:])
    return json.loads(r.stdout)


def board_arch():
    return node_json("const fs=require('fs');const {evalObject}=require('./tools/lib_extract.js');"
                     "process.stdout.write(JSON.stringify(evalObject(fs.readFileSync('app/index.html','utf8'),"
                     "'const ARCH = {')));")


def staged_tiles(arch):
    out = {}

    def walk(node):
        if isinstance(node, list):
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            if isinstance(node.get("n"), str) and isinstance(node.get("st"), str) and node["n"] not in out:
                out[node["n"]] = {"st": node["st"], "stByCloud": node.get("stByCloud") or {}}
            for v in node.values():
                walk(v)

    walk(arch)
    return out


def product_stages(staged, links):
    documented = {n: links[n]["doc"] for n in staged if (links.get(n) or {}).get("doc")}
    prefetch(DOCS[c] + p for p in documented.values() for c in CLOUDS)
    products, missing = {}, {}
    for name in sorted(documented):
        by_cloud = {}
        for c in CLOUDS:
            page_html = get(DOCS[c] + documented[name])
            if page_html is None:
                by_cloud[c] = "Coming soon"
                missing.setdefault(name, []).append(c)
            elif name in CAPABILITY_TABLES:
                by_cloud[c] = capability_stage(page_html)
            else:
                by_cloud[c] = notice_stage(parse(page_html))
        if len(missing.get(name, [])) == len(CLOUDS):
            raise SystemExit(f"{name}: its docs page {documented[name]} is missing on every cloud")
        products[name] = by_cloud
    undocumented = sorted(n for n in staged if n not in documented)
    return products, missing, undocumented


def discover_connectors():
    found = {}
    for idx in CONNECTOR_INDEXES:
        page_html = get(DOCS["aws"] + LC + idx)
        if page_html is None:
            raise SystemExit(f"connector index {LC + idx} is gone — doc layout changed")
        for path, text in index_links(page_html):
            if path not in found or (text and not found[path]):
                found[path] = text
    prefetch(DOCS["aws"] + p for p in found)
    landings = {}
    for path, text in found.items():
        page_html = get(DOCS["aws"] + path)
        if page_html is None:
            continue
        page = parse(page_html)
        crumb = landing_crumb(page)
        if not crumb:
            continue
        if is_connector_landing(page):
            landings[path] = text or crumb[0]
        elif crumb[1]:
            landing = crumb[1].split("/aws/en/", 1)[-1].strip("/")
            landings.setdefault(landing, "")
    unnamed = [p for p, n in landings.items() if not n]
    prefetch(DOCS["aws"] + p for p in unnamed)
    for path in unnamed:
        page_html = get(DOCS["aws"] + path)
        page = parse(page_html) if page_html else None
        if page is None or not is_connector_landing(page):
            del landings[path]
        else:
            landings[path] = landing_crumb(page)[0]
    return landings


def connector_catalog(platdocs):
    curated = {c["p"].strip("/"): c["n"] for c in platdocs["connectors"]}
    discovered = discover_connectors()
    names = dict(curated)
    for path, name in discovered.items():
        names.setdefault(path, name)
    prefetch(DOCS[c] + p for p in names for c in CLOUDS)
    out, added, dropped = [], [], []
    for path, name in names.items():
        by_cloud = {}
        for c in CLOUDS:
            page_html = get(DOCS[c] + path)
            by_cloud[c] = "Coming soon" if page_html is None else notice_stage(parse(page_html))
        if all(v == "Coming soon" for v in by_cloud.values()):
            dropped.append(name)
            continue
        aws_page = get(DOCS["aws"] + path)
        if aws_page is not None and not is_connector_landing(parse(aws_page)):
            raise SystemExit(f"{name}: {path} is not a connector landing page — doc layout changed")
        entry = {"n": name, "p": path, "st": by_cloud["aws"]}
        diff = {c: v for c, v in by_cloud.items() if v != by_cloud["aws"]}
        if diff:
            entry["stByCloud"] = diff
        out.append(entry)
        if path not in curated:
            added.append(name)
    out.sort(key=lambda e: (e["n"].casefold(), e["p"]))
    return out, sorted(added), sorted(dropped)


def claim_refs():
    return sorted({r for frags in CLAIMS.values() for _, _, refs in frags for r in (refs or [])})


def claim_url(ref):
    return API + ref[4:] if ref.startswith("api:") else DOCS["aws"] + ref


def claim_results():
    refs = claim_refs()
    prefetch(claim_url(r) for r in refs)
    seen = {}
    for r in refs:
        page_html = get(claim_url(r))
        if page_html is None:
            seen[r] = "missing"
        elif r.startswith("api:"):
            seen[r] = api_stage(page_html)
        else:
            seen[r] = notice_stage(parse(page_html))
    return seen


def prose_hits(text):
    for m in PROSE_WORD.finditer(text):
        if m.group(2):
            if m.group(2) == "GA":
                yield m.start(), "GA"
        else:
            yield m.start(), CANON[m.group(1).lower()]


def registry_problems():
    bad = []
    for owner, frags in CLAIMS.items():
        for frag, stage, refs in frags:
            said = {s for _, s in prose_hits(frag)}
            if said != {stage}:
                bad.append(f"CLAIMS[{owner!r}] phrase {frag!r} states {sorted(said)}, registered as {stage}")
            if refs is None and stage != "Private Preview":
                bad.append(f"CLAIMS[{owner!r}] phrase {frag!r} has no docs page but is not a Private Preview")
    return bad


def collect_prose(arch, yamls, links):
    found = []

    def add(owner, where, text):
        if any(True for _ in prose_hits(text)):
            found.append((owner or "", where, text))

    def walk(node, owner, where):
        if isinstance(node, list):
            for x in node:
                walk(x, owner, where)
            return
        if not isinstance(node, dict):
            return
        me = node.get("n") if isinstance(node.get("n"), str) else node.get("name") if isinstance(node.get("name"), str) else owner
        for k, v in node.items():
            if k in PROSE_SKIP:
                continue
            if isinstance(v, str):
                add(me, where, v)
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, str):
                        add(me, where, x)
                walk(v, me, where)
            elif isinstance(v, dict):
                walk(v, me, where)

    walk(arch, None, "index.html")
    for name, doc in sorted(yamls.items()):
        walk(doc, None, name)
    for owner, entry in links.items():
        if isinstance(entry, dict) and isinstance(entry.get("note"), str):
            add(owner, "links.json", entry["note"])
    return found


def load_yamls():
    import yaml
    out = {}
    for path in sorted(glob.glob(os.path.join(ARCHITECTURES, "*.yaml"))):
        with open(path, encoding="utf-8") as f:
            out[os.path.basename(path)] = yaml.safe_load(f)
    return out


def claim_verdict(owner, stage, at, text, data, staged):
    for frag, frag_stage, refs in CLAIMS.get(owner, []):
        i = text.find(frag)
        while i >= 0:
            if i <= at < i + len(frag):
                if frag_stage != stage:
                    return False, f"its registered phrase is {frag_stage}", frag
                if refs is None:
                    return stage == "Private Preview", "no public docs page", frag
                seen = data.get("claims") or {}
                bad = {r: seen.get(r, "not scraped") for r in refs if seen.get(r) != stage}
                return not bad, ", ".join(f"{r} reads {v}" for r, v in bad.items()) or "matches its docs pages", frag
            i = text.find(frag, i + 1)
    prod = data["products"].get(owner)
    if prod:
        return prod["aws"] == stage, f"its docs page reads {prod['aws']}", None
    if owner in data["undocumented"]:
        st = (staged.get(owner) or {}).get("st")
        return st == stage, f"the board marks it {st}", None
    return False, "no docs page backs it; register the phrase in CLAIMS", None


def prose_problems(texts, data, staged):
    bad, used = {}, set()
    for owner, where, text in texts:
        for at, stage in prose_hits(text):
            ok, why, frag = claim_verdict(owner, stage, at, text, data, staged)
            if frag:
                used.add((owner, frag))
            if not ok:
                hit = bad.setdefault((owner, stage, why), [set(), []])
                hit[0].add(where)
                snip = squash(text[max(0, at - 50): at + 25])
                if snip not in hit[1]:
                    hit[1].append(snip)
    out = [f"{o or '(no box)'} says {s} in {', '.join(sorted(w)[:3])}{' and more' if len(w) > 3 else ''}"
           f" ({len(snips)} place{'s' if len(snips) > 1 else ''}: "
           + "; ".join(f'"...{x}..."' for x in snips[:2]) + f"): {why}"
           for (o, s, why), (w, snips) in sorted(bad.items())]
    for owner, frags in CLAIMS.items():
        for frag, _, _ in frags:
            if (owner, frag) not in used:
                out.append(f"CLAIMS[{owner!r}] phrase {frag!r} backs no prose any more; remove or update it")
    return registry_problems() + out


def dump_stages(data):
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)


def dump_platdocs(data):
    return json.dumps(data, ensure_ascii=False, indent=0)


def build():
    with open(LINKS, encoding="utf-8") as f:
        links = json.load(f)
    with open(PLATDOCS, encoding="utf-8") as f:
        platdocs = json.load(f)
    arch = board_arch()
    staged = staged_tiles(arch)
    products, missing, undocumented = product_stages(staged, links)
    connectors, added, dropped = connector_catalog(platdocs)
    data = {
        "generated": datetime.date.today().isoformat(),
        "source": SOURCE,
        "products": products,
        "missing": missing,
        "undocumented": undocumented,
        "claims": claim_results(),
    }
    if not products or not connectors:
        raise SystemExit("no box or connector stage scraped — doc layout changed")
    if all(v == "GA" for p in products.values() for v in p.values()):
        raise SystemExit("every box reads GA — the preview notices are no longer detected, doc layout changed")
    if all(c["st"] == "GA" and not c.get("stByCloud") for c in connectors):
        raise SystemExit("every connector reads GA — the preview notices are no longer detected, doc layout changed")
    new_platdocs = dict(platdocs)
    new_platdocs["connectors"] = connectors
    problems = prose_problems(collect_prose(arch, load_yamls(), links), data, staged)
    for name in sorted(products):
        sys.stderr.write(f"{name}: " + ", ".join(f"{c} {products[name][c]}" for c in CLOUDS) + "\n")
    sys.stderr.write(f"{len(products)} boxes from docs, {len(undocumented)} without a docs page "
                     f"({', '.join(undocumented)}); {len(connectors)} connectors"
                     f"{'; new: ' + ', '.join(added) if added else ''}"
                     f"{'; gone from docs: ' + ', '.join(dropped) if dropped else ''}\n")
    return data, new_platdocs, problems


def main():
    ap = argparse.ArgumentParser(description="Read every board feature's release stage (GA, Public Preview, Beta, "
                                             "Private Preview, Coming soon) from the public Databricks docs into "
                                             "app/resources/stages.json, refresh the Lakeflow Connect connector "
                                             "catalog and its stages in platform_docs.json, and check every stage "
                                             "the board's prose states against its docs page.")
    ap.add_argument("--check", action="store_true", help="scrape and diff against the committed files; exit 1 on drift")
    args = ap.parse_args()
    data, platdocs, problems = build()
    new_stages, new_platdocs = dump_stages(data), dump_platdocs(platdocs)
    if args.check:
        def strip_date(s):
            return re.sub(r'"generated":\s*"[^"]*"', '"generated":""', s)
        old_stages = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        old_platdocs = open(PLATDOCS, encoding="utf-8").read()
        stale = [n for n, old, new in (("stages.json", strip_date(old_stages), strip_date(new_stages)),
                                       ("platform_docs.json", old_platdocs, new_platdocs)) if old != new]
        for n in stale:
            sys.stderr.write(f"{n} is stale — re-run tools/scrape_stages.py\n")
        for p in problems:
            sys.stderr.write(f"stage claim: {p}\n")
        if stale or problems:
            sys.exit(1)
        sys.stderr.write("stages.json and platform_docs.json up to date; every prose stage claim matches its docs\n")
        return
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(new_stages)
    with open(PLATDOCS, "w", encoding="utf-8") as f:
        f.write(new_platdocs)
    sys.stderr.write(f"wrote {OUT} and {PLATDOCS}\n")
    for p in problems:
        sys.stderr.write(f"stage claim: {p}\n")
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
