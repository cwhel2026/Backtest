/** Human-readable dataset labels — never show raw UUIDs in UI. */

export type DatasetRow = {
  id: string;
  instrument_id: string;
  provider_id: string;
  timeframe: string;
  coverage_start?: string | null;
  coverage_end?: string | null;
  genuine_for_research?: boolean | null;
  data_lineage_label?: string | null;
  quality_class?: string | null;
  row_count?: number;
  meta?: { label?: string; data_lineage?: string };
};

export function formatDatasetLabel(d: DatasetRow, instrumentSymbol?: string): string {
  if (d.meta?.label) return d.meta.label;
  const sym = instrumentSymbol ?? "Market";
  const provider = d.data_lineage_label ?? d.meta?.data_lineage ?? d.provider_id;
  const start = d.coverage_start?.slice(0, 10);
  const end = d.coverage_end?.slice(0, 10);
  const range = start && end ? `${start} → ${end}` : "coverage TBD";
  const rows = d.row_count != null ? `${d.row_count.toLocaleString()} bars` : "";
  return `${sym} ${d.timeframe} · ${provider} · ${range}${rows ? ` · ${rows}` : ""}`;
}

export function datasetQualityHint(d: DatasetRow): string {
  if (d.genuine_for_research) return "Licensed / genuine for research";
  if (d.quality_class) return `Quality: ${d.quality_class}`;
  return "Not marked genuine — backtest may be restricted";
}