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
