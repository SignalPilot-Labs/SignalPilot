#!/usr/bin/env bash
# validate-admission-policies.sh — machine-validate the SP-SEC-009 admission policies
# and the RBAC migration, with no access to any real cluster.
#
# WHY THIS EXISTS
#
# `yaml.safe_load_all` proves a manifest parses. It does not prove a CEL expression
# compiles, that a Kyverno rule body is well-formed, or that a rule denies what it
# claims to deny. Two real defects were found precisely because they are invisible to a
# YAML check (both fixed; see admission/README.md → "Validation findings"):
#   1. the Kyverno ClusterPolicy was structurally INVALID (a nested `any:` inside
#      `all:`), so `kubectl apply` rejected the whole object and none of the four rules
#      were installed — a silent fail-open of the entire fallback path;
#   2. `kyverno test` reports "N tests passed" even when every result is
#      `Skip / Invalid Policy`, so a broken policy looks like a green suite.
# Phase A below therefore greps for "Invalid Policy" and fails on it explicitly.
#
# PHASES
#   A  (default, no cluster)  kyverno CLI unit tests for every <policy>.test.yaml
#   B  (--e2e, needs Docker)  stand up a throwaway kind cluster and assert, against a
#                             real API server: the VAP CEL compiles; each rule allows the
#                             legitimate write and denies each hostile one; the migration
#                             script is idempotent; and `kubectl auth can-i` shows
#                             SP-SEC-009 closed with the gateway still functional.
#
# USAGE
#   ./validate-admission-policies.sh                # Phase A only
#   ./validate-admission-policies.sh --e2e          # Phase A + B (creates/deletes a kind cluster)
#   ./validate-admission-policies.sh --e2e --keep-cluster
#   KYVERNO=/path/to/kyverno KIND=/path/to/kind ./validate-admission-policies.sh --e2e
#
# TOOLING — neither binary needs to be on PATH permanently. Tested with:
#   kyverno CLI 1.18.2   https://github.com/kyverno/kyverno/releases
#   kind        0.32.0   https://github.com/kubernetes-sigs/kind/releases
#   kubectl     1.34.1
#
# SAFETY
#   Phase B writes ONLY to its own kubeconfig (a temp file) and refuses to run unless the
#   active context is the kind cluster it just created. It never reads or mutates the
#   caller's default kubeconfig, so it cannot touch a real EKS cluster.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADMISSION="$HERE/admission"
KYVERNO="${KYVERNO:-kyverno}"
KIND="${KIND:-kind}"
CLUSTER_NAME="${SP_KIND_CLUSTER:-sp-sec-009-validate}"
NODE_IMAGE="${SP_KIND_NODE_IMAGE:-kindest/node:v1.34.0}"
KYVERNO_CHART_VERSION="${SP_KYVERNO_CHART_VERSION:-3.5.2}"

RUN_E2E=0; KEEP_CLUSTER=0; RUN_KYVERNO_E2E=0
for arg in "$@"; do
  case "$arg" in
    --e2e)            RUN_E2E=1 ;;
    --keep-cluster)   KEEP_CLUSTER=1 ;;
    --with-kyverno)   RUN_E2E=1; RUN_KYVERNO_E2E=1 ;;
    -h|--help)        sed -n '2,45p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg (try --help)" >&2; exit 2 ;;
  esac
done

