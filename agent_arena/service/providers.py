"""Managing connection profiles: store one, test it, discover what it serves.

A profile is the thing that makes "two API keys for the same vendor" and "our
gateway needs these headers and this CA" expressible. Declaring one in a
project's ``config.yaml`` is the portable way; the ones here live in user
settings so they follow you across projects and never end up in a file you
commit.

The rule that shapes this module: a raw key typed into a form must never land
in a plaintext settings file. ``save_provider`` moves it into the OS keyring and
persists only the reference.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

from ..core.config import ProviderSpec
from ..core.errors import ArenaError
from ..core.secrets import Secret, redact, resolve
from . import settings as user_settings
from .errors import NotFoundError, ServiceError

KEYRING_SERVICE = "agent-arena"


def user_providers() -> list[ProviderSpec]:
    """Profiles from user settings.

    One malformed entry is skipped rather than raised: losing every profile
    because a single edit was wrong would be a miserable way to discover a typo.
    """
    out = []
    for index, entry in enumerate(user_settings.load().get("providers") or []):
        try:
            out.append(ProviderSpec.parse(entry, index))
        except ArenaError:
            continue
    return out


def get_provider(provider_id: str) -> ProviderSpec:
    for profile in user_providers():
        if profile.id == provider_id:
            return profile
    raise NotFoundError(f"no provider profile named {provider_id!r}")


def save_provider(payload: dict[str, Any]) -> ProviderSpec:
    """Create or replace a profile, keeping any literal key out of the file."""
    from .secrets import keyring_set  # noqa: PLC0415 — avoids an import cycle

    data = dict(payload)
    raw_key = str(data.get("api_key") or data.get("api_key_ref") or "").strip()
    provider_id = str(data.get("id") or "").strip()
    if not provider_id:
        raise ServiceError("a provider profile needs an 'id'")

    if raw_key and not raw_key.startswith("${"):
        # A literal value. Put it in the OS key store and persist the reference,
        # so settings.json never holds the credential itself.
        keyring_set(KEYRING_SERVICE, provider_id, raw_key)
        data["api_key"] = f"${{keyring:{KEYRING_SERVICE}/{provider_id}}}"

    profile = ProviderSpec.parse(data, 0)
    existing = [p.to_dict() for p in user_providers() if p.id != profile.id]
    user_settings.save({"providers": [*existing, profile.to_dict()]})
    return profile


def delete_provider(
    provider_id: str, *, purge_key: bool = False, dry_run: bool = False
) -> dict[str, Any]:
    """Remove a profile, and optionally the credential it referenced."""
    from .secrets import keyring_delete  # noqa: PLC0415

    profiles = user_providers()
    if not any(p.id == provider_id for p in profiles):
        raise NotFoundError(f"no provider profile named {provider_id!r}")

    plan = {
        "provider_id": provider_id,
        "deleted": False,
        "key_purged": False,
        "dry_run": dry_run,
    }
    if dry_run:
        return plan

    user_settings.save(
        {"providers": [p.to_dict() for p in profiles if p.id != provider_id]}
    )
    plan["deleted"] = True
    if purge_key:
        plan["key_purged"] = keyring_delete(KEYRING_SERVICE, provider_id)
    return plan


def _opener(profile: ProviderSpec) -> Any:
    handlers: list[Any] = []
    if profile.proxy:
        handlers.append(
            urllib.request.ProxyHandler({"http": profile.proxy, "https": profile.proxy})
        )
    if profile.verify_tls is not True:
        if profile.verify_tls is False:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        else:
            context = ssl.create_default_context(cafile=str(profile.verify_tls))
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers)


def _models_url(profile: ProviderSpec) -> str:
    base = (profile.base_url or "").rstrip("/")
    if not base:
        raise ServiceError(f"provider {profile.id!r} has no base_url to check")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}/models"


def _credential(profile: ProviderSpec) -> Secret | None:
    if not profile.api_key_ref:
        return None
    return resolve(profile.api_key_ref)


def health_check(profile: ProviderSpec, timeout_s: float = 10.0) -> dict[str, Any]:
    """Can we reach this endpoint, and how fast?

    Never raises. A settings page that crashed when a gateway was down would be
    useless exactly when you needed it, so every failure comes back in
    ``error`` — with the message redacted, because a misbehaving proxy will
    happily echo your Authorization header back at you.
    """
    result: dict[str, Any] = {
        "provider_id": profile.id,
        "ok": False,
        "status": None,
        "latency_ms": None,
        "error": None,
        "models_endpoint": None,
    }
    secret = None
    try:
        url = _models_url(profile)
        result["models_endpoint"] = url
        secret = _credential(profile)
        headers = dict(profile.headers)
        if secret is not None:
            headers["Authorization"] = f"Bearer {secret.reveal()}"
        request = urllib.request.Request(url, headers=headers, method="GET")
        started = time.perf_counter()
        with _opener(profile).open(request, timeout=timeout_s) as response:
            response.read(2048)
            result["status"] = response.status
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["ok"] = True
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
        # 404 means something is listening but has no /v1/models route, which
        # plenty of gateways do not. That is reachable, not broken.
        result["ok"] = exc.code == 404
        result["error"] = None if result["ok"] else f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 — every failure is data here
        result["error"] = f"{type(exc).__name__}: {exc}"
    if result["error"] and secret is not None:
        result["error"] = redact(result["error"], [secret])
    return result


def discover_models(profile: ProviderSpec, timeout_s: float = 10.0) -> list[str]:
    """What this endpoint says it serves.

    Returns an empty list rather than raising when the endpoint does not support
    the route — many gateways do not, and that is not an error worth surfacing.
    """
    try:
        secret = _credential(profile)
        headers = dict(profile.headers)
        if secret is not None:
            headers["Authorization"] = f"Bearer {secret.reveal()}"
        request = urllib.request.Request(_models_url(profile), headers=headers, method="GET")
        with _opener(profile).open(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return []

    entries = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []
    names = set()
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id"):
            names.add(str(entry["id"]))
        elif isinstance(entry, str):
            names.add(entry)
    return sorted(names)
