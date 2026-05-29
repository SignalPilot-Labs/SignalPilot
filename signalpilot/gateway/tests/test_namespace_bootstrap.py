"""Tests for orchestrator/namespaces.py — per-org K8s namespace bootstrap.

Pure-module tests against a fake K8s client. No FastAPI/DB imports.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from gateway.orchestrator.namespaces import (
    DEFAULT_NAMESPACE_PREFIX,
    ensure_org_namespace,
    namespace_for_org,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_fake_core_api() -> MagicMock:
    api = MagicMock()
    api.create_namespace = AsyncMock()
    api.create_namespaced_resource_quota = AsyncMock()
    api.create_namespaced_limit_range = AsyncMock()
    return api


def _make_fake_networking_api() -> MagicMock:
    api = MagicMock()
    api.create_namespaced_network_policy = AsyncMock()
    return api


def _make_fake_rbac_api() -> MagicMock:
    api = MagicMock()
    api.create_namespaced_role = AsyncMock()
    api.create_namespaced_role_binding = AsyncMock()
    return api


_DEFAULT_KWARGS = {
    "org_id": "test-org-123",
    "namespace": "sp-nb-a1b2c3d4e5f60123",
    "gateway_namespace": "signalpilot",
    "gateway_pod_selector": {"app": "signalpilot-gateway"},
    "gateway_port": 3300,
    "egress_cidr": None,
    "gateway_service_account": "signalpilot-gateway",
}


# ── namespace_for_org ──────────────────────────────────────────────────────────


class TestNamespaceForOrg:
    def test_namespace_for_org_is_deterministic_and_dns_safe(self):
        """Same org_id always produces the same namespace name, with DNS-safe chars."""
        ns1 = namespace_for_org("my-org", prefix="sp-nb")
        ns2 = namespace_for_org("my-org", prefix="sp-nb")
        assert ns1 == ns2
        assert ns1.islower() or all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in ns1)
        assert len(ns1) <= 63
        assert "-" in ns1

    def test_namespace_for_org_uses_sha256_not_hash(self):
        """namespace_for_org uses SHA-256 (deterministic), not Python's hash() (randomized)."""
        import hashlib

        org_id = "my-org-42"
        ns = namespace_for_org(org_id, prefix="sp-nb")
        expected_hash = hashlib.sha256(org_id.encode("utf-8")).hexdigest()[:16]
        assert ns == f"sp-nb-{expected_hash}"

    def test_namespace_for_org_diff_for_diff_orgs(self):
        """Different org_ids produce different namespace names."""
        ns_a = namespace_for_org("org-a", prefix="sp-nb")
        ns_b = namespace_for_org("org-b", prefix="sp-nb")
        assert ns_a != ns_b

    def test_namespace_for_org_rejects_empty(self):
        """Empty org_id raises ValueError."""
        with pytest.raises(ValueError, match="org_id must not be empty"):
            namespace_for_org("", prefix="sp-nb")

    def test_namespace_for_org_sanitizes_prefix(self):
        """Prefix with uppercase and special chars is sanitized to DNS-safe form."""
        ns = namespace_for_org("my-org", prefix="SP-NB")
        assert ns.startswith("sp-nb-")

    def test_namespace_for_org_default_prefix(self):
        """DEFAULT_NAMESPACE_PREFIX constant is 'sp-nb'."""
        assert DEFAULT_NAMESPACE_PREFIX == "sp-nb"
        ns = namespace_for_org("any-org", prefix=DEFAULT_NAMESPACE_PREFIX)
        assert ns.startswith("sp-nb-")


# ── ensure_org_namespace ───────────────────────────────────────────────────────


