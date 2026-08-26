"""Kubernetes support for eval workloads.

Notebook Runtime v2 removed notebook pods — notebooks run on the sandbox
runtime (gateway.sandbox_runtime). This package now serves only the eval
Kubernetes backend: client bootstrap (kubernetes.py) and per-org tenant
namespaces (namespaces.py).
"""
