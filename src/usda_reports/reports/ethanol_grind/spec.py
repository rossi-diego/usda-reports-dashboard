"""Ethanol Grind report spec: wires the direct-download ingest and silver parser into the
registry (through the shared :class:`~usda_reports.nass_common.spec.NassZipSpec`).

Unlike the other ``NassZipSpec`` reports, :meth:`ingest` does not call
``nass_common.ingest.ingest_zips`` (which discovers releases via ESMIS ``findByIdentifier``):
this report has no registered ESMIS identifier, so it fetches directly from
release.nass.usda.gov using the calendar instead (see
:mod:`usda_reports.reports.ethanol_grind.ingest`)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import httpx
import pandas as pd
import pyarrow as pa

from usda_reports.nass_common.spec import NassZipSpec

if TYPE_CHECKING:
    from usda_reports.bronze.store import BronzeStore
    from usda_reports.nass_common.ingest import IngestResult
    from usda_reports.nass_common.spec import StoredRelease
    from usda_reports.reports.ethanol_grind.source import SourceConfig


class EthanolGrindSpec(NassZipSpec):
    """NASS Grain Crushings and Co-Products Production (monthly, ~1st business day 15:00 ET,
    covering month - 2); fetched directly, no ESMIS identifier."""

    title = "Ethanol Grind"
    log_prefix = "ethanol_grind"

    def source_config(self) -> SourceConfig:
        from usda_reports.reports.ethanol_grind.source import SourceConfig

        return SourceConfig.load(self.source_path)

    def error_class(self) -> type[Exception]:
        from usda_reports.reports.ethanol_grind.source import EthanolGrindError

        return EthanolGrindError

    def silver_columns(self) -> list[str]:
        from usda_reports.reports.ethanol_grind.parse import SILVER_COLUMNS

        return SILVER_COLUMNS

    def silver_schema(self) -> pa.Schema:
        from usda_reports.reports.ethanol_grind.parse import SILVER_SCHEMA

        return SILVER_SCHEMA

    def frame(self, releases: list[StoredRelease]) -> pd.DataFrame:
        from usda_reports.reports.ethanol_grind.parse import build_frame

        return build_frame(releases, self.source_config(), self.config.release_time_et)

    def validate(self, silver: pd.DataFrame) -> None:
        from usda_reports.reports.ethanol_grind.parse import validate

        validate(silver, self.contract())

    def ingest(
        self,
        client: httpx.Client,
        store: BronzeStore,
        now: datetime | None = None,
        force: bool = False,
        full: bool = False,
    ) -> IngestResult:
        from usda_reports.reports.ethanol_grind.ingest import ingest as ingest_direct

        return ingest_direct(
            client,
            store,
            self.source_config(),
            self.calendar(),
            error=self.error_class(),
            check=self.check_release,
            full=full,
            force=force,
        )
