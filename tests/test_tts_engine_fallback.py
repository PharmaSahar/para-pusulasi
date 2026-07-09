from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class _Cfg:
    channel_language: str = "tr"
    channel_id: str = "test_channel"
    elevenlabs_enabled: bool = True
    elevenlabs_api_key: str = "el_test_key"
    elevenlabs_voice_id: str = "voice_test"


def test_tts_fallback_chain_azure_then_elevenlabs_then_edge(monkeypatch, tmp_path, caplog):
    from src.tts_engine import TTSEngine

    monkeypatch.setenv("AZURE_TTS_KEY", "azure_test_key")
    monkeypatch.setenv("AZURE_TTS_REGION", "eastus")

    calls: list[str] = []

    def _azure_fail(self, text, output_path):
        calls.append("azure")
        raise RuntimeError("timeout while connecting")

    def _eleven_fail(self, text, output_path):
        calls.append("elevenlabs")
        raise RuntimeError("401 unauthorized api key")

    def _edge_ok(self, text, output_path):
        calls.append("edge")
        Path(output_path).write_bytes(b"ok")

    monkeypatch.setattr(TTSEngine, "_generate_azure_tts", _azure_fail)
    monkeypatch.setattr(TTSEngine, "_generate_elevenlabs", _eleven_fail)
    monkeypatch.setattr(TTSEngine, "_generate_edge_tts", _edge_ok)

    tts = TTSEngine(channel_cfg=_Cfg())
    out = tmp_path / "narration.mp3"

    with caplog.at_level("WARNING"):
        result = tts.generate_audio("Merhaba dunya", str(out))

    assert result == str(out)
    assert out.exists()
    assert calls == ["azure", "elevenlabs", "edge"]

    chain = tts.last_tts_fallback_chain
    assert isinstance(chain, list)
    assert chain[0]["provider"] == "azure"
    assert chain[0]["error_class"] == "transient"
    assert chain[1]["provider"] == "elevenlabs"
    assert chain[1]["error_class"] == "permanent"
    assert chain[2]["provider"] == "edge"
    assert chain[2]["status"] == "success"
    assert "TTS fallback: provider=azure" in caplog.text
    assert "TTS fallback: provider=elevenlabs" in caplog.text


def test_tts_fallback_chain_stops_after_elevenlabs_success(monkeypatch, tmp_path):
    from src.tts_engine import TTSEngine

    monkeypatch.setenv("AZURE_TTS_KEY", "azure_test_key")

    calls: list[str] = []

    def _azure_fail(self, text, output_path):
        calls.append("azure")
        raise RuntimeError("connection reset")

    def _eleven_ok(self, text, output_path):
        calls.append("elevenlabs")
        Path(output_path).write_bytes(b"ok")

    def _edge_should_not_run(self, text, output_path):
        calls.append("edge")
        raise AssertionError("edge should not run when elevenlabs succeeds")

    monkeypatch.setattr(TTSEngine, "_generate_azure_tts", _azure_fail)
    monkeypatch.setattr(TTSEngine, "_generate_elevenlabs", _eleven_ok)
    monkeypatch.setattr(TTSEngine, "_generate_edge_tts", _edge_should_not_run)

    tts = TTSEngine(channel_cfg=_Cfg())
    out = tmp_path / "narration.mp3"

    result = tts.generate_audio("Merhaba dunya", str(out))

    assert result == str(out)
    assert out.exists()
    assert calls == ["azure", "elevenlabs"]
    assert tts.last_tts_fallback_chain[-1]["provider"] == "elevenlabs"
    assert tts.last_tts_fallback_chain[-1]["status"] == "success"
