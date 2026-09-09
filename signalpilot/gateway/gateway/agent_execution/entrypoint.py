"""Single-use cloud container. Stdout contains only bounded public events."""
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path, PurePosixPath

from gateway.agent_execution.artifacts import EXCLUDED, MAX_BYTES, MAX_FILES, pack, read_archive

WORK = Path("/work")
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "status": {"enum": ["completed", "input_required"]},
        "summary": {"type": "string"}, "question": {"type": ["string", "null"]},
        "verification": {"type": "array", "items": {"type": "string"}},
    }, "required": ["status", "summary", "question", "verification"],
}


def emit(kind, **fields):
    print(json.dumps({"type": kind, **fields}), flush=True)


def public_path(value):
    """Expose only bounded project paths, never external paths or input text."""
    if not isinstance(value, str):
        return None
    value = value.removeprefix("/work/project/")
    path = PurePosixPath(value)
    if (not value or len(value) > 240 or path.is_absolute() or
            not re.fullmatch(r"[A-Za-z0-9_./ -]+", value) or
            any(p in EXCLUDED or p in {"..", "."} or p.startswith(".env.") for p in value.split("/"))):
        return None
    return path.as_posix()


class LocalActivity:
    """Reduce Claude envelopes to allowlisted local tool lifecycle events.

    Content, shell arguments, tool output and model text are never forwarded.
    MCP activity is reported by the gateway, which observes actual execution.
    """
    LABELS = {"Read": ("Reading file", "File read returned"),
              "Write": ("Writing file", "File write returned"),
              "Edit": ("Editing file", "File edit returned"),
              "Bash": ("Running shell command", "Shell command returned")}

    def __init__(self):
        self.pending = {}

    def consume(self, event):
        if not isinstance(event, dict) or event.get("type") not in {"assistant", "user"}:
            return []
        message = event.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            return []
        output = []
        for block in message["content"]:
            if not isinstance(block, dict):
                continue
            if event["type"] == "assistant" and block.get("type") == "tool_use":
                tool, identity = block.get("name"), block.get("id")
                if tool not in self.LABELS or not isinstance(identity, str) or len(identity) > 256:
                    continue
                if identity in self.pending or len(self.pending) >= 256:
                    continue
                fields = {"stage": "local_tool", "status": "started", "tool": tool,
                          "message": self.LABELS[tool][0]}
                inputs = block.get("input")
                path = public_path(inputs.get("file_path")) if isinstance(inputs, dict) else None
                if tool != "Bash" and path:
                    fields["path"] = path
                self.pending[identity] = fields
                output.append(dict(fields))
            elif event["type"] == "user" and block.get("type") == "tool_result":
                identity = block.get("tool_use_id")
                if not isinstance(identity, str):
                    continue
                fields = self.pending.pop(identity, None)
                if fields:
                    failed = block.get("is_error") is True
                    fields = dict(fields, status="failed" if failed else "completed",
                                  message="Local tool reported an error" if failed else self.LABELS[fields["tool"]][1])
                    output.append(fields)
        return output


def collect(root):
    files = {}
    total = 0
    # fwalk and O_NOFOLLOW keep background processes from swapping an output
    # path for a credential symlink between validation and the read.
    walks = (os.fwalk(root, follow_symlinks=False) if hasattr(os, "fwalk") else
             ((p, d, n, None) for p, d, n in os.walk(root, followlinks=False)))
    for parent, dirs, names, directory_fd in walks:
        dirs[:] = [d for d in dirs if d not in EXCLUDED and not d.startswith(".env.")]
        if any((Path(parent) / d).is_symlink() for d in dirs):
            raise ValueError("Agent output contains symlinks")
        for name in names:
            if name in EXCLUDED or name.startswith(".env."):
                continue
            path = Path(parent) / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("Agent output contains special files")
            fd = os.open(name if directory_fd is not None else path,
                         os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
                         dir_fd=directory_fd)
            with os.fdopen(fd, "rb") as source:
                metadata = os.fstat(source.fileno())
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError("Agent output contains special files")
                total += metadata.st_size
                if total > MAX_BYTES or len(files) >= MAX_FILES:
                    raise ValueError("Agent output exceeds limits")
                content = source.read(MAX_BYTES - total + metadata.st_size + 1)
                if len(content) != metadata.st_size:
                    raise ValueError("Agent output changed during collection")
                files[path.relative_to(root).as_posix()] = content
    # Apply the same path and expansion validation before publishing.
    return pack(read_archive(pack(files)))


