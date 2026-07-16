import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  BookOpenCheck,
  BrainCircuit,
  Check,
  CircleAlert,
  Database,
  Eye,
  FileCheck2,
  FileSearch,
  FlaskConical,
  Gauge,
  LockKeyhole,
  Network,
  Play,
  RefreshCcw,
  Server,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { AgentArtifact, EvidenceBrief, Experiment, Study, StudyStatus, TrainingJob } from "./types";
import { stages, statusIndex } from "./workflow";

const MetricChart = lazy(() => import("./components/MetricChart"));
const MarkdownReport = lazy(() => import("./components/MarkdownReport"));

function EmptyState({ create }: { create: () => void }) {
  return (
    <main className="empty-shell">
      <div className="eyebrow"><Sparkles size={15} /> AGENTIC FEDERATED RESEARCH</div>
      <h1>让敏感数据留在科室，<br />让研究跨越医院边界。</h1>
      <p>
        RareLink 将研究协议、联邦统计、模型实验、隐私审查与科研报告组织为一条可审批、可复现的 Agent 工作流。
      </p>
      <button className="primary large" onClick={create}>
        创建示范研究 <ArrowRight size={18} />
      </button>
      <div className="boundary-note">
        <ShieldCheck size={18} /> 研究用途，非临床诊断 · 比赛版在一台 DGX Spark 上模拟三个逻辑站点
      </div>
    </main>
  );
}

function StatusRail({ study }: { study: Study }) {
  const current = statusIndex(study.status);
  return (
    <div className="status-rail">
      {stages.map((stage, index) => (
        <div className={`stage ${index <= current ? "active" : ""}`} key={stage.status}>
          <span>{index < current ? <Check size={13} /> : index + 1}</span>
          <small>{stage.label}</small>
        </div>
      ))}
    </div>
  );
}

function SiteCards({ study }: { study: Study }) {
  if (!study.feasibility) {
    return <div className="placeholder">批准协议后，由站点数据管家在本地生成受控汇总统计。</div>;
  }
  return (
    <div className="site-grid">
      {study.feasibility.sites.map((site, index) => (
        <article className="site-card" key={site.site_id}>
          <div className="site-head">
            <span className={`site-dot site-${index + 1}`} />
            <strong>{site.site_id.toUpperCase()}</strong>
            <span className="simulation-tag">模拟站点</span>
          </div>
          <div className="site-number">{site.usable_count}<small> / {site.sample_count} 可用</small></div>
          <div className="meter"><i style={{ width: `${site.label_completeness * 100}%` }} /></div>
          <div className="site-meta">
            <span>标签完整度 {(site.label_completeness * 100).toFixed(0)}%</span>
            <span>模态缺失 {(site.missing_modality_rate * 100).toFixed(0)}%</span>
          </div>
          <p>{site.quality_flags[0]}</p>
        </article>
      ))}
    </div>
  );
}

function JudgeJourney({ study, experiments }: { study: Study; experiments: Experiment[] }) {
  const completed = experiments.filter((item) => item.status === "COMPLETED").length;
  return (
    <section className="judge-journey">
      <div className="journey-intro">
        <span><Eye size={17} /> JUDGE PATH · 90 SECONDS</span>
        <strong>不是“训练一个模型”，而是让多中心科研形成可审计证据。</strong>
      </div>
      <div className="journey-steps">
        <div><span>01</span><strong>数据留在科室</strong><small>原始 MRI 与标签不离站</small></div>
        <div><span>02</span><strong>DGX Spark 本地训练</strong><small>统一内存保护串行真实任务</small></div>
        <div><span>03</span><strong>FLARE 聚合更新</strong><small>Local / FedAvg / FedProx 对照</small></div>
        <div><span>04</span><strong>Agent 解释证据</strong><small>{completed ? `${completed} 项完成实验 · 仅聚合指标` : "等待首项实验完成"}</small></div>
      </div>
    </section>
  );
}

