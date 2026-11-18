export default function Kbd({ children }: { children: string }) {
  return (
    <kbd className="mx-0.5 rounded border border-line bg-surface-2 px-1 py-px font-sans text-[10px] text-muted">
      {children}
    </kbd>
  );
}
