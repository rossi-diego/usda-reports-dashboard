"""Ethanol Grind silver: every bronze zip (one per release) -> one long table of vintages.

Each release prints both tables for three months (year-ago, previous month as revised, current
month). Silver keeps **every** printed value with the release that printed it, so the gold
layer can rebuild what was known at any instant (point in time) and also the latest revised
value per month. Row grain: release x table x month x metric (commodity is constant: corn).

Envelope semantics:

* ``release_key``: the release date (``YYYY-MM-DD``), the calendar date this report's zip was
  fetched for -- never derived from the zip's internal file names.
* ``release_ts_utc``: that date at the configured release time (15:00 ET) in UTC.
* ``vintage_quality``: always ``as_published`` (the zips are the files NASS released).

Other columns: ``month`` (first day of the data month), ``market_year`` (corn marketing year,
September-August, WASDE notation ``2026/27``), ``month_of_my`` (1 = September), ``column_role``
(``current`` | ``previous`` | ``year_ago``), ``reported_month`` (the newest month in that
release), ``value_flag`` (NASS symbol of a withheld value), ``nass_table_id`` (``1`` = corn
consumed, ``3`` = co-products produced).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from usda_reports.core.contracts import Contract
from usda_reports.core.logs import get_logger
from usda_reports.core.manifest import Manifest, release_ts_utc
from usda_reports.core.vocab import UnseenLabelError
from usda_reports.nass_common.csv_tables import (
    NassBlock,
    NassCsvError,
    NassTable,
    find_tables,
    parse_nass_csv,
    parse_value,
)
from usda_reports.nass_common.spec import (
    StoredRelease,
    arrow_schema,
    load_stored_releases,
    write_parquet,
)
from usda_reports.nass_common.zipfetch import NassZipError, read_member
from usda_reports.reports.ethanol_grind.source import (
    REPORT_ID,
    SOURCE,
    EthanolGrindError,
    SourceConfig,
    TableConfig,
)
from usda_reports.silver.envelope import ENVELOPE_COLUMNS

log = get_logger(__name__)

KEY = ["release_key", "nass_table_id", "month", "metric"]
SILVER_COLUMNS = [
    *ENVELOPE_COLUMNS,
    "commodity_id",
    "region_id",
    "unit_id",
    "value",
    "value_flag",
    "metric",
    "month",
    "market_year",
    "my_start",
    "month_of_my",
    "column_role",
    "reported_month",
    "nass_table_id",
    "source_label",
    "source_unit_label",
    "zip_member",
    "source_url",
]
_INT = {"edition", "my_start", "month_of_my"}
_DATES = {"month", "reported_month"}
SILVER_SCHEMA = arrow_schema(SILVER_COLUMNS, ints=_INT, floats={"value"}, dates=_DATES)
# Corn marketing year (dbt/seeds/dim_commodity.csv: corn starts month 9).
MY_START_MONTH = 9

_MONTH_RE = re.compile(r"^([A-Z][a-z]+) (\d{4})$")
_TITLE_MONTH_RE = re.compile(r":\s*([A-Z][a-z]+ \d{4})")


def write_silver(df: pd.DataFrame, path: Path) -> Path:
    return write_parquet(df, SILVER_COLUMNS, SILVER_SCHEMA, path)


def month_label(s: str) -> date:
    """``"September 2026"`` -> 2026-09-01."""
    m = _MONTH_RE.match(s.strip())
    if not m:
        raise EthanolGrindError(f"unexpected month header {s!r}")
    return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%B %Y").date()


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def market_year(month: date, start_month: int = MY_START_MONTH) -> tuple[str, int, int]:
    """(``2026/27``, my_start 2026, month_of_my 1) for September 2026."""
    start = month.year if month.month >= start_month else month.year - 1
    return (
        f"{start}/{(start + 1) % 100:02d}",
        start,
        months_between(date(start, start_month, 1), month) + 1,
    )


def column_role(month: date, reported: date) -> str:
    lag = months_between(month, reported)
    return {0: "current", 1: "previous", 12: "year_ago"}.get(lag, "earlier")


def title_month(title: str) -> date:
    m = _TITLE_MONTH_RE.search(title)
    if not m:
        raise EthanolGrindError(f"no month in table title {title!r}")
    return month_label(m.group(1))


def _find_header_block(table: NassTable, first_cell: str) -> tuple[NassBlock, list[str]] | None:
    for block in table.blocks:
        header = block.header_row(first_cell)
        if header is not None:
            return block, header
    return None


def parse_table(
    table: NassTable,
    cfg: TableConfig,
    header_fixes: dict[str, str],
    release_key: str | None,
    commodity_id: str,
    region_id: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows of one table (no envelope) and any unseen row labels."""
    found = _find_header_block(table, cfg.header_first_cell)
    if found is None:
        raise EthanolGrindError(
            f"table {table.number}: no header row starting with {cfg.header_first_cell!r}"
        )
    block, header = found
    month_cells = [header_fixes.get(c.strip(), c.strip()) for c in header[1:] if c.strip()]
    months = [month_label(c) for c in month_cells]
    if not months or months != sorted(months) or len(set(months)) != len(months):
        raise EthanolGrindError(f"table {table.number}: month columns {month_cells} not in order")
    reported = max(months)
    if reported != title_month(table.title):
        raise EthanolGrindError(
            f"table {table.number}: newest column {reported:%B %Y} differs from the title "
            f"{table.title!r}"
        )
    unit_cells = {c.strip() for u in block.units for c in u[1:] if c.strip()}
    if unit_cells != {cfg.unit_label}:
        raise EthanolGrindError(f"table {table.number}: unit labels {sorted(unit_cells)}")
    known = set(cfg.known_rows)
    rows: list[dict[str, Any]] = []
    unseen: list[str] = []
    seen_metrics: set[str] = set()
    for cells in block.rows:
        label = (cells[0] if cells else "").strip()
        if not label:
            continue
        ref = cfg.metrics.get(label)
        if ref is None:
            if label not in known:
                unseen.append(label)
            continue
        if ref.metric in seen_metrics:
            raise EthanolGrindError(f"table {table.number}: row {label!r} printed twice")
        seen_metrics.add(ref.metric)
        values = cells[1 : 1 + len(months)]
        if len(values) != len(months):
            raise EthanolGrindError(f"table {table.number}: {label!r} has {len(values)} values")
        for mon, cell in zip(months, values, strict=True):
            try:
                value, flag = parse_value(cell)
            except NassCsvError as exc:
                raise EthanolGrindError(f"{label!r} {mon:%Y-%m}: {exc}") from exc
            my, my_start, month_of_my = market_year(mon)
            rows.append(
                {
                    "commodity_id": commodity_id,
                    "region_id": region_id,
                    "unit_id": cfg.unit,
                    "value": value,
                    "value_flag": flag,
                    "metric": ref.metric,
                    "month": mon,
                    "market_year": my,
                    "my_start": my_start,
                    "month_of_my": month_of_my,
                    "column_role": column_role(mon, reported),
                    "reported_month": reported,
                    "nass_table_id": table.number,
                    "source_label": label,
                    "source_unit_label": cfg.unit_label,
                }
            )
    missing = {m.metric for m in cfg.metrics.values()} - seen_metrics
    if missing:
        raise EthanolGrindError(f"table {table.number}: rows missing for {sorted(missing)}")
    return rows, unseen


