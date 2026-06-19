#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

log() {
  printf '\n[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required"
}

run() {
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

need aws
need docker
need git
need kubectl

AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-2}}"
if [[ -z "${AWS_ACCOUNT_ID:-}" && -z "${ECR_REGISTRY:-}" && "${DRY_RUN:-0}" == "1" ]]; then
  AWS_ACCOUNT_ID="000000000000"
else
  AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
fi
ECR_REGISTRY="${ECR_REGISTRY:-${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com}"

NOTEBOOK_ECR_REPO="${NOTEBOOK_ECR_REPO:-signalpilot-notebook}"
NOTEBOOK_IMAGE_TAG="${NOTEBOOK_IMAGE_TAG:-$(git rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)}"
NOTEBOOK_IMAGE_URI="${ECR_REGISTRY}/${NOTEBOOK_ECR_REPO}:${NOTEBOOK_IMAGE_TAG}"
PLATFORM="${PLATFORM:-linux/amd64}"

GATEWAY_DEPLOY_SCRIPT="${GATEWAY_DEPLOY_SCRIPT:-${ROOT_DIR}/../deploy-gateway-eks.sh}"
GATEWAY_IMAGE="${GATEWAY_IMAGE:-signalpilot-gateway}"
NOTEBOOK_NAMESPACE_PREFIX="${SP_NOTEBOOK_NAMESPACE_PREFIX:-sp-nb}"
GATEWAY_NAMESPACE="${GATEWAY_NAMESPACE:-signalpilot}"
GATEWAY_DEPLOYMENT="${GATEWAY_DEPLOYMENT:-signalpilot-gateway}"

[[ -f Dockerfile.gateway ]] || die "run from the SignalPilot repo; Dockerfile.gateway not found"
[[ -f Dockerfile.notebook ]] || die "run from the SignalPilot repo; Dockerfile.notebook not found"
[[ -f "$GATEWAY_DEPLOY_SCRIPT" ]] || die "gateway deploy script not found: $GATEWAY_DEPLOY_SCRIPT"

if [[ "${SKIP_GATEWAY_IMAGE_BUILD:-0}" != "1" ]]; then
  log "Building gateway image: ${GATEWAY_IMAGE}"
  run docker build \
    -f Dockerfile.gateway \
    -t "$GATEWAY_IMAGE" \
    signalpilot/gateway
else
  log "Skipping gateway image build because SKIP_GATEWAY_IMAGE_BUILD=1"
fi

log "Verifying ECR repository exists: ${NOTEBOOK_ECR_REPO} in ${AWS_REGION}"
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  log "DRY_RUN=1: would verify ECR repository ${NOTEBOOK_ECR_REPO}"
else
  ECR_DESCRIBE_ERROR="$(mktemp)"
  if aws ecr describe-repositories \
  --region "$AWS_REGION" \
  --repository-names "$NOTEBOOK_ECR_REPO" >/dev/null 2>"$ECR_DESCRIBE_ERROR"; then
    rm -f "$ECR_DESCRIBE_ERROR"
  elif [[ "${CREATE_ECR_REPOSITORY:-0}" == "1" ]]; then
    rm -f "$ECR_DESCRIBE_ERROR"
    run aws ecr create-repository \
      --region "$AWS_REGION" \
      --repository-name "$NOTEBOOK_ECR_REPO" >/dev/null
  else
    ECR_ERROR="$(cat "$ECR_DESCRIBE_ERROR")"
    rm -f "$ECR_DESCRIBE_ERROR"
    die "ECR repository ${NOTEBOOK_ECR_REPO} is not visible in ${AWS_REGION}. Set AWS_REGION to the region where the repo already exists, or set CREATE_ECR_REPOSITORY=1. AWS error: ${ECR_ERROR}"
  fi
fi

log "Logging in to ECR: ${ECR_REGISTRY}"
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  printf '+ aws ecr get-login-password --region %q | docker login --username AWS --password-stdin %q\n' \
    "$AWS_REGION" "$ECR_REGISTRY"
else
  aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin "$ECR_REGISTRY"
fi

