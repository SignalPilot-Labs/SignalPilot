#!/usr/bin/env bash
# Build the notebook sandbox image and push it to Vercel Container Registry.
#
# Notebook Runtime v2: notebook compute runs on Vercel Sandbox VMs, not EKS.
# This replaces scripts/deploy-gateway-notebook-eks.sh's notebook half; the
# gateway itself deploys via /opt/signalpilot/deploy.sh on the EC2 box.
#
# Usage:
#   VERCEL_REGISTRY=registry.vercel.com/<team> bash scripts/build-notebook-image-vercel.sh
#   DRY_RUN=1 ... prints the commands without running them.
#
# On success, prints the digest-pinned reference to set as
# SP_NOTEBOOK_VERCEL_IMAGE (cloud mode refuses floating tags).
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

[[ -f Dockerfile.notebook ]] || die "run from the SignalPilot repo; Dockerfile.notebook not found"
[[ -n "${VERCEL_REGISTRY:-}" ]] || die "VERCEL_REGISTRY is required (e.g. registry.vercel.com/<team>)"

IMAGE_REPO="${NOTEBOOK_IMAGE_REPO:-sp-notebook}"
IMAGE_TAG="${NOTEBOOK_IMAGE_TAG:-$(git rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)}"
IMAGE_URI="${VERCEL_REGISTRY}/${IMAGE_REPO}:${IMAGE_TAG}"
PLATFORM="${PLATFORM:-linux/amd64}"

run docker buildx build \
  --platform "$PLATFORM" \
  -f Dockerfile.notebook \
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
echo "  SP_NOTEBOOK_VERCEL_IMAGE=${VERCEL_REGISTRY}/${IMAGE_REPO}@${DIGEST}"
