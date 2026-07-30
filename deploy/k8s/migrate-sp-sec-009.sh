#!/usr/bin/env bash
# migrate-sp-sec-009.sh — roll a cluster from the pre-SP-SEC-009 RBAC layout to the
# bootstrap/workload split defined in gateway-runtime-rbac.yaml + gateway-rbac.yaml.
#
# WHY A SCRIPT AND NOT A `kubectl delete` ONE-LINER
#
# `roleRef` is immutable. The per-namespace RoleBinding signalpilot-gateway-org-binding
# used to target a per-namespace Role (signalpilot-gateway-org-role); it must now target
# the ClusterRole signalpilot-gateway-notebook-workload. That cannot be patched — the
# object has to be deleted and recreated, in every tenant namespace, and only where it
# is actually stale (so re-running is a no-op).
#
# The migration block previously carried in the gateway-runtime-rbac.yaml header used:
#   kubectl delete rolebinding signalpilot-gateway-org-binding \
#     -l signalpilot.ai/managed-by=gateway --all-namespaces --ignore-not-found
#   kubectl delete role signalpilot-gateway-org-role --all-namespaces --ignore-not-found
# Both are INVALID kubectl invocations and delete nothing:
#   "error: name cannot be provided when a selector is specified"
#   "error: a resource cannot be retrieved by name across all namespaces"
# An operator pasting them sees an error, no objects are removed, and the cluster is
# left in the pre-migration state while looking like it was migrated. Hence this script.
#
# WHAT IT DOES
#   Phase 1  delete the legacy cluster-wide grant
#            (clusterrolebinding/signalpilot-gateway-runtime, clusterrole/…-runtime)
#   Phase 2  per tenant namespace, delete signalpilot-gateway-org-binding ONLY if its
#            roleRef is stale, plus the superseded Role signalpilot-gateway-org-role
#   Phase 3  verify the end state and report which namespaces await gateway recreation
#
# The gateway recreates the RoleBinding on the next session in that namespace
# (orchestrator/namespaces.py ensure_org_namespace). Deleting it does NOT delete running
# notebook pods; it only blocks new pod/secret writes in that namespace until recreated.
#
# USAGE
#   ./migrate-sp-sec-009.sh                 # dry run (default) — prints the plan only
#   ./migrate-sp-sec-009.sh --apply         # perform the migration
#   ./migrate-sp-sec-009.sh --verify        # verification phase only, no mutation
#   ./migrate-sp-sec-009.sh --rollback      # remove the NEW objects (see ROLLBACK below)
#   SP_TENANT_LABEL=... ./migrate-sp-sec-009.sh --apply
#
# ROLLBACK
#   This migration only DELETES objects; the gateway recreates the per-namespace
#   RoleBindings, so the forward path is self-healing. To return to the pre-SP-SEC-009
#   layout (cluster-wide grant), you must restore the old manifest, which is no longer
#   in the repo:
#     1. ./migrate-sp-sec-009.sh --rollback
#          deletes clusterrole/signalpilot-gateway-runtime-bootstrap and its binding,
#          and the restrict-rbac-writes admission policy (VAP or Kyverno) that would
#          otherwise reject a cluster-wide workload binding.
#     2. git show <pre-SP-SEC-009-commit>:deploy/k8s/gateway-runtime-rbac.yaml \
#          | kubectl apply -f -
#     3. Per-namespace RoleBindings created by the migrated gateway keep working — they
#        reference the workload ClusterRole, which is still defined in gateway-rbac.yaml.
#        Nothing needs deleting to roll back.
#   Rollback re-opens the cluster-wide Secret disclosure SP-SEC-009 describes. Treat it
#   as a break-glass step, not a routine option.
#
# Tested end-to-end against a throwaway kind cluster by validate-admission-policies.sh
# (see deploy/k8s/README.md → "Validating the SP-SEC-009 rollout").

set -euo pipefail

