"""Official Claude Code CLI adapter using the machine's existing subscription login.

No API key, token or credential file is read or forwarded. Each role call is an
independent `claude -p` process with the role system prompt replacing the default
one, every built-in tool disabled, and user/project CLAUDE.md, settings, MCP,
skills and slash commands switched off (see ISOLATION_FLAGS and probe_isolation.py).
"""
import asyncio
import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
import roles as default_roles
from workflow import ProviderError, TransientError, validate

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"
# Context isolation: verified by probe_isolation.py (no CLAUDE.md, tools, MCP or skills).
ISOLATION_FLAGS = ["--tools", "", "--no-session-persistence", "--safe-mode", "--setting-sources", "",
                   "--strict-mcp-config", "--disable-slash-commands"]
# Only what the CLI needs to start and find its normal login; nothing from the parent
# Claude Code session (CLAUDECODE, CLAUDE_CODE_*, messaging tokens) or any API key.
ENV_KEEP = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "USERPROFILE", "HOME",
            "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
            "PROGRAMFILES(X86)", "TEMP", "TMP", "TMPDIR", "USERNAME", "USERDOMAIN", "COMPUTERNAME",
            "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "LANG", "LC_ALL", "HTTPS_PROXY",
            "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS")
TRANSIENT_STATUS = (408, 429, 500, 502, 503, 504, 529)

def cli_environment():
    env = {k: os.environ[k] for k in ENV_KEEP if k in os.environ}
    env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"   # documented second guard besides --safe-mode
    return env

def default_cli():
    found = shutil.which("claude")
    if not found:
        raise ProviderError("Claude Code CLI not found on PATH")
    return [found]

def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def build_command(cli, system_file, schema, model, effort, budget):
    command = list(cli) + ["-p", "--output-format", "json", *ISOLATION_FLAGS,
                           "--system-prompt-file", str(system_file), "--json-schema", json.dumps(schema)]
    if model: command += ["--model", model]
    if effort: command += ["--effort", effort]
    if budget: command += ["--max-budget-usd", str(budget)]
    return command

