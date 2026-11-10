"""Record a fresh table and open the animated replay in one command.

    python -m sim.watch
    python -m sim.watch --tables 3 --lineup tight-passive --seed 7

Records the tables, writes results/replays/watch.json, serves the repo over
a local HTTP server, and opens viewer/table.html in the browser. Ctrl+C
stops the server. No network leaves the machine.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import random
import webbrowser

from sim.engine import DEFAULT_PAYOUTS
from sim.record import record

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    # the request log would drown the one line that matters
    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", type=int, default=1)
    parser.add_argument("--lineup", default="mixed")
    parser.add_argument("--seed", type=int, default=None,
                        help="omit for a fresh random table each run")
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    # a random seed by default so every watch shows new hands -- printed so a
    # table worth keeping can be re-recorded exactly
    seed = args.seed if args.seed is not None else random.randrange(1, 10**6)
    replays = record(args.tables, args.lineup, DEFAULT_PAYOUTS, seed)
    output = ROOT / "results" / "replays" / "watch.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(replays) + "\n")
    hands = sum(len(r["hands"]) for r in replays)
    server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                 partial(QuietHandler, directory=str(ROOT)))
    url = f"http://127.0.0.1:{server.server_address[1]}/viewer/table.html"
    print(f"recorded {hands} hands (seed {seed}) -> {output.relative_to(ROOT)}")
    print(f"watching at {url}  (ctrl+c to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
