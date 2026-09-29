"""Strict YAML loading and portable, secret-free configuration identity."""

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode

from structural_break.config.models import ProjectConfig


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in result:
                raise ValueError(f"Duplicate YAML key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def load_config(directory: Path) -> ProjectConfig:
    values = {}
    for name in ProjectConfig.model_fields:
        path = directory / f"{name}.yaml"
        values[name] = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    return ProjectConfig.model_validate(values)


def normalized_config(config: ProjectConfig) -> str:
    return json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def config_hash(config: ProjectConfig) -> str:
    return hashlib.sha256(normalized_config(config).encode()).hexdigest()
