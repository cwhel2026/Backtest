export type NavItem = {
  href: string;
  label: string;
  short: string;
  icon?: string;
};

export const MOBILE_PRIMARY: NavItem[] = [
  { href: "/", label: "Home", short: "Home", icon: "⌂" },
  { href: "/live-lab", label: "Live Strategy Lab", short: "Live", icon: "◎" },
  { href: "/strategies", label: "Strategies", short: "Lab", icon: "◈" },
  { href: "/backtests", label: "Backtests", short: "Tests", icon: "▣" },
  { href: "/research", label: "AI Research", short: "AI", icon: "✦" },
  { href: "/more", label: "More", short: "More", icon: "⋯" },
];

export const MORE_LINKS: NavItem[] = [
  { href: "/market-data/import", label: "Import historical data", short: "Import" },
  { href: "/market-data/setup", label: "Buy via API estimate", short: "Estimate" },
  { href: "/market-data", label: "Market Data", short: "Data" },
  { href: "/leaderboard", label: "Leaderboard", short: "Rank" },
  { href: "/strategy-debugger", label: "Strategy Debugger", short: "Debug" },
  { href: "/strategy-compare", label: "Compare strategies", short: "Compare" },
  { href: "/berg-tnb", label: "Berg TNB", short: "TNB" },
  { href: "/desk", label: "Prop desk search", short: "Desk" },
  { href: "/paper", label: "Forward test", short: "Paper" },
  { href: "/settings", label: "Settings", short: "Settings" },
  { href: "/market-data/health", label: "System health", short: "Health" },
];

function dedupeNavByHref(items: NavItem[]): NavItem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.href)) return false;
    seen.add(item.href);
    return true;
  });
}

export const DESKTOP_NAV: NavItem[] = dedupeNavByHref([
  ...MOBILE_PRIMARY.filter((i) => i.href !== "/more"),
  ...MORE_LINKS,
]);

export function isNavActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  if (href === "/more") return pathname === "/more";
  return pathname === href || pathname.startsWith(`${href}/`);
}