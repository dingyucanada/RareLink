import { useQuery } from "@tanstack/react-query";
import { Activity, KeyRound, Repeat2, ShieldCheck } from "lucide-react";
import { api } from "../api";

export default function SystemEvidence() {
  const evidence = useQuery({
    queryKey: ["system-evidence"],
    queryFn: api.systemEvidence,
    refetchInterval: (query) => query.state.data?.repeated_benchmark ? false : 5000,
  });
  const repeated = evidence.data?.repeated_benchmark;
  const runtime = evidence.data?.mtls_runtime;
  const privacy = evidence.data?.privacy_comparison;
  const sampleDp = privacy?.mechanism === "opacus_sample_level_dp_sgd";
  const ranked = repeated
    ? Object.entries(repeated.worst_site_win_rate).sort((left, right) => right[1] - left[1])
    : [];
  return (
    <section className="panel system-evidence-panel">
      <div className="panel-title"><div><ShieldCheck size={18} /><span><strong>可验证工程证据</strong><small>重复性 · 安全通信 · 隐私—效用边界</small></span></div><span className="evidence-scope">SYNTHETIC · SPARK VERIFIED</span></div>
      <div className="evidence-kpis">
        <article><Repeat2 size={18} /><div><small>REPEATED BENCHMARK</small><strong>{repeated ? `${repeated.seeds.length} seeds · ${repeated.trial_count} trials` : "RUNNING"}</strong><p>{ranked.length ? `最弱站点胜率领先：${ranked[0][0].toUpperCase()} ${(ranked[0][1] * 100).toFixed(0)}%` : "Spark 正在生成稳定性证据"}</p></div></article>
        <article><KeyRound size={18} /><div><small>FLARE SECURE MODE</small><strong>{runtime ? `${runtime.registered_client_count}/3 clients · mTLS` : "PROVISIONED"}</strong><p>{runtime ? "独立证书身份已注册；运行令牌未导出" : "等待运行态注册证据"}</p></div></article>
        <article><Activity size={18} /><div><small>PRIVACY–UTILITY</small><strong>{privacy ? (sampleDp ? `DP-SGD ε=${privacy.epsilon?.toFixed(3)} · δ=${privacy.delta}` : `SVT ε=${privacy.epsilon_parameter_per_call}`) : "PENDING"}</strong><p>{privacy ? (sampleDp ? `${privacy.rounds_accounted} 轮累计 RDP 会计 · clip ${privacy.max_grad_norm} · noise ${privacy.noise_multiplier}` : `仅共享 ${((privacy.fraction_shared ?? 0) * 100).toFixed(1)}% 更新 · 非样本级会计`) : "等待隐私策略对照完成"}</p></div></article>
      </div>
      {repeated && <div className="stability-grid">{ranked.map(([strategy, winRate]) => {
        const item = repeated.strategy_summaries[strategy];
        return <div key={strategy}><span>{strategy.toUpperCase()}</span><strong>{item.metrics.worst_site_dice.mean.toFixed(4)}</strong><small>最弱站点均值 · 胜率 {(winRate * 100).toFixed(0)}%</small><i><b style={{ width: `${winRate * 100}%` }} /></i></div>;
      })}</div>}
    </section>
  );
}
