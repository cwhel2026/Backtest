export type NavItem = {
  href: string;
  label: string;
  short: string;
  icon?: string;
  description?: string;
};

/** Primary product navigation (8 sections). */
export const PRIMARY_NAV: NavItem[] = [
  { href: "/", label: "Dashboard", short: "Home", icon: "⌂", description: "Command centre" },
  { href: "/scanner", label: "Market Scanner", short: "Scan", icon: "◎", description: "Setups & feed status" },
  { href: "/strategy-lab", label: "Strategy Lab", short: "Lab", icon: "◈", description: "Strategies & rules" },
  { href: "/backtests", label: "Backtesting", short: "Tests", icon: "▣", description: "Historical simulation" },
  { href: "/paper-trading", label: "Paper Trading", short: "Paper", icon: "◇", description: "Forward simulation" },
  { href: "/analytics", label: "Analytics", short: "Stats", icon: "▤", description: "Performance & compare" },
  { href: "/research", label: "AI Research", short: "AI", icon: "✦", description: "Research automation" },
  { href: "/settings", label: "Settings", short: "Set", icon: "⚙", description: "Data, risk & health" },
];

/** Mobile bottom bar — five slots; full nav via Menu. */
export const MOBILE_TAB_NAV: NavItem[] = [
  PRIMARY_NAV[0],
  PRIMARY_NAV[1],
  PRIMARY_NAV[2],
  PRIMARY_NAV[3],
  { href: "/menu", label: "Menu", short: "Menu", icon: "⋯" },
];

export const MENU_NAV: NavItem[] = [
  PRIMARY_NAV[4],
  PRIMARY_NAV[5],
  PRIMARY_NAV[6],
  PRIMARY_NAV[7],
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