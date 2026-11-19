/** Wrap wide tables for horizontal scroll on small screens. */
export function ScrollTable({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`-mx-4 overflow-x-auto px-4 md:mx-0 md:px-0 ${className}`.trim()}>
      <div className="min-w-[640px]">{children}</div>
    </div>
  );
}