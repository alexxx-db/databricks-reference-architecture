# CLAUDE.md: Databricks Reference Architecture (repo guide)

Canonical repo: `databricks-industry-solutions/databricks-reference-architecture` (PUBLIC).
Live site: https://databricks-industry-solutions.github.io/databricks-reference-architecture/

This file is the authoritative engineering guide for THIS repo. Read it first.
`README.md` describes what the board is and lists the repository layout; this file holds
the rules for changing it.

---

## 1. What this is

See `README.md`. What every change here depends on:

- The static board is a single file: `app/index.html`.
- The AI variant is NOT a second board. `app/ai/app.py` serves the SAME `app/index.html`
  and injects the AI layer (`app/ai/ai.css` + `app/ai/ai.js`) at request time. There is
  only ONE board file to edit; a fix in `app/index.html` reaches the AI app automatically.

## 2. Layout

The full tree is in `README.md` under "Repository layout". Two files it does not list:

- `app/version.json`: `{ "build": "<semver>" }` for cache-busting. It moves with `const BUILD`
  in `app/index.html` (§3, rule 4).
- `index.html` (repo root): a cache-busting redirect to `app/index.html`; with `.nojekyll`
  this is what GitHub Pages serves at the site root.

## 3. HARD rules

1. **Databricks Serverless-safe only.** No `cache`/`persist`/`uncache`, no `SparkContext`,
   nothing that assumes a classic cluster. Any notebook/py here must run on Serverless.
2. **No code comments and no stray docs.** Do not add comments to code and do not create
   `.md`/`.txt` files for changes unless explicitly asked. (This `CLAUDE.md` was explicitly
   requested.)
3. **DRY.** Search before writing. Two implementations of one concept is a bug. The AI app
   reuses the shared board for exactly this reason, so do not re-fork it.
4. **Single-digit semver.** Every segment is one digit 0-9; at 9 it rolls to 0 and carries
   left (… v0.4.9 → v0.5.0 … v0.9.9 → v1.0.0). `app/version.json` and the `const BUILD` in
   `app/index.html` move together.
5. **SCHEMA bump on persisted-board content changes.** The board persists to `localStorage`
   keyed by `const SCHEMA = N;`. A returning browser ignores new baked-in content until
   `SCHEMA` changes. If you change anything baked into a persisted board (platform
   bands/rails, top band, cloud band, consumers, or any industry YAML that renders into
   them), bump `SCHEMA` by 1 in `app/index.html`. `SCHEMA` is a plain counter, NOT the
   semver. Pure CSS / render-logic / i18n-corpus changes do not need a bump.
   Verify: `grep -n "const SCHEMA" app/index.html`.
6. **Refresh public data before any change.** Before you edit anything in this repo, run
   `python3 tools/refresh_public_data.py`. It re-reads everything the board takes from public
   Databricks pages (regional availability, release stages, the Lakeflow Connect connector
   catalog, certifications, Academy courses) and rewrites the data files; commit what it
   changes with your work. It exits non-zero when a refresher fails or when the board's prose
   states a stage its docs no longer show. Fix that before you continue (§5).
7. **Write for the reader, who may be a customer.** The board, its tour, the exports, the
   README and anything written about them are read by customers. Speak to the reader ("you",
   "your team", "a meeting"), never about them as someone being sold to: no selling verbs, no
   field jargon, no meeting or design named after the customer. "Databricks customer stories"
   and an industry's own customers are fine. `linkgate` fails on the phrases in
   `SELLER_PHRASES` in any tracked file.

## 4. Links policy

- Every clickable surface on the board links to Databricks only, enforced at render time by
  `isDatabricksUrl()` (allowlist: `databricks.com` and subdomains, the Azure Databricks docs
  on `learn.microsoft.com`, YouTube, and `github.com/databricks*`). A non-allowlisted URL is
  refused by `linkRow()`/`linksHref()`.
- The one exception is a data-format tile's `spec_url`, which links to the STANDARD body's
  own page (iso20022.org, fixtrading.org, finos.org, hl7.org, …). A standard is not a
  competitor.
- Never link to a competitor product page. Competitors live in `links.json` only as unlinked
  `.url`/`.site` fields; only the Databricks federation doc (`.dbx`) renders.
- Docs search fallback must use `…/search?q=` (not `search.html?q=`).

## 5. Regional availability and release stages

`app/resources/regions.json` is generated from two PUBLIC Databricks doc pages per cloud
(`supported-regions` + `feature-region-support`) by `tools/scrape_regions.py`, which holds
the `ALIAS` map (product name → limited-feature column). Policy is PERMISSIVE: a product is
available in ALL supported regions UNLESS the PRODUCT ITSELF is published as region-limited
in public docs. If a limit applies only to a sub-capability, relax it (drop the alias →
all regions). Never show a restriction that public docs do not publish for the product.
When a product's own doc page publishes its region list (`PRODUCT_PAGES` in the scraper,
today Lakebase and Genie App Builder), that list is the source and wins over the feature
table; a cloud the page does not list reads "Not yet available".
The "Available in N of M regions" line links to its exact source doc.

