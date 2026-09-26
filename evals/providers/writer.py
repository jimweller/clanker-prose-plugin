"""promptfoo Python provider: one rewrite (config.task rewrite) or one composed paragraph
(config.task generate) from a claude -p writer holding the clanker-prose plugin.

The writer runs with --setting-sources "" and --plugin-dir from a fresh temp directory, so it sees
this plugin and nothing else from the machine. The plugin's SessionStart hook points it at
skills/prose/SKILL.md, which it loads with the Skill tool or Read. Write is allowed so the editor
puts its notes in a file rather than in the text under test. --bare is never used, because it
disables plugin hooks.

A run whose isolation failed returns {"error", "metadata"}, so promptfoo records an error row and
never grades text the writer produced under the wrong conditions. Whether the writer loaded the
contract is recorded as contract_loaded and never treated as a breach, because skipping the pointer
or the skill is plugin behavior the eval exists to measure.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import uuid
import hashlib

ALIASES = ("haiku", "sonnet", "opus", "fable")
SUITE_ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SUITE_ROOT.parent
SKILL_NAMES = ("clanker-prose:prose",)
SKILL_SUFFIX = "skills/prose/SKILL.md"
TASKS = {"rewrite": "prompts/rewrite-notes.txt", "generate": "prompts/generate-notes.txt"}
TOOLS = "Read,Skill,Write"

BASE_KEYS = ("PATH", "HOME", "USER", "LANG", "TMPDIR", "SHELL")
AUTH_KEYS = ("ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_BASE_URL", "ANTHROPIC_API_KEY",
             "AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_BEARER_TOKEN_BEDROCK")
ROUTING_KEYS = ("CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_BEDROCK", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL")

LEADING_GLYPHS = re.compile(r"^(?:[^\x00-\x7F]+\s*)+")


def check_alias(model):
    if model not in ALIASES:
        raise ValueError(f"model must be an alias ({', '.join(ALIASES)}), got {model!r}")
    return model


def read_settings_env(path):
    p = pathlib.Path(path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text()).get("env", {})


def child_env(parent, settings_env):
    env = {k: parent[k] for k in BASE_KEYS + AUTH_KEYS if k in parent}
    for k in ROUTING_KEYS:
        v = settings_env.get(k, parent.get(k))
        if v is not None:
            env[k] = v
    env["CLAUDE_CODE_PROMPT_CACHE_TTL"] = "5m"
    return env


def strip_glyph(text):
    """Port of perl -CSD -pe 'if ($. == 1) { s/^(?:[^\\x00-\\x7F]+\\s*)+// }'.

    The skill carries a STARTER_CHARACTER line, and a leading glyph belongs to the chat
    register rather than the artifact under test. Only the first line is touched, and the
    trailing \\s* can consume that line's newline, exactly as the perl original does.
    """
    first, sep, rest = text.partition("\n")
    return LEADING_GLYPHS.sub("", first + sep) + rest


def build_argv(model, plugin_root):
    return ["-p", "--setting-sources", "", "--output-format", "stream-json", "--verbose", "--include-hook-events",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--plugin-dir", str(plugin_root),
            "--tools", TOOLS, "--allowedTools", TOOLS,
            # --allowedTools is variadic, so a non-variadic flag must follow it.
            "--model", check_alias(model), "--no-session-persistence"]


def render(template, values):
    missing = [k for k in values if "{{" + k + "}}" not in template]
    if missing:
        raise ValueError(f"template has no placeholder for {', '.join(missing)}")
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)


def text_of(value):
    # TimeoutExpired carries bytes even when the process ran with text=True.
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def run_claude(argv, *, input, cwd, env, timeout_s, binary="claude"):
    try:
        p = subprocess.run([binary, *argv], input=input, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout_s)
        return p.returncode, p.stdout, p.stderr, False
    except subprocess.TimeoutExpired as e:
        return None, text_of(e.stdout), text_of(e.stderr), True


def inspect(stdout):
    init, result = None, None
    hook_events, hook_ok, calls, ok_ids = [], {}, {}, set()
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") == "system" and e.get("subtype") == "init":
            init = e
        elif e.get("type") == "system" and e.get("subtype") == "hook_response":
            hook_events.append(e.get("hook_event"))
            if e.get("exit_code") == 0:
                hook_ok[e.get("hook_event")] = hook_ok.get(e.get("hook_event"), 0) + 1
        elif e.get("type") == "assistant":
            for c in (e.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_use":
                    calls[c.get("id")] = (c.get("name"), c.get("input") or {})
        elif e.get("type") == "user":
            content = (e.get("message") or {}).get("content")
            for c in content if isinstance(content, list) else []:
                if c.get("type") == "tool_result" and not c.get("is_error"):
                    ok_ids.add(c.get("tool_use_id"))
        elif e.get("type") == "result":
            result = e
    via = None
    for tid, (name, inp) in calls.items():
        if tid not in ok_ids:
            continue
        if name == "Skill" and inp.get("skill") in SKILL_NAMES:
            via = "Skill"
            break
        if name == "Read" and str(inp.get("file_path", "")).endswith(SKILL_SUFFIX):
            via = "Read"
            break
    return init or {}, result, hook_events, hook_ok, via


def call_api(prompt, options, context, runner=None, environ=None, settings_path=None):
    config = (options or {}).get("config") or {}
    environ = os.environ if environ is None else environ
    runner = runner or run_claude
    task = config.get("task")
    meta = {"task": task}
    try:
        if task not in TASKS:
            raise ValueError(f"unknown task {task!r}, expected one of {sorted(TASKS)}")
        model = check_alias(environ.get("EVAL_MODEL") or "opus")
        argv = build_argv(model, config.get("plugin_dir", PLUGIN_ROOT))
        notes_dir = pathlib.Path(environ.get("REWRITE_NOTES_DIR") or SUITE_ROOT / "corpus" / "notes")
        # A persistent worker reuses its PID, so the name carries a random suffix.
        notes_name = f"{hashlib.sha256(prompt.encode()).hexdigest()[:12]}.{uuid.uuid4().hex[:8]}.txt"
        template = (SUITE_ROOT / TASKS[task]).read_text()
    except ValueError as e:
        return {"error": f"WRITER_ERROR: {e}", "metadata": meta}
    notes_path = notes_dir / notes_name
    meta.update({"model": model, "argv": argv, "notes_path": str(notes_path)})

    env = child_env(environ, read_settings_env(settings_path or pathlib.Path.home() / ".claude" / "settings.json"))
    # Claude Code refuses a write inside a --plugin-dir directory as a sensitive file, and
    # corpus/notes sits inside the plugin, so the editor writes to its own working
    # directory and the notes are copied out before that directory is removed.
    cwd = tempfile.mkdtemp(prefix="writer-")
    try:
        cwd_notes = pathlib.Path(cwd) / notes_name
        text = render(template, {"notes": str(cwd_notes), "input": prompt})
        code, stdout, stderr, timed_out = runner(argv, input=text, cwd=cwd, env=env,
                                                 timeout_s=int(config.get("writer_timeout_ms", 540000)) / 1000)
        if cwd_notes.is_file():
            notes_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cwd_notes, notes_path)
    except Exception as e:
        return {"error": f"WRITER_ERROR: {type(e).__name__}: {e}", "metadata": meta}
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    stdout, stderr = text_of(stdout), text_of(stderr)
    meta["stream_tail"] = stdout[-1500:]

    init, result, hook_events, hook_ok, via = inspect(stdout)
    notes = notes_path.read_text() if notes_path.is_file() else ""
    meta.update({
        "plugins": [p.get("name") for p in init.get("plugins") or []],
        "skills": init.get("skills") or [],
        "tools": init.get("tools") or [],
        "hook_events": hook_events,
        "hook_fired": hook_ok,
        "contract_loaded": via is not None,
        "contract_via": via,
        "notes": notes,
        "notes_missing": not notes_path.is_file(),
    })
    if timed_out:
        return {"error": "WRITER_ERROR: timeout", "metadata": meta}
    if code != 0:
        return {"error": f"WRITER_ERROR: exit {code}: {(stderr or '').strip()[:300]}", "metadata": meta}
    if result is None:
        return {"error": "WRITER_ERROR: no result event", "metadata": meta}
    meta["models"] = sorted((result.get("modelUsage") or {}).keys())
    meta["num_turns"] = result.get("num_turns")
    if result.get("is_error") or result.get("subtype") != "success":
        return {"error": f"WRITER_ERROR: is_error subtype={result.get('subtype')}: {str(result.get('result'))[:300]}", "metadata": meta}

    breaches = []
    if meta["plugins"] != ["clanker-prose"]:
        breaches.append(f"plugins {meta['plugins']} is not ['clanker-prose']")
    if not hook_ok.get("SessionStart"):
        breaches.append("SessionStart hook did not fire")
    if not any(s in meta["skills"] for s in SKILL_NAMES):
        breaches.append(f"prose skill missing from {meta['skills']}")
    meta["breaches"] = breaches
    if breaches:
        return {"error": "ISOLATION_BREACH: " + "; ".join(breaches), "metadata": meta}

    usage = result.get("usage") or {}
    prompt_tokens = sum(usage.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    completion = usage.get("output_tokens", 0)
    return {
        "output": strip_glyph(result.get("result") or ""),
        "cost": result.get("total_cost_usd", 0),
        "latencyMs": result.get("duration_ms"),
        "tokenUsage": {"prompt": prompt_tokens, "completion": completion, "total": prompt_tokens + completion, "numRequests": 1},
        "metadata": meta,
    }
