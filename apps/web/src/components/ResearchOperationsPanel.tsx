import { useQuery } from "@tanstack/react-query";
import {
  Boxes,
  Building2,
  CircleAlert,
  FileKey2,
  PackageCheck,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { api } from "../api";
import type { Study } from "../types";

function digest(value: string | null): string {
  if (!value) return "—";
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}

function statusClass(status: string): string {
  if (status === "RELEASED" || status === "VERIFIED" || status === "ACTIVE") {
    return "registry-status success";
  }
  if (status === "REVOKED" || status === "WITHDRAWN") {
    return "registry-status danger";
  }
  return "registry-status pending";
}

export default function ResearchOperationsPanel({ study }: { study: Study }) {
  const summary = useQuery({
    queryKey: ["operations-summary", study.organization_id],
    queryFn: () => api.operationsSummary(study.organization_id),
  });
  const sites = useQuery({
    queryKey: ["study-sites", study.id],
    queryFn: () => api.studySites(study.id),
  });
  const models = useQuery({
    queryKey: ["model-versions", study.id],
    queryFn: () => api.modelVersions(study.id),
  });
  const evidence = useQuery({
    queryKey: ["evidence-packages", study.id],
    queryFn: () => api.evidencePackages(study.id),
  });
  const loading = summary.isLoading || sites.isLoading || models.isLoading || evidence.isLoading;
  if (loading) {
    return <section className="panel operations-panel placeholder">正在读取多研究运营账本…</section>;
  }
  const alerts = summary.data?.alerts;
  const alertCount = alerts
    ? alerts.sites_paused_or_withdrawn
      + alerts.models_waiting_for_review
      + alerts.evidence_waiting_for_verification
    : 0;
  return (
    <section className="panel operations-panel">
      <div className="operations-heading">
        <div>
          <div className="eyebrow"><Workflow size={14} /> RESEARCH OPERATIONS PLANE</div>
          <h2>多研究运营与可信模型治理</h2>
          <p>
            研究、站点、模型和证据包使用独立状态机；仿真结果不能晋级为物理验证模型。
          </p>
        </div>
        <div className={alertCount ? "operations-alert active" : "operations-alert"}>
          {alertCount ? <CircleAlert size={18} /> : <ShieldCheck size={18} />}
          <span><strong>{alertCount}</strong><small>待处理治理项</small></span>
        </div>
      </div>

      <div className="operations-metrics">
        <article><Building2 size={18} /><span><small>组织内研究</small><strong>{summary.data?.studies.total ?? 0}</strong></span></article>
        <article><Boxes size={18} /><span><small>纳入站点</small><strong>{summary.data?.sites.total ?? 0}</strong></span></article>
        <article><PackageCheck size={18} /><span><small>模型版本</small><strong>{summary.data?.models.total ?? 0}</strong></span></article>
        <article><FileKey2 size={18} /><span><small>证据包</small><strong>{summary.data?.evidence_packages.total ?? 0}</strong></span></article>
      </div>

      <div className="operations-grid">
        <div className="registry-column">
          <div className="registry-title"><Building2 size={16} /><strong>研究站点</strong><small>{study.organization_id}</small></div>
          {(sites.data ?? []).map((site) => (
            <article className="registry-row" key={site.id}>
              <div><strong>{site.display_name}</strong><small>{site.site_id} · {site.organization}</small></div>
              <div className={statusClass(site.status)}>{site.status}</div>
              <div className="registry-proof">
                <span className={site.data_use_approved ? "pass" : ""}>DUA</span>
                <span className={site.certificate_bound ? "pass" : ""}>CERT</span>
                <span className={site.dataset_fingerprint ? "pass" : ""}>DATA</span>
              </div>
            </article>
          ))}
          {!sites.data?.length && <div className="registry-empty">尚未邀请研究站点。</div>}
        </div>

        <div className="registry-column">
          <div className="registry-title"><PackageCheck size={16} /><strong>模型注册中心</strong><small>promotion gate</small></div>
          {(models.data ?? []).map((model) => (
            <article className="registry-row" key={model.id}>
              <div><strong>{model.name} · {model.semantic_version}</strong><small>{model.model_family} · {digest(model.artifact_sha256)}</small></div>
              <div className={statusClass(model.status)}>{model.status.replaceAll("_", " ")}</div>
              <div className="registry-proof">
                <span className={model.signature_present ? "pass" : ""}>SIGN</span>
                <span className={model.evidence_package_id ? "pass" : ""}>EVIDENCE</span>
                <span className={model.validation_tier.startsWith("L3") || model.validation_tier.startsWith("L4") ? "pass" : ""}>{model.validation_tier}</span>
              </div>
            </article>
          ))}
          {!models.data?.length && <div className="registry-empty">训练模型将在摘要、签名和证据核验后登记。</div>}
        </div>

        <div className="registry-column">
          <div className="registry-title"><FileKey2 size={16} /><strong>研究证据生命周期</strong><small>offline verifiable</small></div>
          {(evidence.data ?? []).map((item) => (
            <article className="registry-row" key={item.id}>
              <div><strong>{digest(item.package_sha256)}</strong><small>{item.validation_tier} · {item.site_count}/{item.required_quorum} sites</small></div>
              <div className={statusClass(item.status)}>{item.status}</div>
              <div className="registry-proof">
                <span className={item.gates.quorum ? "pass" : ""}>3/3</span>
                <span className={item.gates.privacy ? "pass" : ""}>DP</span>
                <span className={item.gates.security ? "pass" : ""}>SEC</span>
                <span className={item.gates.dual_approval ? "pass" : ""}>2P</span>
              </div>
            </article>
          ))}
          {!evidence.data?.length && <div className="registry-empty">L3/L4 收据齐备后才能登记正式研究证据包。</div>}
        </div>
      </div>
      <div className="operations-boundary">
        <ShieldCheck size={15} />
        <span>仅展示摘要、状态和哈希；模型二进制、私钥、本地路径和患者数据均不进入运营控制面。</span>
      </div>
    </section>
  );
}