def parse_release(data: bytes, cfg: SourceConfig, release_key: str | None = None) -> pd.DataFrame:
    """Rows of both tables of one release zip (no envelope).

    Raises :class:`EthanolGrindError` on a structural problem and :class:`UnseenLabelError` on
    a row label that is neither a configured metric nor a known non-metric row."""
    try:
        member, csv_bytes = read_member(data, cfg.zip_member)
        all_tables = parse_nass_csv(csv_bytes)
    except (NassZipError, NassCsvError) as exc:
        raise EthanolGrindError(str(exc)) from exc
    fixes = cfg.header_fixes.get(release_key or "", {})
    rows: list[dict[str, Any]] = []
    unseen: list[str] = []
    for table_cfg in cfg.tables.values():
        matches = [
            t
            for t in find_tables(all_tables, table_cfg.title_prefix)
            if t.number == table_cfg.number
        ]
        if len(matches) != 1:
            raise EthanolGrindError(
                f"expected one table {table_cfg.number!r} titled {table_cfg.title_prefix!r}, "
                f"found {len(matches)}"
            )
        table_rows, table_unseen = parse_table(
            matches[0], table_cfg, fixes, release_key, cfg.commodity_id, cfg.region_id
        )
        for r in table_rows:
            r["zip_member"] = member
        rows.extend(table_rows)
        unseen.extend(table_unseen)
    if unseen:
        raise UnseenLabelError(
            f"unseen Ethanol Grind row labels {sorted(set(unseen))}: add them to "
            "config/reports/ethanol_grind/source.yaml (metrics or known_rows)"
        )
    return pd.DataFrame(rows)


