---
name: github
description: "Load before any git or GitHub work in a chat: committing model changes, pushing a branch, opening a pull request, updating a pull request, or commenting on one. Covers the sandbox git checkout, the signalpilot/ branch rule, and the open_pull_request, update_pull_request, and comment_on_pull_request tools."
type: skill
---

# GitHub: publish chat work as a pull request

The chat agent publishes work through git and pull requests. A person reviews
and merges on GitHub. The agent never merges.

## Where git runs

The sandbox VM holds the project at `/workspace`. `/workspace` is a git
repository. The remote `origin` is SignalPilot's git server, not GitHub.
Credentials are already configured. You do not need a token.

Run every git command with `sandbox_exec`. Set `cwd` to `/workspace`. Edit
files with `sandbox_write_file`. Do not edit files in your own working
directory. It is a frozen copy for reading only.

The system prompt names the base branch. Your commits go on top of that
branch.

## Branch rule

The server accepts a push only to a branch that starts with `signalpilot/`.
Use the form `signalpilot/<short-name>`. Use a short lowercase name with
hyphens that describes the change. Example: `signalpilot/fix-revenue-grain`.

Use one branch name for one piece of work. Push to the same name each time
you add commits.

The server refuses these pushes and prints the reason:

- A push to any branch that does not start with `signalpilot/`.
- A force push. Add a new commit instead.
- A branch deletion.
- A branch that another chat created. Use a new name.
- A new branch name that already exists on GitHub. Use a new name.
- Any push when the project is not linked to GitHub. Tell the user and give
  the diff in your answer instead.

## Steps to publish

1. Change the files in `/workspace` in the sandbox VM.
2. For model changes, run `dbt_execute` with `build` on the changed models.
   Fix errors until the build passes.
3. Check the diff: `git status` and `git diff`.
4. Stage and commit: `git add -A && git commit -m "<clear message>"`.
5. Push: `git push origin HEAD:signalpilot/<short-name>`.
6. Call `open_pull_request` with a title and a body. In the body, list the
   files or models you changed, what changed in each, and the build result.
7. Put the pull request URL from the tool result in your final answer.

## Pull request tools

- `open_pull_request(title, body, draft, branch)`: opens the pull request
  for the branch you pushed. Leave `branch` empty to use your most recent
  push. Set `draft` true for work that is not ready for review. If the
  branch already has an open pull request, the tool returns it.
- `update_pull_request(title, body, pr_number)`: changes the title or the
  body. Use it after you push more commits, so the description stays true.
- `comment_on_pull_request(body, pr_number)`: adds a comment. Use it to
  report a new build result, to answer a review comment, or to explain one
  part of the change in detail.

Every tool returns `pr_url`. Give the user that link. Every tool acts only
on branches and pull requests that this chat created.

## Good pull request messaging

- Title: one line, imperative, under 70 characters.
- Body: what changed, why, how you verified it, and what the reviewer
  should check.
- When the user asks for detailed explanations, put one topic per comment
  with `comment_on_pull_request`.

## Do not

- Do not run `git push --force`.
- Do not push to `main` or to any branch outside `signalpilot/`.
- Do not try to merge. There is no tool for it.
- Do not put tokens or credentials in commits, comments, or answers.
