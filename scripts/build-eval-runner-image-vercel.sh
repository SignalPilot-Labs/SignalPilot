#!/usr/bin/env bash
# Build the eval runner image and push it to Vercel Container Registry.
#
# The eval runner (Dockerfile.eval-runner) ships the Claude CLI, the
# SignalPilot plugin (skills + verifier agents) and a dbt toolchain. In cloud
# mode the Vercel eval backend boots this image for every task, so it must be
# pushed to the same registry the notebook image lives in.
#
# Usage:
#   VERCEL_REGISTRY=registry.vercel.com/<team> bash scripts/build-eval-runner-image-vercel.sh
#   DRY_RUN=1 ... prints the commands without running them.
#
# On success, prints the digest-pinned reference to set as
# SP_EVAL_RUNNER_IMAGE (cloud mode refuses floating tags).
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required"; }
run() {
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    printf '+'; printf ' %q' "$@"; printf '\n'; return 0
  fi
  "$@"
}

need docker
need git

[[ -f Dockerfile.eval-runner ]] || die "run from the SignalPilot repo; Dockerfile.eval-runner not found"
[[ -f signalpilot-plugin/.claude-plugin/plugin.json ]] || die "canonical SignalPilot plugin is missing from signalpilot-plugin/"
[[ -n "${VERCEL_REGISTRY:-}" ]] || die "VERCEL_REGISTRY is required (e.g. registry.vercel.com/<team>)"

IMAGE_REPO="${EVAL_RUNNER_IMAGE_REPO:-sp-eval-runner}"
IMAGE_TAG="${EVAL_RUNNER_IMAGE_TAG:-$(git rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)}"
IMAGE_URI="${VERCEL_REGISTRY}/${IMAGE_REPO}:${IMAGE_TAG}"
PLATFORM="${PLATFORM:-linux/amd64}"

run docker buildx build \
  --platform "$PLATFORM" \
  -f Dockerfile.eval-runner \
  -t "$IMAGE_URI" \
  --push \
  .

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "DRY_RUN: would resolve the digest of $IMAGE_URI"
  exit 0
fi

DIGEST="$(docker buildx imagetools inspect "$IMAGE_URI" --format '{{json .Manifest.Digest}}' | tr -d '"')"
[[ -n "$DIGEST" ]] || die "could not resolve the image digest for $IMAGE_URI"

echo
echo "Pushed: $IMAGE_URI"
echo "Set this (digest-pinned) in the gateway environment:"
echo "  SP_EVAL_RUNNER_IMAGE=${VERCEL_REGISTRY}/${IMAGE_REPO}@${DIGEST}"
