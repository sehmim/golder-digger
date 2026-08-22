"""Thin CLI so the pipeline is usable without the API."""
import argparse
import csv
import json
import sys

from . import config, db, ingest, scoring


CSV_FIELDS = ["rank", "chunk_id", "path", "role", "bpm", "tonic", "is_major",
              "key_confidence", "fit", "novelty", "H", "R", "P", "distance", "fit_floor"]


def write_csv(results, floor, distance, stream=None):
    """Flatten the ranked results into one row per candidate."""
    w = csv.DictWriter(stream or sys.stdout, fieldnames=CSV_FIELDS)
    w.writeheader()
    for rank, r in enumerate(results, 1):
        w.writerow({
            "rank": rank,
            "chunk_id": r["chunk_id"],
            "path": r["path"],
            "role": r["role"] or "",
            "bpm": "" if r["bpm"] is None else r["bpm"],
            "tonic": r["tonic"] or "",
            "is_major": int(r["is_major"]),
            "key_confidence": r["key_confidence"],
            "fit": r["fit"],
            "novelty": r["novelty"],
            "H": r["components"]["H"],
            "R": r["components"]["R"],
            "P": r["components"]["P"],
            "distance": distance,
            "fit_floor": round(float(floor), 3),
        })
    print(f"fit_floor={floor:.3f}  rows={len(results)}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(prog="golddigger")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="walk a folder and extract features")
    p.add_argument("root")

    sub.add_parser("stats", help="what is in the database")

    p = sub.add_parser("analyze", help="rank candidates against a context")
    p.add_argument("context_ids", nargs="+")
    p.add_argument("--distance", type=float, default=50)
    p.add_argument("-k", type=int, default=config.DEFAULT_K)
    p.add_argument("--format", choices=["json", "csv"], default="json",
                   help="csv writes rows to stdout; fit_floor goes to stderr")

    sub.add_parser("serve", help="run the API")
    args = ap.parse_args()

    conn = db.connect()
    db.init(conn)

    if args.cmd == "ingest":
        job = ingest.new_job(conn, args.root)
        ingest.run_job(conn, job, args.root)
        print(json.dumps(dict(conn.execute(
            "SELECT * FROM jobs WHERE job_id=?", (job,)).fetchone()), indent=2))

    elif args.cmd == "stats":
        n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        print(f"mock={config.MOCK}  chunks={n}  db={config.DB_PATH}")
        for r in conn.execute("SELECT role, COUNT(*) c FROM chunks GROUP BY role ORDER BY c DESC"):
            print(f"  {r['role'] or '(none)':10s} {r['c']}")

    elif args.cmd == "analyze":
        corpus = ingest.load_corpus(conn)
        ctx = scoring.build_context(corpus, args.context_ids)
        results, floor = scoring.select(corpus, ctx, args.distance, args.k)
        if args.format == "csv":
            write_csv(results, floor, args.distance)
        else:
            print(json.dumps({"fit_floor": floor, "results": results}, indent=2))

    elif args.cmd == "serve":
        import uvicorn
        uvicorn.run("goldigger.api:app", host="127.0.0.1", port=8420)


if __name__ == "__main__":
    main()
