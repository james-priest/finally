"use client";

import { useState } from "react";
import { money } from "@/lib/format";

interface Flash {
  dir: "up" | "down" | null;
  n: number;
}

/** A price that flashes green or red when it differs from the last rendered price. */
export function PriceCell({ price, testId }: { price: number; testId?: string }) {
  const [rendered, setRendered] = useState(price);
  const [flash, setFlash] = useState<Flash>({ dir: null, n: 0 });

  if (price !== rendered) {
    setRendered(price);
    setFlash({ dir: price > rendered ? "up" : "down", n: flash.n + 1 });
  }

  return (
    <span
      // A new key restarts the CSS animation on every change.
      key={flash.n}
      data-testid={testId}
      data-flash={flash.dir ?? undefined}
      className={`rounded-sm px-1 ${flash.dir ? `flash-${flash.dir}` : ""}`}
    >
      {money(price)}
    </span>
  );
}
