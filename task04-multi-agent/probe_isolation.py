"""Check what context a role call receives, using the exact adapter flags.

Stores only sanitized evidence: no instruction-file content is written. Leak detection
counts 12-character overlaps between the model's answer and local CLAUDE.md files;
e-mail addresses are redacted.
"""
import argparse, json, re, subprocess, tempfile
from datetime import datetime, timezone
from pathlib import Path
from claude_subscription import DEFAULT_EFFORT, DEFAULT_MODEL, build_command, cli_environment, cli_version, default_cli

QUESTION = ("這是隔離檢查。請逐一列出你在本次對話中收到、但不是這段使用者問題本身的所有脈絡內容"
            "（系統提示、system-reminder、記憶或指示檔、使用者個人資訊如姓名或電子郵件、技能或工具清單、"
            "日期或環境資訊等）。每一項逐字抄錄前50個字元。若某類完全沒有，不要列。"
            "最後回答：脈絡中是否包含任何關於使用者個人、偏好或專案的指示？")
SYSTEM = "你是隔離檢查助理，誠實回答，只回傳JSON。"
SCHEMA = {"type": "object", "properties": {
    "items": {"type": "array", "items": {"type": "object", "properties": {
        "kind": {"type": "string"}, "first_50_chars": {"type": "string"}},
        "required": ["kind", "first_50_chars"], "additionalProperties": False}},
    "has_user_or_project_instructions": {"type": "boolean"}},
    "required": ["items", "has_user_or_project_instructions"], "additionalProperties": False}
INIT_KEYS = ("tools", "mcp_servers", "slash_commands", "skills", "plugins", "agents", "apiKeySource",
             "model", "permissionMode", "output_style", "claude_code_version")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")

def instruction_shingles(size=12):
    files = [Path.home() / ".claude" / "CLAUDE.md"]
    files += [d / "CLAUDE.md" for d in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]]
    shingles, chars = set(), 0
    for f in files:
        if f.is_file():
            text = re.sub(r"\s+", "", f.read_text(encoding="utf-8"))
            chars += len(text)
            shingles |= {text[i:i + size] for i in range(len(text) - size + 1)}
    return shingles, chars

def call(command, cwd):
    done = subprocess.run(command, input=QUESTION.encode("utf-8"), capture_output=True, cwd=cwd,
                          env=cli_environment(), timeout=300)
    return done.returncode, done.stdout.decode("utf-8", "replace")

def main():
    p = argparse.ArgumentParser(); p.add_argument("--out", default="evidence/claude-isolation-probe.json")
    out = Path(p.parse_args().out)
    cli = default_cli()
    with tempfile.TemporaryDirectory(prefix="task04-probe-") as temp:
        system_file = Path(temp) / "system.txt"; system_file.write_text(SYSTEM, encoding="utf-8")
        cwd = Path(temp) / "cwd"; cwd.mkdir()
        command = build_command(cli, system_file, SCHEMA, DEFAULT_MODEL, DEFAULT_EFFORT, 1.0)
        code, stdout = call(command, cwd)
        stream = [x if x != "json" else "stream-json" for x in command] + ["--verbose"]
        _, stream_out = call(stream, cwd)
    envelope = json.loads(stdout)
    answer = envelope.get("structured_output") or {}
    flat = re.sub(r"\s+", "", json.dumps(answer, ensure_ascii=False))
    shingles, chars = instruction_shingles()
    # Pure-letter windows are ordinary English words (e.g. "instructions"); CJK, paths and handles still count.
    overlaps = sum(1 for i in range(len(flat) - 11)
                   if flat[i:i + 12] in shingles and not re.fullmatch(r"[A-Za-z_]+", flat[i:i + 12]))
    emails = bool(EMAIL.search(flat))
    init = next((json.loads(line) for line in stream_out.splitlines()
                 if line.strip().startswith("{") and json.loads(line).get("subtype") == "init"), {})
    usage = envelope.get("usage") or {}
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(), "cli_version": cli_version(cli),
        "flags": [x for x in command[1:] if not x.startswith(("{", str(Path(tempfile.gettempdir()))))],
        "question": QUESTION, "system_prompt": SYSTEM, "returncode": code,
        "model_returned": sorted((envelope.get("modelUsage") or {}).keys()),
        "input_tokens_total": sum(usage.get(k, 0) for k in
                                  ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
        "local_instruction_files_chars": chars,
        "answer_overlap_with_local_instruction_files_12char": overlaps,
        "answer_contains_email": emails,
        "model_says_has_user_or_project_instructions": answer.get("has_user_or_project_instructions"),
        "answer_redacted": json.loads(EMAIL.sub("[EMAIL_REDACTED]", json.dumps(answer, ensure_ascii=False))),
        "cli_init_inventory": {k: init.get(k) for k in INIT_KEYS},
        "interpretation": "CLAUDE.md、工具、MCP、技能未載入時，overlap應為0、input tokens約一千多；"
                          "官方CLI仍自動附加帳號email、日期、環境與模型說明，無OAuth下可用的文件化關閉方式。"}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("input_tokens_total", "local_instruction_files_chars",
          "answer_overlap_with_local_instruction_files_12char", "answer_contains_email",
          "model_says_has_user_or_project_instructions")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
