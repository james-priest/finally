export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Binary-split treemap: divide items into two halves of near-equal weight,
 * split the rect along its longer side, and recurse. Rects are in the units of `rect`.
 */
export function treemap<T>(
  items: { value: number; item: T }[],
  rect: Rect,
): (Rect & { item: T })[] {
  const sorted = [...items].filter((i) => i.value > 0).sort((a, b) => b.value - a.value);
  return split(sorted, rect);
}

function split<T>(items: { value: number; item: T }[], rect: Rect): (Rect & { item: T })[] {
  if (items.length === 0) return [];
  if (items.length === 1) return [{ ...rect, item: items[0].item }];

  const total = items.reduce((s, i) => s + i.value, 0);
  let acc = 0;
  let cut = 0;
  while (cut < items.length - 1 && acc + items[cut].value <= total / 2) acc += items[cut++].value;
  if (cut === 0) acc = items[cut++].value;

  const ratio = acc / total;
  const [a, b] =
    rect.w >= rect.h
      ? [
          { ...rect, w: rect.w * ratio },
          { ...rect, x: rect.x + rect.w * ratio, w: rect.w * (1 - ratio) },
        ]
      : [
          { ...rect, h: rect.h * ratio },
          { ...rect, y: rect.y + rect.h * ratio, h: rect.h * (1 - ratio) },
        ];
  return [...split(items.slice(0, cut), a), ...split(items.slice(cut), b)];
}