class TestEnsureNamespaceCreatesAllResourcesInOrder:
    @pytest.mark.asyncio
    async def test_ensure_namespace_creates_all_resources_in_order(self):
        """All 7 resources created in the correct order: Namespace → deny NP → allow NP
        → ResourceQuota → LimitRange → Role → RoleBinding."""
        core = _make_fake_core_api()
        networking = _make_fake_networking_api()
        rbac = _make_fake_rbac_api()

        creation_order = []

        async def _track_ns(body):
            creation_order.append("Namespace")

        async def _track_np(namespace, body):
            creation_order.append(f"NetworkPolicy:{body['metadata']['name']}")

        async def _track_quota(namespace, body):
            creation_order.append("ResourceQuota")

        async def _track_lr(namespace, body):
            creation_order.append("LimitRange")

        async def _track_role(namespace, body):
            creation_order.append("Role")

        async def _track_rb(namespace, body):
            creation_order.append("RoleBinding")

        core.create_namespace = _track_ns
        networking.create_namespaced_network_policy = _track_np
        core.create_namespaced_resource_quota = _track_quota
        core.create_namespaced_limit_range = _track_lr
        rbac.create_namespaced_role = _track_role
        rbac.create_namespaced_role_binding = _track_rb

        await ensure_org_namespace(
            core, networking, rbac, **_DEFAULT_KWARGS
        )

        assert creation_order[0] == "Namespace"
        assert creation_order[1] == "NetworkPolicy:default-deny"
        assert creation_order[2] == "NetworkPolicy:allow-gateway-ingress-and-egress"
        assert creation_order[3] == "ResourceQuota"
        assert creation_order[4] == "LimitRange"
        assert creation_order[5] == "Role"
        assert creation_order[6] == "RoleBinding"
        assert len(creation_order) == 7


class TestEnsureNamespaceIdempotent:
    @pytest.mark.asyncio
    async def test_ensure_namespace_idempotent_on_409(self):
        """409 AlreadyExists errors are swallowed — second call succeeds."""
        core = _make_fake_core_api()
        networking = _make_fake_networking_api()
        rbac = _make_fake_rbac_api()

        # All calls raise 409 — simulating resources already exist.
        # Use an exception with .status=409 (R5: _is_409 now uses exc.status, not str(exc)).
        _E = type("ApiException", (Exception,), {})
        error_409 = _E("AlreadyExists: namespace already exists")
        error_409.status = 409  # type: ignore[attr-defined]
        core.create_namespace.side_effect = error_409
        networking.create_namespaced_network_policy.side_effect = error_409
        core.create_namespaced_resource_quota.side_effect = error_409
        core.create_namespaced_limit_range.side_effect = error_409
        rbac.create_namespaced_role.side_effect = error_409
        rbac.create_namespaced_role_binding.side_effect = error_409

        # Should not raise — all 409s are swallowed.
        await ensure_org_namespace(core, networking, rbac, **_DEFAULT_KWARGS)

    @pytest.mark.asyncio
    async def test_ensure_namespace_raises_on_non_409_error(self):
        """Non-409 errors are re-raised — no silent fallback."""
        core = _make_fake_core_api()
        networking = _make_fake_networking_api()
        rbac = _make_fake_rbac_api()

        core.create_namespace.side_effect = Exception("500 InternalServerError")

        with pytest.raises(Exception, match="500"):
            await ensure_org_namespace(core, networking, rbac, **_DEFAULT_KWARGS)


class TestEnsureNamespaceConcurrentLock:
    @pytest.mark.asyncio
    async def test_ensure_namespace_concurrent_calls_same_org_lock(self):
        """Two concurrent ensure_org_namespace calls for same org are serialized by the lock.

        The per-org asyncio.Lock prevents double-creation churn. Both calls succeed,
        but only one set of creates actually runs (second sees 409 or resources exist).
        """
        from gateway.orchestrator.namespaces import _org_locks

        call_count = 0

        async def _counting_create_ns(body):
            nonlocal call_count
            call_count += 1

        core = _make_fake_core_api()
        networking = _make_fake_networking_api()
        rbac = _make_fake_rbac_api()

        org_id = "concurrent-test-org-unique-9999"
        # Clear any existing lock for this org
        _org_locks.pop(org_id, None)

        core.create_namespace = _counting_create_ns

        # First call succeeds, second sees 409 on namespace (simulating already-exists).
        first_call_done = False

        async def _create_ns_first_then_409(body):
            nonlocal first_call_done, call_count
            call_count += 1
            if first_call_done:
                # R5: _is_409 uses exc.status, not str(exc).
                _E = type("ApiException", (Exception,), {})
                exc = _E("AlreadyExists")
                exc.status = 409  # type: ignore[attr-defined]
                raise exc
            first_call_done = True

        core.create_namespace = _create_ns_first_then_409

        kwargs = {**_DEFAULT_KWARGS, "org_id": org_id}
        results = await asyncio.gather(
            ensure_org_namespace(core, networking, rbac, **kwargs),
            ensure_org_namespace(core, networking, rbac, **kwargs),
        )
        # Both calls should complete without raising.
        assert results == [None, None]
        # Namespace create was called exactly twice (once per serialized call),
        # but the second was a 409 and was swallowed.
        assert call_count == 2


