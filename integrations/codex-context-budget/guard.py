"""Event-driven image-context budget. Stores sizes and identifiers, never image content."""

import argparse
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent
MARKER = "codex-context-budget-v1"
EVENTS = ("PostToolUse", "UserPromptSubmit", "Stop", "PostCompact")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def session_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + 2
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Context-budget state is busy")
                time.sleep(0.02)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def policy_at(path):
    policy = read_json(path)
    required = {"schema_version", "warning_bytes", "maximum_bytes", "maximum_tool_image_bytes"}
    if set(policy) != required or policy["schema_version"] != 1:
        raise ValueError("Unsupported context-budget policy")
    values = [policy[key] for key in required - {"schema_version"}]
    if any(type(value) is not int or value <= 0 for value in values):
        raise ValueError("Budget values must be positive integer byte counts")
    if not policy["maximum_tool_image_bytes"] <= policy["warning_bytes"] < policy["maximum_bytes"]:
        raise ValueError("Require per-output maximum <= warning < maximum")
    return policy


def image_bytes(value):
    """Count native/MCP image encodings without decoding or saving their content."""
    size = 0
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            image_url = item.get("image_url")
            if isinstance(image_url, dict):
                image_url = image_url.get("url")
            if isinstance(image_url, str) and image_url.startswith("data:image/"):
                size += len(image_url)
            if item.get("type") == "image" and isinstance(item.get("data"), str):
                size += len(item["data"])
            stack.extend(child for child in item.values() if isinstance(child, (dict, list)))
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str) and item.lstrip().startswith(("{", "[")) and "image" in item:
            try:
                stack.append(json.loads(item))
            except ValueError:
                pass
    return size


