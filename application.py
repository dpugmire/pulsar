from typing import List, Optional

from pulsar.backends import (
    BackendStatus,
    CatalogBackend,
    LocalCampaignBackend,
    NavigationNode,
    NavigationRequest,
    NavigationResource,
    NavigationView,
    PulsarBackend,
    SourceDescriptor,
    SourceLookupRequest,
    SourceRestrictionRequest,
    SourceRestrictionResult,
    SourceSummary,
    SourceSummaryRequest,
)


class PulsarApplication:
    """Backend application facade used by Trame controller adapters."""

    def __init__(
        self,
        campaign_db=None,
        *,
        backend: Optional[PulsarBackend] = None,
    ):
        if backend is None:
            if campaign_db is None:
                raise TypeError("PulsarApplication requires a backend or campaign_db")
            backend = LocalCampaignBackend(campaign_db)
        self._backend = backend

    def get_navigation(self, request: NavigationRequest) -> List[NavigationNode]:
        return self._backend.get_navigation(request)

    def get_backend_status(self) -> BackendStatus:
        return self._backend.get_status()

    def get_source_summary(self, request: SourceSummaryRequest) -> SourceSummary:
        return self._backend.get_source_summary(request)

    def find_source(
        self, request: SourceLookupRequest
    ) -> Optional[SourceDescriptor]:
        return self._backend.find_source(request)

    def resolve_source_restriction(
        self, request: SourceRestrictionRequest
    ) -> SourceRestrictionResult:
        return self._backend.resolve_source_restriction(request)


__all__ = (
    "BackendStatus",
    "CatalogBackend",
    "NavigationNode",
    "NavigationRequest",
    "NavigationResource",
    "NavigationView",
    "PulsarBackend",
    "PulsarApplication",
    "SourceDescriptor",
    "SourceLookupRequest",
    "SourceRestrictionRequest",
    "SourceRestrictionResult",
    "SourceSummary",
    "SourceSummaryRequest",
)