# ── NetworkPolicy shape tests ──────────────────────────────────────────────────


class TestDefaultDenyPolicyShape:
    def test_default_deny_policy_shape(self):
        """default-deny policy: podSelector: {}, policyTypes: [Ingress, Egress], no rules."""
        from gateway.orchestrator.namespaces import _default_deny_policy

        policy = _default_deny_policy("sp-nb-abc")
        spec = policy["spec"]
        assert spec["podSelector"] == {}
        assert "Ingress" in spec["policyTypes"]
        assert "Egress" in spec["policyTypes"]
        # No ingress or egress keys — deny by omission.
        assert "ingress" not in spec
        assert "egress" not in spec


class TestAllowGatewayPolicyShape:
    def _get_policy(self, egress_cidr: str | None = None) -> dict:
        from gateway.orchestrator.namespaces import _allow_gateway_policy

        return _allow_gateway_policy(
            namespace="sp-nb-abc",
            gateway_namespace="signalpilot",
            gateway_pod_selector={"app": "signalpilot-gateway"},
            gateway_port=3300,
            egress_cidr=egress_cidr,
        )

    def test_allow_gateway_policy_shape(self):
        """allow-gateway policy: podSelector: {}, policyTypes includes Ingress and Egress."""
        policy = self._get_policy()
        spec = policy["spec"]
        assert spec["podSelector"] == {}
        assert "Ingress" in spec["policyTypes"]
        assert "Egress" in spec["policyTypes"]
        # Ingress rule: from gateway, port 2718/TCP.
        ingress = spec["ingress"]
        assert len(ingress) == 1
        assert ingress[0]["ports"][0]["port"] == 2718
        assert ingress[0]["ports"][0]["protocol"] == "TCP"

    def test_allow_gateway_egress_dns_peers_are_separate(self):
        """DNS egress uses two distinct `to:` entries — NOT collapsed into one peer.

        A single peer's namespaceSelector + podSelector is intersected (AND logic),
        which would match only pods that are BOTH kube-dns AND coredns — impossible.
        We need two separate egress rules so they are unioned (OR logic).
        """
        policy = self._get_policy()
        egress_rules = policy["spec"]["egress"]

        # Find DNS rules (port 53 UDP/TCP)
        dns_rules = [
            rule for rule in egress_rules
            if any(p.get("port") == 53 for p in rule.get("ports", []))
        ]
        assert len(dns_rules) == 2, f"Expected 2 separate DNS egress rules, got {len(dns_rules)}"

        # Each DNS rule has exactly one `to:` entry.
        for rule in dns_rules:
            assert len(rule["to"]) == 1

        # The two rules target different pod selectors.
        dns_selectors = [
            rule["to"][0]["podSelector"]["matchLabels"].get("k8s-app")
            for rule in dns_rules
        ]
        assert "kube-dns" in dns_selectors
        assert "coredns" in dns_selectors

    def test_allow_gateway_egress_gateway_port(self):
        """Egress to gateway uses sp_public_gateway_port from config, not a hardcoded value."""
        # Test with a non-default port to confirm it's configurable.
        from gateway.orchestrator.namespaces import _allow_gateway_policy

        policy = _allow_gateway_policy(
            namespace="sp-nb-abc",
            gateway_namespace="signalpilot",
            gateway_pod_selector={"app": "signalpilot-gateway"},
            gateway_port=8080,
            egress_cidr=None,
        )
        egress_rules = policy["spec"]["egress"]
        gateway_rules = [
            rule for rule in egress_rules
            if any(p.get("port") == 8080 for p in rule.get("ports", []))
        ]
        assert len(gateway_rules) == 1
        assert gateway_rules[0]["ports"][0]["protocol"] == "TCP"

    def test_allow_gateway_egress_cidr_optional(self):
        """When egress_cidr=None no ipBlock rule; when set, one ipBlock rule on port 443/TCP."""
        policy_no_cidr = self._get_policy(egress_cidr=None)
        ip_block_rules_no = [
            rule for rule in policy_no_cidr["spec"]["egress"]
            if any("ipBlock" in peer for peer in rule.get("to", []))
        ]
        assert len(ip_block_rules_no) == 0

        policy_with_cidr = self._get_policy(egress_cidr="10.0.0.0/8")
        ip_block_rules_yes = [
            rule for rule in policy_with_cidr["spec"]["egress"]
            if any("ipBlock" in peer for peer in rule.get("to", []))
        ]
        assert len(ip_block_rules_yes) == 1
        assert ip_block_rules_yes[0]["ports"][0]["port"] == 443
        assert ip_block_rules_yes[0]["ports"][0]["protocol"] == "TCP"
        assert ip_block_rules_yes[0]["to"][0]["ipBlock"]["cidr"] == "10.0.0.0/8"

    def test_allow_gateway_policy_no_pypi(self):
        """No 0.0.0.0/0 rule — PyPI access is not permitted from notebook pods."""
        policy = self._get_policy(egress_cidr=None)
        for rule in policy["spec"]["egress"]:
            for peer in rule.get("to", []):
                if "ipBlock" in peer:
                    assert peer["ipBlock"]["cidr"] != "0.0.0.0/0", (
                        "Found a 0.0.0.0/0 egress rule — PyPI must not be reachable!"
                    )

    def test_egress_cidr_includes_imds_except(self):
        """0.0.0.0/0 egress has except containing 169.254.0.0/16 and 127.0.0.0/8."""
        policy = self._get_policy(egress_cidr="0.0.0.0/0")
        ip_block_rules = [
            rule for rule in policy["spec"]["egress"]
            if any("ipBlock" in peer for peer in rule.get("to", []))
        ]
        assert len(ip_block_rules) == 1
        ip_block = ip_block_rules[0]["to"][0]["ipBlock"]
        assert "except" in ip_block
        excepts = ip_block["except"]
        assert "169.254.0.0/16" in excepts
        assert "127.0.0.0/8" in excepts

    def test_egress_cidr_narrow_omits_except(self):
        """52.0.0.0/8 is not a parent of any mandatory except — no except key emitted."""
        policy = self._get_policy(egress_cidr="52.0.0.0/8")
        ip_block_rules = [
            rule for rule in policy["spec"]["egress"]
            if any("ipBlock" in peer for peer in rule.get("to", []))
        ]
        assert len(ip_block_rules) == 1
        ip_block = ip_block_rules[0]["to"][0]["ipBlock"]
        assert "except" not in ip_block

    def test_egress_cidr_ipv6_imds_excepted(self):
        """IPv6 ::/0 egress cidr has fd00:ec2::/32 in except list."""
        policy = self._get_policy(egress_cidr="::/0")
        ip_block_rules = [
            rule for rule in policy["spec"]["egress"]
            if any("ipBlock" in peer for peer in rule.get("to", []))
        ]
        assert len(ip_block_rules) == 1
        ip_block = ip_block_rules[0]["to"][0]["ipBlock"]
        assert "except" in ip_block
        assert "fd00:ec2::/32" in ip_block["except"]

    def test_egress_cidr_ipv4_with_ipv6_excepts_filtered(self):
        """IPv4 egress cidr does not raise TypeError from IPv6 except entries."""
        # This test verifies the family-mismatch guard in _filter_except_entries.
        # 52.0.0.0/8 is IPv4; the mandatory list includes fd00:ec2::/32 (IPv6).
        # The builder must not raise and must silently drop the IPv6 entries.
        from gateway.orchestrator.namespaces import _allow_gateway_policy

        # Should not raise.
        policy = _allow_gateway_policy(
            namespace="sp-nb-abc",
            gateway_namespace="signalpilot",
            gateway_pod_selector={"app": "signalpilot-gateway"},
            gateway_port=3300,
            egress_cidr="52.0.0.0/8",
        )
        ip_block_rules = [
            rule for rule in policy["spec"]["egress"]
            if any("ipBlock" in peer for peer in rule.get("to", []))
        ]
        assert len(ip_block_rules) == 1
        ip_block = ip_block_rules[0]["to"][0]["ipBlock"]
        # No except (no IPv4 mandatories are subnets of 52/8).
        assert "except" not in ip_block

    def test_egress_cidr_equal_to_except_drops_entry(self):
        """When egress_cidr == an except candidate, that entry is dropped (not emitted)."""
        from gateway.orchestrator.namespaces import _allow_gateway_policy

        policy = _allow_gateway_policy(
            namespace="sp-nb-abc",
            gateway_namespace="signalpilot",
            gateway_pod_selector={"app": "signalpilot-gateway"},
            gateway_port=3300,
            egress_cidr="169.254.0.0/16",
        )
        ip_block_rules = [
            rule for rule in policy["spec"]["egress"]
            if any("ipBlock" in peer for peer in rule.get("to", []))
        ]
        assert len(ip_block_rules) == 1
        ip_block = ip_block_rules[0]["to"][0]["ipBlock"]
        # 169.254.0.0/16 must NOT appear as its own except entry.
        excepts = ip_block.get("except", [])
        assert "169.254.0.0/16" not in excepts


