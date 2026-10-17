"""Blind rater for the v8 experiment (M3): one isolated `claude -p` call, the package text on stdin.

Same isolation as the role calls (claude_subscription.ISOLATION_FLAGS, no tools, empty working directory,
whitelisted environment), so a rater reads nothing but the package: no repo, no CLAUDE.md, no answer key.
The raw reply, prompt hashes and token counts are saved next to the ratings.

usage: python blind_rate.py --package <package.md> --out <ratings.json> --raw <raw.json>
"""
import argparse, asyncio, hashlib, json, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from claude_subscription import (DEFAULT_EFFORT, DEFAULT_MODEL, ISOLATION_FLAGS, build_command, cli_version,
                                 default_cli, run_cli)
from verify_run import ISOLATION_TOKEN_CEILING, request_context_tokens

SYSTEM = "你是一位評審，第一次看到這些大綱。依使用者訊息中的指示逐份獨立評分，結果寫在 ratings，每份大綱一個物件。"
VIOLATION = {"type": "object", "properties": {k: {"type": "string"} for k in ("quote", "rule", "reason")},
             "required": ["quote", "rule", "reason"], "additionalProperties": False}
RATING = {"type": "object", "properties": {
    "label": {"type": "string"}, "click_appeal": {"type": "integer"}, "click_reason": {"type": "string"},
    "reading_value": {"type": "integer"}, "reading_reason": {"type": "string"},
    "violations": {"type": "array", "items": VIOLATION}},
    "required": ["label", "click_appeal", "click_reason", "reading_value", "reading_reason", "violations"],
    "additionalProperties": False}
SCHEMA = {"type": "object", "properties": {"ratings": {"type": "array", "items": RATING}},
          "required": ["ratings"], "additionalProperties": False}


async def rate(package_text, cli, timeout=900, budget=3.0):
    with tempfile.TemporaryDirectory(prefix="task04-rater-") as temp:
        system_file = Path(temp) / "system.txt"
        system_file.write_text(SYSTEM, encoding="utf-8")
        cwd = Path(temp) / "cwd"
        cwd.mkdir()
        command = build_command(cli, system_file, SCHEMA, DEFAULT_MODEL, DEFAULT_EFFORT, budget)
        started = time.monotonic()
        code, stdout, stderr = await asyncio.wait_for(run_cli(command, package_text, cwd), timeout)
    return code, stdout, stderr, round(time.monotonic() - started, 3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--package", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--raw", required=True)
    args = ap.parse_args()
    for path in (args.out, args.raw):
        if Path(path).exists():
            raise SystemExit(f"{path} exists; ratings are never overwritten")
    text = Path(args.package).read_text(encoding="utf-8")
    cli = default_cli()
    code, stdout, stderr, elapsed = asyncio.run(rate(text, cli))
    envelope = json.loads(stdout)
    tokens = request_context_tokens(envelope)
    raw = {"at": datetime.now(timezone.utc).isoformat(), "cli_version": cli_version(cli), "model": DEFAULT_MODEL,
           "effort": DEFAULT_EFFORT, "isolation_flags": ISOLATION_FLAGS, "system_prompt": SYSTEM,
           "package_file": Path(args.package).name, "package_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
           "returncode": code, "elapsed_seconds": elapsed, "max_request_context_tokens": tokens,
           "context_isolated": tokens < ISOLATION_TOKEN_CEILING, "response_text": stdout, "cli_stderr": stderr}
    Path(args.raw).parent.mkdir(parents=True, exist_ok=True)
    Path(args.raw).write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if code != 0 or envelope.get("is_error") or envelope.get("subtype") != "success":
        print("rater call failed; raw reply saved", file=sys.stderr)
        return 2
    ratings = envelope["structured_output"]["ratings"]
    Path(args.out).write_text(json.dumps(ratings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"ratings": len(ratings), "context_isolated": raw["context_isolated"], "tokens": tokens}))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace")
    raise SystemExit(main())
