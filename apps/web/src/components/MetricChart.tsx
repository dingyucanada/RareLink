import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Experiment } from "../types";

export default function MetricChart({ experiments }: { experiments: Experiment[] }) {
  const data = experiments
    .filter((item) => item.metrics)
    .map((item) => ({
      strategy: item.strategy.toUpperCase(),
      "平均 Dice": item.metrics!.mean_dice,
      "最差站点 Dice": item.metrics!.worst_site_dice,
    }));
  if (!data.length) {
    return <div className="placeholder">完成实验后显示公平预算下的策略比较。</div>;
  }
  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} margin={{ top: 10, right: 4, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#dfe7e2" vertical={false} />
          <XAxis dataKey="strategy" tickLine={false} axisLine={false} />
          <YAxis domain={[0.4, 0.8]} tickLine={false} axisLine={false} />
          <Tooltip cursor={{ fill: "#f1f5f2" }} />
          <Legend />
          <Bar dataKey="平均 Dice" fill="#15805f" radius={[5, 5, 0, 0]} />
          <Bar dataKey="最差站点 Dice" fill="#d9a441" radius={[5, 5, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

