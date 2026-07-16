from types import SimpleNamespace

from src.community_poster import post_video_announcement
from src.playlist_manager import PlaylistManager
from src.shorts_creator import ShortsCreator
from src.video_creator import VideoCreator as VideoCreatorBasic
from src.video_creator_pro import VideoCreator as VideoCreatorPro


class _FakeCredentials:
    expired = False
    refresh_token = None


class _FakeResponse:
    status_code = 200


class _FakeSession:
    last_payload = None

    def __init__(self, _creds):
        self.payload = None

    def post(self, _url, json):
        self.payload = json
        _FakeSession.last_payload = json
        return _FakeResponse()


class _FakePlaylistsInsert:
    def execute(self):
        return {"id": "playlist-123"}


class _FakePlaylists:
    def insert(self, **_kwargs):
        return _FakePlaylistsInsert()


class _FakePlaylistItemsInsert:
    def execute(self):
        return {"ok": True}


class _FakePlaylistItems:
    def insert(self, **_kwargs):
        return _FakePlaylistItemsInsert()


class _FakeYoutubeService:
    def playlists(self):
        return _FakePlaylists()

    def playlistItems(self):
        return _FakePlaylistItems()


def test_generic_renderer_defaults_are_neutral():
    creator = VideoCreatorBasic(channel_cfg=None)
    assert creator.channel_name == "Genel Kanal"

    creator_pro = VideoCreatorPro(channel_cfg=None)
    assert creator_pro.channel_name == "Genel Kanal"
    assert creator_pro.channel_tagline == "Uzmanlik Rehberi"


def test_finance_renderer_branding_is_preserved_when_explicit():
    cfg = SimpleNamespace(
        video_width=1280,
        video_height=720,
        videos_dir="output/videos",
        color_primary=(1, 2, 3),
        color_bg=(4, 5, 6),
        name="Borsa Akademi",
        tagline="Finans & Yatirim Rehberi",
        base_dir=".",
    )
    creator = VideoCreatorBasic(channel_cfg=cfg)
    assert creator.channel_name == "Borsa Akademi"

    creator_pro = VideoCreatorPro(channel_cfg=cfg)
    assert creator_pro.channel_name == "Borsa Akademi"
    assert creator_pro.channel_tagline == "Finans & Yatirim Rehberi"


def test_generic_playlist_fallback_is_neutral():
    manager = PlaylistManager(_FakeYoutubeService())
    assert manager._match_playlist("Kuantum ogrenme notlari") == "Genel Bilgi Rehberi 2026"  # noqa: SLF001


def test_finance_playlist_mapping_is_preserved():
    manager = PlaylistManager(_FakeYoutubeService())
    assert manager._match_playlist("Borsa portfoy yonetimi") == "Yatirim Rehberi 2026"  # noqa: SLF001


def test_generic_shorts_and_community_fallbacks_are_neutral(monkeypatch, tmp_path):
    shorts_creator = ShortsCreator(channel_cfg=None)
    assert shorts_creator.channel_name == "Genel Kanal"

    token_path = tmp_path / "token.pickle"
    import pickle

    token_path.write_bytes(pickle.dumps(_FakeCredentials()))

    from src import community_poster as cp

    monkeypatch.setattr(cp, "AuthorizedSession", _FakeSession)

    cfg = SimpleNamespace(token_path=str(token_path))
    ok = post_video_announcement(cfg, "video1", "Baslik")
    assert ok is True
    text = _FakeSession.last_payload["snippet"]["topLevelComment"]["snippet"]["textOriginal"]
    assert "Genel Kanal" in text


def test_existing_renderer_regressions_stay_green_smoke():
    cfg = SimpleNamespace(
        video_width=1280,
        video_height=720,
        videos_dir="output/videos",
        color_primary=(12, 34, 56),
        color_bg=(21, 43, 65),
        name="Test Kanal",
        tagline="Test Tagline",
        base_dir=".",
    )
    creator = VideoCreatorBasic(channel_cfg=cfg)
    creator_pro = VideoCreatorPro(channel_cfg=cfg)
    assert creator.width == 1280
    assert creator.height == 720
    assert creator_pro.width == 1280
    assert creator_pro.height == 720
