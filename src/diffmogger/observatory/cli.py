"""Run a local visual observatory for Diffmogger automation state."""

from __future__ import annotations

from .common import *
from .html_render import render_html
from .markdown_render import render_review_markdown, write_output_file, write_review_bundle
from .scoring import persist_recommendation_history
from .server import run_server
from .snapshots import build_snapshot

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=".", help="Target project directory to observe")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host for the local observatory server")
    parser.add_argument("--port", type=int, default=0, help="Bind port; 0 chooses a free local port")
    parser.add_argument("--open", action="store_true", help="Open the observatory URL in the default browser")
    parser.add_argument("--once", action="store_true", help="Render a standalone HTML snapshot and exit")
    parser.add_argument("--output", default="", help="Output path for --once; stdout is used when omitted")
    parser.add_argument(
        "--review-output",
        default="",
        help="Write a compact Markdown self-review report; use '-' for stdout",
    )
    parser.add_argument(
        "--review-dir",
        default="",
        help=(
            "Write first-review HTML and Markdown artifacts to this directory "
            f"as {FIRST_REVIEW_OBSERVATORY_FILENAME} and {FIRST_REVIEW_SELF_REVIEW_FILENAME}"
        ),
    )
    args = parser.parse_args(argv)
    if args.review_dir:
        if args.review_dir.strip() == "-":
            parser.error("--review-dir requires a directory path")
        if args.once or args.output or args.review_output:
            parser.error("--review-dir cannot be combined with --once, --output, or --review-output")
    if args.once and not args.output and args.review_output == "-":
        parser.error("--review-output - cannot be combined with --once unless --output is also set")

    target = Path(args.target).expanduser().resolve()
    snapshot = build_snapshot(target)
    if args.review_dir or (args.review_output and args.review_output != "-"):
        snapshot = persist_recommendation_history(target, snapshot)
    if args.review_dir:
        write_review_bundle(args.review_dir, snapshot)
        return 0
    if args.once:
        body = render_html(snapshot, live=False)
        if args.output:
            write_output_file(args.output, body, label="observatory snapshot")
        else:
            sys.stdout.write(body)
    if args.review_output:
        write_output_file(args.review_output, render_review_markdown(snapshot), label="self-review report")
    if args.once or args.review_output:
        return 0

    return run_server(target, args.host, args.port, args.open)


if __name__ == "__main__":
    raise SystemExit(main())
