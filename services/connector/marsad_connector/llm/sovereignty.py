"""
Data-residency guard for the LLM layer.

MARSAD's whole claim is that plaintext never leaves the institution. The connector
is the only process that holds narrative, analyst notes and PII — and the LLM layer
is the one component inside it that takes that plaintext and *sends it somewhere*.
A base URL pointing at a hosted vendor turns the privacy boundary into a fiction
before A3 ever gets a chance to redact anything: the disclosure happens at
extraction time, upstream of every control this repository documents.

So the endpoint is checked when the provider is CONSTRUCTED, not when a request is
made. A connector that boots happily and only fails when an analyst files their
first incident has already failed — it failed at deployment, and nobody found out
until the worst possible moment.

The check is deliberately conservative and fails closed. A name we cannot *prove*
resolves inside the perimeter is refused, because "probably internal" is not a
property an institution's security team can sign off on.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Callable
from urllib.parse import urlparse

log = logging.getLogger("marsad.sovereignty")

#: Suffixes reserved for internal networks. A name ending in one of these cannot
#: be registered on the public internet, so it needs no resolution to be trusted.
PRIVATE_SUFFIXES: tuple[str, ...] = (".internal", ".local", ".lan")

#: Hostnames that are internal by definition regardless of resolution.
ALWAYS_LOCAL: frozenset[str] = frozenset({"localhost"})

#: API-key prefixes that identify a hosted vendor. Holding one of these means the
#: operator has credentials for an endpoint outside the perimeter, which is worth
#: refusing on its own even if the base URL currently looks internal — the key is
#: the standing capability to leak, and base URLs get edited.
#: Ordered longest-first so the reported vendor is the specific one.
VENDOR_KEY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("sk-ant-", "Anthropic"),
    ("sk-", "OpenAI"),
    ("AIza", "Google"),
    ("gsk_", "Groq"),
    ("hf_", "Hugging Face"),
)

#: Set MARSAD_SOVEREIGN_MODE=false to disable this guard. Documented because an
#: undocumented escape hatch gets rediscovered as a workaround under deadline
#: pressure, by someone who does not know what it turns off.
SOVEREIGN_MODE_ENV = "MARSAD_SOVEREIGN_MODE"

Resolver = Callable[[str], list[str]]


class SovereigntyError(RuntimeError):
    """
    Raised at construction when an LLM endpoint cannot be shown to sit inside the
    institution's perimeter. Never caught and downgraded — a degraded-but-running
    connector here is one that is exfiltrating incident narrative.
    """


def _resolve(host: str) -> list[str]:
    """Every address this name currently answers with, IPv4 and IPv6."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def _is_private(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _consequence(detail: str) -> str:
    return (
        f"{detail}\n\n"
        "The connector is the only process that holds incident narrative, analyst notes "
        "and PII. Sending that text to an endpoint outside the institution's perimeter is "
        "the exact disclosure MARSAD exists to prevent, and it happens at extraction time "
        "— before A3 redacts anything, so no boundary control downstream can catch it.\n"
        "Point the base URL at a model hosted inside the perimeter (Ollama or vLLM on the "
        f"institution's own network), or set {SOVEREIGN_MODE_ENV}=false to accept "
        "responsibility for sending plaintext off-premises."
    )


def check_api_key(api_key: str | None) -> None:
    """Refuse credentials issued by a hosted model vendor."""
    key = (api_key or "").strip()
    for prefix, vendor in VENDOR_KEY_PREFIXES:
        if key.startswith(prefix):
            raise SovereigntyError(_consequence(
                f"Refusing to construct an LLM provider with a {vendor} API key "
                f"(prefix {prefix!r}). A sovereign endpoint does not need a hosted "
                f"vendor's credential; a local server ignores it entirely."
            ))


def check_endpoint(base_url: str, *, resolver: Resolver | None = None) -> None:
    """
    Refuse a base URL that is reachable on the public internet.

    Accepted: bare hostnames with no dots (Docker/Compose service names), localhost,
    private and loopback IP literals, and the `.internal` / `.local` / `.lan`
    suffixes. A dotted name is accepted only if it resolves and **every** address it
    resolves to is private — one public answer is enough to refuse, because
    split-horizon DNS that returns a private address here and a public one elsewhere
    would otherwise walk straight through this check.
    """
    raw = (base_url or "").strip()
    if not raw:
        raise SovereigntyError(_consequence("Refusing to construct an LLM provider with no base URL."))

    parsed = urlparse(raw if "://" in raw else f"//{raw}", scheme="http")
    if parsed.scheme not in ("http", "https"):
        raise SovereigntyError(_consequence(
            f"Refusing an LLM base URL with scheme {parsed.scheme!r}; expected http or https."
        ))

    host = (parsed.hostname or "").strip().rstrip(".").lower()
    if not host:
        raise SovereigntyError(_consequence(
            f"Refusing an LLM base URL with no host: {base_url!r}."
        ))

    # An IP literal answers for itself; no resolution involved, so no split horizon.
    try:
        if not _is_private(host):
            raise SovereigntyError(_consequence(
                f"Refusing an LLM endpoint at the public IP address {host}."
            ))
        return
    except ValueError:
        pass  # not an IP literal — fall through to name handling

    if host in ALWAYS_LOCAL or "." not in host or host.endswith(PRIVATE_SUFFIXES):
        return

    resolve = resolver or _resolve
    try:
        addresses = resolve(host)
    except OSError as exc:
        raise SovereigntyError(_consequence(
            f"Refusing the LLM endpoint {host!r}: it looks like a public domain name and "
            f"does not resolve here ({exc}), so it cannot be shown to be inside the "
            f"perimeter. This check fails closed on purpose."
        )) from exc

    if not addresses:
        raise SovereigntyError(_consequence(
            f"Refusing the LLM endpoint {host!r}: it resolves to no addresses, so it "
            f"cannot be shown to be inside the perimeter."
        ))

    public = [a for a in addresses if not _is_private(a)]
    if public:
        raise SovereigntyError(_consequence(
            f"Refusing the LLM endpoint {host!r}: it resolves to {', '.join(addresses)}, "
            f"of which {', '.join(public)} {'is' if len(public) == 1 else 'are'} routable on "
            f"the public internet. Every resolved address must be private — a name that "
            f"answers privately here and publicly elsewhere is split-horizon DNS, not a "
            f"sovereign endpoint."
        ))


def assert_sovereign(
    base_url: str,
    api_key: str | None = None,
    *,
    sovereign_mode: bool = True,
    resolver: Resolver | None = None,
) -> None:
    """
    The single entry point. Called from provider construction, never from a request
    path — see the module docstring for why that distinction is the whole point.
    """
    if not sovereign_mode:
        log.warning(
            "sovereignty.DISABLED base_url=%s — %s is off. Plaintext incident narrative, "
            "analyst notes and PII may now leave the institution's perimeter. This is a "
            "deliberate operator decision and is not a supported configuration.",
            base_url, SOVEREIGN_MODE_ENV,
        )
        return

    check_api_key(api_key)
    check_endpoint(base_url, resolver=resolver)
    log.info("sovereignty.ok base_url=%s", base_url)


__all__ = [
    "ALWAYS_LOCAL",
    "PRIVATE_SUFFIXES",
    "SOVEREIGN_MODE_ENV",
    "VENDOR_KEY_PREFIXES",
    "SovereigntyError",
    "assert_sovereign",
    "check_api_key",
    "check_endpoint",
]
