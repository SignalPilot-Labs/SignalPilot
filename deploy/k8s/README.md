# SignalPilot Gateway — Kubernetes Deployment Notes

## Prerequisites

### (a) NetworkPolicy-enforcing CNI is required

The NetworkPolicy resources created by `ensure_org_namespace` are only enforced
if the cluster has a CNI plugin that supports NetworkPolicy. Examples of compatible
CNIs:

- [Calico](https://docs.tigera.io/calico/latest/about/)
- [Cilium](https://cilium.io/)
- AWS VPC CNI with network policy add-on enabled
- Google GKE Dataplane V2

Clusters without a policy-enforcing CNI will still run, but the `default-deny`
and `allow-gateway-ingress-and-egress` NetworkPolicies will have **no effect**.
Cross-org isolation at the network layer will not exist.

**Verify CNI enforces policy:** see the verification section below.

### (b) Apply `gateway-rbac.yaml` before the first session

```bash
# Create the signalpilot namespace if it does not exist.
kubectl create namespace signalpilot --dry-run=client -o yaml | kubectl apply -f -

# Apply cluster-scope RBAC bootstrap.
kubectl apply -f deploy/k8s/gateway-rbac.yaml
```

This provisions:
- `ServiceAccount signalpilot-gateway` in the `signalpilot` namespace.
- `ClusterRole signalpilot-gateway-namespaces` — namespace create/get/list/patch.
- `ClusterRole signalpilot-gateway-rbac-provisioner` — roles/rolebindings create/get/patch.
- Two `ClusterRoleBinding` resources binding the SA to these ClusterRoles.

The gateway pod must run as this ServiceAccount. Per-namespace Roles and
RoleBindings are created lazily by the gateway on first session per org.

### (c) Required environment variables for the gateway pod

| Variable | Example | Purpose |
|---|---|---|
| `SP_DEPLOYMENT_MODE` | `cloud` | Enables cloud-mode paths. |
| `SP_NOTEBOOK_UPSTREAM_MODE` | `pod_ip` | Required for `KubernetesOrchestrator`. |
| `SP_PUBLIC_GATEWAY_URL` | `https://gateway.example.com` | Gateway URL injected into pods. |
| `SP_PUBLIC_GATEWAY_PORT` | `3300` | Port used in NetworkPolicy egress rules. |
| `SP_GATEWAY_NAMESPACE` | `signalpilot` | Namespace where the gateway pod runs. |
| `SP_GATEWAY_POD_SELECTOR` | `app=signalpilot-gateway` | Single k=v label selector for gateway pods. Used in NetworkPolicy ingress. |
| `SP_GATEWAY_SERVICE_ACCOUNT` | `signalpilot-gateway` | SA name for per-namespace RoleBinding subjects. |
| `SP_NOTEBOOK_NAMESPACE_PREFIX` | `sp-nb` | Prefix for org namespaces. **Set at bootstrap, never change** (see warning below). |
| `SP_NOTEBOOK_EGRESS_CIDR` | `52.0.0.0/8` | (Optional) Allow notebook pods to reach this CIDR on port 443 (e.g. S3). |
| `SP_NOTEBOOK_IMAGE` | `your-registry/notebook:tag` | Container image for notebook pods. |

### (d) Verification: cross-namespace network isolation

After deploying, verify that the CNI enforces cross-org isolation:

```bash
# 1. Get pod names for two orgs.
ORG_A_NS=sp-nb-<hash-for-org-a>
ORG_B_NS=sp-nb-<hash-for-org-b>
ORG_A_POD=$(kubectl get pods -n $ORG_A_NS -o jsonpath='{.items[0].metadata.name}')
ORG_B_POD_IP=$(kubectl get pods -n $ORG_B_NS -o jsonpath='{.items[0].status.podIP}')

# 2. Try to reach Org B's pod from Org A's pod — should time out (default-deny).
kubectl exec -n $ORG_A_NS $ORG_A_POD -- nc -zv -w 3 $ORG_B_POD_IP 2718
# Expected: nc: Connection timed out (or similar failure)

# 3. Verify gateway can reach Org A's pod (from gateway namespace).
GATEWAY_POD=$(kubectl get pods -n signalpilot -l app=signalpilot-gateway -o jsonpath='{.items[0].metadata.name}')
ORG_A_POD_IP=$(kubectl get pods -n $ORG_A_NS -o jsonpath='{.items[0].status.podIP}')
kubectl exec -n signalpilot $GATEWAY_POD -- nc -zv -w 3 $ORG_A_POD_IP 2718
# Expected: Connection succeeded
```

If the cross-namespace `nc` succeeds (step 2), the CNI is **not** enforcing
NetworkPolicy. Investigate the CNI configuration before proceeding.

### (e) One-way config: SP_NOTEBOOK_NAMESPACE_PREFIX

`SP_NOTEBOOK_NAMESPACE_PREFIX` determines the name of every org namespace:
`{prefix}-{sha256(org_id)[:16]}`. **Set this once at initial deployment and never
change it.** Changing the prefix after pods exist will orphan all running pods and
sessions — the gateway will create new namespaces with the new prefix but will not
migrate or clean up the old ones.

If you must change the prefix, drain all sessions first and perform a coordinated
namespace migration.
