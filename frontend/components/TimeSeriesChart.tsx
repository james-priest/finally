"use client";

import { useEffect, useRef } from "react";
import {
  AreaSeries,
  ColorType,
  createChart,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { PricePoint } from "@/lib/usePriceStream";

const INK_3 = "#6b7888";
const GRID = "#1c2530";
const LINE = "#242f3d";

/** Single-series area chart over Unix-second points. */
export function TimeSeriesChart({ points, color }: { points: PricePoint[]; color: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);

  useEffect(() => {
    const chart = createChart(containerRef.current!, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: INK_3,
        fontFamily: "IBM Plex Sans Condensed, system-ui, sans-serif",
        fontSize: 11,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: GRID },
      },
      rightPriceScale: { borderColor: LINE },
      timeScale: { borderColor: LINE, timeVisible: true, secondsVisible: true },
      crosshair: {
        vertLine: { color: INK_3, style: LineStyle.Solid, labelBackgroundColor: LINE },
        horzLine: { color: INK_3, style: LineStyle.Solid, labelBackgroundColor: LINE },
      },
    });
    chartRef.current = chart;
    seriesRef.current = chart.addSeries(AreaSeries, {
      lineColor: color,
      lineWidth: 2,
      topColor: `${color}33`,
      bottomColor: `${color}00`,
      priceLineVisible: false,
    });
    return () => {
      chartRef.current = null;
      seriesRef.current = null;
      chart.remove();
    };
  }, [color]);

  useEffect(() => {
    seriesRef.current?.setData(
      points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })),
    );
    chartRef.current?.timeScale().fitContent();
  }, [points, color]);

  return <div ref={containerRef} className="absolute inset-0" />;
}