function EvidenceBriefPanel({
  study,
  experiments,
  artifacts,
}: {
  study: Study;
  experiments: Experiment[];
  artifacts: AgentArtifact[];
}) {
  const client = useQueryClient();
  const completed = experiments.filter((item) => item.status === "COMPLETED");
  const brief = artifacts.find((item) => item.artifact_type === "evidence_brief")?.content as
    | EvidenceBrief
    | undefined;
  const mutation = useMutation({
    mutationFn: () => api.generateEvidenceBrief(study.id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["agent-artifacts", study.id] });
      void client.invalidateQueries({ queryKey: ["events", study.id] });
    },
  });
  return (
    <section className="panel evidence-brief-panel">
      <div className="panel-title">
        <div><BrainCircuit size={18} /><span><strong>Agent 证据解读</strong><small>只接收锁定合同与聚合指标，不接触影像、标签或患者字段</small></span></div>
        {brief && <span className="agent-source">{brief.source}</span>}
      </div>
      {!completed.length ? (
        <div className="placeholder">先完成一项实验；随后 Agent 将解释平均表现、最弱站点与公平性风险。</div>
      ) : brief ? (
        <div className="evidence-brief">
          <div className="evidence-lead"><span>当前工程候选</span><strong>{brief.leading_strategy.toUpperCase()}</strong><p>{brief.recommendation}</p></div>
          <div><small>AGGREGATE EVIDENCE</small><ul>{brief.evidence.map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div><small>FAIRNESS CHECK</small><ul>{brief.fairness_findings.map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div className="limitations"><small>BOUNDARY</small><ul>{brief.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>
        </div>
      ) : (
        <div className="evidence-empty">
          <div><FileSearch size={22} /><span><strong>把指标变成可解释研究结论</strong><small>输入：{completed.length} 项完成实验的聚合 Dice、HD95、最弱站点与站点差异。</small></span></div>
          <button className="secondary-button" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? <RefreshCcw className="spin" size={15} /> : <BrainCircuit size={15} />}
            {mutation.isPending ? "正在生成…" : "生成证据解读"}
          </button>
          {mutation.error && <p className="inline-error">{mutation.error instanceof Error ? mutation.error.message : "生成失败"}</p>}
        </div>
      )}
    </section>
  );
}

function ActionPanel({ study, experiments, artifacts }: { study: Study; experiments: Experiment[]; artifacts: AgentArtifact[] }) {
  const client = useQueryClient();
  const [error, setError] = useState("");
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["studies"] }),
      client.invalidateQueries({ queryKey: ["experiments", study.id] }),
      client.invalidateQueries({ queryKey: ["events", study.id] }),
      client.invalidateQueries({ queryKey: ["agent-artifacts", study.id] }),
      client.invalidateQueries({ queryKey: ["training-jobs", study.id] }),
    ]);
  };
  const mutation = useMutation({
    mutationFn: async () => {
      setError("");
      switch (study.status) {
        case "DRAFT": return api.generateProtocol(study.id);
        case "PROTOCOL_REVIEW": return api.approve(study.id, "Protocol approved for simulated-site feasibility analysis");
        case "FEASIBILITY_RUNNING": return api.runFeasibility(study.id);
        case "FEASIBILITY_REVIEW": {
          const proposal = artifacts.find((item) => item.artifact_type === "experiment_proposal");
          if (!proposal) return api.proposeContract(study.id);
          return api.lockContract(study.id, proposal.content);
        }
        case "CONTRACT_LOCKED":
        case "TRAINING_RUNNING": {
          const existing = new Map(experiments.map((item) => [item.strategy, item]));
          for (const strategy of ["local", "fedavg", "fedprox"]) {
            let experiment = existing.get(strategy);
            if (!experiment) experiment = await api.createExperiment(study.id, strategy);
            if (experiment.status === "PENDING") await api.runExperiment(experiment.id);
          }
          return api.getStudy(study.id);
        }
        case "FAILED_RETRYABLE": {
          const failed = experiments.find((item) => item.status === "FAILED");
          if (!failed) throw new Error("没有可重试的失败实验");
          return api.runExperiment(failed.id);
        }
        case "RESULTS_REVIEW":
          if (!study.review_markdown) return api.generateReview(study.id);
          return api.approve(study.id, "Metrics and limitations reviewed; proceed to privacy report");
        case "PRIVACY_REVIEW": return api.generateReport(study.id);
        default: return study;
      }
    },
    onSuccess: refresh,
    onError: (reason) => setError(reason instanceof Error ? reason.message : "操作失败"),
  });

  const labels: Partial<Record<StudyStatus, string>> = {
    DRAFT: "生成研究协议",
    PROTOCOL_REVIEW: "批准协议，启动站点统计",
    FEASIBILITY_RUNNING: "运行联邦可行性分析",
    FEASIBILITY_REVIEW: artifacts.some((item) => item.artifact_type === "experiment_proposal")
      ? "人工批准并锁定 Agent 实验提案"
      : "实验设计 Agent 生成比较方案",
    CONTRACT_LOCKED: "运行三策略基准实验",
    TRAINING_RUNNING: "继续未完成实验",
    FAILED_RETRYABLE: "重试失败的真实训练任务",
    RESULTS_REVIEW: study.review_markdown ? "批准结果与局限性" : "生成循证评审",
    PRIVACY_REVIEW: "通过隐私复核，生成报告",
  };
  const label = labels[study.status];
  if (!label) {
    return (
      <div className="complete-banner">
        <FileCheck2 size={20} />
        <span>研究包已生成，可进入提交材料整理。</span>
        <a className="secondary-link" href={api.exportUrl(study.id)}>导出可复现研究包</a>
      </div>
    );
  }
  return (
    <div className="action-panel">
      <div>
        <small>NEXT CONTROLLED ACTION</small>
        <strong>{label}</strong>
        <p>所有关键动作均写入不可覆盖的审计时间线。</p>
      </div>
      <button className="primary" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
        {mutation.isPending ? <Activity className="spin" size={18} /> : <Play size={17} />}
        {mutation.isPending ? "执行中…" : label}
      </button>
      {error && <div className="error"><CircleAlert size={15} />{error}</div>}
    </div>
  );
}

