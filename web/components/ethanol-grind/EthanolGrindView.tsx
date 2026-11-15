"use client";

import Link from "next/link";

import { ChartTable, Chevron } from "@/components/charts/common";
import PaceChart from "@/components/charts/PaceChart";
import WeeklyBars from "@/components/charts/WeeklyBars";
import { T, useLang, useT } from "@/components/chrome/I18n";
import TopBar, { type ReleaseInfo } from "@/components/chrome/TopBar";
import { SmallChip } from "@/components/home/InsightCards";
import type { EthanolGrindCommodity, Insight, InsightsDoc } from "@/lib/data-contract";
import { bushels, bushelsAxis, bytes, monthOf, monthYear, num, share, shortDate, shortTons, signed, stPerKbu } from "@/lib/format";
import { byId, caveatText, suppressedText } from "@/lib/insight-text";
import type { Key } from "@/lib/i18n";

export type TakeFile = { file: string; dataset: string; format: string; href: string; bytes: number; rows: number };

const ROSE = "var(--r-ethanol)";

/** Marketing-year month 1..12 -> calendar month (1 = September). */
const calMonth = (m: number) => ((m + 7) % 12) + 1;

/** A share difference (0.0042) in percentage points: "+0.4", "-0.6", "0". */
const pp = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : Math.abs(v) < 1e-12 ? "0" : signed(v * 100, d);

function Chapter({ n, id, eyebrow, title, children }: { n: number; id: string; eyebrow: Key; title: Key; children: React.ReactNode }) {
  return (
    <article aria-labelledby={id} className="card flex min-w-0 flex-col gap-3 p-5" data-testid={`chapter-${n}`}>
      <div>
        <div className="eyebrow" style={{ color: ROSE }}>
          <T k="esr.ch" v={{ n: `0${n}` }} /> · <T k={eyebrow} />
        </div>
        <h2 id={id} className="m-0 mt-0.5 text-[17px] font-bold">
          <T k={title} />
        </h2>
      </div>
      {children}
    </article>
  );
}

function Stat({ label, value, sub, testid }: { label: React.ReactNode; value: React.ReactNode; sub?: React.ReactNode; testid?: string }) {
  return (
    <div className="card flex min-w-0 flex-col gap-0.5 p-4" style={{ borderTop: `4px solid ${ROSE}` }}>
      <div className="text-xs font-semibold text-muted">{label}</div>
      <div className="mono text-[22px] font-semibold" data-testid={testid}>
        {value}
      </div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
}

function Suppressed({ i }: { i: Insight }) {
  const { lang } = useLang();
  return (
    <p className="m-0 rounded-xl bg-bg px-3 py-2 text-[13px] text-muted" data-testid="suppressed">
      {suppressedText(i.suppressed_reason!, lang)}
    </p>
  );
}

function Meta({ i }: { i: Insight }) {
  const t = useT();
  const { lang } = useLang();
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
      {i.params.position ? (
        <span className="rounded-full bg-nav-active px-2 py-[1px] font-semibold text-ink">{t(`pos.${i.params.position as string}` as Key)}</span>
      ) : null}
      <span className="font-semibold text-ink" data-testid="n">
        {t("card.n", { n: i.n ?? "—" })}
      </span>
      {i.caveats.includes("small_sample") && <SmallChip />}
      {i.caveats
        .filter((x) => x !== "small_sample")
        .map((x) => (
          <span key={x}>· {caveatText(x, lang)}</span>
        ))}
    </div>
  );
}

