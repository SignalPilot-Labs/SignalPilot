"""Ref policy for chat agent pushes to the gateway git server.

A chat run token (execution_identity ``chat:<run_id>``) may create or update
refs under ``refs/heads/signalpilot/`` only. It may not delete a ref and may
not touch any other ref. Force pushes are refused by git itself
(``receive.denyNonFastForwards``), so this module only has to decide whether a
receive-pack request is allowed at all and, if not, write the report-status
the git client prints as ``! [remote rejected] ... (reason)``.
"""

from __future__ import annotations

from dataclasses import dataclass

CHAT_REF_PREFIX = "refs/heads/signalpilot/"
CHAT_BRANCH_PREFIX = "signalpilot/"

REASON_OUTSIDE_NAMESPACE = "chat agents may publish only to signalpilot/... branches"
REASON_DELETE = "chat agents may not delete branches"


def reason_other_chat(branch: str) -> str:
    return f"branch {branch} belongs to another chat; use a new branch name"


def reason_exists_on_github(branch: str) -> str:
    return f"branch {branch} already exists on GitHub; use a new branch name"

_FLUSH = b"0000"


@dataclass(frozen=True)
class RefUpdate:
    old_sha: str
    new_sha: str
    refname: str

    @property
    def is_delete(self) -> bool:
        return bool(self.new_sha) and set(self.new_sha) == {"0"}

    @property
    def is_create(self) -> bool:
        return bool(self.old_sha) and set(self.old_sha) == {"0"}

    @property
    def branch(self) -> str | None:
        return self.refname[len("refs/heads/"):] if self.refname.startswith("refs/heads/") else None


def parse_receive_pack_commands(body: bytes) -> tuple[list[RefUpdate], list[str]]:
    """Parse the ref-update commands at the head of a git-receive-pack body.

    Returns ``(commands, capabilities)``. The command section is a run of
    pkt-lines ``<old-sha> <new-sha> <refname>`` (the first one carries the
    client capabilities after a NUL) terminated by a flush packet; the pack
    data that follows is not read. Lines that are not commands (``shallow``,
    push options, a push certificate) are skipped.
    """
    commands: list[RefUpdate] = []
    capabilities: list[str] = []
    pos = 0
    first = True
    while pos + 4 <= len(body):
        try:
            length = int(body[pos:pos + 4], 16)
        except ValueError:
            break
        if length == 0:
            break
        if length < 4 or pos + length > len(body):
            break
        line = body[pos + 4:pos + length]
        pos += length
        if first:
            first = False
            if b"\0" in line:
                line, caps = line.split(b"\0", 1)
                capabilities = caps.decode("utf-8", errors="replace").strip().split()
        parts = line.rstrip(b"\n").decode("utf-8", errors="replace").split(" ", 2)
        if len(parts) != 3 or len(parts[0]) < 40 or len(parts[1]) < 40 or not parts[2]:
            continue
        commands.append(RefUpdate(old_sha=parts[0], new_sha=parts[1], refname=parts[2]))
    return commands, capabilities


def pushed_branches(body: bytes) -> list[str]:
    """Branch names named by the ref-update commands of a receive-pack body."""
    branches: list[str] = []
    for command in parse_receive_pack_commands(body)[0]:
        branch = command.branch
        if branch and branch not in branches:
            branches.append(branch)
    return branches


def chat_rejection_reason(command: RefUpdate) -> str | None:
    """The reason a chat identity may not run ``command``, or None if allowed."""
    if not command.refname.startswith(CHAT_REF_PREFIX) or command.refname == CHAT_REF_PREFIX:
        return REASON_OUTSIDE_NAMESPACE
    if command.is_delete:
        return REASON_DELETE
    return None


def check_chat_push(commands: list[RefUpdate]) -> dict[str, str]:
    """Map refname -> reason for every command a chat identity may not run.

    One offending command refuses the whole push, so the caller rejects every
    command; the map only carries the ones with a policy reason of their own.
    """
    return {c.refname: reason for c in commands if (reason := chat_rejection_reason(c))}


def pkt_line(payload: bytes) -> bytes:
    return f"{len(payload) + 4:04x}".encode("ascii") + payload


def build_rejection_report(
    commands: list[RefUpdate], reasons: dict[str, str], capabilities: list[str]
) -> bytes:
    """A valid receive-pack report-status that rejects every command.

    ``unpack ok`` followed by one ``ng <refname> <reason>`` line per command
    and a flush. When the client asked for ``side-band-64k`` the report goes
    out on band 1 and the reason is repeated on band 2 so git prints it as a
    ``remote:`` line as well.
    """
    report = pkt_line(b"unpack ok\n")
    fallback = next(iter(reasons.values()), "push refused")
    for command in commands:
        reason = reasons.get(command.refname, fallback)
        report += pkt_line(f"ng {command.refname} {reason}\n".encode())
    report += _FLUSH
    if "side-band-64k" not in capabilities and "side-band" not in capabilities:
        return report
    out = b""
    for reason in dict.fromkeys(reasons.values()):
        out += pkt_line(b"\x02" + f"error: {reason}\n".encode())
    out += pkt_line(b"\x01" + report)
    return out + _FLUSH
