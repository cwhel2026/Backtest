export type NavItem = {
  href: string;
  label: string;
  short: string;
  icon?: string;
  description?: string;
};

/** Primary product navigation — operator-first (6 sections). */
export const PRIMARY_NAV: NavItem[] = [
  { href: "/", label: "Home", short: "Home", icon: "⌂", description: "Markets, setups & paper P&L" },
  { href: "/scanner", label: "Scanner", short: "Scan", icon: "◎", description: "Detected setups" },
  { href: "/strategy-lab", label: "Strategies", short: "Strat", icon: "◈", description: "Strategy library" },
  { href: "/backtests", label: "Backtests", short: "Tests", icon: "▣", description: "Historical tests" },
  { href: "/research", label: "AI Research", short: "AI", icon: "✦", description: "Experiments & rankings" },
  { href: "/settings", label: "Settings", short: "Set", icon: "⚙", description: "Data & health" },
];

/** Mobile bottom bar */
export const MOBILE_TAB_NAV: NavItem[] = [
  PRIMARY_NAV[0],
  PRIMARY_NAV[1],
  PRIMARY_NAV[2],
  PRIMARY_NAV[3],
  { href: "/menu", label: "More", short: "More", icon: "⋯" },
];

export const MENU_NAV: NavItem[] = [
  { href: "/ai-arena", label: "AI Research Arena", short: "Arena", icon: "⚔", description: "Multi-provider AI researchers" },
  { href: "/paper-trading", label: "Paper Trading", short: "Paper", icon: "◇", description: "Simulated forward runs" },
  { href: "/analytics", label: "Analytics", short: "Stats", icon: "▤", description: "Performance compare" },
  PRIMARY_NAV[4],
  PRIMARY_NAV[5],
];

export const ADVANCED_NAV: NavItem[] = [
  { href: "/strategy-debugger", label: "Strategy debugger", short: "Debug" },
  { href: "/berg-tnb", label: "Berg TNB explorer", short: "TNB" },
  { href: "/desk", label: "Prop desk search", short: "Desk" },
  { href: "/market-data", label: "Historical data admin", short: "Data" },
  { href: "/paper-trading/certification", label: "Accuracy certification", short: "Cert" },
  { href: "/prop-firms", label: "Prop firms reference", short: "Firms" },
];

export const DESKTOP_NAV: NavItem[] = [...PRIMARY_NAV];

export const SCAN_SYMBOLS = ["MNQ", "MES", "MGC"] as const;

export function isNavActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  if (href === "/menu") return pathname === "/menu";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function latencyLabel(mode: string | null | undefined): string {
  if (!mode) return "Unknown";
  if (mode === "licensed_realtime" || mode === "live") return "Live (licensed)";
  if (mode === "delayed") return "Delayed";
  if (mode === "historical_replay" || mode === "replay") return "Replay";
  if (mode === "synthetic") return "Synthetic";
  return mode.replace(/_/g, " ");
}