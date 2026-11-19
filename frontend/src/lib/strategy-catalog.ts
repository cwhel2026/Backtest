/** Curated strategy cards for Strategy Lab (templates + library entries). */

export type FeaturedStrategy = {
  key: string;
  name: string;
  summary: string;
  markets: string[];
  timeframes: string[];
  entryType?: string;
  href: string;
  badge?: string;
};

export const FEATURED_STRATEGIES: FeaturedStrategy[] = [
  {
    key: "berg_tnb",
    name: "Berg TNB Model",
    summary: "PDF-driven session sweep, 4H bias, fakeout, and Fibonacci entry on CME micro futures.",
    markets: ["MNQ", "MES", "MGC"],
    timeframes: ["5m", "4h bias"],
    entryType: "berg_tnb_model_v1",
    href: "/berg-tnb",
    badge: "Research",
  },
  {
    key: "liquidity_sweep",
    name: "Liquidity Sweep Reversal",
    summary: "Prior session high/low sweep with optional BOS and fib limit entry.",
    markets: ["MNQ", "MES", "MGC"],
    timeframes: ["5m"],
    entryType: "video_liquidity_sweep",
    href: "/strategies",
    badge: "Video",
  },
  {
    key: "anchor_bos",
    name: "Anchor BOS Fibonacci",
    summary: "Confirmed pivot break with anchor fib retracement limit orders.",
    markets: ["MNQ", "MES", "MGC"],
    timeframes: ["5m"],
    entryType: "video_anchor_bos",
    href: "/strategies",
    badge: "Video",
  },
];

export function lifecycleLabel(lc: string): string {
  const map: Record<string, string> = {
    draft: "Draft",
    backtesting: "Backtesting",
    historically_validated: "Validated",
    paper_trading: "Paper",
    rejected: "Rejected",
    eligible_for_approval: "Keeper",
  };
  return map[lc] || lc.replace(/_/g, " ");
}