class TestRoleAndRoleBindingShape:
    def _get_role(self) -> dict:
        from gateway.orchestrator.namespaces import _gateway_org_role

        return _gateway_org_role("sp-nb-abc")

    def _get_role_binding(self) -> dict:
        from gateway.orchestrator.namespaces import _gateway_org_role_binding

        return _gateway_org_role_binding(
            namespace="sp-nb-abc",
            gateway_namespace="signalpilot",
            gateway_service_account="signalpilot-gateway",
        )

    def test_role_and_rolebinding_shape(self):
        """Role has correct verbs on pods, services, networkpolicies, etc.
        RoleBinding references gateway SA in gateway namespace and Role in org namespace.
        """
        role = self._get_role()
        rules = role["rules"]

        # Find rule for pods/services etc.
        pod_rule = next(
            (r for r in rules if "pods" in r.get("resources", [])), None
        )
        assert pod_rule is not None
        assert set(pod_rule["verbs"]) >= {"create", "get", "list", "delete", "patch"}
        assert "services" not in pod_rule["resources"]
        assert "resourcequotas" in pod_rule["resources"]
        assert "limitranges" in pod_rule["resources"]

        # Find pods/log rule — no create verb.
        log_rule = next(
            (r for r in rules if "pods/log" in r.get("resources", [])), None
        )
        assert log_rule is not None
        assert "get" in log_rule["verbs"]
        assert "list" in log_rule["verbs"]
        assert "create" not in log_rule["verbs"]
        assert "pods/status" in log_rule["resources"]

        # R4: Find pods/exec rule — create verb required for workspace sync.
        exec_rule = next(
            (r for r in rules if "pods/exec" in r.get("resources", [])), None
        )
        assert exec_rule is not None, "pods/exec rule must be in the per-namespace Role (R4)"
        assert "create" in exec_rule["verbs"], "pods/exec must allow 'create' verb"
        assert exec_rule["apiGroups"] == [""], "pods/exec rule must be in '' apiGroup"

        # Find networkpolicies rule.
        np_rule = next(
            (r for r in rules if "networkpolicies" in r.get("resources", [])), None
        )
        assert np_rule is not None
        assert set(np_rule["verbs"]) >= {"create", "get", "list", "delete", "patch"}
        assert np_rule["apiGroups"] == ["networking.k8s.io"]

        # RoleBinding shape.
        rb = self._get_role_binding()
        assert rb["roleRef"]["name"] == "signalpilot-gateway-org-role"
        assert rb["roleRef"]["kind"] == "Role"
        subjects = rb["subjects"]
        assert len(subjects) == 1
        assert subjects[0]["kind"] == "ServiceAccount"
        assert subjects[0]["name"] == "signalpilot-gateway"
        assert subjects[0]["namespace"] == "signalpilot"
