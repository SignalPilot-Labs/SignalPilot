"""Non-secret credential identity passed from the store to the pool manager.

The store stamps this key into the credential extras it returns; the pool manager
pops it back out before the extras reach a connector and folds it into the pool
key so two tenants sharing a visible connection string never share a connector.

The value is derived from row identity and stored ciphertext only — it must never
carry, or be derived from, plaintext secret material, and must never be logged.

Lives in gateway.common so neither gateway.store nor gateway.connectors has to
import the other.
"""

from __future__ import annotations

CREDENTIAL_IDENTITY_KEY = "_credential_identity"
