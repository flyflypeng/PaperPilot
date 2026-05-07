"""
arXiv-specific network configuration.

Only requests to arxiv.org/export.arxiv.org use the optional arXiv proxy
settings. Other backend HTTP clients should keep their own direct/default
network behavior.
"""

from __future__ import annotations

import os
import urllib.request
from typing import Any
from urllib.parse import urlparse

import arxiv
import requests

ARXIV_PROXY_ENV_NAMES = (
    "ARXIV_PROXY",
    "ARXIV_API_PROXY",
)


def is_arxiv_url(url: str) -> bool:
    """Return True when the URL belongs to arXiv."""
    hostname = urlparse(url).hostname or ""
    return hostname == "arxiv.org" or hostname.endswith(".arxiv.org")


def _get_proxy_value(scheme: str) -> str:
    scheme_env_name = f"ARXIV_{scheme.upper()}_PROXY"
    for env_name in (scheme_env_name, *ARXIV_PROXY_ENV_NAMES):
        value = os.getenv(env_name, "").strip()
        if value:
            return value
    return ""


def get_arxiv_requests_proxies(url: str) -> dict[str, str] | None:
    """Build a requests-compatible proxies dict for arXiv URLs only."""
    if not is_arxiv_url(url):
        return None

    proxies: dict[str, str] = {}
    http_proxy = _get_proxy_value("http")
    https_proxy = _get_proxy_value("https")
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies or None


def new_arxiv_requests_session(url: str = "https://export.arxiv.org/api/query") -> requests.Session:
    """Create a requests session that ignores global proxy env vars."""
    session = requests.Session()
    session.trust_env = False
    proxies = get_arxiv_requests_proxies(url)
    if proxies:
        session.proxies.update(proxies)
    return session


def arxiv_get(url: str, **kwargs: Any) -> requests.Response:
    """Run a GET request with arXiv-only proxy handling."""
    with new_arxiv_requests_session(url) as session:
        return session.get(url, **kwargs)


def configure_arxiv_client(client: arxiv.Client) -> arxiv.Client:
    """Apply arXiv proxy settings to the arxiv package client."""
    client.query_url_format = "https://export.arxiv.org/api/query?{}"
    session = getattr(client, "_session", None)
    if session is None:
        return client

    session.trust_env = False
    proxies = get_arxiv_requests_proxies("https://export.arxiv.org/api/query")
    if proxies:
        session.proxies.update(proxies)
    return client


def arxiv_urlopen(url_or_request: str | urllib.request.Request, timeout: int):
    """Open an arXiv URL with urllib while ignoring global proxy env vars."""
    if isinstance(url_or_request, urllib.request.Request):
        url = url_or_request.full_url
    else:
        url = url_or_request

    proxies = get_arxiv_requests_proxies(url) or {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    return opener.open(url_or_request, timeout=timeout)