def command(payload):
    return ["claude", "-p", "--output-format", "stream-json", "--verbose",
            "--json-schema", json.dumps(SCHEMA), "--model", payload["model"],
            "--max-turns", str(payload["max_turns"]),
            "--dangerously-skip-permissions", "--strict-mcp-config", "--bare",
            "--allowedTools", ",".join(["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Skill"] +
                ["mcp__signalpilot__" + name for name in payload.get("allowed_mcp_tools", [])]),
            "--mcp-config", "/work/mcp.json", "--setting-sources", "",
            "--plugin-dir", "/opt/signalpilot-plugin"]


def main():
    # PID 1 exits independently of gateway connectivity. AutoRemove discards the
    # container and tmpfs even when the gateway dies before receiving a result.
    signal.signal(signal.SIGALRM, lambda *_: os._exit(124))
    signal.alarm(60)
    payload = json.loads(sys.stdin.buffer.readline(256 * 1024 + 1))
    timeout = min(max(int(payload["timeout_seconds"]), 1), 3600)
    signal.alarm(timeout + 30)
    project = WORK / "project"
    project.mkdir()
    emit("progress", stage="preparing", status="started", message="Preparing project")
    with urllib.request.urlopen(payload["snapshot_url"], timeout=30) as response:
        data = response.read(MAX_BYTES + 1)
    for name, content in read_archive(data).items():
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    emit("progress", stage="preparing", status="completed", message="Project prepared")
    config = {"mcpServers": {"signalpilot": {
        "type": "http", "url": payload["mcp_url"],
        "headers": {"Authorization": "Bearer " + payload["mcp_token"]},
    }}}
    (WORK / "mcp.json").write_text(json.dumps(config))
    (WORK / "mcp.json").chmod(0o600)
    env = dict(os.environ, ANTHROPIC_API_KEY=payload["api_key"])
    prompt = ("Use the SignalPilot dbt-workflow skill for this task. Work only in /work/project. "
              "Return input_required with a question if user input is necessary. "
              "Do not publish changes or modify remote projects. Report verification actually performed.\n"
              + json.dumps({"task": payload["task"], "history": payload.get("history", [])}))
    emit("progress", stage="launching", status="started", message="Starting SignalPilot agent")
    result = None
    total = 0
    activity = LocalActivity()
    with subprocess.Popen(command(payload), cwd=project, env=env, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        process.stdin.write(prompt.encode())
        process.stdin.close()
        emit("progress", stage="launching", status="completed", message="Agent process started")
        while True:
            line = process.stdout.readline(256 * 1024 + 1)
            if not line:
                break
            total += len(line)
            if len(line) > 256 * 1024 or total > 8 * 1024 * 1024:
                process.kill()
                raise ValueError("Agent output exceeds limits")
            event = json.loads(line)
            for fields in activity.consume(event):
                emit("progress", **fields)
            if event.get("type") == "result":
                if event.get("is_error"):
                    raise RuntimeError("Agent execution failed")
                result = event.get("structured_output")
        if process.wait() != 0 or not isinstance(result, dict):
            raise RuntimeError("Missing structured agent result")
    emit("progress", stage="packaging", status="started", message="Collecting changed project files")
    (WORK / "output.tgz").write_bytes(collect(project))
    emit("progress", stage="packaging", status="completed", message="Project snapshot collected")
    emit("result", result=result)
    # Keep tmpfs available until the gateway downloads the result and removes us.
    while True:
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        emit("error", message="Agent container failed")
        raise SystemExit(1)