# --- constants (keep in sync with orchestrator/namespaces.py) ------------------------
WORKLOAD_CLUSTER_ROLE="signalpilot-gateway-notebook-workload"
ORG_BINDING_NAME="signalpilot-gateway-org-binding"
LEGACY_ORG_ROLE="signalpilot-gateway-org-role"
LEGACY_CLUSTER_ROLE="signalpilot-gateway-runtime"
LEGACY_CLUSTER_ROLE_BINDING="signalpilot-gateway-runtime-binding"
TENANT_LABEL="${SP_TENANT_LABEL:-signalpilot.dev/tenant=user}"

MODE="dry-run"
case "${1:-}" in
  --apply)    MODE="apply" ;;
  --verify)   MODE="verify" ;;
  --rollback) MODE="rollback" ;;
  --dry-run|"") MODE="dry-run" ;;
  -h|--help)  sed -n '2,60p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
esac

log()  { printf '%s\n' "$*"; }
step() { printf '\n=== %s\n' "$*"; }
# Emits the action, or just describes it in dry-run mode.
run() {
  if [ "$MODE" = "apply" ] || [ "$MODE" = "rollback" ]; then
    "$@"
  else
    log "    would run: $*"
  fi
}

FAILURES=0
check() { # check <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    printf '  PASS  %-58s %s\n' "$1" "$3"
  else
    printf '  FAIL  %-58s expected=%s actual=%s\n' "$1" "$2" "$3"
    FAILURES=$((FAILURES + 1))
  fi
}

# --- preflight ----------------------------------------------------------------------
step "Preflight"
if ! kubectl version -o json >/dev/null 2>&1; then
  log "  cannot reach a cluster with the current kubeconfig context." >&2
  log "  context: $(kubectl config current-context 2>/dev/null || echo '<none>')" >&2
  exit 1
fi
log "  context: $(kubectl config current-context)"
log "  mode:    $MODE"

if [ "$MODE" != "rollback" ]; then
  # The RoleBindings the gateway is about to recreate reference this ClusterRole. If it
  # is absent, apply gateway-rbac.yaml FIRST or every recreation 403s on `bind`.
  if kubectl get clusterrole "$WORKLOAD_CLUSTER_ROLE" >/dev/null 2>&1; then
    log "  workload ClusterRole present: $WORKLOAD_CLUSTER_ROLE"
  else
    log "  ERROR: ClusterRole $WORKLOAD_CLUSTER_ROLE not found." >&2
    log "  Apply deploy/k8s/gateway-rbac.yaml before migrating." >&2
    exit 1
  fi
  # Admission policy is the layer that pins WHERE the binding may be created. Migrating
  # without it still works, but drops a defence — warn loudly rather than fail.
  if kubectl get validatingadmissionpolicy restrict-rbac-writes-signalpilot >/dev/null 2>&1; then
    log "  admission: ValidatingAdmissionPolicy restrict-rbac-writes-signalpilot present"
  elif kubectl get clusterpolicy restrict-rbac-writes-signalpilot >/dev/null 2>&1; then
    log "  admission: Kyverno ClusterPolicy restrict-rbac-writes-signalpilot present"
  else
    log "  WARNING: restrict-rbac-writes admission policy NOT installed."
    log "           RBAC alone cannot pin WHICH namespace a RoleBinding lands in."
    log "           See deploy/k8s/admission/README.md."
  fi
fi

# --- rollback -----------------------------------------------------------------------
if [ "$MODE" = "rollback" ]; then
  step "Rollback — removing the SP-SEC-009 objects"
  log "  (the pre-SP-SEC-009 manifest must then be re-applied from git; see header)"
  run kubectl delete clusterrolebinding signalpilot-gateway-runtime-bootstrap-binding --ignore-not-found
  run kubectl delete clusterrole signalpilot-gateway-runtime-bootstrap --ignore-not-found
  run kubectl delete validatingadmissionpolicybinding restrict-rbac-writes-signalpilot-binding --ignore-not-found
  run kubectl delete validatingadmissionpolicy restrict-rbac-writes-signalpilot --ignore-not-found
  run kubectl delete clusterpolicy restrict-rbac-writes-signalpilot --ignore-not-found
  log ""
  log "  Rollback complete. The cluster now has NO cluster-wide gateway grant and NO"
  log "  restrict-rbac-writes policy. Re-apply the old manifest to restore service."
  exit 0
