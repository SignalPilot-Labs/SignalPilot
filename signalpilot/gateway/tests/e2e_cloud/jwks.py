"""Local stand-in for Clerk's JWKS endpoint.

The gateway derives its JWKS URL and expected issuer by base64-decoding the domain
out of CLERK_PUBLISHABLE_KEY (see gateway/auth/user.py::_get_jwks_client).  By
encoding "127.0.0.1:<port>" as that domain we can point the *real* PyJWKClient at
an HTTPS server we control, sign our own RS256 tokens, and exercise the genuine
verification path end to end — no monkeypatching of jwt.decode or of the key
lookup.

TLS: a self-signed leaf certificate with SAN ``IP:127.0.0.1`` is generated at
runtime and handed to the gateway subprocess via ``SSL_CERT_FILE``, which
``ssl.create_default_context()`` (and therefore ``urllib``, and therefore
``PyJWKClient``) honours as a trust anchor.  Nothing is written to a shared
location and no key material is ever logged.
"""

from __future__ import annotations

import base64
import datetime
import http.server
import ipaddress
import json
import ssl
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

PRIMARY_KID = "e2e-primary-kid"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _jwk_from_public(pub: rsa.RSAPublicKey, kid: str) -> dict:
    numbers = pub.public_numbers()
    n = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
    e = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": _b64u(n), "e": _b64u(e)}


def _self_signed(dirpath: Path) -> tuple[Path, Path]:
    """Write a self-signed cert (SAN IP:127.0.0.1) + key; return (cert, key) paths."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path = dirpath / "jwks-tls.crt"
    key_path = dirpath / "jwks-tls.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@dataclass
class FakeClerk:
    """A running HTTPS JWKS endpoint plus the signing keys behind it."""

    port: int
    ca_file: Path
    signing_key: rsa.RSAPrivateKey
    impostor_key: rsa.RSAPrivateKey
    _httpd: http.server.ThreadingHTTPServer = field(repr=False, default=None)  # type: ignore[assignment]
    _thread: threading.Thread = field(repr=False, default=None)  # type: ignore[assignment]
    _tmp: tempfile.TemporaryDirectory = field(repr=False, default=None)  # type: ignore[assignment]

    # ── identity the gateway will derive from the publishable key ──────────────
    @property
    def domain(self) -> str:
        return f"127.0.0.1:{self.port}"

    @property
    def issuer(self) -> str:
        return f"https://{self.domain}"

    @property
    def publishable_key(self) -> str:
        """A synthetic pk_test_ key whose embedded domain is this server."""
        encoded = base64.b64encode(f"{self.domain}$".encode()).decode().rstrip("=")
        return f"pk_test_{encoded}"

    # ── token minting ─────────────────────────────────────────────────────────
    def mint(
        self,
        sub: str = "user_e2e",
        org_id: str | None = "org_e2e",
        org_role: str | None = None,
        *,
        claim_style: str = "dev",
        issuer: str | None = None,
        azp: str | None = None,
        exp_delta: int = 900,
        iat_delta: int = 0,
        kid: str = PRIMARY_KID,
        omit_sub: bool = False,
        omit_exp: bool = False,
        omit_iat: bool = False,
        sign_with_impostor: bool = False,
        extra: dict | None = None,
    ) -> str:
        """Mint a Clerk-shaped RS256 session token.

        claim_style:
          "dev"   — Clerk development form: top-level ``org_id`` / ``org_role``.
          "short" — Clerk production form: ``o = {"id": ..., "rol": ...}``.
          "none"  — no organization claims at all.
        """
        now = int(datetime.datetime.now(datetime.UTC).timestamp())
        claims: dict = {"iss": issuer if issuer is not None else self.issuer}
        if not omit_sub:
            claims["sub"] = sub
        if not omit_iat:
            claims["iat"] = now + iat_delta
        if not omit_exp:
            claims["exp"] = now + exp_delta
        claims["nbf"] = now - 60
        claims["sid"] = "sess_e2e"
        if azp is not None:
            claims["azp"] = azp

        if claim_style == "dev":
            if org_id is not None:
                claims["org_id"] = org_id
            if org_role is not None:
                claims["org_role"] = org_role
        elif claim_style == "short":
            o: dict = {}
            if org_id is not None:
                o["id"] = org_id
            if org_role is not None:
                o["rol"] = org_role
            if o:
                o.setdefault("slg", "e2e-org")
                claims["o"] = o
        elif claim_style == "none":
            pass
        else:  # pragma: no cover
            raise ValueError(f"unknown claim_style {claim_style!r}")

        if extra:
            claims.update(extra)

        key = self.impostor_key if sign_with_impostor else self.signing_key
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._tmp is not None:
            self._tmp.cleanup()


def start_fake_clerk() -> FakeClerk:
    """Start the HTTPS JWKS server on an ephemeral port and return its handle."""
    tmp = tempfile.TemporaryDirectory(prefix="sp-e2e-jwks-")
    tmpdir = Path(tmp.name)
    cert_path, key_path = _self_signed(tmpdir)

    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    impostor_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks_body = json.dumps(
        {"keys": [_jwk_from_public(signing_key.public_key(), PRIMARY_KID)]}
    ).encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            if self.path.startswith("/.well-known/jwks.json"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(jwks_body)))
                self.end_headers()
                self.wfile.write(jwks_body)
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def log_message(self, *args):  # silence
            return

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    port = httpd.server_address[1]

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    return FakeClerk(
        port=port,
        ca_file=cert_path,
        signing_key=signing_key,
        impostor_key=impostor_key,
        _httpd=httpd,
        _thread=thread,
        _tmp=tmp,
    )
