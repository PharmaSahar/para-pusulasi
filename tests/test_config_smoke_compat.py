from __future__ import annotations

from src.config import Config


def test_config_exposes_niche_alias_for_smoke_path():
    cfg = Config(channel_niche="kisisel_finans")

    assert cfg.niche == "kisisel_finans"


def test_config_niche_alias_updates_channel_niche():
    cfg = Config(channel_niche="kisisel_finans")

    cfg.niche = "kripto"

    assert cfg.channel_niche == "kripto"
    assert cfg.niche == "kripto"
