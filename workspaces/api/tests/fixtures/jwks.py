"""JWKS test helpers.

One 2048-bit RSA keypair is generated and cached at module scope.
Many JWTs can be minted from it without regeneration per test.
This keeps CI fast (~200ms for keygen amortized over all tests).
"""

from __future__ import annotations

import time
import uuid
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm


class FakeJwksFactory:
    """Helper for generating test JWKS dicts and signed JWTs.

    Usage:
        factory = FakeJwksFactory()
        keypair = factory.keypair()
        jwks = factory.jwks_dict(kid="test-kid")
        token = factory.mint_jwt(sub="user_abc", kid="test-kid", issuer="https://clerk.example.com")
    """

    _DEFAULT_KID = "test-kid-0001"

    @lru_cache(maxsize=1)  # type: ignore[misc]
    def keypair(self) -> rsa.RSAPrivateKey:
        """Return the cached 2048-bit RSA keypair (generated once at module scope)."""
        return rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

    def private_key(self) -> rsa.RSAPrivateKey:
        return self.keypair()

    def public_key(self) -> rsa.RSAPublicKey:
        return self.keypair().public_key()

    def jwks_dict(self, kid: str = _DEFAULT_KID) -> dict:
        """Return a JWKS dict with a single RS256 key."""
        public_key = self.public_key()
        jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
        jwk["kid"] = kid
        jwk["kty"] = "RSA"
        jwk["alg"] = "RS256"
        jwk["use"] = "sig"
        return {"keys": [jwk]}

    def mint_jwt(
        self,
        sub: str,
        *,
        kid: str = _DEFAULT_KID,
        issuer: str,
        audience: str | None = None,
        exp_offset: int = 300,
        alg: str = "RS256",
    ) -> str:
        """Mint a signed JWT using the cached keypair."""
        now = int(time.time())
        payload: dict = {
            "sub": sub,
            "iss": issuer,
            "iat": now,
            "exp": now + exp_offset,
            "jti": uuid.uuid4().hex,
        }
        if audience is not None:
            payload["aud"] = audience

        private_key = self.private_key()
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return jwt.encode(
            payload,
            pem,
            algorithm=alg,
            headers={"kid": kid},
        )

    def mint_expired_jwt(
        self,
        sub: str,
        *,
        kid: str = _DEFAULT_KID,
        issuer: str,
    ) -> str:
        """Mint an already-expired JWT."""
        return self.mint_jwt(sub=sub, kid=kid, issuer=issuer, exp_offset=-10)


# Module-scope singleton so the keypair is generated once per pytest session.
_factory = FakeJwksFactory()
