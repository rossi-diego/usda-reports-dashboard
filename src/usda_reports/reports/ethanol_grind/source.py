"""Configuration and errors of the NASS Grain Crushings ("Ethanol Grind") source.

Everything verified in the spike lives in ``config/reports/ethanol_grind/source.yaml``: the
direct release.nass.usda.gov URL template, the zip member, the two tables' titles, unit labels
and the row labels mapped to silver metrics. Unlike the other NASS reports this one has no
registered ESMIS quick identifier, so it is fetched directly rather than discovered via
``findByIdentifier`` (see :mod:`usda_reports.reports.ethanol_grind.ingest`).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

REPORT_ID = "ethanol_grind"
SOURCE = "nass_direct_zip"


class EthanolGrindError(RuntimeError):
    """An Ethanol Grind release (or its zip) cannot be used as published."""


# Kept as an alias so the shared NASS plumbing (nass_common.spec) can refer to one name across
# reports if needed.
NassError = EthanolGrindError


class MetricRef(BaseModel):
    metric: str


class LagMonths(BaseModel):
    min: int = 1
    max: int = 3


class TableConfig(BaseModel):
    number: str
    title_prefix: str
    header_first_cell: str
    unit_label: str
    unit: str
    metrics: dict[str, MetricRef]
    known_rows: list[str] = Field(default_factory=list)


class SourceConfig(BaseModel):
    base_url: str
    zip_member: str = "*_all_tables.csv"
    history_start: str = "2016-03-01"
    recheck_last: int = 2
    lag_months: LagMonths = Field(default_factory=LagMonths)
    commodity_id: str = "corn"
    region_id: str = "united_states"
    tables: dict[str, TableConfig]
    header_fixes: dict[str, dict[str, str]] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> SourceConfig:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