def check_lag(key: str, reported: date, cfg: SourceConfig) -> None:
    lag = months_between(reported, date.fromisoformat(key))
    if not cfg.lag_months.min <= lag <= cfg.lag_months.max:
        raise EthanolGrindError(
            f"release {key} reports {reported:%B %Y}: {lag} months earlier "
            f"(expected {cfg.lag_months.min}-{cfg.lag_months.max})"
        )


def build_frame(
    releases: list[StoredRelease], cfg: SourceConfig, release_time_et: str = "15:00"
) -> pd.DataFrame:
    """Silver frame (envelope first) of ``releases``; raises on any parse problem."""
    frames = []
    for r in releases:
        df = parse_release(r.data, cfg, r.key)
        check_lag(r.key, df["reported_month"].iloc[0], cfg)
        ts = release_ts_utc(r.key, release_time_et)
        df.insert(0, "report_id", REPORT_ID)
        df.insert(1, "release_key", r.key)
        df.insert(2, "release_ts_utc", pd.Timestamp(ts))
        df.insert(3, "edition", r.edition)
        df.insert(4, "source", SOURCE)
        df.insert(5, "bronze_sha256", r.sha256)
        df.insert(6, "vintage_quality", "as_published")
        df["source_url"] = r.url
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=SILVER_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    out["release_ts_utc"] = pd.to_datetime(out["release_ts_utc"], utc=True)
    for c in _INT:
        out[c] = out[c].astype("int32")
    return out[SILVER_COLUMNS].sort_values(KEY, kind="stable").reset_index(drop=True)


def load_releases(bronze_dir: Path, manifest: Manifest, strict: bool = True) -> list[StoredRelease]:
    return load_stored_releases(bronze_dir, manifest, REPORT_ID, EthanolGrindError, strict)


def validate(silver: pd.DataFrame, contract: Contract) -> None:
    contract.enforce(silver)
    if silver.empty:
        return
    # Each month's newest vintage must not jump between releases by more than a revision would
    # (a mis-read column would): the current-month DDGS value must match how the next release
    # prints it as the previous month within 20% (co-products are noisier than the crush itself).
    ddgs = silver[silver.metric == "ddgs_st"]
    cur = ddgs[ddgs.column_role == "current"].set_index("month")["value"]
    prev = ddgs[ddgs.column_role == "previous"].set_index("month")["value"]
    both = cur.to_frame("cur").join(prev.to_frame("prev"), how="inner").dropna()
    bad = both[(both.prev - both.cur).abs() > 0.20 * both.cur]
    if len(bad):
        from usda_reports.core.contracts import ContractError

        raise ContractError(f"DDGS revisions above 20% for months {list(bad.index)[:5]}")
