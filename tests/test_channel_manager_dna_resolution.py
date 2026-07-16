import json

from src import channel_manager


def test_get_channel_resolves_explicit_channel_dna_fields(tmp_path, monkeypatch):
    registry = {
        "channels": {
            "saglik_pusulasi": {
                "name": "Saglik Pusulasi",
                "niche": "saglik",
                "language": "tr",
                "upload_times": ["10:30"],
                "color_primary": [1, 2, 3],
                "color_bg": [4, 5, 6],
                "persona": "Saglik odakli kanal",
                "topics": ["uyku"],
                "tone": "bilimsel ve sade",
                "audience": "saglik odakli yetiskinler",
                "voice_archetype": "saglik rehberi",
                "evidence_style": "kaynak destekli",
                "forbidden_patterns": ["piyasa spekulasyonu"],
                "signature_structure": ["hook", "adim", "ozet"],
                "channel_dna_version": "v2",
            }
        }
    }
    registry_path = tmp_path / "channel_registry.json"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(channel_manager, "REGISTRY_PATH", str(registry_path))

    cfg = channel_manager.get_channel("saglik_pusulasi")

    assert cfg.tone == "bilimsel ve sade"
    assert cfg.audience == "saglik odakli yetiskinler"
    assert cfg.voice_archetype == "saglik rehberi"
    assert cfg.evidence_style == "kaynak destekli"
    assert cfg.forbidden_patterns == ["piyasa spekulasyonu"]
    assert cfg.signature_structure == ["hook", "adim", "ozet"]
    assert cfg.channel_dna_version == "v2"


def test_get_channel_assigns_neutral_pexels_query_default_when_missing(tmp_path, monkeypatch):
    registry = {
        "channels": {
            "saglik_pusulasi": {
                "name": "Saglik Pusulasi",
                "niche": "saglik",
                "language": "tr",
                "upload_times": ["10:30"],
                "color_primary": [1, 2, 3],
                "color_bg": [4, 5, 6],
            }
        }
    }
    registry_path = tmp_path / "channel_registry.json"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(channel_manager, "REGISTRY_PATH", str(registry_path))

    cfg = channel_manager.get_channel("saglik_pusulasi")

    assert cfg.pexels_query == "business office planning"


def test_get_channel_preserves_explicit_pexels_query_from_registry(tmp_path, monkeypatch):
    registry = {
        "channels": {
            "saglik_pusulasi": {
                "name": "Saglik Pusulasi",
                "niche": "saglik",
                "language": "tr",
                "upload_times": ["10:30"],
                "color_primary": [1, 2, 3],
                "color_bg": [4, 5, 6],
                "pexels_query": "health wellness nutrition clinic fitness",
            }
        }
    }
    registry_path = tmp_path / "channel_registry.json"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(channel_manager, "REGISTRY_PATH", str(registry_path))

    cfg = channel_manager.get_channel("saglik_pusulasi")

    assert cfg.pexels_query == "health wellness nutrition clinic fitness"


def test_get_channel_assigns_allow_market_language_from_niche_fallback(tmp_path, monkeypatch):
    registry = {
        "channels": {
            "borsa_akademi": {
                "name": "Borsa Akademi",
                "niche": "borsa",
                "language": "tr",
                "upload_times": ["10:30"],
                "color_primary": [1, 2, 3],
                "color_bg": [4, 5, 6],
            },
            "saglik_pusulasi": {
                "name": "Saglik Pusulasi",
                "niche": "saglik",
                "language": "tr",
                "upload_times": ["10:30"],
                "color_primary": [1, 2, 3],
                "color_bg": [4, 5, 6],
            },
        }
    }
    registry_path = tmp_path / "channel_registry.json"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(channel_manager, "REGISTRY_PATH", str(registry_path))

    finance_cfg = channel_manager.get_channel("borsa_akademi")
    health_cfg = channel_manager.get_channel("saglik_pusulasi")

    assert finance_cfg.allow_market_language is True
    assert health_cfg.allow_market_language is False


def test_get_channel_preserves_explicit_allow_market_language_override(tmp_path, monkeypatch):
    registry = {
        "channels": {
            "saglik_pusulasi": {
                "name": "Saglik Pusulasi",
                "niche": "saglik",
                "language": "tr",
                "upload_times": ["10:30"],
                "color_primary": [1, 2, 3],
                "color_bg": [4, 5, 6],
                "allow_market_language": "true",
            }
        }
    }
    registry_path = tmp_path / "channel_registry.json"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(channel_manager, "REGISTRY_PATH", str(registry_path))

    cfg = channel_manager.get_channel("saglik_pusulasi")

    assert cfg.allow_market_language is True


def test_get_channel_explicit_false_overrides_finance_niche_fallback(tmp_path, monkeypatch):
    registry = {
        "channels": {
            "borsa_akademi": {
                "name": "Borsa Akademi",
                "niche": "borsa",
                "language": "tr",
                "upload_times": ["10:30"],
                "color_primary": [1, 2, 3],
                "color_bg": [4, 5, 6],
                "allow_market_language": False,
            }
        }
    }
    registry_path = tmp_path / "channel_registry.json"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(channel_manager, "REGISTRY_PATH", str(registry_path))

    cfg = channel_manager.get_channel("borsa_akademi")

    assert cfg.allow_market_language is False
