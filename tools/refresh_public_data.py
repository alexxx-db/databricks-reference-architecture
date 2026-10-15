#!/usr/bin/env python3
import argparse, concurrent.futures, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = ["scrape_regions.py", "scrape_stages.py", "build_certifications.py", "build_academy.py"]


def run(step, check):
    started = time.time()
    r = subprocess.run([sys.executable, os.path.join(HERE, step)] + (["--check"] if check else []),
                       capture_output=True, text=True)
    return step, r.returncode, (r.stdout + r.stderr).strip(), time.time() - started


def main():
    ap = argparse.ArgumentParser(description="Refresh everything the board reads from public Databricks pages: "
                                             "regional availability, release stages and the Lakeflow Connect "
                                             "connector catalog, certifications, and Academy courses. Run it before "
                                             "any change to the repo and commit what it changes.")
    ap.add_argument("--check", action="store_true",
                    help="report drift without writing; exit 1 if any data is stale or a prose stage claim no longer matches its docs")
    args = ap.parse_args()
    with concurrent.futures.ThreadPoolExecutor(len(STEPS)) as ex:
        done = list(ex.map(lambda step: run(step, args.check), STEPS))
    failed = []
    for step, code, out, secs in done:
        sys.stdout.write(f"== {step}{' --check' if args.check else ''} ({secs:.0f}s, exit {code})\n{out}\n\n")
        if code:
            failed.append(step)
    sys.stdout.write(("FAILED: " + ", ".join(failed)) if failed else "all public data is current")
    sys.stdout.write("\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
