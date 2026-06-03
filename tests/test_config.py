"""Tests for corp_collab.config module."""

from __future__ import annotations

import pytest
from pathlib import Path

from corp_collab.config import Config, get_config, DEFAULTS


class TestConfigDefaults:
    """Config returns correct defaults when no file exists."""

    def test_max_delegation_depth_default(self, tmp_path):
        cfg = Config(base_path=tmp_path)
        assert cfg.max_delegation_depth == 10

    def test_max_idle_headcount_default(self, tmp_path):
        cfg = Config(base_path=tmp_path)
        assert cfg.max_idle_headcount == 5

    def test_auto_register_managers_default(self, tmp_path):
        cfg = Config(base_path=tmp_path)
        assert cfg.auto_register_managers is True

    def test_get_unknown_key(self, tmp_path):
        cfg = Config(base_path=tmp_path)
        assert cfg.get("nonexistent") is None
        assert cfg.get("nonexistent", 42) == 42


class TestConfigFile:
    """Config reads/writes YAML file."""

    def test_set_persists(self, tmp_path):
        cfg = Config(base_path=tmp_path)
        cfg.set("max_delegation_depth", 5)
        assert (tmp_path / "config.yaml").exists()

        cfg2 = Config(base_path=tmp_path)
        assert cfg2.max_delegation_depth == 5

    def test_max_depth_hard_cap(self, tmp_path):
        cfg = Config(base_path=tmp_path)
        cfg.max_delegation_depth = 99
        assert cfg.max_delegation_depth == 10  # hard cap

    def test_reload(self, tmp_path):
        cfg = Config(base_path=tmp_path)
        cfg.set("max_idle_headcount", 20)

        cfg2 = Config(base_path=tmp_path)
        cfg2.set("max_idle_headcount", 30)

        cfg.reload()
        assert cfg.max_idle_headcount == 30

    def test_to_dict_merges(self, tmp_path):
        cfg = Config(base_path=tmp_path)
        cfg.set("custom_key", "hello", persist=False)
        d = cfg.to_dict()
        assert d["max_delegation_depth"] == 10
        assert d["custom_key"] == "hello"


class TestGetConfig:
    def test_factory(self, tmp_path):
        cfg = get_config(base_path=tmp_path)
        assert isinstance(cfg, Config)
        assert cfg.base_path == tmp_path
