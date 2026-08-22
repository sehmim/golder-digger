"""Thin CLI so the pipeline is usable without the API."""
import argparse
import json

from . import config, db, ingest, scoring


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
        print(json.dumps({"fit_floor": floor, "results": results}, indent=2))

    elif args.cmd == "serve":
        import uvicorn
        uvicorn.run("goldigger.api:app", host="127.0.0.1", port=8420)


if __name__ == "__main__":
    main()