fi

# --- phase 1: legacy cluster-wide grant ---------------------------------------------
if [ "$MODE" != "verify" ]; then
  step "Phase 1 — delete the legacy cluster-wide grant"
  # These are the objects that made a gateway compromise a cluster-wide secret
  # disclosure. --ignore-not-found keeps the script idempotent.
  if kubectl get clusterrolebinding "$LEGACY_CLUSTER_ROLE_BINDING" >/dev/null 2>&1; then
    log "  found clusterrolebinding/$LEGACY_CLUSTER_ROLE_BINDING -> deleting"
    run kubectl delete clusterrolebinding "$LEGACY_CLUSTER_ROLE_BINDING" --ignore-not-found
  else
    log "  clusterrolebinding/$LEGACY_CLUSTER_ROLE_BINDING absent (already migrated)"
  fi
  if kubectl get clusterrole "$LEGACY_CLUSTER_ROLE" >/dev/null 2>&1; then
    log "  found clusterrole/$LEGACY_CLUSTER_ROLE -> deleting"
    run kubectl delete clusterrole "$LEGACY_CLUSTER_ROLE" --ignore-not-found
  else
    log "  clusterrole/$LEGACY_CLUSTER_ROLE absent (already migrated)"
  fi

  # Any ClusterRoleBinding of the workload role is the SP-SEC-009 regression itself,
  # whatever its name. Report every one; do not guess at deleting unknown objects.
  stray=$(kubectl get clusterrolebindings \
      -o jsonpath="{range .items[?(@.roleRef.name=='$WORKLOAD_CLUSTER_ROLE')]}{.metadata.name}{'\n'}{end}" \
      2>/dev/null | grep -v '^$' || true)
  if [ -n "$stray" ]; then
    log "  WARNING: ClusterRoleBinding(s) bind $WORKLOAD_CLUSTER_ROLE cluster-wide:"
    printf '           %s\n' $stray
    log "           These re-introduce SP-SEC-009. Delete them after confirming nothing"
    log "           depends on them:  kubectl delete clusterrolebinding <name>"
  fi
fi

# --- phase 2: stale per-namespace RoleBindings ---------------------------------------
if [ "$MODE" != "verify" ]; then
  step "Phase 2 — delete stale per-namespace RoleBindings (roleRef is immutable)"
  tenant_ns=$(kubectl get namespaces -l "$TENANT_LABEL" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)
  if [ -z "${tenant_ns// /}" ]; then
    log "  no namespaces match label $TENANT_LABEL — nothing to migrate"
  fi
  for ns in $tenant_ns; do
    # Only delete a binding whose roleRef actually differs from the target. This is what
    # makes the script safe to re-run: after a successful migration every binding
    # already points at the workload ClusterRole and is left untouched.
    current=$(kubectl get rolebinding "$ORG_BINDING_NAME" -n "$ns" \
                -o jsonpath='{.roleRef.kind}/{.roleRef.name}' 2>/dev/null || true)
    if [ -z "$current" ]; then
      log "  $ns: no $ORG_BINDING_NAME (gateway will create it on next session)"
    elif [ "$current" = "ClusterRole/$WORKLOAD_CLUSTER_ROLE" ]; then
      log "  $ns: binding already targets $WORKLOAD_CLUSTER_ROLE — leaving in place"
    else
      log "  $ns: stale binding -> $current — deleting for recreation"
      run kubectl delete rolebinding "$ORG_BINDING_NAME" -n "$ns" --ignore-not-found
    fi
    # The per-namespace Role is superseded by the ClusterRole template and can never be
    # recreated (creating a Role needs `escalate`, which the bootstrap role omits).
    if kubectl get role "$LEGACY_ORG_ROLE" -n "$ns" >/dev/null 2>&1; then
      log "  $ns: deleting superseded role/$LEGACY_ORG_ROLE"
      run kubectl delete role "$LEGACY_ORG_ROLE" -n "$ns" --ignore-not-found
    fi
  done
