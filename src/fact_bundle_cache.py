"""Cache interface for validated fact bundles."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .fact_bundle import FactBundle


class FactBundleCache(ABC):
    """Abstract cache interface for bundle storage and invalidation."""

    @abstractmethod
    def get(self, bundle_id: str) -> FactBundle | None:
        raise NotImplementedError

    @abstractmethod
    def set(self, bundle: FactBundle) -> None:
        raise NotImplementedError

    @abstractmethod
    def invalidate(self, bundle_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        raise NotImplementedError


__all__ = ["FactBundleCache"]