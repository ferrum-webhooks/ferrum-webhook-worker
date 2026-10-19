# file: app/ssrf.py
#
# SSRF guard for customer-supplied webhook URLs. Mirrored in ferrum-webhook-worker/app/ssrf.py.
#
# A webhook URL is attacker-controlled input that the platform will POST to from inside the
# cluster. Without a guard a tenant can aim it at the cloud metadata service (169.254.169.254),
# the Kubernetes API, Postgres/Redis, or any other pod IP.
#
# Checked twice: at registration (fast feedback, gateway) and again right before every delivery
# (worker), because DNS can change after registration (DNS rebinding). Residual risk: the name is
# resolved by the check and again by the HTTP client; closing that fully needs connecting to the
# pinned IP or an egress proxy / NetworkPolicy (Project 2, Phase 0/2).

import ipaddress
import os
import socket
from typing import List
from urllib.parse import urlsplit

ALLOW_PRIVATE = os.getenv("ALLOW_PRIVATE_WEBHOOK_TARGETS", "false").lower() == "true"
ALLOWED_SCHEMES = ("https", "http") if os.getenv("ALLOW_INSECURE_WEBHOOKS", "true").lower() == "true" else ("https",)
ALLOWED_PORTS = None  # any port; tighten here if you want to restrict to 80/443/8443


class BlockedTarget(ValueError):
    pass


def _is_public(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:   # ::ffff:127.0.0.1
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def resolve(host: str, port: int) -> List[ipaddress._BaseAddress]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]


def check_url(url: str, resolve_dns: bool = True) -> None:
    """Raises BlockedTarget unless the URL is http(s) to a public address.
    Unresolvable hostnames pass at registration (resolve_dns=True only blocks what resolves);
    at delivery time they fail as ordinary connection errors."""
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise BlockedTarget(f"scheme must be one of {ALLOWED_SCHEMES}")
    host = parts.hostname
    if not host:
        raise BlockedTarget("missing host")
    if parts.username or parts.password:
        raise BlockedTarget("credentials in URL are not allowed")
    if ALLOW_PRIVATE:
        return
    port = parts.port or (443 if parts.scheme == "https" else 80)

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public(literal):
            raise BlockedTarget("target address is not publicly routable")
        return

    lowered = host.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith((".localhost", ".local", ".internal", ".svc", ".cluster.local")):
        raise BlockedTarget("internal hostnames are not allowed")
    if not resolve_dns:
        return
    try:
        addrs = resolve(host, port)
    except socket.gaierror:
        return
    for ip in addrs:
        if not _is_public(ip):
            raise BlockedTarget(f"{host} resolves to a non-public address")