log "Building and pushing notebook image: ${NOTEBOOK_IMAGE_URI}"
if docker buildx version >/dev/null 2>&1; then
  run docker buildx build \
    --platform "$PLATFORM" \
    -f Dockerfile.notebook \
    -t "$NOTEBOOK_IMAGE_URI" \
    --push \
    .
else
  run docker build -f Dockerfile.notebook -t "$NOTEBOOK_IMAGE_URI" .
  run docker push "$NOTEBOOK_IMAGE_URI"
fi

log "Resolving notebook image digest"
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  NOTEBOOK_IMAGE_DIGEST="sha256:DRY_RUN_DIGEST"
else
  NOTEBOOK_IMAGE_DIGEST="$(aws ecr describe-images \
    --region "$AWS_REGION" \
    --repository-name "$NOTEBOOK_ECR_REPO" \
    --image-ids imageTag="$NOTEBOOK_IMAGE_TAG" \
    --query 'imageDetails[0].imageDigest' \
    --output text)"
fi
[[ "$NOTEBOOK_IMAGE_DIGEST" == sha256:* ]] \
  || die "could not resolve digest for ${NOTEBOOK_IMAGE_URI}: ${NOTEBOOK_IMAGE_DIGEST}"

export SP_NOTEBOOK_IMAGE="${ECR_REGISTRY}/${NOTEBOOK_ECR_REPO}@${NOTEBOOK_IMAGE_DIGEST}"
log "Deploying gateway with SP_NOTEBOOK_IMAGE=${SP_NOTEBOOK_IMAGE}"

GATEWAY_DEPLOY_DIR="$(cd "$(dirname "$GATEWAY_DEPLOY_SCRIPT")" && pwd)"
GATEWAY_DEPLOY_FILE="$(basename "$GATEWAY_DEPLOY_SCRIPT")"
(
  cd "$GATEWAY_DEPLOY_DIR"
  run env GATEWAY_IMAGE="$GATEWAY_IMAGE" SP_NOTEBOOK_IMAGE="$SP_NOTEBOOK_IMAGE" bash "./$GATEWAY_DEPLOY_FILE"
)

if [[ "${SKIP_GATEWAY_ROLLOUT_WAIT:-0}" != "1" ]]; then
  log "Waiting for gateway rollout: ${GATEWAY_NAMESPACE}/${GATEWAY_DEPLOYMENT}"
  run kubectl rollout status \
    -n "$GATEWAY_NAMESPACE" \
    "deployment/${GATEWAY_DEPLOYMENT}" \
    --timeout="${GATEWAY_ROLLOUT_TIMEOUT:-300s}"
fi

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  log "DRY_RUN=1: would delete notebook pods in namespaces matching ${NOTEBOOK_NAMESPACE_PREFIX}-*"
  exit 0
fi

if [[ "${SKIP_NOTEBOOK_POD_DELETE:-0}" == "1" ]]; then
  log "Skipping notebook pod deletion because SKIP_NOTEBOOK_POD_DELETE=1"
  exit 0
fi

log "Finding notebook namespaces with prefix: ${NOTEBOOK_NAMESPACE_PREFIX}-"
mapfile -t NOTEBOOK_NAMESPACES < <(
  kubectl get namespaces -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
    | awk -v prefix="${NOTEBOOK_NAMESPACE_PREFIX}" '$0 == prefix || index($0, prefix "-") == 1'
)

if [[ "${#NOTEBOOK_NAMESPACES[@]}" -eq 0 ]]; then
  log "No ${NOTEBOOK_NAMESPACE_PREFIX} namespaces found"
  exit 0
fi

if [[ "${DELETE_SP_NB_NAMESPACES:-0}" == "1" ]]; then
  log "Deleting notebook namespaces: ${NOTEBOOK_NAMESPACES[*]}"
  run kubectl delete namespace "${NOTEBOOK_NAMESPACES[@]}" --wait=false
else
  log "Deleting notebook pods in namespaces: ${NOTEBOOK_NAMESPACES[*]}"
  for namespace in "${NOTEBOOK_NAMESPACES[@]}"; do
    run kubectl delete pods -n "$namespace" --all --wait=false --ignore-not-found
  done
fi

log "Done"
