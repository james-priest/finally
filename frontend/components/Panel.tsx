import type { ReactNode } from "react";

interface PanelProps {
  title: ReactNode;
  aside?: ReactNode;
  className?: string;
  testId?: string;
  children: ReactNode;
}

export function Panel({ title, aside, className = "", testId, children }: PanelProps) {
  return (
    <section
      data-testid={testId}
      className={`flex min-h-0 min-w-0 flex-col bg-panel ${className}`}
    >
      <header className="flex h-8 shrink-0 items-center justify-between gap-3 border-b border-line px-3">
        <h2 className="text-[13px] font-medium text-ink-2">{title}</h2>
        {aside}
      </header>
      <div className="relative min-h-0 flex-1">{children}</div>
    </section>
  );
}