fi

# --- phase 3: verify ----------------------------------------------------------------
step "Phase 3 — verify end state"

crb_count=$(kubectl get clusterrolebindings \
    -o jsonpath="{range .items[?(@.roleRef.name=='$WORKLOAD_CLUSTER_ROLE')]}x{end}" 2>/dev/null | tr -cd 'x' | wc -c | tr -d ' ')
check "no ClusterRoleBinding of $WORKLOAD_CLUSTER_ROLE" "0" "$crb_count"

legacy_cr=$(kubectl get clusterrole "$LEGACY_CLUSTER_ROLE" >/dev/null 2>&1 && echo present || echo absent)
check "legacy clusterrole/$LEGACY_CLUSTER_ROLE removed" "absent" "$legacy_cr"

legacy_crb=$(kubectl get clusterrolebinding "$LEGACY_CLUSTER_ROLE_BINDING" >/dev/null 2>&1 && echo present || echo absent)
check "legacy clusterrolebinding removed" "absent" "$legacy_crb"

bootstrap_cr=$(kubectl get clusterrole signalpilot-gateway-runtime-bootstrap >/dev/null 2>&1 && echo present || echo absent)
check "bootstrap clusterrole present" "present" "$bootstrap_cr"

# Every surviving org binding must reference the ClusterRole template, and no tenant
# namespace may still carry the superseded Role.
stale=0; legacy_roles=0; pending=0; migrated=0
for ns in $(kubectl get namespaces -l "$TENANT_LABEL" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true); do
  current=$(kubectl get rolebinding "$ORG_BINDING_NAME" -n "$ns" \
              -o jsonpath='{.roleRef.kind}/{.roleRef.name}' 2>/dev/null || true)
  if [ -z "$current" ]; then pending=$((pending + 1))
  elif [ "$current" = "ClusterRole/$WORKLOAD_CLUSTER_ROLE" ]; then migrated=$((migrated + 1))
  else stale=$((stale + 1)); fi
  kubectl get role "$LEGACY_ORG_ROLE" -n "$ns" >/dev/null 2>&1 && legacy_roles=$((legacy_roles + 1)) || true
done
check "tenant namespaces with a stale roleRef" "0" "$stale"
check "tenant namespaces with superseded $LEGACY_ORG_ROLE" "0" "$legacy_roles"
log "  info  tenant namespaces already migrated:            $migrated"
log "  info  tenant namespaces awaiting gateway recreation: $pending"
if [ "$pending" -gt 0 ] && [ "$MODE" != "dry-run" ]; then
  log ""
  log "  $pending namespace(s) have no $ORG_BINDING_NAME. This is expected immediately"
  log "  after migration: the gateway recreates the binding when the next notebook"
  log "  session starts in that namespace (ensure_org_namespace). Verify with:"
  log "    kubectl get rolebinding $ORG_BINDING_NAME -n <ns> -o yaml"
fi

step "Result"
if [ "$MODE" = "dry-run" ]; then
  log "  DRY RUN — nothing was changed. Re-run with --apply to perform the migration."
fi
if [ "$FAILURES" -eq 0 ]; then
  log "  verification: OK ($FAILURES failures)"
  exit 0
fi
log "  verification: $FAILURES check(s) FAILED"
# In dry-run the legacy objects are expected to still be present, so a non-zero count
# is informational rather than an error.
[ "$MODE" = "dry-run" ] && { log "  (expected in dry-run: legacy objects are still in place)"; exit 0; }
exit 1
