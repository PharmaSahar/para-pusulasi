from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from src import youtube_auth


class FakeCreds:
    def __init__(self, *, valid: bool = True, expired: bool = False, scopes: list[str] | None = None):
        self.valid = valid
        self.expired = expired
        self.refresh_token = "refresh-token"
        self.scopes = scopes or []

    def has_scopes(self, scopes):
        return set(scopes).issubset(set(self.scopes))


def _write_token(path: Path, credentials: FakeCreds) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(credentials, handle)


def test_get_credentials_requires_existing_analytics_token(tmp_path):
    missing_token = tmp_path / "youtube_analytics_token.pickle"

    with pytest.raises(FileNotFoundError, match="analytics_token_missing"):
        youtube_auth._get_credentials(
            scopes=youtube_auth.ANALYTICS_SCOPES,
            token_path=str(missing_token),
            secrets_path=str(tmp_path / "client_secrets.json"),
            allow_oauth_flow=False,
            require_existing_token=True,
        )


def test_get_credentials_rejects_invalid_analytics_scopes(tmp_path):
    token_path = tmp_path / "youtube_analytics_token.pickle"
    _write_token(token_path, FakeCreds(scopes=["https://www.googleapis.com/auth/youtube.upload"]))

    with pytest.raises(PermissionError, match="analytics_token_scope_invalid"):
        youtube_auth._get_credentials(
            scopes=youtube_auth.ANALYTICS_SCOPES,
            token_path=str(token_path),
            secrets_path=str(tmp_path / "client_secrets.json"),
            allow_oauth_flow=False,
            require_existing_token=True,
        )