async def terminate(proc):
    """Stop the CLI and any children; Windows has no POSIX process groups."""
    if proc.returncode is not None:
        return
    try:
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(proc.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await killer.wait()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass

async def run_cli(command, stdin_text, cwd):
    """Returns (returncode, stdout, stderr). Cancels cleanly on workflow timeout."""
    extra = {"start_new_session": True} if os.name != "nt" else {}
    proc = await asyncio.create_subprocess_exec(*command, cwd=cwd, env=cli_environment(),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **extra)
    communication = asyncio.ensure_future(proc.communicate(stdin_text.encode("utf-8")))
    try:
        stdout, stderr = await asyncio.shield(communication)
    except asyncio.CancelledError:
        await terminate(proc)
        try:
            stdout, stderr = await asyncio.wait_for(communication, 10)
        except (TimeoutError, asyncio.CancelledError):
            stdout, stderr = b"", b""
        raise CliCancelled(proc.returncode, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace"))
    return proc.returncode, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")

class CliCancelled(asyncio.CancelledError):
    def __init__(self, returncode, stdout, stderr):
        super().__init__("cancelled")
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

def classify(envelope, returncode, stderr):
    """Map CLI failure to the workflow's retry policy; usage limits are never retried."""
    if envelope is None:
        text = stderr.lower()
        if any(x in text for x in ("overloaded", "econnreset", "etimedout", "socket hang up", "network")):
            raise TransientError("Claude CLI transient failure (exit %s)" % returncode)
        raise ProviderError("Claude CLI returned no JSON (exit %s)" % returncode)
    message = str(envelope.get("result") or "")
    status = envelope.get("api_error_status")
    if "limit" in message.lower() and ("usage" in message.lower() or "reset" in message.lower()):
        raise ProviderError("Subscription usage limit reported; not retried")
    if status in TRANSIENT_STATUS or "overloaded" in message.lower():
        raise TransientError("Claude API transient error %s" % status)
    raise ProviderError("Claude CLI error: %s" % (envelope.get("subtype") or status or "unknown"))

class ClaudeDualRoleAgent:
    def __init__(self, policy, raw_log, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT, cli=None,
                 max_calls=12, budget_usd=1.0, evidence_mode="llm_runtime", roles=None):
        self.policy, self.raw_log, self.model, self.effort = policy, raw_log, model, effort
        # Prompt version: roles.py (v6) unless a run asks for another module such as roles_v7.
        self.roles = roles or default_roles
        self.cli = cli or default_cli()
        self.max_calls, self.budget_usd, self.evidence_mode = max_calls, budget_usd, evidence_mode
        self.calls = 0

    async def __call__(self, role, state):
        if self.calls >= self.max_calls:
            raise ProviderError("CLI request limit reached")
        self.calls += 1
        messages = self.roles.build_messages(role, state, self.policy)
        system, user = messages[0]["content"], messages[1]["content"]
        schema = self.roles.output_schema(role)
        event = {"call": self.calls, "run_id": state["run_id"], "role": role, "iteration": state["iteration"],
                 "mode": self.evidence_mode, "transport": "claude_cli",
                 "started_at": datetime.now(timezone.utc).isoformat(),
                 "request": {"system_prompt": system, "system_prompt_sha256": sha256(system),
                             "user_prompt": user, "user_prompt_sha256": sha256(user), "json_schema": schema,
                             "model_requested": self.model, "effort": self.effort,
                             "isolation_flags": ISOLATION_FLAGS, "max_budget_usd": self.budget_usd}}
        started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(prefix="task04-claude-") as temp:
                system_file = Path(temp) / "system.txt"
                system_file.write_text(system, encoding="utf-8")
                cwd = Path(temp) / "cwd"   # empty: no CLAUDE.md or files reachable
                cwd.mkdir()
                command = build_command(self.cli, system_file, schema, self.model, self.effort, self.budget_usd)
                try:
                    returncode, stdout, stderr = await run_cli(command, user, cwd)
                except CliCancelled as e:
                    event.update({"error": "cancelled", "returncode": e.returncode,
                                  "response_text": e.stdout, "cli_stderr": e.stderr})
                    raise
            event.update({"returncode": returncode, "response_text": stdout, "cli_stderr": stderr})
            try:
                envelope = json.loads(stdout)
                if not isinstance(envelope, dict): envelope = None
            except ValueError:
                envelope = None
            if envelope is not None:
                event.update({"model_returned": sorted((envelope.get("modelUsage") or {}).keys()),
                              "usage": envelope.get("usage"), "duration_ms": envelope.get("duration_ms"),
                              "session_id": envelope.get("session_id"),
                              "total_cost_usd_list_estimate": envelope.get("total_cost_usd")})
            if returncode != 0 or envelope is None or envelope.get("is_error") or envelope.get("subtype") != "success":
                classify(envelope, returncode, stderr)
            value = envelope.get("structured_output")
            try:
                validate(role, value)
            except ValueError as e:
                raise ProviderError("Invalid structured output: " + str(e)) from e
            return value
        except (TransientError, ProviderError) as e:
            event["error"] = str(e)
            raise
        except OSError as e:
            event["error"] = "launch_failed: " + type(e).__name__
            raise ProviderError("Could not launch Claude CLI") from e
        finally:
            event["finished_at"] = datetime.now(timezone.utc).isoformat()
            event["elapsed_seconds"] = round(time.monotonic() - started, 3)
            self.raw_log(event)

def cli_version(cli=None):
    cli = cli or default_cli()
    done = subprocess.run(list(cli) + ["--version"], capture_output=True, text=True, encoding="utf-8",
                          env=cli_environment(), timeout=60)
    return done.stdout.strip()
