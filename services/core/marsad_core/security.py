"""
Who may talk to the core, and how the core knows.

Two different callers with two different proofs, and they must not be confused:

* **A connector** proves itself with a client certificate. The TLS handshake happens at
  the proxy in front of this process (Caddy for a remote firm, the boundary gateway for
  a local one), which verifies the certificate against the federation CA and passes the
  verified subject in `X-Client-Cert-Subject`. Both proxies overwrite that header, so a
  value a client sets for itself never arrives here.

* **A person at the console** presents a bearer token. A token is the wrong tool for a
  connector (it would sit in an environment variable forever) and the right one for a
  browser, which has no way to hold a client key an operator can reasonably provision.

What a certificate is bound to
------------------------------
Mutual TLS alone proves "some firm in the federation". Without the check in
`require_connector`, any enrolled firm could submit under another firm's pseudonym and
manufacture a correlation with itself as the victim. So the certificate's CN must equal
the `institution_ref` in the payload, and must be on the registered list when one is
configured. A rotating pseudonym means a new certificate per epoch, which is the
property a rotation is supposed to have.

Enforcement is a setting because the single-laptop demo has no certificates and relies
on Docker's network isolation instead. `/health` reports which mode this core is in, so
a core running without enforcement says so rather than looking identical to one with it.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from marsad_core.config import Settings, settings

log = logging.getLogger("marsad.core.security")

#: The shape a pseudonym in a certificate must have. Deliberately narrower than the
#: boundary contract's field: a CN is parsed out of a string, so anything unexpected in
#: it is refused rather than interpreted.
_PSEUDONYM = re.compile(r"^[a-z0-9_\-]{6,64}$")
_CN = re.compile(r"(?:^|,)\s*CN=([^,+]+)")

#: Roles a console token may carry. A closed list, so a typo in the configuration fails
#: at startup instead of minting a role nothing checks for.
CONSOLE_ROLES = frozenset({"operator", "regulator"})


def common_name(subject: str | None) -> str | None:
    """The pseudonym in a verified certificate subject, or None if there is not one."""
    if not subject:
        return None
    match = _CN.search(subject)
    if match is None:
        return None
    candidate = match.group(1).strip()
    return candidate if _PSEUDONYM.match(candidate) else None


def connector_identity(
    cfg: Annotated[Settings, Depends(settings)],
    x_client_cert_subject: Annotated[str | None, Header()] = None,
) -> str | None:
    """
    The certified pseudonym of the caller, or None when enforcement is off.

    Runs as a dependency so an unauthenticated caller is refused before its body is
    parsed; a stranger does not get to learn the contract from our validation errors.
    """
    if not cfg.require_client_identity:
        return None
    if not x_client_cert_subject:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "a client certificate is required")
    name = common_name(x_client_cert_subject)
    if name is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "certificate carries no valid pseudonym")
    registered = cfg.registered_institutions
    if registered and name not in registered:
        log.warning("security.unregistered_certificate cn=%s", name)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "certificate is not registered")
    return name


def assert_bound_to(certified: str | None, institution_ref: str) -> None:
    """
    The binding itself: a certificate may only speak for the pseudonym it names.

    Called with the parsed payload, because this is the one check that needs both.
    """
    if certified is not None and certified != institution_ref:
        log.warning(
            "security.certificate_mismatch cn=%s claimed=%s", certified, institution_ref,
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "certificate does not match the institution_ref in this submission",
        )


@dataclass(frozen=True)
class ConsoleTokens:
    """Configured console credentials, held as digests so a heap dump is not a login."""

    digests: tuple[tuple[bytes, str], ...]

    @classmethod
    def parse(cls, raw: str) -> ConsoleTokens:
        """`role:token,role:token`. Refuses anything it cannot understand."""
        pairs: list[tuple[bytes, str]] = []
        for entry in filter(None, (e.strip() for e in raw.split(","))):
            role, separator, token = entry.partition(":")
            if not separator or role not in CONSOLE_ROLES:
                raise RuntimeError(
                    f"MARSAD_CORE_CONSOLE_TOKENS entry has unknown role {role!r}; "
                    f"expected one of {sorted(CONSOLE_ROLES)}"
                )
            if len(token) < 16:
                raise RuntimeError("console tokens must be at least 16 characters")
            pairs.append((hashlib.sha256(token.encode()).digest(), role))
        return cls(tuple(pairs))

    def role_of(self, presented: str) -> str | None:
        digest = hashlib.sha256(presented.encode()).digest()
        role: str | None = None
        # Every entry is compared, so timing says nothing about which one matched.
        for known, candidate in self.digests:
            if hmac.compare_digest(known, digest):
                role = candidate
        return role


def console_role(
    cfg: Annotated[Settings, Depends(settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> str | None:
    """The caller's console role, or None when no tokens are configured."""
    tokens = ConsoleTokens.parse(cfg.console_tokens)
    if not tokens.digests:
        return None
    scheme, _, presented = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not presented:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "console token required",
                            headers={"WWW-Authenticate": "Bearer"})
    role = tokens.role_of(presented.strip())
    if role is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown console token",
                            headers={"WWW-Authenticate": "Bearer"})
    return role


def parse_origins(raw: str) -> list[str]:
    """
    The browser origins allowed to read this service.

    `*` is refused rather than honoured. The console is one known address, and a
    wildcard would let any page a logged-in analyst visits read the API on their behalf.
    """
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    if "*" in origins:
        raise RuntimeError("CORS origin '*' is not permitted; list the console address")
    return origins


__all__ = [
    "CONSOLE_ROLES", "ConsoleTokens", "assert_bound_to", "common_name", "connector_identity",
    "console_role", "parse_origins",
]
