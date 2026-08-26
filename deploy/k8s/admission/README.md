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

## pods/exec narrowing — removed (Notebook Runtime v2)

The former `restrict-pod-exec-*` policies narrowed the gateway's `pods/exec`
grant to notebook pods. Notebook Runtime v2 moved notebook compute off the
cluster and deleted the grant itself, so the policies were removed with it.
History: git log -- deploy/k8s/admission/restrict-pod-exec-*.

## RBAC bootstrap confinement (SP-SEC-009)

### Why RBAC is insufficient

The gateway creates tenant notebook namespaces on demand, so it cannot be given a
purely static namespaced Role. Its one retained cluster-wide write capability is
"create a RoleBinding" (`ClusterRole signalpilot-gateway-runtime-bootstrap` /
`signalpilot-gateway-rbac-provisioner`), which it uses to bind the ClusterRole
`signalpilot-gateway-notebook-workload` into the `sp-nb-*` namespace it just created.

RBAC pins **what** may be bound - `bind` on `clusterroles` with
`resourceNames: [signalpilot-gateway-notebook-workload]` - but it cannot pin **where**.
Without an admission policy, a compromised gateway could create the same RoleBinding in
`kube-system` and read every Secret there. That is the SP-SEC-009 escalation path.

### Install - ValidatingAdmissionPolicy (default, k8s >= 1.30)

```bash
kubectl apply -f restrict-rbac-writes-validatingadmissionpolicy.yaml
```

### Install - Kyverno (fallback, k8s < 1.30 or VAP disabled)

```bash
kubectl apply -f restrict-rbac-writes-kyverno.yaml
```

Do NOT install both. The Kyverno namespace-label rule needs `get` on namespaces for the
Kyverno SA (granted by the default `kyverno:background-controller` aggregation).

### What the policy enforces

For any RBAC object whose `roleRef` is `signalpilot-gateway-notebook-workload`:

1. **deny-clusterwide-workload-binding** - it may never be the target of a
   `ClusterRoleBinding`. This is the exact regression that produced SP-SEC-009.
2. **restrict-workload-binding-namespace** - a `RoleBinding` to it may only exist in a
   namespace labeled `signalpilot.dev/tenant: user`.
3. **restrict-workload-binding-name** - that RoleBinding must be named
   `signalpilot-gateway-org-binding`, so the capability is one auditable object per
   namespace rather than an unbounded set.
4. **restrict-workload-binding-subject-kinds** / **-subject-groups** - subjects may only
   be namespaced ServiceAccounts or named Groups. `User` subjects and any `system:*`
   group are denied (`system:authenticated` would hand the workload verbs, Secrets
   included, to every authenticated principal).

   In the Kyverno form this is deliberately **two rules**, not one. `deny.conditions`
   accepts either a flat `all:` list or a flat `any:` list; nesting an `any:` block as an
   element of `all:` is not valid Kyverno and invalidates the whole ClusterPolicy. The
   VAP form expresses both checks in a single CEL expression, where boolean nesting is
   fine.

...and for any **core/v1 Namespace** CREATE or UPDATE (rules 5-7, see the pivot below):

5. **restrict-tenant-label-to-tenant-namespaces** - the label `signalpilot.dev/tenant`
   (any value) may only appear on a namespace whose name starts with `sp-nb-`, the
   `DEFAULT_NAMESPACE_PREFIX` in `orchestrator/namespaces.py`.
6. **deny-tenant-label-on-system-namespaces** - `kube-*`, `default`, `signalpilot` and
   `kyverno` may never carry the label, whatever the prefix is set to.
7. **deny-tenant-label-adoption-on-update** - the label may not be *added* to an existing
   namespace unless that namespace also carries `signalpilot.ai/managed-by: gateway`.
   `ensure_org_namespace` sets both labels in the single CREATE call, so a namespace
   acquiring the tenant label later is being adopted, not bootstrapped.

### The namespace-label pivot — why rules 5-7 exist

Rule 2 confines the workload RoleBinding to namespaces labeled
`signalpilot.dev/tenant=user`. Governing only `rbac.authorization.k8s.io` left that
predicate **attacker-controlled**, because the gateway also holds
`namespaces: [create, get, list, patch]` cluster-wide
(`gateway-rbac.yaml`, `gateway-runtime-rbac.yaml`):

```
kubectl label ns kube-system signalpilot.dev/tenant=user     # step 1 — permitted by RBAC
kubectl apply -f org-binding-in-kube-system.yaml             # step 2 — now rule-compliant
# -> secrets/pods/pods-exec in kube-system == every ServiceAccount token on the cluster
```

