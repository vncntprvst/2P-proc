"""Utilities for loading pipeline configuration files with extras.

Supports:
    - `_env` blocks for defining reusable path prefixes or variables.
    - `${VAR}` style environment substitution in all string fields.
    - `__include` directives to merge reusable JSON snippets.
    - Metadata keys prefixed with `__` that should be ignored downstream.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict

_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _expand_string(value: str, env: Dict[str, str]) -> str:
    """Expand ${VAR} placeholders using the provided environment mapping."""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in env:
            return env[key]
        return os.environ.get(key, match.group(0))

    return _VAR_PATTERN.sub(_replace, value)


def _process_node(node: Any, base_dir: Path, env: Dict[str, str]) -> Any:
    if isinstance(node, dict):
        return _process_dict(node, base_dir, env)
    if isinstance(node, list):
        return [_process_node(item, base_dir, env) for item in node]
    if isinstance(node, str):
        return _expand_string(node, env)
    return node


def _process_dict(data: Dict[str, Any], base_dir: Path, env: Dict[str, str]) -> Dict[str, Any]:
    # Allow local environment overrides
    local_env = env
    if "_env" in data:
        env_block = data.get("_env") or {}
        local_env = env.copy()
        for key, raw_val in env_block.items():
            if key.startswith("__"):
                continue
            if raw_val is None:
                continue
            value = _expand_string(str(raw_val), local_env)
            local_env[key] = value

    result: Dict[str, Any] = {}

    # Handle include directives before processing the rest of the keys
    include_target = data.get("__include")
    if include_target is not None:
        include_path = _expand_string(str(include_target), local_env)
        include_file = (base_dir / include_path).resolve()
        if not include_file.exists():
            raise FileNotFoundError(f"Included config file not found: {include_file}")
        with include_file.open("r") as include_fp:
            include_raw = json.load(include_fp)
        included = _process_node(include_raw, include_file.parent, local_env)
        if not isinstance(included, dict):
            raise ValueError("Included JSON must define an object at the top level")
        result.update(included)

    for key, value in data.items():
        if key in {"_env", "__include"}:
            continue
        if key.startswith("__"):
            # Metadata keys are ignored downstream
            continue
        result[key] = _process_node(value, base_dir, local_env)

    return result


def load_config(config_path: str | Path) -> Dict[str, Any]:
    """Load a configuration file resolving includes and environment variables."""

    path = Path(config_path)
    with path.open("r") as fp:
        data = json.load(fp)

    initial_env = dict(os.environ)
    return _process_node(data, path.parent, initial_env)
