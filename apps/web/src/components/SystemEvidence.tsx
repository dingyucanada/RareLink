import { useQuery } from "@tanstack/react-query";
import { Activity, Bot, Database, FileSearch, KeyRound, Repeat2, Server, ShieldAlert, ShieldCheck } from "lucide-react";
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
  const localInference = evidence.data?.local_inference;
  const localInferenceRedteam = evidence.data?.local_inference_redteam;
  const localInferenceVerification = evidence.data?.local_inference_verification;
  const localInferenceBenchmark = evidence.data?.local_inference_benchmark;
  const stepInference = evidence.data?.step_inference;
  const localGpu = localInference?.gpu_snapshot_after.gpus[0];
  const localInferenceVerified = localInferenceVerification?.passed === true;
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
        <article className={`local-inference-evidence ${localInferenceVerified ? "verified" : "pending"}`}>
          <Server size={18} />
          <div><small>SPARK LOCAL LLM</small><strong>{localInference ? `${localInference.model.split("/").at(-1)} · ${localInference.latency_ms} ms` : "本地推理证据待采集"}</strong><p>{localInference ? `本地端点 · Step API 调用：${localInference.remote_step_api_called ? "是" : "否"} · 原始患者数据传输：${localInference.raw_patient_data_transmitted ? "是" : "否"}` : "启动 TensorRT-LLM 后，由 Agent 调用自动记录模型、延迟、用量与输出哈希，不存储提示词正文。"}</p>{localGpu && <p>GPU：{localGpu.name} · 显存 {localGpu.memory_used_mib}/{localGpu.memory_total_mib} MiB · 利用率 {localGpu.gpu_utilization_percent}%</p>}{localInferenceRedteam && <p>本地网关红队：{localInferenceRedteam.passed_count}/{localInferenceRedteam.case_count} · 实测本地请求 {localInferenceRedteam.local_model_request_count} 次</p>}{localInferenceBenchmark?.peak_safe_throughput && <p>固定安全负载峰值：并发 {localInferenceBenchmark.peak_safe_throughput.concurrency} · {localInferenceBenchmark.peak_safe_throughput.accepted_requests_per_second.toFixed(2)} 请求/秒</p>}</div>
          <span>{localInferenceVerified ? "VERIFIED" : localInferenceRedteam?.all_passed ? "RED TEAM PASS" : localInference ? "CAPTURED" : "NOT CLAIMED"}</span>
        </article>
        <article className={`local-inference-evidence ${stepInference ? "verified" : "pending"}`}>
          <Bot size={18} />
          <div><small>STEP 3.7 AGENT RUNTIME</small><strong>{stepInference ? `${stepInference.model} · ${stepInference.latency_ms} ms` : "实时回执待采集"}</strong><p>{stepInference ? `角色：${stepInference.role} · 结构校验与输出安全门：${stepInference.output_safety_gate_passed ? "通过" : "未通过"}` : "仅在真实受控 Agent 请求成功后显示；已配置密钥不等同模型已经运行。"}</p><p>{stepInference ? `Step API：${stepInference.remote_step_api_called ? "已调用" : "否"} · 原始患者数据：${stepInference.raw_patient_data_transmitted ? "传输" : "未传输"} · 提示词/回答正文：不落盘` : "固定合成研究问题；不含影像、标识符或病例级统计。"}</p></div>
          <span>{stepInference ? "VERIFIED" : "NOT CLAIMED"}</span>
        </article>
      </div>
      {repeated && <div className="stability-grid" aria-label="五种子最弱站点 Dice 对比">{ranked.map(([strategy, winRate], index) => {
        const item = repeated.strategy_summaries[strategy];
        return <div key={strategy} className={index === 0 ? "leading-strategy" : ""}><span>{index === 0 ? "CURRENT ENGINEERING CANDIDATE" : strategy.toUpperCase()}</span><strong>{strategy.toUpperCase()} · {item.metrics.worst_site_dice.mean.toFixed(4)}</strong><small>最弱站点 Dice 均值 · 胜率 {(winRate * 100).toFixed(0)}%</small><i aria-hidden="true"><b style={{ width: `${winRate * 100}%` }} /></i></div>;
      })}</div>}
    </section>
  );
}
