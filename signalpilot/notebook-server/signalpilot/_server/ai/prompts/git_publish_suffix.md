## Publish your work

The sandbox VM holds the project at `/workspace`. `/workspace` is a git
repository. The remote `origin` is SignalPilot. The base branch is
`{base_branch}`. Credentials are already configured.

Load the `github` skill before any git or pull request work. It covers the
`signalpilot/` branch rule, the publish steps, and the `open_pull_request`,
`update_pull_request`, and `comment_on_pull_request` tools.

Rules that always apply:

- Run git commands with `sandbox_exec` in `/workspace`.
- Push only to `signalpilot/<short-name>` branches. Do not force push. Do not
  delete branches.
- You cannot merge. A person merges the pull request on GitHub.
- Put the pull request URL in your final answer.
