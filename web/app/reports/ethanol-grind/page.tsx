import type { Metadata } from "next";

import { T } from "@/components/chrome/I18n";
import TopBar from "@/components/chrome/TopBar";
import EthanolGrindView, { type TakeFile } from "@/components/ethanol-grind/EthanolGrindView";
import { releaseInfo } from "@/lib/dashboard";
import { getEthanolGrind, getInsights, getReleaseCatalog, servedPath } from "@/lib/data";

export const metadata: Metadata = { title: "Ethanol Grind (NASS) · USDA Reports Dashboard" };

const EG_DATASETS = new Set(["ethanol_grind:monthly_grind", "cross:ethanol_pace"]);

/** Ethanol Grind files of the release catalogue: the site copy when served, else the release asset. */
function takeFiles(): TakeFile[] {
  const cat = getReleaseCatalog();
  if (!cat) return [];
  return cat.files
    .filter((f) => EG_DATASETS.has(`${f.report_id}:${f.dataset}`) && !f.legacy_alias_of)
    .map((f) => ({ f, href: servedPath(f.site_url) ?? f.release_url }))
    .filter((x): x is { f: (typeof cat.files)[number]; href: string } => Boolean(x.href))
    .map(({ f, href }) => ({ file: f.file, dataset: f.dataset, format: f.format, href, bytes: f.bytes, rows: f.rows }));
}

export default function EthanolGrindPage() {
  const d = getEthanolGrind();
  if (!d) {
    return (
      <>
        <TopBar title={<T k="eg.title" />} release={releaseInfo()} />
        <p className="m-0 text-muted">
          <T k="eg.none" />
        </p>
      </>
    );
  }
  return <EthanolGrindView d={d} insights={getInsights()} take={takeFiles()} release={releaseInfo()} />;
}