PASS=0; FAIL=0
step() { printf '\n=== %s\n' "$*"; }
ok()   { PASS=$((PASS+1)); printf '  PASS  %s\n' "$*"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$*"; }
# check <want> <desc> <got>
check(){ [ "$1" = "$3" ] && ok "$(printf '%-56s %s' "$2" "$3")" || bad "$(printf '%-56s want=%s got=%s' "$2" "$1" "$3")"; }

# =====================================================================================
# Phase A — Kyverno CLI unit tests (no cluster required)
# =====================================================================================
step "Phase A — Kyverno CLI policy unit tests"
if ! command -v "$KYVERNO" >/dev/null 2>&1 && [ ! -x "$KYVERNO" ]; then
  bad "kyverno CLI not found (set KYVERNO=/path/to/kyverno). Install from
        https://github.com/kyverno/kyverno/releases — no PATH change needed."
else
  printf '  kyverno CLI: %s\n' "$("$KYVERNO" version 2>&1 | head -1)"
  # The CLI only auto-discovers files literally named kyverno-test.yaml. This repo uses
  # <policy>.test.yaml, so every file must be passed explicitly with --file-name;
  # otherwise `kyverno test <dir>` prints "No test yamls available" and exits 0.
  shopt -s nullglob
  tests=("$ADMISSION"/*.test.yaml)
  shopt -u nullglob
  if [ ${#tests[@]} -eq 0 ]; then
    bad "no *.test.yaml files found under $ADMISSION"
  fi
  for t in "${tests[@]}"; do
    name="$(basename "$t")"
    out="$("$KYVERNO" test "$ADMISSION" --file-name "$name" 2>&1)"
    rc=$?
    # An invalid policy yields Skip rows AND a "N tests passed" summary, so the summary
    # alone cannot be trusted — check for the marker directly.
    if printf '%s' "$out" | grep -q 'Invalid Policy'; then
      bad "$name — POLICY IS INVALID (rules are not enforced at all):"
      printf '%s\n' "$out" | grep -o 'path: spec\.rules.*' | sort -u | head -3 | sed 's/^/          /'
    elif [ $rc -ne 0 ]; then
      bad "$name — kyverno test exited $rc"
      printf '%s\n' "$out" | tail -6 | sed 's/^/          /'
    else
      summary="$(printf '%s' "$out" | grep -E 'Test Summary' | tail -1)"
      if printf '%s' "$summary" | grep -qE '[1-9][0-9]* tests failed'; then
        bad "$name — $summary"
        printf '%s\n' "$out" | grep -E '\| Fail ' | head -6 | sed 's/^/          /'
      else
        ok "$name — ${summary:-no summary}"
      fi
    fi
  done
fi

if [ "$RUN_E2E" -eq 0 ]; then
  step "Result"
  printf '  Phase A only (pass --e2e for live-cluster validation of the CEL and the migration)\n'
  printf '  %d passed, %d failed\n' "$PASS" "$FAIL"
  [ "$FAIL" -eq 0 ] && exit 0 || exit 1
fi

# =====================================================================================
# Phase B — live throwaway kind cluster
# =====================================================================================
step "Phase B — live cluster validation (kind)"
for bin in "$KIND" kubectl docker; do
  command -v "$bin" >/dev/null 2>&1 || { bad "$bin not found; cannot run --e2e"; \
    printf '  %d passed, %d failed\n' "$PASS" "$FAIL"; exit 1; }
done

KCFG="$(mktemp -t sp-sec-009-kubeconfig.XXXXXX)"
export KUBECONFIG="$KCFG"
cleanup() {
  if [ "$KEEP_CLUSTER" -eq 0 ]; then
    printf '\n  tearing down kind cluster %s\n' "$CLUSTER_NAME"
    "$KIND" delete cluster --name "$CLUSTER_NAME" >/dev/null 2>&1
    rm -f "$KCFG"
  else
    printf '\n  --keep-cluster: cluster %s left running; KUBECONFIG=%s\n' "$CLUSTER_NAME" "$KCFG"
  fi
}
trap cleanup EXIT

printf '  creating kind cluster %s (%s)\n' "$CLUSTER_NAME" "$NODE_IMAGE"
"$KIND" create cluster --name "$CLUSTER_NAME" --image "$NODE_IMAGE" --wait 180s >/dev/null 2>&1 \
  || { bad "kind create cluster failed"; exit 1; }

# Refuse to mutate anything that is not the cluster we just made.
CTX="$(kubectl config current-context 2>/dev/null)"
if [ "$CTX" != "kind-$CLUSTER_NAME" ]; then
  bad "active context is '$CTX', expected 'kind-$CLUSTER_NAME' — refusing to continue"
  exit 1
fi
ok "isolated kubeconfig, context $CTX"

W=signalpilot-gateway-notebook-workload
B=signalpilot-gateway-org-binding
GW="--as=sp-gateway --as-group=signalpilot-gateway-ec2"

kubectl create ns signalpilot >/dev/null 2>&1
kubectl apply -f "$HERE/gateway-rbac.yaml" >/dev/null 2>&1
kubectl apply -f "$HERE/gateway-runtime-rbac.yaml" >/dev/null 2>&1

# --- B1: the VAP's CEL must compile in the API server -------------------------------
step "B1 — ValidatingAdmissionPolicy CEL compilation"
vap_out="$(kubectl apply -f "$ADMISSION/restrict-rbac-writes-validatingadmissionpolicy.yaml" 2>&1)"
if [ $? -eq 0 ]; then
  ok "VAP + binding accepted (all validations[].expression compiled)"
else
  bad "VAP rejected — CEL does not compile:"
  printf '%s\n' "$vap_out" | head -5 | sed 's/^/          /'
fi
sleep 2

# --- B2: rule-by-rule ALLOW / DENY against a real API server ------------------------
# Server-side dry-run runs the full admission chain without persisting anything.
step "B2 — VAP rule matrix (server-side dry-run)"
kubectl create ns sp-nb-tenant-a >/dev/null 2>&1
kubectl label ns sp-nb-tenant-a signalpilot.dev/tenant=user --overwrite >/dev/null 2>&1
kubectl create ns plain-ns >/dev/null 2>&1
kubectl create sa signalpilot-gateway -n signalpilot >/dev/null 2>&1

# admit <desc> <allow|deny> ; manifest on stdin
admit() {
  local desc="$1" want="$2" out got=allow
  out="$(kubectl apply --dry-run=server -f - 2>&1)" || got=deny
  if [ "$got" = "$want" ]; then ok "$(printf '%-50s expect=%-5s got=%s' "$desc" "$want" "$got")"
  else bad "$(printf '%-50s expect=%-5s got=%s\n            %s' "$desc" "$want" "$got" "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-150)")"; fi
}
rb() { # rb <name> <namespace> <roleRefName> <subjects-yaml>
  printf 'apiVersion: rbac.authorization.k8s.io/v1\nkind: RoleBinding\nmetadata: {name: %s, namespace: %s}\nroleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: %s}\nsubjects: %s\n' "$1" "$2" "$3" "$4"
}
SA_SUBJ='[{kind: ServiceAccount, name: signalpilot-gateway, namespace: signalpilot}]'
GOOD_SUBJ='[{kind: ServiceAccount, name: signalpilot-gateway, namespace: signalpilot}, {kind: Group, name: signalpilot-gateway-ec2, apiGroup: rbac.authorization.k8s.io}]'

admit "ALLOW legit org-binding in labeled tenant ns" allow < <(rb "$B" sp-nb-tenant-a "$W" "$GOOD_SUBJ")
admit "R1 DENY ClusterRoleBinding of workload role" deny <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: evil-clusterwide}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: $W}
subjects: [{kind: Group, name: signalpilot-gateway-ec2, apiGroup: rbac.authorization.k8s.io}]
EOF
admit "R2 DENY org-binding in unlabeled ns"        deny  < <(rb "$B" plain-ns "$W" "$SA_SUBJ")
admit "R2 DENY org-binding in kube-system"         deny  < <(rb "$B" kube-system "$W" "$SA_SUBJ")
admit "R3 DENY unpinned binding name"              deny  < <(rb attacker-extra-binding sp-nb-tenant-a "$W" "$SA_SUBJ")
admit "R4 DENY User subject"                       deny  < <(rb "$B" sp-nb-tenant-a "$W" '[{kind: User, name: alice@example.com, apiGroup: rbac.authorization.k8s.io}]')
admit "R4 DENY system:* group subject"             deny  < <(rb "$B" sp-nb-tenant-a "$W" '[{kind: Group, name: system:authenticated, apiGroup: rbac.authorization.k8s.io}]')
admit "R4 DENY ServiceAccount without namespace"   deny  < <(rb "$B" sp-nb-tenant-a "$W" '[{kind: ServiceAccount, name: signalpilot-gateway}]')
# Controls: the policy must not disturb unrelated RBAC anywhere in the cluster.
admit "CONTROL allow unrelated RoleBinding (view)" allow < <(rb some-team-view kube-system view '[{kind: Group, name: platform-team, apiGroup: rbac.authorization.k8s.io}]')
admit "CONTROL allow unrelated ClusterRoleBinding" allow <<'EOF'
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: some-team-view-crb}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: view}
subjects: [{kind: Group, name: platform-team, apiGroup: rbac.authorization.k8s.io}]
EOF

# --- B3: optional Kyverno fallback path on the same cluster --------------------------
if [ "$RUN_KYVERNO_E2E" -eq 1 ]; then
  step "B3 — Kyverno fallback path (live)"
  if ! command -v helm >/dev/null 2>&1; then
    bad "helm not found; skipping Kyverno e2e"
  else
    kubectl delete -f "$ADMISSION/restrict-rbac-writes-validatingadmissionpolicy.yaml" >/dev/null 2>&1
    helm repo add kyverno https://kyverno.github.io/kyverno/ >/dev/null 2>&1
    helm repo update kyverno >/dev/null 2>&1
    # The chart's DEFAULT webhook namespaceSelector excludes kube-system, which would
    # silently exempt the single most valuable target this policy exists to protect.
    # See admission/README.md → "Kyverno namespace exclusions".
    helm install kyverno kyverno/kyverno -n kyverno --create-namespace \
      --version "$KYVERNO_CHART_VERSION" \
      --set-json 'config.webhooks.namespaceSelector.matchExpressions=[]' \
      --set-json 'config.resourceFiltersExcludeNamespaces=["kube-system","kube-public","kube-node-lease"]' \
      --wait --timeout 8m >/dev/null 2>&1 || bad "kyverno helm install failed"
    sleep 5
    if kubectl apply -f "$ADMISSION/restrict-rbac-writes-kyverno.yaml" >/dev/null 2>&1; then
      ok "Kyverno ClusterPolicy admitted (rule bodies are well-formed)"
    else
      bad "Kyverno rejected the ClusterPolicy:"
      kubectl apply -f "$ADMISSION/restrict-rbac-writes-kyverno.yaml" 2>&1 | head -4 | sed 's/^/          /'
    fi
    sleep 10
    nssel="$(kubectl get validatingwebhookconfiguration kyverno-resource-validating-webhook-cfg \
              -o jsonpath='{.webhooks[0].namespaceSelector}' 2>/dev/null)"
    if printf '%s' "$nssel" | grep -q kube-system; then
      bad "Kyverno webhook still excludes kube-system — the policy CANNOT protect it"
    else
      ok "Kyverno webhook covers kube-system"
    fi
    admit "KYV ALLOW legit org-binding"              allow < <(rb "$B" sp-nb-tenant-a "$W" "$GOOD_SUBJ")
    admit "KYV R2 DENY unlabeled ns (apiCall)"       deny  < <(rb "$B" plain-ns "$W" "$SA_SUBJ")
    admit "KYV R2 DENY kube-system"                  deny  < <(rb "$B" kube-system "$W" "$SA_SUBJ")
    admit "KYV R3 DENY unpinned binding name"        deny  < <(rb attacker-extra-binding sp-nb-tenant-a "$W" "$SA_SUBJ")
    admit "KYV R4 DENY User subject"                 deny  < <(rb "$B" sp-nb-tenant-a "$W" '[{kind: User, name: alice@example.com, apiGroup: rbac.authorization.k8s.io}]')
    admit "KYV R4 DENY system:* group"               deny  < <(rb "$B" sp-nb-tenant-a "$W" '[{kind: Group, name: system:authenticated, apiGroup: rbac.authorization.k8s.io}]')
    # Restore the default path for the migration phase.
    kubectl delete clusterpolicy restrict-rbac-writes-signalpilot >/dev/null 2>&1
    kubectl apply -f "$ADMISSION/restrict-rbac-writes-validatingadmissionpolicy.yaml" >/dev/null 2>&1
    sleep 2
  fi
fi

# --- B4: migration script, on a cluster in the pre-SP-SEC-009 state ------------------
step "B4 — migrate-sp-sec-009.sh against a pre-migration cluster"
kubectl apply -f - >/dev/null 2>&1 <<'EOF'
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: {name: signalpilot-gateway-runtime}
rules:
- apiGroups: [""]
  resources: [pods, secrets, namespaces]
  verbs: [create, get, list, delete, patch]
- apiGroups: [""]
  resources: [pods/exec]
  verbs: [create, get]
- apiGroups: [rbac.authorization.k8s.io]
  resources: [roles, rolebindings]
  verbs: [create, get, list, delete, patch]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: signalpilot-gateway-runtime-binding}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: signalpilot-gateway-runtime}
subjects: [{kind: Group, name: signalpilot-gateway-ec2, apiGroup: rbac.authorization.k8s.io}]
EOF
for ns in sp-nb-org-alpha sp-nb-org-beta; do
  kubectl create ns "$ns" >/dev/null 2>&1
  kubectl label ns "$ns" signalpilot.dev/tenant=user --overwrite >/dev/null 2>&1
  kubectl apply -n "$ns" -f - >/dev/null 2>&1 <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: signalpilot-gateway-org-role, namespace: $ns}
rules:
- apiGroups: [""]
  resources: [pods, secrets]
  verbs: [create, get, list, delete]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: signalpilot-gateway-org-binding
  namespace: $ns
  labels: {signalpilot.ai/managed-by: gateway}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: Role, name: signalpilot-gateway-org-role}
subjects: [{kind: Group, name: signalpilot-gateway-ec2, apiGroup: rbac.authorization.k8s.io}]
EOF
done
# Pre-migration, the legacy grant must actually be exploitable — otherwise the
# post-migration assertions below prove nothing.
check yes "PRE: gateway can read Secrets in kube-system" "$(kubectl auth can-i $GW get secrets -n kube-system 2>&1 | tail -1)"

bash "$HERE/migrate-sp-sec-009.sh" >/dev/null 2>&1
check present "dry-run must NOT delete the legacy ClusterRole" \
  "$(kubectl get clusterrole signalpilot-gateway-runtime >/dev/null 2>&1 && echo present || echo absent)"

if bash "$HERE/migrate-sp-sec-009.sh" --apply >/dev/null 2>&1; then
  ok "migration --apply completed with verification OK"
else
  bad "migration --apply reported verification failures"
fi
if bash "$HERE/migrate-sp-sec-009.sh" --apply >/dev/null 2>&1; then
  ok "migration is idempotent (second --apply also clean)"
else
  bad "second --apply run FAILED — script is not idempotent"
fi

# --- B5: the gateway must be able to recreate the binding with bootstrap rights only --
step "B5 — gateway recreation under least privilege"
if kubectl $GW apply -f - >/dev/null 2>&1 < <(rb "$B" sp-nb-org-alpha "$W" '[{kind: Group, name: signalpilot-gateway-ec2, apiGroup: rbac.authorization.k8s.io}]'); then
  ok "migrated ns: gateway recreated $B via bootstrap 'bind' grant"
else
  bad "migrated ns: gateway could NOT recreate $B (check the clusterroles/bind resourceNames pin)"
fi
# Brand-new namespace, in ensure_org_namespace order: Namespace -> RoleBinding -> netpol.
kubectl $GW create ns sp-nb-org-gamma >/dev/null 2>&1
kubectl $GW label ns sp-nb-org-gamma signalpilot.dev/tenant=user --overwrite >/dev/null 2>&1
if kubectl $GW apply -f - >/dev/null 2>&1 < <(rb "$B" sp-nb-org-gamma "$W" '[{kind: Group, name: signalpilot-gateway-ec2, apiGroup: rbac.authorization.k8s.io}]'); then
  ok "new ns: Namespace then RoleBinding succeeded"
else
  bad "new ns: RoleBinding creation failed"
fi
np='apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: sp-nb-default-deny, namespace: sp-nb-org-gamma}
spec: {podSelector: {}, policyTypes: [Ingress, Egress]}'
if printf '%s\n' "$np" | kubectl $GW apply -f - >/dev/null 2>&1; then
  ok "new ns: NetworkPolicy AFTER the RoleBinding succeeded (ordering fix holds)"
else
  bad "new ns: NetworkPolicy failed even after the RoleBinding"
fi
# And the ordering bug itself: netpol BEFORE the RoleBinding must 403.
kubectl $GW create ns sp-nb-org-delta >/dev/null 2>&1
kubectl $GW label ns sp-nb-org-delta signalpilot.dev/tenant=user --overwrite >/dev/null 2>&1
np_delta="${np//sp-nb-org-gamma/sp-nb-org-delta}"
if printf '%s\n' "$np_delta" | kubectl $GW apply -f - >/dev/null 2>&1; then
  bad "NetworkPolicy before RoleBinding SUCCEEDED — least privilege is not in effect"
else
  ok "NetworkPolicy before RoleBinding is 403 (why RBAC must be created first)"
fi

# --- B6: post-migration authorization matrix ----------------------------------------
step "B6 — post-migration kubectl auth can-i"
can(){ check "$1" "$2" "$(kubectl auth can-i $GW ${@:3} 2>&1 | tail -1)"; }
can no  "DENY get secrets in kube-system"        get secrets -n kube-system
can no  "DENY list secrets in default"           list secrets -n default
can no  "DENY get secrets in gateway ns"         get secrets -n signalpilot
can no  "DENY create pods/exec in kube-system"   create pods/exec -n kube-system
can no  "DENY create pods in default"            create pods -n default
can no  "DENY create roles -A"                   create roles -A
can no  "DENY escalate roles -A"                 escalate roles -A
can no  "DENY delete namespaces"                 delete namespaces
can no  "DENY list nodes"                        list nodes
can no  "DENY get secrets in non-tenant ns"      get secrets -n plain-ns
can no  "DENY delete rolebindings in tenant ns"  delete rolebindings -n sp-nb-org-alpha
can yes "ALLOW get secrets in tenant ns"         get secrets -n sp-nb-org-alpha
can yes "ALLOW create pods in tenant ns"         create pods -n sp-nb-org-alpha
can yes "ALLOW create pods/exec in tenant ns"    create pods/exec -n sp-nb-org-alpha
can yes "ALLOW create netpols in tenant ns"      create networkpolicies -n sp-nb-org-alpha
can yes "ALLOW create namespaces"                create namespaces
can yes "ALLOW create rolebindings"              create rolebindings -A
can yes "ALLOW list namespaces (jwt gc)"         list namespaces

# --- B7: pods/exec restriction (F-21) — only provable on a live cluster --------------
# `kyverno test` cannot evaluate this policy at all: it matches operations [CONNECT] and
# the CLI only ever simulates CREATE, so every resource returns "Pass / Excluded".
# See restrict-pod-exec.test.yaml for the full explanation.
if [ "$RUN_KYVERNO_E2E" -eq 1 ] && command -v helm >/dev/null 2>&1; then
  step "B7 — pods/exec restriction, live (F-21)"
  # require-gvisor would block these plain test pods; keep it out of this cluster.
  kubectl delete clusterpolicy require-gvisor-runtime-class --ignore-not-found >/dev/null 2>&1
  if kubectl apply -f "$ADMISSION/restrict-pod-exec-kyverno.yaml" >/dev/null 2>&1; then
    ok "restrict-pod-exec ClusterPolicy admitted (rule bodies are well-formed)"
  else
    bad "restrict-pod-exec ClusterPolicy REJECTED — pods/exec is entirely unrestricted:"
    kubectl apply -f "$ADMISSION/restrict-pod-exec-kyverno.yaml" 2>&1 | grep -o 'path: spec\.rules.*' | head -2 | sed 's/^/          /'
  fi
  sleep 8
  kubectl create ns sp-nb-exec >/dev/null 2>&1
  kubectl label ns sp-nb-exec signalpilot.dev/tenant=user --overwrite >/dev/null 2>&1
  mkpod() {
    kubectl run "$1" -n sp-nb-exec --image=busybox --restart=Never \
      --overrides="{\"spec\":{\"containers\":[{\"name\":\"$2\",\"image\":\"busybox\",\"command\":[\"sleep\",\"3600\"]}]}}" \
      >/dev/null 2>&1
  }
  mkpod nb-abc123def456 notebook
  mkpod badname-pod notebook
  mkpod nb-abc123def999 sidecar
  kubectl wait --for=condition=Ready pod/nb-abc123def456 pod/badname-pod pod/nb-abc123def999 \
    -n sp-nb-exec --timeout=120s >/dev/null 2>&1
  execq() { # execq <want allow|deny> <desc> <pod> <container>
    local want="$1" desc="$2" got=allow
    kubectl exec -n sp-nb-exec "$3" -c "$4" -- true >/dev/null 2>&1 || got=deny
    if [ "$got" = "$want" ]; then ok "$(printf '%-50s expect=%-5s got=%s' "$desc" "$want" "$got")"
    else bad "$(printf '%-50s expect=%-5s got=%s' "$desc" "$want" "$got")"; fi
  }
  execq allow "exec nb-<12hex> container=notebook"  nb-abc123def456 notebook
  execq deny  "exec non-conforming pod name"        badname-pod     notebook
  execq deny  "exec wrong container name"           nb-abc123def999 sidecar
fi

step "Result"
printf '  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