Step 1 was allowed by the pre-fix policy: its `matchConstraints` covered only
`rolebindings` and `clusterrolebindings`. `validate-admission-policies.sh` phase **B0**
now asserts, as the gateway identity and before any policy is installed, that step 1
*succeeds* — so the B2b denials cannot be mistaken for an RBAC 403 — and B2b then
asserts the same write is rejected by name (`restrict-rbac-writes-signalpilot`).

If you override `SP_NOTEBOOK_NAMESPACE_PREFIX`, you must change `tenantPrefix` in the VAP
and the `sp-nb-*` value in the Kyverno rule to match. It fails **closed**: the gateway's
own namespace CREATE is denied on the first session.

**Scope:** unlike the two policies above, this one has **no `namespaceSelector`** - it
matches every namespace on purpose, because the namespaces it must protect are the
unrelated ones. It is also **caller-agnostic**: it constrains the object, not the
requester, so a non-default `SP_GATEWAY_SERVICE_ACCOUNT` or EKS access-entry group needs
no policy edit, and cluster-admins are bound by it too.

### Test

```bash
# Kyverno CLI unit tests only (no cluster needed)
deploy/k8s/validate-admission-policies.sh

# ...plus a throwaway kind cluster: real CEL compilation, rule-by-rule ALLOW/DENY,
# the migration script, and `kubectl auth can-i`
deploy/k8s/validate-admission-policies.sh --e2e

# ...and additionally install Kyverno in that cluster to exercise the fallback path
deploy/k8s/validate-admission-policies.sh --e2e --with-kyverno
```

Do **not** run a bare `kyverno test deploy/k8s/admission/`. The CLI only auto-discovers
files literally named `kyverno-test.yaml`; against this repo's `<policy>.test.yaml`
convention it prints `No test yamls available` and **exits 0**. Use the wrapper, or pass
`--file-name <policy>.test.yaml` explicitly.

`restrict-rbac-writes.test.yaml` covers rules 1, 3, 4a, 4b, 5 and 6, plus the ALLOW path
of rule 2. Two DENY paths are not expressible offline and are asserted against a live
cluster instead:

- **rule 2 DENY** resolves the target namespace's label with a context `apiCall` that the
  CLI cannot serve (and Value-file overrides are keyed by name only, while cases A/D/F
  share a name).
- **rule 7** matches `operations: [UPDATE]` and the CLI only ever simulates CREATE, so it
  reports Skip/Excluded for every resource — the same limitation as
  `restrict-pod-exec.test.yaml`. Covered by the `labelns` cases in B2b/B3.

---

## Validation findings

Everything below was found by actually running the policies (Kyverno CLI 1.18.2, kind
0.32.0, k8s 1.34.0) rather than by reading them, and is fixed in-tree. They are recorded
because each one is invisible to a YAML-parse check and each failed **open**.

1. **The `restrict-rbac-writes` Kyverno ClusterPolicy was structurally invalid.**
   Rule 4 nested an `any:` block inside `all:`; Kyverno parses that as a condition with
   no `operator` and rejects the entire object:
   `path: spec.rules[3].validate.foreach.deny.conditions.any[1].: entered value of
   'operator' is invalid`. Because a ClusterPolicy is one object, `kubectl apply` failed
   outright and **none of the four rules were installed** — the whole fallback path was a
   no-op. Fixed by splitting rule 4 into two flat-`all:` rules.

2. **The `restrict-pod-exec` Kyverno ClusterPolicy (F-21) was invalid for the same class
   of reason.** It used `operator: NotMatch`, which does not exist in Kyverno — the valid
   set is `Equals/NotEquals/In/NotIn/AnyIn/AllIn/AnyNotIn/AllNotIn` plus the numeric and
   `Duration` comparators. Regex matching is done with the JMESPath `regex_match()`
   function. Same consequence: policy rejected, `pods/exec` entirely unrestricted. Fixed.

3. **`kyverno test` reports success on an invalid policy.** With either defect above in
   place the suite printed `Test Summary: 48 tests passed and 0 tests failed` while every
   individual row read `Skip / Invalid Policy`. `validate-admission-policies.sh`
   therefore greps for `Invalid Policy` and fails the run explicitly; do not rely on the
   summary line alone.

4. **`resourceSpecs:` in a test result is silently ignored unless `resources:` is also
   set**, and a result with no effective resource filter is asserted against *every*
   loaded resource. In `commands/test/output.go` the `ResourceSpecs` loop sits inside
   `if test.Resources != nil`, and `if len(resources) == 0` then falls through to "check
   all". Use `resources: [<namespace>/<name>]`, which disambiguates by namespace.

