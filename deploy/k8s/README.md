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

### (c) Runtime sandbox (gVisor / Kata)

#### Threat model

User notebook pods run arbitrary code supplied by LLM agents. Without a kernel-level sandbox, any container-escape primitive (CVE in the container runtime or kernel) lands the attacker as root on the EC2/k3s node. `runtimeClassName` routes the pod through an alternative OCI runtime (gVisor `runsc` or Kata Containers) that interposes a user-space kernel or a dedicated VM between the pod and the host kernel.

#### Required: set SP_NOTEBOOK_RUNTIME_CLASS

In cloud mode (`SP_DEPLOYMENT_MODE=cloud`), `SP_NOTEBOOK_RUNTIME_CLASS` **must** be set explicitly. The gateway refuses to start if it is empty. Recommended value: `gvisor`.

```bash
SP_NOTEBOOK_RUNTIME_CLASS=gvisor
```

In local/dev mode, the variable may be left empty (no sandbox runtime applied).

#### Apply the RuntimeClass resource

```yaml
# gvisor-runtimeclass.yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
```

```bash
kubectl apply -f gvisor-runtimeclass.yaml
```

#### k3s: install gVisor (runsc)

Follow the [gVisor k3s guide](https://gvisor.dev/docs/user_guide/k3s/):

```bash
# On each k3s node:
curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list
sudo apt-get update && sudo apt-get install -y runsc

# Add runsc shim to containerd config (/var/lib/rancher/k3s/agent/etc/containerd/config.toml):
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc]
  runtime_type = "io.containerd.runsc.v1"

sudo systemctl restart k3s
```

#### EKS: install gVisor

Use a custom launch template or a maintained AMI with gVisor pre-installed. After nodes are ready:

```bash
# Create the RuntimeClass (handler must match containerd runtime registration):
kubectl apply -f gvisor-runtimeclass.yaml
```

Alternatively, use managed node groups with the [gVisor EKS AMI](https://gvisor.dev/docs/user_guide/eks/) or install runsc via user-data.

#### Kata Containers alternative

If gVisor is unavailable (e.g. ARM64 or environments requiring full VM isolation), use Kata:

```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata
```

Set `SP_NOTEBOOK_RUNTIME_CLASS=kata` and install kata-runtime on each node per the [Kata Containers docs](https://katacontainers.io/docs/).

#### RBAC

The gateway needs `get` on `node.k8s.io/runtimeclasses` for the pre-flight check. This is included in `gateway-rbac.yaml` (`ClusterRole signalpilot-gateway-runtimeclass-reader`). Re-apply after upgrading:

```bash
kubectl apply -f deploy/k8s/gateway-rbac.yaml
```

---

### (d) Required environment variables for the gateway pod

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
| `SP_NOTEBOOK_EGRESS_CIDR` | `52.0.0.0/8` | (Optional) Allow notebook pods to reach this CIDR on port 443 (e.g. S3). **Validator hard-fails on startup if this CIDR contains AWS IMDS (`169.254.169.254` or `fd00:ec2::/32`). `0.0.0.0/0` and `169.254.0.0/16` are rejected.** |
| `SP_NOTEBOOK_IMAGE` | `your-registry/notebook:tag` | Container image for notebook pods. |
| `SP_NOTEBOOK_RUNTIME_CLASS` | `gvisor` | **Required in cloud mode.** RuntimeClass name for notebook pod isolation. Empty in local mode. |

### (e) IMDSv2 hop-limit enforcement at the EC2 node level

The NetworkPolicy `except:` list blocks link-local IMDS routes at the CNI layer.
For defense in depth, enforce IMDSv2 with hop-limit=1 at the node level so that
even if the CNI is misconfigured, container processes cannot reach the host IMDS.

- [ ] Set `HttpTokens=required` on the EKS/k3s node launch template (IMDSv2 mandatory).
- [ ] Set `HttpPutResponseHopLimit=1` on the same launch template (prevents container processes — one hop from host — from reaching IMDS even if CNI bypasses NetworkPolicy).
- [ ] Verify `SP_NOTEBOOK_EGRESS_CIDR` is set to the narrowest range your workload requires. `0.0.0.0/0` is rejected by the validator. `169.254.0.0/16` is rejected.
- [ ] Confirm the deployed CNI enforces NetworkPolicy (Calico, Cilium, AWS VPC CNI with policy add-on). Without enforcement, the `except` list is documentation only.

### (f) Verification: cross-namespace network isolation

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

### (g) One-way config: SP_NOTEBOOK_NAMESPACE_PREFIX

`SP_NOTEBOOK_NAMESPACE_PREFIX` determines the name of every org namespace:
`{prefix}-{sha256(org_id)[:16]}`. **Set this once at initial deployment and never
change it.** Changing the prefix after pods exist will orphan all running pods and
sessions — the gateway will create new namespaces with the new prefix but will not
migrate or clean up the old ones.

If you must change the prefix, drain all sessions first and perform a coordinated
namespace migration.
