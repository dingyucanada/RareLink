import { useQuery } from "@tanstack/react-query";
import { CircleAlert, Network, Server, ShieldCheck, WifiOff } from "lucide-react";
import { api } from "../api";

function ageLabel(value: string | null): string {
  if (!value) return "尚无心跳";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds} 秒前`;
  return `${Math.floor(seconds / 60)} 分钟前`;
}

export default function PhysicalFederationPanel() {
  const sites = useQuery({
    queryKey: ["physical-sites"],
    queryFn: api.physicalSites,
    refetchInterval: 5000,
  });
  const jobs = useQuery({
    queryKey: ["physical-jobs"],
    queryFn: api.physicalJobs,
    refetchInterval: 3000,
  });
  const audit = useQuery({
    queryKey: ["physical-audit-summary"],
    queryFn: api.physicalAuditSummary,
    refetchInterval: 5000,
  });
  const physicalSites = sites.data ?? [];
  const latestJob = jobs.data?.[0];
  const unavailable = sites.isError || jobs.isError || audit.isError;
  const mode = physicalSites[0]?.deployment_mode ?? latestJob?.deployment_mode ?? "disabled";
  const readyCount = physicalSites.filter(
    (site) =>
      site.status === "READY" &&
      site.certificate_status === "VALID" &&
      site.data_ready &&
      site.gpu_ready &&
      site.monai_ready &&
      site.nvflare_ready,
  ).length;

  return (
    <section className="physical-federation">
      <div className="physical-heading">
        <div>
          <small>PHYSICAL FEDERATION CONTROL PLANE</small>
          <strong><Network size={19} /> 三物理 Spark 运行面</strong>
          <p>
            {mode === "physical"
              ? "PHYSICAL · 状态来自独立 Spark Site Agent 的签名心跳。"
              : mode === "isolated-integration"
                ? "ISOLATED INTEGRATION · 独立进程协议验收，不作为三台 Spark 实机证据。"
                : "DISABLED · 尚未启用物理控制面。"}
            {" "}不读取影像、标签、病例 ID 或本地路径。
          </p>
        </div>
        <div className="physical-heading-badges">
          <div className={`physical-audit ${audit.data?.verified ? "ready" : ""}`}>
            <span><ShieldCheck size={12} /> {audit.data?.event_count ?? 0}</span>
            <small>{audit.data?.verified ? "审计链通过" : "审计链待核验"}</small>
          </div>
          <div className={`physical-quorum ${readyCount === 3 ? "ready" : ""}`}>
            <span>{readyCount}/{physicalSites.length || 3}</span>
            <small>站点就绪</small>
          </div>
        </div>
      </div>

      {unavailable ? (
        <div className="physical-empty physical-error">
          <CircleAlert size={22} />
          <div>
            <strong>物理控制 API 当前不可用</strong>
            <p>未以缓存或模拟站点补造状态；请检查协调服务、访问控制和数据库。</p>
          </div>
        </div>
      ) : !physicalSites.length ? (
        <div className="physical-empty">
          <Server size={22} />
          <div>
            <strong>等待物理站点注册</strong>
            <p>完成三台 Spark 的启动包分发后，Site Agent 将在这里报告真实状态。</p>
          </div>
        </div>
      ) : (
        <div className="physical-site-grid">
          {physicalSites.map((site) => {
            const online = site.status !== "OFFLINE" && site.status !== "UNKNOWN";
            const valid = site.certificate_status === "VALID";
            return (
              <article className={`physical-site ${site.status.toLowerCase()}`} key={site.site_id}>
                <div className="physical-site-head">
                  <span>{online ? <Server size={16} /> : <WifiOff size={16} />}</span>
                  <div><strong>{site.display_name}</strong><small>{site.site_id}</small></div>
                  <em>{site.status}</em>
                </div>
                <div className="physical-checks">
                  <span className={valid ? "ok" : ""}><ShieldCheck size={13} /> 证书 {site.certificate_status}</span>
                  <span className={site.data_ready ? "ok" : ""}>数据 {site.data_ready ? "READY" : "WAIT"}</span>
                  <span className={site.gpu_ready ? "ok" : ""}>GPU {site.gpu_ready ? "READY" : "WAIT"}</span>
                </div>
                <div className="physical-progress">
                  <div>
                    <span>训练轮次</span>
                    <strong>{site.current_round}/{site.total_rounds || "—"}</strong>
                  </div>
                  <div>
                    <span>最后心跳</span>
                    <strong>{ageLabel(site.last_heartbeat_at)}</strong>
                  </div>
                </div>
                {site.dataset_fingerprint && (
                  <code>DATASET {site.dataset_fingerprint.slice(0, 12)}…</code>
                )}
                {site.receipt_sha256 && <code>RECEIPT {site.receipt_sha256.slice(0, 12)}…</code>}
              </article>
            );
          })}
        </div>
      )}

      {latestJob && (
        <div className="physical-job">
          <div>
            <small>LATEST PHYSICAL JOB</small>
            <strong>{latestJob.strategy.toUpperCase()} · {latestJob.status}</strong>
          </div>
          <div><span>NVFLARE JOB ID</span><strong>{latestJob.external_job_id ?? "等待人工审批提交"}</strong></div>
          <div><span>ROUND</span><strong>{latestJob.current_round}/{latestJob.total_rounds}</strong></div>
          <div><span>UPDATES</span><strong>{latestJob.received_updates}/{latestJob.quorum_required}</strong></div>
          {latestJob.error && <p><CircleAlert size={14} /> {latestJob.error}</p>}
        </div>
      )}
    </section>
  );
}