5. **A resource the policy does not match is reported as `Pass`, whatever the test
   declared.** `output.go` sets `Result = Pass; Reason = "Excluded"` unconditionally when
   a resource produced no rule response. Consequence: `restrict-pod-exec` cannot be
   tested by `kyverno test` at all — it matches `operations: [CONNECT]` and the CLI only
   simulates CREATE, so a `result: fail` assertion there is a false green. Those rules are
   validated only by the live `kubectl exec` checks in Phase B7.

6. **The previous `*.test.yaml` files had never executed.** Both used a top-level
   `namespaces:` key and `resource:` / `namespace:` keys on results. None of those exist
   in the `cli.kyverno.io/v1alpha1` Test schema and the decoder is strict, so both files
   failed to load: `json: unknown field "namespaces"`. Namespace labels belong in a Value
   file (`<policy>-values.yaml`), whose `ValuesSpec` is **inlined** — a `spec:` wrapper is
   ignored.

7. **`restrict-rbac-writes` governed the RoleBinding but not its own precondition.**
   `matchConstraints` (VAP) and the rule `match` blocks (Kyverno) covered only
   `rolebindings`/`clusterrolebindings`, while the gateway holds `namespaces: patch`
   cluster-wide. Rule 2's "namespace must be labeled `signalpilot.dev/tenant=user`" was
   therefore a check the attacker could satisfy: label `kube-system`, then create a
   fully-compliant binding there. Confirmed on a live cluster — as the gateway identity,
   `kubectl label ns kube-system signalpilot.dev/tenant=user` was **ALLOWED** by the
   pre-fix policy set (now asserted as the B0 negative control, so the fix cannot silently
   regress into "denied by RBAC anyway"). Fixed by rules 5-7, which govern
   `core/v1 namespaces` CREATE and UPDATE.

   Generalisation worth carrying forward: **if a policy's predicate is a mutable field,
   the write to that field is part of the policy's attack surface.** A label-based
   allowlist is only as strong as the weakest identity that can set the label.

### Kyverno namespace exclusions — the fallback path does NOT protect kube-system by default

This one is an install-time property of Kyverno, not of the policy, and it defeats the
policy's primary purpose if left alone.

The Kyverno Helm chart ships `config.webhooks.namespaceSelector` excluding `kube-system`,
and `config.resourceFilters` blanket-excluding `kube-system`, `kube-public` and
`kube-node-lease`. The generated `ValidatingWebhookConfiguration` therefore never sees
RoleBinding writes in those namespaces. Verified on a live cluster: with a default
Kyverno install, binding `signalpilot-gateway-notebook-workload` into `kube-system` was
**ALLOWED** — precisely the escalation this policy exists to stop, and the example named
in its own rationale.

The `ValidatingAdmissionPolicy` form has no such carve-out and denies it correctly. **This
is a further reason to prefer the VAP path.** If you must use Kyverno, install it with the
exclusions cleared (verified to close the gap):

```bash
helm install kyverno kyverno/kyverno -n kyverno --create-namespace \
  --set-json 'config.webhooks.namespaceSelector.matchExpressions=[]' \
  --set-json 'config.resourceFiltersExcludeNamespaces=["kube-system","kube-public","kube-node-lease"]'
```

Kyverno still excludes its own namespace (`config.excludeKyvernoNamespace`, default
`true`); that is fine and should be left alone. Review the operability trade-off Kyverno
documents at <https://kyverno.io/docs/installation/#security-vs-operability> before
clearing exclusions on a production cluster — evaluating every `kube-system` write adds
the admission webhook to that path.

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

For `restrict-rbac-writes` (SP-SEC-009). Run these as the gateway identity where
possible (`kubectl --as=...`); as cluster-admin they still exercise the policy, since it
is caller-agnostic:

```bash
# Should be DENIED — workload ClusterRole bound cluster-wide
kubectl create clusterrolebinding sp-escalate-test \
  --clusterrole=signalpilot-gateway-notebook-workload \
  --group=signalpilot-gateway-ec2

# Should be DENIED — bound into an unlabeled namespace
kubectl -n kube-system create rolebinding signalpilot-gateway-org-binding \
  --clusterrole=signalpilot-gateway-notebook-workload \
  --group=signalpilot-gateway-ec2

# Should be DENIED — wrong binding name in a real tenant namespace
kubectl -n <a-tenant-namespace> create rolebinding sp-extra-binding \
  --clusterrole=signalpilot-gateway-notebook-workload \
  --group=signalpilot-gateway-ec2

# Should be ALLOWED — this is exactly what the gateway creates itself
kubectl -n <a-tenant-namespace> create rolebinding signalpilot-gateway-org-binding \
  --clusterrole=signalpilot-gateway-notebook-workload \
  --group=signalpilot-gateway-ec2
```