function App() {
  const client = useQueryClient();
  const settledJobsRef = useRef("");
  const studies = useQuery({ queryKey: ["studies"], queryFn: api.listStudies });
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities });
  const study = studies.data?.[0];
  const experiments = useQuery({
    queryKey: ["experiments", study?.id],
    queryFn: () => api.experiments(study!.id),
    enabled: Boolean(study),
  });
  const events = useQuery({
    queryKey: ["events", study?.id],
    queryFn: () => api.events(study!.id),
    enabled: Boolean(study),
  });
  const artifacts = useQuery({
    queryKey: ["agent-artifacts", study?.id],
    queryFn: () => api.agentArtifacts(study!.id),
    enabled: Boolean(study),
  });
  const trainingJobs = useQuery({
    queryKey: ["training-jobs", study?.id],
    queryFn: () => api.trainingJobs(study!.id),
    enabled: Boolean(study),
    refetchInterval: (query) => {
      const jobs = query.state.data as TrainingJob[] | undefined;
      if (jobs?.some((job) => job.status === "QUEUED" || job.status === "RUNNING")) return 1500;
      return study?.status === "TRAINING_RUNNING" ? 1500 : false;
    },
  });
  const create = useMutation({
    mutationFn: api.createStudy,
    onSuccess: () => client.invalidateQueries({ queryKey: ["studies"] }),
  });
  const policyBlocks = useMemo(
    () => study?.feasibility?.policy_decisions.reduce((sum, item) => sum + item.blocked_fields.length, 0) ?? 0,
    [study],
  );
  useEffect(() => {
    const jobs = trainingJobs.data ?? [];
    if (!study || !jobs.length || jobs.some((job) => job.status === "QUEUED" || job.status === "RUNNING")) return;
    const signature = jobs.map((job) => `${job.id}:${job.status}`).join("|");
    if (settledJobsRef.current === signature) return;
    settledJobsRef.current = signature;
    void Promise.all([
      client.invalidateQueries({ queryKey: ["studies"] }),
      client.invalidateQueries({ queryKey: ["experiments", study.id] }),
      client.invalidateQueries({ queryKey: ["events", study.id] }),
    ]);
  }, [client, study, trainingJobs.data]);

  if (studies.isLoading) return <div className="loading"><Activity className="spin" /> Loading RareLink</div>;
  if (!study) return <EmptyState create={() => create.mutate()} />;

  return (
    <div className="app-shell">
      <header>
        <div className="brand"><div className="brand-mark"><Network size={21} /></div><div><strong>RareLink</strong><small>稀联 · 联邦科研智能体</small></div></div>
        <div className="header-boundary"><ShieldCheck size={16} /> RESEARCH USE ONLY · 三站点模拟</div>
        <div className="system-pills">
          <span className={capabilities.data?.gpu_available ? "ok" : "muted"}><Server size={14} /> {capabilities.data?.gpu_available ? "GPU READY" : "LOCAL DEV"}</span>
          <span><BrainCircuit size={14} /> {capabilities.data?.step_mode?.toUpperCase() ?? "…"}</span>
        </div>
      </header>

      <main className="dashboard">
        <section className="hero-row">
          <div>
            <div className="eyebrow"><FlaskConical size={14} /> ACTIVE RESEARCH STUDY</div>
            <h1>{study.title}</h1>
            <p>{study.research_question}</p>
          </div>
          <div className="status-badge"><i /> {study.status.replaceAll("_", " ")}</div>
        </section>

        <StatusRail study={study} />
        <JudgeJourney study={study} experiments={experiments.data ?? []} />
        <ActionPanel study={study} experiments={experiments.data ?? []} artifacts={artifacts.data ?? []} />

        <section className="metrics-strip">
          <div><Database size={18} /><span><small>可用研究样本</small><strong>{study.feasibility?.total_usable_count ?? "—"}</strong></span></div>
          <div><LockKeyhole size={18} /><span><small>策略阻断字段</small><strong>{policyBlocks}</strong></span></div>
          <div><Gauge size={18} /><span><small>实验合同</small><strong>{study.contract ? "LOCKED" : "OPEN"}</strong></span></div>
          <div><BookOpenCheck size={18} /><span><small>账本事件</small><strong>{events.data?.length ?? 0}</strong></span></div>
        </section>

        <div className="content-grid">
          <section className="panel wide">
            <div className="panel-title"><div><Network size={18} /><span><strong>站点可行性</strong><small>原始数据不离开逻辑站点</small></span></div>{study.feasibility && <em>{study.feasibility.finding}</em>}</div>
            <SiteCards study={study} />
          </section>

          <EvidenceBriefPanel study={study} experiments={experiments.data ?? []} artifacts={artifacts.data ?? []} />

          {(trainingJobs.data?.length ?? 0) > 0 && (
            <section className="panel wide">
              <div className="panel-title"><div><Server size={18} /><span><strong>真实训练任务</strong><small>统一内存保护下串行执行 · 状态每 1.5 秒刷新</small></span></div></div>
              <div className="site-grid">
                {(trainingJobs.data as TrainingJob[]).map((job) => (
                  <article className="site-card" key={job.id}>
                    <div className="site-head"><span className="site-dot site-1" /><strong>{job.strategy.toUpperCase()}</strong><span className="simulation-tag">{job.backend}</span></div>
                    <div className="site-number">{job.progress}<small>% · {job.status}</small></div>
                    <div className="meter"><i style={{ width: `${job.progress}%` }} /></div>
                    <p>{job.error ?? job.message}</p>
                    {job.global_model_path && <small>GLOBAL MODEL · {job.global_model_path}</small>}
                  </article>
                ))}
              </div>
            </section>
          )}

          <section className="panel protocol-panel">
            <div className="panel-title"><div><BrainCircuit size={18} /><span><strong>研究主任 Agent</strong><small>{study.protocol ? `Source · ${study.protocol.source}` : "等待研究问题"}</small></span></div></div>
            {study.protocol ? (
              <div className="protocol-content">
                <small>HYPOTHESIS</small><p>{study.protocol.hypothesis}</p>
                <small>FIXED ENDPOINT</small><div className="tag-row"><span>{study.protocol.primary_endpoint}</span>{study.protocol.guardrail_metrics.map((item) => <span key={item}>{item}</span>)}</div>
                <small>LIMITATIONS</small><ul>{study.protocol.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            ) : <div className="placeholder">Step 3.7 或安全模板将把问题转换为结构化协议。</div>}
          </section>

          <section className="panel wide">
            <div className="panel-title"><div><Activity size={18} /><span><strong>策略公平比较</strong><small>相同划分 · 相同预算 · 同时关注最差站点</small></span></div><span className="mock-label">{capabilities.data?.federation_mode ?? "mock"} MODE</span></div>
            <Suspense fallback={<div className="placeholder">正在加载指标视图…</div>}>
              <MetricChart experiments={experiments.data ?? []} />
            </Suspense>
          </section>

          <section className="panel ledger-panel">
            <div className="panel-title"><div><ShieldCheck size={18} /><span><strong>审计时间线</strong><small>协议、策略与实验均可追溯</small></span></div></div>
            <div className="timeline">
              {(events.data ?? []).slice(-7).reverse().map((event) => (
                <div className="timeline-item" key={event.id}><i /><div><strong>{event.event_type}</strong><small>{event.actor} · {new Date(event.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</small></div></div>
              ))}
            </div>
          </section>

          <section className="panel ledger-panel">
            <div className="panel-title"><div><BrainCircuit size={18} /><span><strong>Agent Team 资产</strong><small>每个角色输出独立留痕，不能越过人工审批</small></span></div></div>
            <div className="timeline">
              {(artifacts.data ?? []).slice(-7).reverse().map((artifact) => (
                <div className="timeline-item" key={artifact.id}><i /><div><strong>{artifact.artifact_type}</strong><small>{artifact.role} · {artifact.source}</small></div></div>
              ))}
              {!artifacts.data?.length && <div className="placeholder">Agent 结构化产物将在此登记。</div>}
            </div>
          </section>

          {(study.review_markdown || study.report_markdown) && (
            <section className="panel report-panel">
              <div className="panel-title"><div><FileCheck2 size={18} /><span><strong>研究资产</strong><small>所有数字回链到实验账本</small></span></div></div>
              <Suspense fallback={<div className="placeholder">正在加载研究资产…</div>}>
                <MarkdownReport content={study.report_markdown ?? study.review_markdown ?? ""} />
              </Suspense>
            </section>
          )}
        </div>
      </main>
      <footer>RareLink v{capabilities.data?.app_version ?? "0.1"} · Patient-level data is never sent to Step 3.7 · Apache-2.0</footer>
    </div>
  );
}

export default App;
