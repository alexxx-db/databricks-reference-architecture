#!/usr/bin/env python3
"""Region-data gate for app/resources/regions.json.

Verifies the file the Region menu and drawer read is internally consistent and
matches the runtime resolver in app/index.html:

  * structure: every cloud has a non-empty regions[] (code+loc) and a features{}
    map whose columns are {region_code: bool} over that cloud's region codes;
  * alias parity: every ALIAS value resolves to a real feature column on at least
    one cloud by the SAME case-insensitive substring rule regionFeatureLabel()
    uses, so no alias silently maps to nothing (which would look "available
    everywhere" and hide a real regional limit);
  * product parity: every ALIAS key is a real Databricks product tile in
    links.json (an entry carrying a `doc` path or a product `site`), so the map
    cannot drift to a product the board does not draw;
  * product pages: every "<product> (product page)" column carries the doc page it
    was read from (feature_sources, Databricks docs hosts only), and a product's
    page-sourced column lists at least one region on some cloud;
  * a limited feature actually excludes at least one region (else the alias is
    pointless and should be dropped).

With --live it also HEAD-checks the source doc pages, product pages included, so a
doc-side move is caught.
Exit code is non-zero on any failure so it chains in a gate pipeline.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scrape_regions

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGIONS = os.path.join(ROOT, "app", "resources", "regions.json")
LINKS = os.path.join(ROOT, "app", "resources", "links.json")
PAGE_SUFFIX = " (product page)"
DOC_HOSTS = {"docs.databricks.com", "learn.microsoft.com"}


def feature_label(features, want):
    w = want.lower()
    return (next((lab for lab in features if lab.lower().startswith(w)), None)
            or next((lab for lab in features if w in lab.lower()), None))


def unowned(features, alias, part_of):
    owned = {feature_label(features, want) for want in alias.values()}
    return sorted(lab for lab in features
                  if lab not in owned and not any(lab.lower().startswith(p.lower()) for p in part_of))


def check_url(u):
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(u, method=method,
                                         headers={"User-Agent": "regiongate/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return (200 <= r.status < 400, r.status)
        except urllib.error.HTTPError as e:
            if e.code in (403, 405, 429) and method == "HEAD":
                continue
            return (False, e.code)
        except Exception as e:
            return (False, str(e)[:60])
    return (False, "no-response")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="also HEAD-check the source doc pages")
    args = ap.parse_args()

    d = json.load(open(REGIONS))
    links = json.load(open(LINKS))
    fails, warns = [], []

    clouds = d.get("clouds") or {}
    if set(clouds) != {"aws", "azure", "gcp"}:
        fails.append(f"clouds must be exactly aws/azure/gcp, got {sorted(clouds)}")

    for cl, cv in clouds.items():
        regions = cv.get("regions") or []
        codes = {r.get("code") for r in regions}
        if not regions:
            fails.append(f"{cl}: no supported regions")
        for r in regions:
            if not r.get("code") or not r.get("loc"):
                fails.append(f"{cl}: region missing code/loc: {r}")
        feats = cv.get("features") or {}
        for lab, col in feats.items():
            if not isinstance(col, dict) or not col:
                fails.append(f"{cl}: feature '{lab}' has no per-region map")
                continue
            stray = set(col) - codes
            if stray:
                fails.append(f"{cl}: feature '{lab}' references unknown regions {sorted(stray)}")
            if all(bool(v) for v in col.values()):
                warns.append(f"{cl}: feature '{lab}' excludes no region (alias would be a no-op)")

    for cl, cv in clouds.items():
        feats = cv.get("features") or {}
        for lab, url in (cv.get("feature_sources") or {}).items():
            if lab not in feats:
                fails.append(f"{cl}: feature source '{lab}' names no feature column")
            host = urllib.parse.urlsplit(url or "").hostname or ""
            if not (url or "").startswith("https://") or host not in DOC_HOSTS:
                fails.append(f"{cl}: feature source for '{lab}' is not a Databricks docs page: {url}")
        for lab in feats:
            if lab.endswith(PAGE_SUFFIX) and lab not in (cv.get("feature_sources") or {}):
                fails.append(f"{cl}: product-page column '{lab}' has no source page")

    alias = d.get("alias") or {}
    if not alias:
        fails.append("alias map is empty")
    for prod, want in alias.items():
        L = links.get(prod)
        if not (isinstance(L, dict) and (L.get("doc") or L.get("site"))):
            fails.append(f"alias key '{prod}' is not a Databricks product tile in links.json")
        if want.endswith(PAGE_SUFFIX) and not any(
                any((cv.get("features") or {}).get(want, {}).values()) for cv in clouds.values()):
            fails.append(f"alias '{prod}' -> '{want}' lists no region on any cloud")
        hits = [cl for cl, cv in clouds.items()
                if feature_label(cv.get("features") or {}, want)]
        if not hits:
            fails.append(f"alias '{prod}' -> '{want}' resolves to NO feature column on any cloud")

    part_of = scrape_regions.PART_OF
    for cl, cv in clouds.items():
        for lab in unowned(cv.get("features") or {}, alias, part_of):
            fails.append(f"{cl}: limited column '{lab}' belongs to no board product: map it in ALIAS or "
                         f"record in PART_OF why it has no box of its own")
    for p in part_of:
        if not any(lab.lower().startswith(p.lower()) for cv in clouds.values() for lab in (cv.get("features") or {})):
            fails.append(f"PART_OF['{p}'] matches no limited column on any cloud any more; remove it")

    if args.live:
        for cl, src in (d.get("sources") or {}).items():
            for kind, u in src.items():
                ok, code = check_url(u)
                if not ok:
                    fails.append(f"{cl}:{kind} source dead: {u} ({code})")
        for cl, cv in clouds.items():
            for lab, u in (cv.get("feature_sources") or {}).items():
                ok, code = check_url(u)
                if not ok:
                    fails.append(f"{cl}: source page for '{lab}' dead: {u} ({code})")

    for w in warns:
        print("WARN:", w)
    if fails:
        print(f"\nREGIONGATE FAIL ({len(fails)}):")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print(f"REGIONGATE OK — {len(clouds)} clouds, "
          f"{sum(len(c.get('regions', [])) for c in clouds.values())} regions, "
          f"{len(alias)} aliases, {len(warns)} warnings")


if __name__ == "__main__":
    main()
