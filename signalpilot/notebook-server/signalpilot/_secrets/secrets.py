# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from typing import TYPE_CHECKING

from signalpilot import _loggers
from signalpilot._config.config import SpConfig
from signalpilot._secrets.env_provider import (
    DotEnvSecretsProvider,
    EnvSecretsProvider,
)
from signalpilot._secrets.models import SecretKeysWithProvider, SecretProvider

LOGGER = _loggers.sp_logger()

if TYPE_CHECKING:
    from signalpilot._server.models.secrets import CreateSecretRequest


def _get_providers(
    config: SpConfig, original_environ: dict[str, str]
) -> list[SecretProvider]:
    providers: list[SecretProvider] = [EnvSecretsProvider(original_environ)]

    # Add dotenv providers
    dotenvs: list[str] = config.get("runtime", {}).get("dotenv", [])
    if dotenvs and isinstance(dotenvs, list):
        providers.extend(DotEnvSecretsProvider(dotenv) for dotenv in dotenvs)

    return providers


def get_secret_keys(
    config: SpConfig, original_environ: dict[str, str]
) -> list[SecretKeysWithProvider]:
    providers: list[SecretProvider] = _get_providers(config, original_environ)
    results: list[SecretKeysWithProvider] = []
    seen_keys: set[str] = set()
    for provider in providers:
        keys = provider.get_keys()
        results.append(
            SecretKeysWithProvider(
                # We remove duplicates by only adding keys that haven't been
                # seen yet.
                # This is because we don't override existing keys in the
                # environment.
                provider=provider.type,
                name=provider.name,
                keys=sorted(keys - seen_keys),
            )
        )
        seen_keys.update(keys)

    return results


def write_secret(request: CreateSecretRequest, config: SpConfig) -> None:
    # original_environ is not used for anything in the write operation
    providers = _get_providers(config, {})
    for provider in providers:
        if provider.type == request.provider and provider.name == request.name:
            provider.write_key(request.key, request.value)
            return
    LOGGER.error(
        f"Can't find provider {request.provider} with name {request.name}. Possible providers: {[f'{p.name} ({p.type})' for p in providers]}"
    )
    raise ValueError(
        f"Can't find provider {request.provider} with name {request.name}"
    )
