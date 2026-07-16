import { useQuery } from "@tanstack/react-query";
import { Activity, Database, FileSearch, KeyRound, Repeat2, ShieldAlert, ShieldCheck } from "lucide-react";
import { api } from "../api";

export default function SystemEvidence() {
  const evidence = useQuery({
    queryKey: ["system-evidence"],
    queryFn: api.systemEvidence,
    refetchInterval: (query) => query.state.data?.repeated_benchmark ? false : 5000,
  });
  const repeated = evidence.data?.repeated_benchmark;
  const runtime = evidence.data?.mtls_runtime;
  const crossDevice = evidence.data?.cross_device_mtls;
  const privacy = evidence.data?.privacy_comparison;
  const redteam = evidence.data?.agent_redteam;
  const publicBenchmark = evidence.data?.public_benchmark;
  const publicMriVerified = Boolean(
    publicBenchmark?.public_mri_intake_verified ?? publicBenchmark?.public_benchmark_verified,
  );
  const sampleDp = privacy?.mechanism === "opacus_sample_level_dp_sgd";
  const ranked = repeated
    ? Object.entries(repeated.worst_site_win_rate).sort((left, right) => right[1] - left[1])
    : [];
  return (
    <section className="panel system-evidence-panel">
      <div className="panel-title"><div><ShieldCheck size={18} /><span><strong>评审证据驾驶舱</strong><small>先看结论，再核对来源、结果与边界</small></span></div><span className="evidence-scope">RESEARCH ONLY · SPARK VERIFIED</span></div>
      <div className="evidence-reading-path" aria-label="评审阅读路径">
        <strong>结论：RareLink 已在 DGX Spark 上形成“本地训练—受控聚合—可审计证据”的工程闭环。</strong>
        <span>本页展示的是合成训练稳定性、安全通信、样本级 DP 会计与 Agent 防护；不展示或传输患者影像。</span>
      </div>
      <div className="evidence-kpis">
        <article><Repeat2 size={18} /><div><small>REPEATED BENCHMARK</small><strong>{repeated ? `${repeated.seeds.length} seeds · ${repeated.trial_count} trials` : "RUNNING"}</strong><p>{ranked.length ? `最弱站点胜率领先：${ranked[0][0].toUpperCase()} ${(ranked[0][1] * 100).toFixed(0)}%` : "Spark 正在生成稳定性证据"}</p></div></article>
        <article><KeyRound size={18} /><div><small>FLARE SECURE MODE</small><strong>{crossDevice ? "2 devices · mTLS" : runtime ? `${runtime.registered_client_count}/3 clients · mTLS` : "PROVISIONED"}</strong><p>{crossDevice ? `掉线重连成功 · 错误身份已拒绝（${crossDevice.negative_control.reason_category}）` : runtime ? "独立证书身份已注册；运行令牌未导出" : "等待运行态注册证据"}</p></div></article>
        <article><Activity size={18} /><div><small>PRIVACY–UTILITY</small><strong>{privacy ? (sampleDp ? `DP-SGD ε=${privacy.epsilon?.toFixed(3)} · δ=${privacy.delta}` : `SVT ε=${privacy.epsilon_parameter_per_call}`) : "PENDING"}</strong><p>{privacy ? (sampleDp ? `${privacy.rounds_accounted} 轮累计 RDP 会计 · clip ${privacy.max_grad_norm} · noise ${privacy.noise_multiplier}` : `仅共享 ${((privacy.fraction_shared ?? 0) * 100).toFixed(1)}% 更新 · 非样本级会计`) : "等待隐私策略对照完成"}</p></div></article>
        <article><ShieldAlert size={18} /><div><small>AGENT RED TEAM</small><strong>{redteam ? `${redteam.passed_count}/${redteam.case_count} passed` : "PENDING"}</strong><p>{redteam ? "LLM 前置脱敏 · 输出临床越权门禁" : "等待固定攻击集评测"}</p></div></article>
      </div>
      <div className="evidence-detail-grid">
        <article className={`public-benchmark-status ${publicBenchmark ? "verified" : "pending"}`}>
          <FileSearch size={18} />
          <div><small>PUBLIC NIFTI INTAKE</small><strong>{publicBenchmark ? `${publicBenchmark.case_count} cases · ${publicBenchmark.site_count} sites` : "MSD Task01 pending"}</strong><p>{publicBenchmark ? `${publicBenchmark.source.name} · ${publicBenchmark.modalities.join(" / ")}` : "公开脑肿瘤数据仅允许由 Spark 直接下载；不会通过 SSH 传输。"}</p></div>
          <span>{publicMriVerified ? "VERIFIED" : "NOT CLAIMED"}</span>
        </article>
        <article className="evidence-boundary">
          <Database size={18} />
          <div><small>SOURCE & BOUNDARY</small><strong>可复现实验，不替代临床验证</strong><p>{publicBenchmark?.claim_boundary ?? "当前稳定性结果来自三逻辑站点的合成数据；公开基准完成后将单独标注其数据来源与工程边界。"}</p></div>
        </article>
      </div>
      {repeated && <div className="stability-grid" aria-label="五种子最弱站点 Dice 对比">{ranked.map(([strategy, winRate], index) => {
        const item = repeated.strategy_summaries[strategy];
        return <div key={strategy} className={index === 0 ? "leading-strategy" : ""}><span>{index === 0 ? "CURRENT ENGINEERING CANDIDATE" : strategy.toUpperCase()}</span><strong>{strategy.toUpperCase()} · {item.metrics.worst_site_dice.mean.toFixed(4)}</strong><small>最弱站点 Dice 均值 · 胜率 {(winRate * 100).toFixed(0)}%</small><i aria-hidden="true"><b style={{ width: `${winRate * 100}%` }} /></i></div>;
      })}</div>}
    </section>
  );
}
