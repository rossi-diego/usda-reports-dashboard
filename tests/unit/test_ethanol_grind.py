"""NASS Grain Crushings and Co-Products Production ("Ethanol Grind"): parser, direct-download
ingest and the silver contract. Fixtures are real release.nass.usda.gov zips (no network;
downloaded 2026-11-15 as part of the initial backfill of this report)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from usda_reports.core.contracts import Contract
from usda_reports.core.vocab import UnseenLabelError
from usda_reports.reports.ethanol_grind.ingest import release_url
from usda_reports.reports.ethanol_grind.parse import (
    StoredRelease,
    build_frame,
    column_role,
    market_year,
    months_between,
    parse_release,
    title_month,
    validate,
)
from usda_reports.reports.ethanol_grind.source import EthanolGrindError, SourceConfig

FX = Path(__file__).resolve().parents[1] / "fixtures" / "ethanol_grind"


@pytest.fixture
def cfg(config_dir: Path) -> SourceConfig:
    return SourceConfig.load(config_dir / "reports" / "ethanol_grind" / "source.yaml")


def zip_bytes(key: str) -> bytes:
    return (FX / f"{key}.zip").read_bytes()


# ------------------------------------------------------------------ small helpers


def test_market_year_and_column_role():
    assert market_year(date(2026, 9, 1)) == ("2026/27", 2026, 1)
    assert market_year(date(2026, 8, 1)) == ("2025/26", 2025, 12)
    assert column_role(date(2026, 9, 1), date(2026, 9, 1)) == "current"
    assert column_role(date(2026, 8, 1), date(2026, 9, 1)) == "previous"
    assert column_role(date(2025, 9, 1), date(2026, 9, 1)) == "year_ago"
    assert column_role(date(2025, 8, 1), date(2026, 9, 1)) == "earlier"


def test_title_month():
    assert title_month(
        "Dry and Wet Mill, Corn Consumed - United States: September 2026 with Comparisons"
    ) == date(2026, 9, 1)
    with pytest.raises(EthanolGrindError):
        title_month("no month here")


def test_release_url():
    assert (
        release_url("https://release.nass.usda.gov/reports/cagc{code}.zip", date(2026, 11, 2))
        == "https://release.nass.usda.gov/reports/cagc1126.zip"
    )
    assert (
        release_url("https://release.nass.usda.gov/reports/cagc{code}.zip", date(2016, 3, 1))
        == "https://release.nass.usda.gov/reports/cagc0316.zip"
    )


# ------------------------------------------------------------------ parse_release


def test_parse_release_current_month(cfg: SourceConfig):
    df = parse_release(zip_bytes("2026-11-02"), cfg, "2026-11-02")
    assert set(df.nass_table_id) == {"1", "3"}
    # 6 corn-consumed metrics + 11 co-product metrics, x 3 printed months each.
    assert len(df) == (6 + 11) * 3
    cur = df[(df.column_role == "current") & (df.metric == "corn_fuel_alcohol_kbu")]
    assert cur.value.iloc[0] == 438423
    ddgs = df[(df.column_role == "current") & (df.metric == "ddgs_st")]
    assert ddgs.value.iloc[0] == 1699191
    # Fuel alcohol = dry mill + wet mill (same release, same column).
    dry = df[(df.column_role == "current") & (df.metric == "corn_fuel_dry_mill_kbu")].value.iloc[0]
    wet = df[(df.column_role == "current") & (df.metric == "corn_fuel_wet_mill_kbu")].value.iloc[0]
    assert dry + wet == cur.value.iloc[0]


def test_parse_release_early_history_has_extra_wet_mill_corn_oil_row(cfg: SourceConfig):
    """The 2016-03-01 release prints a bare "Corn oil" row (wet mill) dropped since ~2017;
    it must be a known (dropped) row, not an unseen label, and not collide with the tracked
    dry-mill "Corn oil (Corn Distillers Oil - CDO)" metric."""
    df = parse_release(zip_bytes("2016-03-01"), cfg, "2016-03-01")
    assert len(df) == (6 + 11) * 3
    assert df["metric"].eq("corn_oil_st").sum() == 3  # the tracked dry-mill CDO row only


def test_parse_release_rejects_unseen_label(cfg: SourceConfig):
    """Mutate a non-metric section-header label (not a required row, so no metric goes
    missing) into something unrecognised and confirm it fails loudly instead of silently
    dropping it."""
    import io
    import zipfile

    src = zip_bytes("2026-11-02")
    with zipfile.ZipFile(io.BytesIO(src)) as zin:
        member = next(n for n in zin.namelist() if n.endswith("all_tables.csv"))
        raw = zin.read(member)
    mutated = raw.replace(b"Consumed for other purposes", b"Consumed for a brand new purpose")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zout, zipfile.ZipFile(io.BytesIO(src)) as zin:
        for n in zin.namelist():
            zout.writestr(n, mutated if n == member else zin.read(n))
    with pytest.raises(UnseenLabelError):
        parse_release(buf.getvalue(), cfg, "2026-11-02")


# ------------------------------------------------------------------ build_frame / contract


def test_build_frame_and_lag_check(cfg: SourceConfig):
    releases = [
        StoredRelease(
            key="2025-12-10", sha256="0" * 64, edition=1, url=None, data=zip_bytes("2025-12-10")
        ),
        StoredRelease(
            key="2026-11-02", sha256="0" * 64, edition=1, url=None, data=zip_bytes("2026-11-02")
        ),
    ]
    df = build_frame(releases, cfg, "15:00")
    assert set(df.report_id) == {"ethanol_grind"}
    assert set(df.commodity_id) == {"corn"}
    assert set(df.region_id) == {"united_states"}
    assert df.release_ts_utc.notna().all()
    # Each release covers a month 1-3 months before its release date (lag_months in source.yaml).
    for key, group in df.groupby("release_key"):
        reported = pd.Timestamp(group.reported_month.iloc[0]).date()
        lag = months_between(reported, date.fromisoformat(key))
        assert 1 <= lag <= 3


def test_validate_runs_the_silver_contract(cfg: SourceConfig, config_dir: Path):
    releases = [
        StoredRelease(
            key="2026-11-02", sha256="0" * 64, edition=1, url=None, data=zip_bytes("2026-11-02")
        ),
    ]
    df = build_frame(releases, cfg, "15:00")
    contract = Contract.load(config_dir / "contracts" / "ethanol_grind.yaml")
    validate(df, contract)  # must not raise
