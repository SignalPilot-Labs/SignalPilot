# Admission Policies — Require gVisor RuntimeClass

**Default install path:** apply `require-gvisor-validatingadmissionpolicy.yaml` (k8s >= 1.30 with `ValidatingAdmissionPolicy` GA). **Do NOT also install the Kyverno policy** — double-enforcement risks conflicting failure modes and policy conflicts. Install Kyverno path ONLY if your cluster is < 1.30 or VAP is disabled.

## Why this exists (F-12)

F-5 added a gateway-side preflight check that verifies the `gvisor` RuntimeClass exists in
the cluster before creating any notebook pod.  F-12 closes the bypass where a pod is created
by a path that is NOT the gateway (operator `kubectl apply`, another controller, a rogue
workload).  Admission policy is the only enforcement that survives a malicious or buggy
controller.

## Namespace targeting

Both policies match pods created in namespaces with the label:

```
signalpilot.dev/tenant: user
```

The gateway sets this label on every tenant namespace it creates via
`orchestrator/namespaces.py::_namespace_manifest`.  If you provision tenant namespaces by a
different mechanism, ensure this label is applied.

## Default: ValidatingAdmissionPolicy (k8s >= 1.30)

```bash
kubectl apply -f require-gvisor-validatingadmissionpolicy.yaml
```

Requires k8s >= 1.30 (VAP is GA).  The policy and binding are cluster-scoped resources; you
need cluster-admin to apply.

## Fallback: Kyverno (k8s < 1.30)

```bash
kubectl apply -f require-gvisor-kyverno.yaml
```

Requires Kyverno to be installed.  Install Kyverno first:
`https://kyverno.io/docs/installation/`

## pods/exec narrowing — Kyverno (F-21)

### Why RBAC is insufficient

The gateway ServiceAccount holds a broad `pods/exec create` permission in each
tenant namespace. Kubernetes RBAC `resourceNames` does not support prefix wildcards,
and notebook pod names are dynamic (`nb-<12hex>`), so RBAC cannot restrict which
pods may be exec'd. This admission policy fills the gap.

This is a **defense-in-depth** layer. It does NOT replace:
- The AST gate (`tests/test_pod_exec_caller_invariant.py`, R4 C4) — verifies the
  call path in gateway code.
- The hardcoded `"notebook"` container name in `kubernetes.py::pod_exec_io`.

### Install — ValidatingAdmissionPolicy (default, k8s >= 1.30)

```bash
kubectl apply -f restrict-pod-exec-validatingadmissionpolicy.yaml
```

Default path, mirrors the gVisor VAP. A CONNECT on the `pods/exec` subresource is
allowed only when `request.name` matches `^nb-[0-9a-f]{12}$` and
`object.container == 'notebook'`. No Kyverno install needed. Cluster-scoped; you
need cluster-admin to apply.

### Install — Kyverno (fallback, k8s < 1.30 or VAP disabled)

```bash
kubectl apply -f restrict-pod-exec-kyverno.yaml
```

Apply after the gVisor policy. The policy is cluster-scoped; you need cluster-admin.
Do NOT install both the VAP and Kyverno forms.

### What the policy enforces

Two rules, independently auditable:

1. **restrict-pod-name** — exec is only permitted into pods whose name matches
   `^nb-[0-9a-f]{12}$`. Any other pod name is denied.
2. **restrict-container** — exec is only permitted when the target container is
   `notebook`. Other container names are denied.

The policy is **SA-agnostic**: no ServiceAccount or username pin. Namespace label
`signalpilot.dev/tenant: user` scopes enforcement to tenant namespaces (the same
label used by `require-gvisor-kyverno.yaml`). Operators using a non-default
`SP_GATEWAY_SERVICE_ACCOUNT` need zero policy edits.

### Test

```bash
kyverno test deploy/k8s/admission/
```

Should exit 0 with all cases passing.

---

## Verification

After applying the policy, test it:

```bash
# Should be DENIED
kubectl run test-no-gvisor --image=busybox \
  --namespace=<a-tenant-namespace> \
  --restart=Never -- sleep 1

# Should be ALLOWED
kubectl run test-gvisor --image=busybox \
  --namespace=<a-tenant-namespace> \
  --restart=Never \
  --overrides='{"spec":{"runtimeClassName":"gvisor"}}' -- sleep 1
```