`app/resources/stages.json` holds every board box's release stage per cloud, read by
`tools/scrape_stages.py` from the notice at the top of the box's own docs page (the `links.json`
`doc` path): "This feature is in Beta / Public Preview / Private Preview", linked or not. A page
without that notice is GA. A box whose page does not exist on a cloud is "Coming soon" there,
and its `links.json` `docClouds` must list exactly the clouds that have the page. LTAP reads its
"Capability | Status" table: the least mature capability wins, and "Not available" is "Coming
soon". A box with no public docs page (`undocumented`) keeps the stage typed on the board. On the
board, `stageFor` shows the docs stage for every box that carries a typed `st`/`stByCloud` and
falls back to the typed value; a box without a typed stage never takes one from the docs, even
when it shares a product's name. Keep the typed values in step when you touch a box. The same
scraper refreshes the Lakeflow Connect connector
catalog in `platform_docs.json`: it adds connectors the docs list, drops connectors whose page is
gone, and records each connector's stage per cloud.
Stage words in prose (descriptions, capability tags, notes, industry YAML) are claims. A claim
about a box's own stage must match its docs stage; any other claim must be a phrase registered
in `CLAIMS` in the scraper, with the docs pages that back it. Prefer no stage in prose: the badge
already shows it.

## 6. Gates: run before every PR

```bash
python3 tools/refresh_public_data.py --check # regions, release stages, connectors, certifications, Academy: no drift, every prose stage claim backed by docs
python3 tools/regiongate.py --live          # region data consistent + alias parity + source docs live
node   tools/verify_all_sections.js         # 70 industries + the generic board, uc/genie/dash/app = 10/4/4/4, the deck's editable appendix builds, 0 page errors
node   tools/verify_i18n_coverage.js        # translation coverage over the DATA corpus
python3 tools/linkgate.py                    # structural completeness, retired names, seller phrasing (add --urls for live link check)
python3 tools/heightgate.py                  # layout / no clipping
node   tools/perfgate.js                     # motion rests at idle, reduced motion honoured, boot fetches once and in parallel
node   tools/verify_exports.js               # deck with its editable appendix + PDF, the four drawing-app exports (shape parity, structure, links; --live also opens them in draw.io, excalidraw.com, LibreOffice), and the HTML export (every boot resource frozen, opens offline)
node   tools/smoke_yaml.js                   # YAML descriptor round trip; edited, AI and imported tabs export what is on screen
node   tools/smoke_share.js                  # share links and the address bar: every option in the URL, a copied link reopens the same board
python3 tools/test_certifications.py         # certification builder + gate, offline: catalog drift, exam-guide evidence, mapping integrity
python3 tools/test_linkgate.py               # linkgate file checks, offline: retired name, archived repo, owner-pending exemptions
python3 tools/test_regions.py                # region scraper + gate, offline: product-page lists, source pages, mapping integrity
node   tools/smoke_regions.js                # every cloud's availability line matches its source and links to it; the AI assistant pointer
python3 tools/test_stages.py                 # stage scraper, offline: notices, missing clouds, LTAP table, connector discovery, prose claims, data integrity
node   tools/smoke_stages.js                 # every box and connector shows its docs stage on each cloud; docs win over typed stages; undated credit
```

Local preview: `cd app && python3 -m http.server 8777` then open
`http://localhost:8777/index.html`.

## 7. Fork + PR workflow (HARD)

- `origin`: your fork of the canonical repo. Push all day-to-day work there.
- `upstream`: fetch from `https://github.com/databricks-industry-solutions/databricks-reference-architecture.git`.
  Disable its push URL so `git push upstream` fails by design:
  `git remote set-url --push upstream DISABLED-use-a-PR`.
- The old `amralieg/interactive-databricks-enterprise-architecture` repo is ARCHIVED; do not use it.

Anything landing on the canonical repo goes through a PULL REQUEST, never a direct push:

```bash
git fetch upstream && git checkout -b <feature> upstream/main   # branch off the canonical main
python3 tools/refresh_public_data.py                             # §3 rule 6: refresh public data first
# ...edit, bump BUILD + version.json (+ SCHEMA if persisted content changed), run §6 gates...
git push origin <feature>                                        # to your fork
gh pr create --repo databricks-industry-solutions/databricks-reference-architecture \
  --base main --head <your-github-user>:<feature>
```

Keep the branch current with the canonical repo before opening a PR:

```bash
git fetch upstream && git rebase upstream/main && git push --force-with-lease origin <feature>
```

## 8. Release process

A release is a merged PR into the canonical `main`. The data was refreshed before the change
(§3, rule 6); run `python3 tools/refresh_public_data.py` again right before the PR so the release
ships current data, and ship any change with it. Bump `const BUILD` + `app/version.json`
to the next single-digit semver (and `SCHEMA` if persisted content changed), pass all §6
gates, open the PR, and tag `vX.Y.Z` after merge. Release notes cover a summary, highlights,
per-change detail, regressions, validation, and upgrade notes. GitHub Pages redeploys
automatically from `main`.
