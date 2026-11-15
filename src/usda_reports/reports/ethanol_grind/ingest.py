"""Ethanol Grind ingestion into bronze: direct download from release.nass.usda.gov.

Unlike the other NASS reports (Fats & Oils, Crop Progress, Grain Stocks), this one has no
registered ESMIS quick identifier (see ``config/reports/ethanol_grind/source.yaml``), so there
is no ``findByIdentifier`` listing to discover releases from. Instead, the calendar
(``config/calendars/ethanol_grind.yaml``) names every scheduled release date, and the zip for
each is fetched directly from NASS's own release server using its predictable naming
(``cagc<MM><YY>.zip``, where MM/YY is the *release* month).

* **Backfill** (``full=True``): try every calendar date from ``history_start`` through today.
* **Regular run**: try only dates newer than the newest release already in bronze, plus the
  newest ``recheck_last`` stored releases (changed bytes become a new edition of the same key).
* A scheduled date whose zip is not yet there (404) is simply not in bronze yet; it is tried
  again on every later run (the calendar, not a "skipped" record, is the source of truth for
  what was ever scheduled).

Every zip is parsed and contract-checked (``check``) *before* it reaches bronze; a problem
raises the report's own error (or an unseen-label error) and leaves bronze as it was.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date

import httpx

from usda_reports.bronze.store import BronzeStore, sha256
from usda_reports.core.logs import get_logger
from usda_reports.nass_common.ingest import IngestResult
from usda_reports.nass_common.zipfetch import NassZipError, fetch_zip
from usda_reports.reports.ethanol_grind.source import SOURCE, SourceConfig

log = get_logger(__name__)


def release_url(base_url: str, release_date: date) -> str:
    """``cagc1126`` for a 2026-11-xx release (code = release month + 2-digit release year)."""
    code = f"{release_date.month:02d}{release_date.year % 100:02d}"
    return base_url.format(code=code)


def ingest(
    client: httpx.Client,
    store: BronzeStore,
    cfg: SourceConfig,
    dates: list[date],
    *,
    error: type[Exception],
    check: Callable[[str, bytes], None] | None = None,
    full: bool = False,
    force: bool = False,
    pause_s: float = 0.3,
) -> IngestResult:
    """Store every new (or changed) release zip of Ethanol Grind in bronze."""
    result = IngestResult()
    ok_keys = sorted(k for k, e in store.entries.items() if e.status == "ok")
    candidates = sorted(d.isoformat() for d in dates if d.isoformat() >= cfg.history_start)
    if not candidates:
        raise error(f"calendar lists no Ethanol Grind date since {cfg.history_start}")
    if full:
        to_try = candidates
    else:
        newest_ok = ok_keys[-1] if ok_keys else None
        newer = [k for k in candidates if newest_ok is None or k > newest_ok]
        recheck = set(ok_keys[-cfg.recheck_last :]) if cfg.recheck_last else set()
        to_try = sorted(set(newer) | recheck)
    for key in to_try:
        old = store.entries.get(key)
        if (
            old is not None
            and not force
            and old.status == "ok"
            and key not in (set() if full else recheck)
        ):
            continue
        url = release_url(cfg.base_url, date.fromisoformat(key))
        try:
            data = fetch_zip(client, url)
        except NassZipError as exc:
            raise error(f"release {key}: {exc}") from exc
        result.calls += 1
        if pause_s:
            time.sleep(pause_s)
        if data is None:
            log.info("ethanol_grind.not_yet_available", release=key, url=url)
            continue
        if old is not None and old.status == "ok" and old.sha256 == sha256(data):
            continue
        if check is not None:
            check(key, data)  # raises: nothing is written to bronze
        edition = old.edition + 1 if old is not None and old.status == "ok" else 1
        store.put(key, data, source=SOURCE, url=url, release_date=key, edition=edition)
        result.ingested.append(key)
    result.note = "ingested" if result.ingested else "no new release"
    log.info(
        "ethanol_grind.ingest",
        tried=len(to_try),
        ingested=result.ingested,
        full=full,
        calls=result.calls,
    )
    return result
