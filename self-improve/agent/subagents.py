"""Subagent definitions for parallel work delegation.

Each subagent has a prompt file in prompts/agent-{name}.md, a model
assignment (opus for deep analysis, sonnet for fast execution), and a
restricted tool set based on its purpose.
"""

from claude_agent_sdk.types import AgentDefinition

from agent import prompt


def build_subagent_definitions() -> dict[str, AgentDefinition]:
    """Build the subagent definitions dict for the SDK."""
    return {
        # --- Execution agents (sonnet, write access) ---
        "code-writer": AgentDefinition(
            description="Use for writing new files, generating boilerplate, creating components, or implementing straightforward features. Delegates code generation so the main agent can continue planning.",
            prompt=prompt.load_agent_prompt("code-writer"),
            model="sonnet",
            tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        ),
        "test-writer": AgentDefinition(
            description="Use for writing tests, running test suites, and verifying code works correctly. Delegates test creation and execution.",
            prompt=prompt.load_agent_prompt("test-writer"),
            model="sonnet",
            tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        ),
        "frontend-builder": AgentDefinition(
            description="Use for building React/Next.js components, pages, layouts, and styling. Handles TSX, CSS, Tailwind, and frontend-specific code generation.",
            prompt=prompt.load_agent_prompt("frontend-builder"),
            model="sonnet",
            tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        ),
        "qa": AgentDefinition(
            description="Use for full QA cycles — systematically finds bugs, proves them with tests, fixes them, and verifies fixes. Goes beyond test-writer by probing edge cases, integration points, and failure conditions. Use when you need thorough quality assurance, not just test generation.",
            prompt=prompt.load_agent_prompt("qa"),
            model="sonnet",
            tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        ),
        "investigator": AgentDefinition(
            description="Use when encountering a bug, failing test, or unexpected behavior that isn't immediately obvious. Systematically traces root causes instead of fixing symptoms. Reproduces the issue, forms hypotheses, tests them, and fixes the underlying problem.",
            prompt=prompt.load_agent_prompt("investigator"),
            model="sonnet",
            tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        ),
        # --- Research agent (sonnet, read + web) ---
        "researcher": AgentDefinition(
            description="Use for researching the codebase, finding patterns, understanding architecture, or looking up documentation. Returns findings without making changes.",
            prompt=prompt.load_agent_prompt("researcher"),
            model="sonnet",
            tools=["Read", "Glob", "Grep", "Bash", "WebSearch", "WebFetch"],
        ),
        # --- Review agents (opus, read-only) ---
        "reviewer": AgentDefinition(
            description="MUST be called after completing each feature or significant change. Reviews recent commits for security vulnerabilities, performance issues, duplicated code, god files, and code quality problems. Runs on Opus for thorough analysis. Returns a structured review with critical issues, warnings, and files that need splitting.",
            prompt=prompt.load_agent_prompt("reviewer"),
            model="opus",
            tools=["Read", "Glob", "Grep", "Bash"],
        ),
        "plan-reviewer": AgentDefinition(
            description="Use BEFORE implementing a complex feature or architectural change. Reviews the plan for product value, architecture soundness, scalability, and scope. Returns a verdict (SCOPE EXPANSION, SELECTIVE EXPANSION, HOLD SCOPE, or SCOPE REDUCTION) with specific recommendations. Runs on Opus for deep strategic thinking.",
            prompt=prompt.load_agent_prompt("plan-reviewer"),
            model="opus",
            tools=["Read", "Glob", "Grep", "Bash"],
        ),
        "design-reviewer": AgentDefinition(
            description="Use after frontend changes to review UI/UX quality. Scores visual consistency, hierarchy, typography, interaction design, and accessibility on a 0-10 scale. Catches spacing issues, AI slop patterns, and design inconsistencies. Runs on Opus for thorough design analysis.",
            prompt=prompt.load_agent_prompt("design-reviewer"),
            model="opus",
            tools=["Read", "Glob", "Grep", "Bash"],
        ),
        "security-guard": AgentDefinition(
            description="Use for deep security audits focused on OWASP Top 10, credential handling, SQL injection, auth flows, and data exposure. More thorough than the reviewer's security section. Essential for changes touching auth, database credentials, SQL generation, or API endpoints. Runs on Opus for exhaustive analysis.",
            prompt=prompt.load_agent_prompt("security-guard"),
            model="opus",
            tools=["Read", "Glob", "Grep", "Bash"],
        ),
    }
