const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const usdSmall = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
});
const qty = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

/** `$10,000.00`; prices below $1 keep 4 decimals. */
export function money(value: number): string {
  return Math.abs(value) > 0 && Math.abs(value) < 1 ? usdSmall.format(value) : usd.format(value);
}

/** `+$5.00` / `-$5.00`. */
export function signedMoney(value: number): string {
  return `${value < 0 ? "-" : "+"}${usd.format(Math.abs(value))}`;
}

/** `+0.26%` from a percentage value (0.26 means 0.26%). */
export function signedPercent(value: number): string {
  return `${value < 0 ? "-" : "+"}${Math.abs(value).toFixed(2)}%`;
}

export function quantity(value: number): string {
  return qty.format(value);
}

/** Tailwind text color class for a signed value. */
export function trendClass(value: number): string {
  if (value > 0) return "text-up";
  if (value < 0) return "text-down";
  return "text-ink-2";
}
