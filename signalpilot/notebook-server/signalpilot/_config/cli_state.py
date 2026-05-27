# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass

from signalpilot._utils.config.config import ConfigReader


@dataclass
class SpCLIState:
    latest_version: str | None = None
    last_checked_at: str | None = None
    accepted_text_to_notebook_terms_at: str | None = None
    notices: list[str] | None = None


FILE_NAME = "state.toml"


def get_cli_state() -> SpCLIState:
    config_reader = ConfigReader.for_filename(FILE_NAME)
    # Load the state file or create a default state if it doesn't exist
    state = config_reader.read_toml(SpCLIState, fallback=SpCLIState())
    return state


def write_cli_state(state: SpCLIState) -> None:
    config_reader = ConfigReader.for_filename(FILE_NAME)
    config_reader.write_toml(state)
