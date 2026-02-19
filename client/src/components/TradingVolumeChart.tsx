import { useEffect, useRef } from 'react';
import { ColorType, HistogramSeries, createChart } from 'lightweight-charts';
import type { PriceHistory } from '../types';

export function TradingVolumeChart({ history }: { history: PriceHistory[] }) {
  const chartRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!chartRef.current || history.length < 2) return;

    const container = chartRef.current;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 160,
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
      },
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceLineVisible: false,
      lastValueVisible: false,
      priceScaleId: 'right',
    });

    const data = history.map((entry, index) => {
      const [year, month, day] = entry.date.split('-').map(Number);
      const prev = index > 0 ? history[index - 1].price_usd : entry.price_usd;
      const isUp = entry.price_usd >= prev;
      return {
        time: { year, month, day },
        value: entry.total_volume_usd,
        color: isUp ? 'rgba(34,197,94,0.65)' : 'rgba(239,68,68,0.65)',
      };
    });

    volumeSeries.setData(data);
    chart.timeScale().fitContent();

    const resizeChart = () => {
      chart.applyOptions({ width: container.clientWidth });
    };

    const observer = new ResizeObserver(resizeChart);
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [history]);

  return <div className="tv-volume-chart" ref={chartRef} aria-label="Gráfico de volume" />;
}
