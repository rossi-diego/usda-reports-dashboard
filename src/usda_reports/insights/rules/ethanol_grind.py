"""Ethanol Grind insights H1-H2 (the F1/F2 analogue for the NASS crush). Corn; marketing year
September-August; history window 2016/17+ (release.nass.usda.gov has Ethanol Grind files from
the 2016-03-01 release only, so no "since 2010" claims). Every row of ``fct_ethanol_pace`` is
point in time: the NASS vintages and the WASDE that were public when NASS first printed that
month. History = the same month of the 5 prior MYs, each against its own as-of WASDE.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from usda_reports.insights import stats
from usda_reports.insights.schema import InputRef, Insight

WINDOW_5Y = "prior_5_my_same_month"
SHARE_DP = 6
HISTORY_START = "2016-03"  # first release.nass.usda.gov Ethanol Grind file
COMMODITY = "corn"


def _f(v: Any) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def _r(v: float | None, nd: int) -> float | None:
    return None if v is None else round(v, nd)


def _ts(v: Any) -> str | None:
    if v is None or pd.isna(v):
        return None
    return pd.Timestamp(v).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _s(v: Any) -> str | None:
    return v if isinstance(v, str) else None


def pace_frame(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("select * from fct_ethanol_pace order by month").df()


def current_row(pace: pd.DataFrame) -> pd.Series:
    return pace.sort_values("month").iloc[-1]


def history_at_month(pace: pd.DataFrame, cur: pd.Series) -> pd.DataFrame:
    """The same month_of_my in the 5 previous marketing years."""
    h = pace[
        (pace.month_of_my == cur.month_of_my)
        & (pace.my_start >= cur.my_start - 5)
        & (pace.my_start <= cur.my_start - 1)
    ]
    return h.sort_values("my_start")


def _common(cur: pd.Series) -> dict[str, Any]:
    return {
        "market_year": cur.market_year,
        "month": str(pd.Timestamp(cur.month).date()),
        "month_of_my": int(cur.month_of_my),
        "release_key": cur.release_key,
        "first_printed_as": _s(cur.first_printed_as),
        "history_start": HISTORY_START,
    }


def _inputs(cur: pd.Series, wasde_key: Any) -> list[InputRef]:
    refs = [InputRef(report_id="ethanol_grind", release_key=str(cur.release_key))]
    if isinstance(wasde_key, str):
        refs.append(InputRef(report_id="wasde", release_key=wasde_key))
    return refs


def _range(value: float | None, vals: list[float], nd: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "hist_mean": None,
        "hist_min": None,
        "hist_max": None,
        "position": None,
        "outside_distance": None,
    }
    if not vals:
        return out
    lo, hi = min(vals), max(vals)
    out.update(hist_mean=_r(stats.mean(vals), nd), hist_min=_r(lo, nd), hist_max=_r(hi, nd))
    if value is not None:
        out["position"] = stats.range_position(value, lo, hi)
        out["outside_distance"] = round(stats.outside_distance(value, lo, hi), max(nd, 4))
    return out


def h1_grind_pace(pace: pd.DataFrame) -> list[Insight]:
    """H1: MY-to-date corn-for-fuel-alcohol use (bu) / the as-of WASDE "Ethanol & by-products"
    projection, vs the 5 prior MYs at the same month."""
    if pace.empty:
        return []
    cur = current_row(pace)
    hist = history_at_month(pace, cur)
    hist = hist[hist.pct_of_target.notna()]
    pct = _f(cur.pct_of_target)
    vals = [float(v) for v in hist.pct_of_target]
    params: dict[str, Any] = {
        **_common(cur),
        "unit_id": "bu",
        "cum_bu": _f(cur.cum_bu),
        "cum_kbu": _f(cur.cum_kbu),
        "month_grind_bu": _f(cur.month_grind_bu),
        "month_grind_kbu": _f(cur.month_grind_kbu),
        "wasde_release_key": _s(cur.wasde_release_key),
        "target_bu": _f(cur.wasde_ethanol_bu),
        "target_native": _f(cur.wasde_ethanol_native),
        "target_unit_id": _s(cur.wasde_ethanol_unit_id),
        "target_flag": _s(cur.wasde_proj_est_flag),
        "pct": _r(pct, SHARE_DP),
        **_range(pct, vals, SHARE_DP),
        "history": [
            {
                "market_year": r.market_year,
                "pct": round(float(r.pct_of_target), SHARE_DP),
                "wasde_release_key": r.wasde_release_key,
            }
            for r in hist.itertuples()
        ],
    }
    return [
        Insight(
            id=f"H1:{COMMODITY}",
            rule="H1",
            report_id="ethanol_grind",
            commodity_id=COMMODITY,
            kind="grind_pace",
            params=params,
            n=len(vals),
            window=WINDOW_5Y,
            robustness="robust",
            caveats=[
                "history_point_in_time",
                "ethanol_grind_history_from_2016",
                "nass_revises_previous_month",
            ],
            inputs=_inputs(cur, cur.wasde_release_key),
            as_of=_ts(cur.release_ts_utc),
            suppressed_reason="asof_missing" if pct is None else None,
        )
    ]


def h2_required_monthly_grind(pace: pd.DataFrame, min_months: int = 5) -> list[Insight]:
    """H2: (as-of WASDE ethanol-use target - MY-to-date) / months remaining vs the mean of the
    same remaining months last MY (as known at the time)."""
    if pace.empty:
        return []
    cur = current_row(pace)
    target = _f(cur.wasde_ethanol_bu)
    req = _f(cur.required_monthly_bu)
    last = _f(cur.last_my_remaining_mean_bu)
    months = int(cur.months_remaining)
    reason: Any = None
    if target is None:
        reason = "asof_missing"
    elif months < min_months:
        reason = "months_remaining_below_min"
    elif last is None:
        reason = "no_data"
    cum = _f(cur.cum_bu)
    return [
        Insight(
            id=f"H2:{COMMODITY}",
            rule="H2",
            report_id="ethanol_grind",
            commodity_id=COMMODITY,
            kind="required_monthly_grind",
            params={
                **_common(cur),
                "unit_id": "bu",
                "cum_bu": cum,
                "wasde_release_key": _s(cur.wasde_release_key),
                "target_bu": target,
                "target_native": _f(cur.wasde_ethanol_native),
                "target_unit_id": _s(cur.wasde_ethanol_unit_id),
                "remaining_to_target_bu": target - cum
                if target is not None and cum is not None
                else None,
                "months_remaining": months,
                "required_monthly_bu": _r(req, 0),
                "last_my_remaining_mean_bu": _r(last, 0),
                "last_my_remaining_n": int(cur.last_my_remaining_n),
                "ratio_required_to_last_my": round(req / last, 4)
                if req is not None and last not in (None, 0)
                else None,
            },
            n=int(cur.last_my_remaining_n),
            window="last_my_same_remaining_months",
            robustness="robust",
            caveats=["nass_revises_previous_month"],
            inputs=_inputs(cur, cur.wasde_release_key),
            as_of=_ts(cur.release_ts_utc),
            suppressed_reason=reason,
        )
    ]