export default function EthanolGrindView({
  d,
  insights,
  take,
  release,
}: {
  d: EthanolGrindCommodity;
  insights: InsightsDoc | null;
  take: TakeFile[];
  release: ReleaseInfo;
}) {
  const t = useT();
  const { lang } = useLang();
  const k = d.kpis;
  const h1 = byId(insights, "H1:corn");
  const h2 = byId(insights, "H2:corn");
  const ok = (i: Insight | undefined) => (i && i.suppressed_reason === null ? i : undefined);
  const h1ok = ok(h1);
  const monthLong = monthOf(Number(d.latest.month.slice(5, 7)), "long", lang);
  const dataMonth = monthYear(d.latest.month.slice(0, 7), lang);
  const targetMonth = monthYear(d.target.wasde_release_key, lang);
  const xTicks = [1, 3, 5, 7, 9, 11].map((m) => ({ x: m, label: monthOf(calMonth(m), "short", lang) }));
  const mo = t("unit.perMonth");

  // ---- chapter 1: pace vs USDA
  const cur = d.pace.series.find((s) => s.current);
  const hasPace = d.pace.series.some((s) => s.points.some((p) => p[1] !== null));
  // Cumulative grind is almost linear, so on a 0-100% axis the band, the mean and every year
  // overlap as one diagonal. The chart plots each year's share minus the 5-yr mean at that
  // month (percentage points): the band becomes min-mean ... max-mean around a zero line.
  const meanAt = new Map(d.pace.band.map((b) => [b[0], b[1]] as [number, number | null]));
  const dev = (m: number, v: number | null) => {
    const mu = meanAt.get(m);
    return v === null || mu === null || mu === undefined ? null : v - mu;
  };
  const lines = d.pace.series.map((s) => ({ id: s.market_year, current: s.current, points: s.points.map((p) => [p[0], dev(p[0], p[1])] as [number, number | null]) }));
  const band = d.pace.band.map((b) => ({
    x: b[0],
    mean: b[1] === null ? null : 0,
    min: b[1] === null || b[2] === null ? null : b[2] - b[1],
    max: b[1] === null || b[3] === null ? null : b[3] - b[1],
  }));
  const priorYears = d.pace.series.filter((s) => !s.current).map((s) => s.market_year);
  const paceAria = t("eg.c1.aria", {
    my: d.market_year,
    month: monthLong,
    pct: share(k.pct_of_target),
    min: share(k.pct_5yr_min),
    max: share(k.pct_5yr_max),
  });
  const paceRows = d.pace.band.map((b) => {
    const p = cur?.points.find((x) => x[0] === b[0]);
    return [monthOf(calMonth(b[0]), "short", lang), share(p?.[1]), share(b[1]), share(b[2]), share(b[3]), pp(dev(b[0], p?.[1] ?? null)), b[4]];
  });

  // ---- chapter 2: still needed (H2)
  const req = h2?.suppressed_reason === null ? (h2.params.required_monthly_bu as number) : null;
  const last = h2?.suppressed_reason === null ? (h2.params.last_my_remaining_mean_bu as number) : null;
  const lastMonths = d.remaining.last_my_months;

  // ---- chapter 3: DDGS yield (no formal insight rule; shown as data only)
  const yLines = d.pace.series.map((s) => ({ id: s.market_year, current: s.current, points: s.yield.map((p) => [p[0], p[1]] as [number, number | null]) }));
  const yBand = d.yield.band.map((b) => ({ x: b[0], mean: b[1], min: b[2], max: b[3] }));
  const yieldAria = t("eg.c3.aria", {
    month: monthLong,
    v: stPerKbu(k.ddgs_yield_st_per_kbu),
    min: stPerKbu(k.yield_5yr_min),
    max: stPerKbu(k.yield_5yr_max),
  });
  const yieldRows = d.yield.band.map((b) => {
    const p = d.pace.series.find((s) => s.current)?.yield.find((x) => x[0] === b[0]);
    return [monthOf(calMonth(b[0]), "short", lang), stPerKbu(p?.[1] ?? null), stPerKbu(b[1]), stPerKbu(b[2]), stPerKbu(b[3]), b[4]];
  });

  return (
    <>
      <TopBar
        title={t("eg.title")}
        release={release}
        sub={t("eg.sub", {
          month: dataMonth,
          date: shortDate(d.latest.release_key, true, lang) ?? "",
          next: shortDate(d.next_release, false, lang) ?? "—",
        })}
      />

      <section aria-label={t("eg.k.month", { month: monthLong })} className="flex flex-col gap-3">
        <p className="m-0 max-w-[720px] text-[17px] leading-snug" data-testid="eg-lead">
          {h1ok && h1ok.params.position
            ? t("eg.lead", {
                month: monthLong,
                pct: share(h1ok.params.pct as number),
                my: d.market_year,
                pos: t(`pos.${h1ok.params.position as string}` as Key),
                min: share(h1ok.params.hist_min as number),
                max: share(h1ok.params.hist_max as number),
                n: h1ok.n ?? 0,
              })
            : k.pct_of_target !== null
              ? t("eg.leadPlain", { month: monthLong, pct: share(k.pct_of_target), my: d.market_year })
              : t("eg.leadNoTarget", { month: monthLong, total: bushels(k.cum_bu, lang) })}
        </p>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          {d.target.wasde_release_key && <span>{t("eg.target", { month: targetMonth })}</span>}
          {d.latest.first_printed_as === "previous" && <span>· {t("eg.shutdown")}</span>}
          {h1 && h1.suppressed_reason !== null && <Suppressed i={h1} />}
          {h1ok && (
            <>
              <span className="font-semibold text-ink" data-testid="n">
                {t("card.n", { n: h1ok.n ?? "—" })}
              </span>
              {h1ok.caveats.includes("small_sample") && <SmallChip />}
            </>
          )}
        </div>
        <div className="grid-fit-220">
          <Stat
            label={t("eg.k.month", { month: monthLong })}
            value={bushels(k.month_grind_bu, lang)}
            testid="eg-month"
            sub={t("eg.k.monthSub", { kbu: num(k.month_grind_kbu ?? 0, 0) })}
          />
          <Stat
            label={t("eg.k.mytd", { my: d.market_year })}
            value={bushels(k.cum_bu, lang)}
            testid="eg-mytd"
            sub={
              d.target.ethanol_bu !== null ? (
                <span data-testid="eg-target">{t("eg.k.mytdSub", { target: bushels(d.target.ethanol_bu, lang), month: targetMonth, pct: share(k.pct_of_target) })}</span>
              ) : (
                t("supp.asof_missing")
              )
            }
          />
          <Stat
            label={<T k="eg.k.ddgs" />}
            value={shortTons(k.month_ddgs_st, lang)}
            testid="eg-ddgs"
            sub={t("eg.k.ddgsSub", { v: stPerKbu(k.ddgs_yield_st_per_kbu) })}
          />
          <Stat label={<T k="eg.k.next" />} value={shortDate(d.next_release, true, lang) ?? "—"} sub={<T k="eg.k.nextSub" />} testid="eg-next" />
        </div>
      </section>

      <Chapter n={1} id="h-eg-pace" eyebrow="eg.c1.eb" title="eg.c1">
        {hasPace ? (
          <>
            <PaceChart
              lines={lines}
              band={band}
              xMax={12}
              xTicks={xTicks}
              color={ROSE}
              ariaLabel={paceAria}
              targetLabel=""
              reference={null}
              domain="data"
              yUnit={t("eg.c1.yUnit")}
              format={(v) => pp(v)}
            />
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              <span className="flex items-center gap-1.5">
                <span aria-hidden="true" className="inline-block h-1 w-5 rounded" style={{ background: ROSE }} />
                {t("esr.c1.cur", { my: d.market_year })}
              </span>
              <span className="flex items-center gap-1.5">
                <span aria-hidden="true" className="inline-block h-2.5 w-5 rounded" style={{ background: ROSE, opacity: 0.18 }} />
                {t("esr.c1.band")}
              </span>
              <span className="flex items-center gap-1.5">
                <span aria-hidden="true" className="inline-block w-5 border-t-2 border-dashed" style={{ borderColor: "var(--muted)" }} />
                {t("eg.c1.mean0")}
              </span>
              <span className="flex items-center gap-1.5">
                <span aria-hidden="true" className="inline-block h-0.5 w-5" style={{ background: "var(--bar-past)" }} />
                {t("esr.c1.prior")} ({priorYears.join(", ")})
              </span>
              <span>{t("eg.axis.month")}</span>
            </div>
            <p className="m-0 text-xs text-muted" data-testid="pace-deviation">
              {t("eg.c1.dev")}
            </p>
            <p className="m-0 text-xs text-muted" data-testid="pace-legend">
              <strong className="text-ink">{t("caveat.history_point_in_time")}:</strong> {t("eg.c1.note")}
            </p>
            {h1ok && <Meta i={h1ok} />}
            <ChartTable caption={paceAria} head={[t("eg.h.month"), d.market_year, t("esr.h.mean"), t("esr.h.min"), t("esr.h.max"), t("eg.h.vsMean"), "n"]} rows={paceRows} />
          </>
        ) : (
          <p className="m-0 text-[13px] text-muted">{t("eg.c1.none")}</p>
        )}
      </Chapter>

      <div className="grid-fit-380">
        <Chapter n={2} id="h-eg-needed" eyebrow="eg.c2.eb" title="eg.c2">
          {h2 && h2.suppressed_reason !== null ? (
            <Suppressed i={h2} />
          ) : req !== null && h2 ? (
            req <= 0 ? (
              <p className="m-0">{t("eg.c2.met")}</p>
            ) : (
              <>
                <p className="m-0 text-[15px] leading-snug" data-testid="eg-needed">
                  {t("eg.c2.sentence", {
                    target: bushels(h2.params.target_bu as number, lang),
                    req: bushels(req, lang),
                    months: h2.params.months_remaining as number,
                    ratio: num(h2.params.ratio_required_to_last_my as number, 2),
                    avg: bushels(last, lang),
                    my: d.remaining.market_year,
                  })}
                </p>
                <h3 className="m-0 text-[14px] font-semibold">{t("eg.c2.bars", { my: d.remaining.market_year })}</h3>
                <WeeklyBars
                  items={lastMonths.map((m) => ({ label: monthOf(calMonth(m.month_of_my), "short", lang), value: m.grind_bu }))}
                  reference={req}
                  referenceLabel={t("eg.c2.ref", { v: `${bushels(req, lang)}${mo}` })}
                  color={ROSE}
                  format={(v) => bushelsAxis(v, lang)}
                  ariaLabel={t("eg.c2.aria", {
                    my: d.remaining.market_year,
                    req: bushels(req, lang),
                    list: lastMonths.map((m) => `${monthOf(calMonth(m.month_of_my), "short", lang)}: ${bushels(m.grind_bu, lang)}`).join(", "),
                  })}
                />
                <Meta i={h2} />
              </>
            )
          ) : (
            <p className="m-0 text-[13px] text-muted">{t("supp.asof_missing")}</p>
          )}
        </Chapter>

        <Chapter n={3} id="h-eg-yield" eyebrow="eg.c3.eb" title="eg.c3">
          {k.ddgs_yield_st_per_kbu !== null && (
            <p className="m-0 text-[15px] leading-snug" data-testid="eg-yield-line">
              {t("eg.c3.plain", { month: monthLong, v: stPerKbu(k.ddgs_yield_st_per_kbu) })}
            </p>
          )}
          <PaceChart
            lines={yLines}
            band={yBand}
            xMax={12}
            xTicks={xTicks}
            color={ROSE}
            ariaLabel={yieldAria}
            targetLabel=""
            reference={null}
            domain="data"
            height={220}
            format={(v) => num(v, 2)}
          />
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted" data-testid="yield-legend">
            <span className="flex items-center gap-1.5">
              <span aria-hidden="true" className="inline-block h-1 w-5 rounded" style={{ background: ROSE }} />
              {t("esr.c1.cur", { my: d.market_year })}
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden="true" className="inline-block h-2.5 w-5 rounded" style={{ background: ROSE, opacity: 0.18 }} />
              {t("esr.c1.band")}
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden="true" className="inline-block w-5 border-t-2 border-dashed" style={{ borderColor: "var(--muted)" }} />
              {t("esr.c1.mean")}
            </span>
          </div>
          <p className="m-0 text-xs text-muted">
            {t("eg.c3.note")} {t("eg.c3.axis")}
          </p>
          <ChartTable caption={yieldAria} head={[t("eg.h.month"), d.market_year, t("esr.h.mean"), t("esr.h.min"), t("esr.h.max"), "n"]} rows={yieldRows} />
        </Chapter>
      </div>

      <details className="card group p-5" data-testid="eg-explore">
        <summary className="flex min-h-11 items-center justify-between gap-3 text-[15px] font-semibold">
          <T k="eg.explore" />
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-line text-link group-hover:bg-nav-active">
            <Chevron size={16} />
          </span>
        </summary>
        <div className="flex flex-col gap-2 pt-3">
          <h3 id="h-eg-monthly" className="m-0 text-[14px] font-semibold">
            {t("eg.ex.monthly", { n: d.monthly.length })}
          </h3>
          <div tabIndex={0} role="region" aria-labelledby="h-eg-monthly" className="max-h-96 overflow-auto">
            <table className="data-table">
              <thead>
                <tr>
                  {[t("eg.h.month"), t("wasde.h.my"), t("eg.h.grindKbu"), t("eg.h.grindBu"), t("eg.h.ddg"), t("eg.h.ddgs"), t("eg.h.yield"), t("crush.h.revised")].map((h) => (
                    <th key={h} scope="col">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...d.monthly].reverse().map((m) => (
                  <tr key={m.month}>
                    <th scope="row" className="font-normal">
                      {monthYear(m.month.slice(0, 7), lang)}
                    </th>
                    <td>{m.market_year}</td>
                    <td className="tabular">{num(m.corn_fuel_alcohol_kbu)}</td>
                    <td className="tabular">{bushels(m.corn_fuel_alcohol_bu, lang)}</td>
                    <td className="tabular">{num(m.ddg_st)}</td>
                    <td className="tabular">{num(m.ddgs_st)}</td>
                    <td className="tabular">{stPerKbu(m.ddgs_yield_st_per_kbu)}</td>
                    <td>{m.is_revised ? t("crush.revisedYes") : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="m-0 text-xs text-muted">{t("eg.ex.units")}</p>
        </div>
      </details>

      <section aria-labelledby="h-take" className="card flex flex-col gap-2 p-5" data-testid="eg-take">
        <h2 id="h-take" className="m-0 text-[17px] font-bold">
          <T k="eg.take" />
        </h2>
        <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-1 p-0 text-[13px]">
          {take.map((f) => (
            <li key={f.file}>
              <a href={f.href} className="inline-flex min-h-11 items-center gap-1.5 font-semibold text-link" download={f.href.startsWith("/") ? "" : undefined}>
                {t(`ds.${f.dataset}` as Key)} · {f.format === "csv" ? (f.file.endsWith(".gz") ? "CSV.gz" : "CSV") : "Parquet"}
                <span className="font-normal text-muted">({bytes(f.bytes)})</span>
              </a>
            </li>
          ))}
        </ul>
        <p className="m-0 text-xs text-muted" data-testid="eg-window">
          {t("eg.window", { from: monthYear(d.history_start, lang) })}
        </p>
        <div className="flex flex-wrap gap-x-5 text-[13px]">
          <Link href="/data/#report-ethanol_grind" className="inline-flex min-h-11 items-center text-link">
            <T k="esr.take.all" />
          </Link>
          <Link href="/methodology/#ethanol-grind" className="inline-flex min-h-11 items-center text-link">
            <T k="esr.take.method" />
          </Link>
        </div>
      </section>
    </>
  );
}