def wire_size(codex_home, session_id, after_ns=0):
    """Best-effort observation of current Codex logs, separate from the hook contract."""
    database = codex_home / "logs_2.sqlite"
    if not database.is_file():
        return {"status": "unavailable", "bytes": None}
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.2)) as connection:
            row = connection.execute(
                "SELECT ts, ts_nanos, feedback_log_body FROM logs WHERE thread_id=? "
                "AND target='codex_http_client::request' "
                "AND feedback_log_body LIKE '%Compressed request body%' ORDER BY id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        if row is None or row[0] * 1_000_000_000 + row[1] <= after_ns:
            return {"status": "not_observed", "bytes": None}
        matched = re.search(r"post_compression_bytes=(\d+)", row[2])
        if matched:
            return {"status": "observed", "bytes": int(matched[1]), "at_ns": row[0] * 1_000_000_000 + row[1]}
    except (sqlite3.Error, OSError, ValueError):
        pass
    return {"status": "unavailable", "bytes": None}


def state_path(codex_home, session_id):
    identifier = hashlib.sha256(session_id.encode()).hexdigest()
    return codex_home / "context-budget" / (identifier + ".json")


def new_state(session_id):
    return {"schema_version": 1, "session_id": session_id, "estimated_bytes": 0,
            "last_compacted_at_ns": 0, "seen_tool_ids": [], "last_warning_turn": None}


def current_budget(codex_home, state):
    observation = wire_size(codex_home, state["session_id"], state["last_compacted_at_ns"])
    return max(state["estimated_bytes"], observation["bytes"] or 0), observation


def warning_message(budget, policy):
    return (f"图片上下文预算约 {budget / 1_000_000:.1f} MB，提醒阈值为 "
            f"{policy['warning_bytes'] / 1_000_000:.0f} MB。建议在当前小批次结束时保存已审图片路径、结论和未覆盖项，"
            "再从斜杠菜单选择“压缩”。当前消息可继续提交，后续按需重读原图。")


def hook(payload, codex_home, policy):
    event = payload.get("hook_event_name")
    session_id = payload.get("session_id")
    if event not in EVENTS or not isinstance(session_id, str) or not session_id:
        return {}
    if payload.get("agent_id") or payload.get("model", "").startswith("codex-auto-review"):
        return {}
    added = image_bytes(payload.get("tool_response")) if event == "PostToolUse" else 0
    if event == "PostToolUse" and not added:
        return {}
    path = state_path(codex_home, session_id)
    with session_lock(path.with_suffix(".lock")):
        state = read_json(path) if path.exists() else new_state(session_id)
        if event == "PostCompact":
            state = new_state(session_id)
            state["last_compacted_at_ns"] = time.time_ns()
            state["last_event"] = event
            write_json(path, state)
            return {}
        budget, observation = current_budget(codex_home, state)
        tool_id = payload.get("tool_use_id")
        if event == "PostToolUse" and tool_id and tool_id in state["seen_tool_ids"]:
            return {}
        projected = budget + added
        reason = None
        if added > policy["maximum_tool_image_bytes"]:
            reason = (f"本次工具返回含 {added / 1_000_000:.1f} MB 图片，单次上限为 "
                      f"{policy['maximum_tool_image_bytes'] / 1_000_000:.0f} MB。请拆分回图，或返回合适尺寸的总览及必要的原尺寸局部。")
        elif event == "PostToolUse" and projected > policy["maximum_bytes"]:
            reason = (f"本次回图会使图片上下文预算达到约 {projected / 1_000_000:.1f} MB，"
                      f"超过 {policy['maximum_bytes'] / 1_000_000:.0f} MB。请先保存检查点并从斜杠菜单选择“压缩”，再继续读取原图。")
        if reason:
            state["last_event"] = event
            state["last_blocked_at_ns"] = time.time_ns()
            state["last_blocked_bytes"] = added
            write_json(path, state)
            suffix = "本次图片尚未交给模型审阅，复核记录应保持未覆盖。"
            return {"decision": "block", "reason": reason + suffix, "systemMessage": reason}
        state["estimated_bytes"] = projected
        state["last_event"] = event
        state["last_invoked_at_ns"] = time.time_ns()
        state["wire_observation"] = observation
        if tool_id and added:
            state["seen_tool_ids"].append(tool_id)
        output = {}
        turn_id = payload.get("turn_id") or event
        if projected >= policy["warning_bytes"] and state["last_warning_turn"] is None:
            message = warning_message(projected, policy)
            state["last_warning_turn"] = turn_id
            output["systemMessage"] = message
            if event in ("PostToolUse", "UserPromptSubmit"):
                output["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": message}
        write_json(path, state)
        return output


def owned_handler(handler):
    return handler.get("statusMessage") == MARKER


def source_revision(policy_path):
    digest = hashlib.sha256(Path(__file__).read_bytes())
    digest.update(policy_path.read_bytes())
    return digest.hexdigest()


def configure_hooks(codex_home, policy_path, apply, remove=False):
    path = codex_home / "hooks.json"
    before = read_json(path) if path.exists() else {}
    after = json.loads(json.dumps(before))
    hooks = after.setdefault("hooks", {})
    command = subprocess.list2cmdline([
        Path(sys.executable).as_posix(), "-X", "utf8", "-B", Path(__file__).resolve().as_posix(),
        "hook", "--codex-home", codex_home.as_posix(), "--policy", policy_path.as_posix(),
        "--revision", source_revision(policy_path),
    ])
    for event in EVENTS:
        groups = []
        for original in hooks.get(event, []):
            group = dict(original)
            group["hooks"] = [handler for handler in original.get("hooks", []) if not owned_handler(handler)]
            if group["hooks"]:
                groups.append(group)
        if not remove:
            groups.append({"hooks": [{"type": "command", "command": command, "timeout": 10,
                                       "statusMessage": MARKER}]})
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    changed = after != before
    backup = None
    if changed and apply:
        if path.exists():
            backup = codex_home / "context-budget" / ("hooks.before-" + str(time.time_ns()) + ".json")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        write_json(path, after)
    return {"action": "uninstall" if remove else "install", "applied": apply and changed,
            "changed": changed, "path": str(path), "backup": str(backup) if backup else None,
            "events": list(EVENTS), "hook_trust": "not_applicable" if remove else "review_required_in_codex"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("hook", "status", "install", "uninstall"))
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--policy", type=Path, default=ROOT / "policy.json")
    parser.add_argument("--session")
    parser.add_argument("--revision")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and args.action in ('install', 'uninstall') and args.codex_home is None:
        parser.error('--codex-home is required for an applied client configuration change')
    codex_home = (args.codex_home or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))).resolve()
    policy = policy_at(args.policy) if args.action != "uninstall" else {}
    if args.action == "hook":
        try:
            if args.revision != source_revision(args.policy):
                raise ValueError("Source changed; reinstall and review the updated hook definition")
            result = hook(json.load(sys.stdin), codex_home, policy)
        except (OSError, ValueError, KeyError, TimeoutError) as error:
            result = {"systemMessage": "图片上下文保护检查未完成，请运行 guard.py status 核对。"}
            print(type(error).__name__, file=sys.stderr)
    elif args.action in ("install", "uninstall"):
        result = configure_hooks(codex_home, args.policy.resolve(), args.apply, args.action == "uninstall")
    else:
        hooks_path = codex_home / "hooks.json"
        installed = read_json(hooks_path).get("hooks", {}) if hooks_path.exists() else {}
        result = {"policy": policy, "configured_events": [event for event in EVENTS if any(
            owned_handler(handler) for group in installed.get(event, []) for handler in group.get("hooks", []))],
            "hook_trust": "inspect_in_codex_hooks", "state_directory": str(codex_home / "context-budget")}
        revision = source_revision(args.policy)
        result["source_revision"] = revision
        result["configured_revision_matches"] = all(
            "--revision " + revision in handler.get("command", "")
            for groups in installed.values() for group in groups for handler in group.get("hooks", [])
            if owned_handler(handler)
        )
        if args.session:
            path = state_path(codex_home, args.session)
            state = read_json(path) if path.exists() else new_state(args.session)
            budget, observation = current_budget(codex_home, state)
            result.update({"session_id": args.session, "estimated_bytes": budget,
                           "wire_observation": observation, "last_event": state.get("last_event")})
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
