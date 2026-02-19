import { useEffect, useRef } from 'react';
import { AreaSeries, ColorType, LineSeries, createChart } from 'lightweight-charts';
import type { BusinessDay, UTCTimestamp } from 'lightweight-charts';

export interface PriceLineSeries {
  id: string;
  points: Array<{
    time: BusinessDay | UTCTimestamp;
    value: number;
  }>;
  color: string;
}

export function TradingPriceChart({
  series,
  normalized = false,
  liveWindowSeconds,
}: {
  series: PriceLineSeries[];
  normalized?: boolean;
  liveWindowSeconds?: number;
}) {
  const chartRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!chartRef.current || series.length === 0) return;

    const container = chartRef.current;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 320,
      layout: {
        background: { type: ColorType.Solid, color: '#0b1220' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1f2937' },
        horzLines: { color: '#1f2937' },
      },
      rightPriceScale: {
        borderColor: '#334155',
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
        secondsVisible: true,
        minBarSpacing: 0.5,
      },
      crosshair: {
        vertLine: { color: '#38bdf8' },
        horzLine: { color: '#38bdf8' },
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: true,
        axisDoubleClickReset: false,
      },
    });

    const useSingleArea = !normalized && series.length === 1;
    for (const line of series) {
      if (line.points.length < 2) continue;
      const base = line.points[0].value;
      if (normalized && base <= 0) continue;
      const data = line.points.map((entry) => ({
        time: entry.time,
        value: normalized ? ((entry.value - base) / base) * 100 : entry.value,
      }));
      if (useSingleArea) {
        const areaSeries = chart.addSeries(AreaSeries, {
          lineColor: line.color,
          topColor: 'rgba(34, 211, 238, 0.22)',
          bottomColor: 'rgba(34, 211, 238, 0.02)',
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: true,
          priceScaleId: 'right',
        });
        areaSeries.setData(data);
      } else {
        const lineSeries = chart.addSeries(LineSeries, {
          color: line.color,
          lineWidth: line.id === 'primary' ? 3 : 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          priceScaleId: 'right',
        });
        lineSeries.setData(data);
      }
    }
    if (liveWindowSeconds) {
      const primary = series[0];
      const numericTimes = primary?.points
        .map((p) => (typeof p.time === 'number' ? p.time : null))
        .filter((p): p is UTCTimestamp => p !== null) ?? [];
      const latest = numericTimes.length > 0 ? numericTimes[numericTimes.length - 1] : null;
      if (latest !== null) {
        chart.timeScale().setVisibleRange({
          from: (latest - liveWindowSeconds) as UTCTimestamp,
          to: latest,
        });
      } else {
        chart.timeScale().fitContent();
      }
    } else {
      chart.timeScale().fitContent();
    }

    const resizeChart = () => {
      chart.applyOptions({ width: container.clientWidth });
    };

    const observer = new ResizeObserver(resizeChart);
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [liveWindowSeconds, normalized, series]);

  return <div className="tv-chart" ref={chartRef} aria-label="Grafico estilo TradingView" />;
}
