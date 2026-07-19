import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, ChevronUp, Cpu, FileKey2, PlayCircle, RefreshCcw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { api } from "../api";

const readableCheck: Record<string, string> = {
  three_logical_sites: "三逻辑站点收据齐全",
  all_three_updates_aggregated: "三份本地更新已聚合",
  global_model_persisted: "全局模型已持久化",
  aggregate_only_receipt: "收据不含病例或患者字段",
  integrity_hashes_present: "四份证据文件哈希完整",
};

export default function VerifiedRunConsole() {
  const [expanded, setExpanded] = useState(false);
  const run = useQuery({ queryKey: ["msd-run"], queryFn: api.msdRun });
  const verify = useMutation({ mutationFn: api.verifyMsdRun });
  const receipt = verify.data?.receipt ?? run.data;

  if (run.isLoading) return <section className="run-console loading-console">正在装载 DGX Spark 实机收据…</section>;
  if (!receipt?.available || !receipt.execution || !receipt.aggregate_metrics) {
    return <section className="run-console unavailable-console">未发现已提交的 MSD Spark 实机收据。</section>;
  }

  const { execution, aggregate_metrics: metrics } = receipt;
  return (
    <section className="run-console" aria-label="DGX Spark verified run console">
      <div className="console-heading">
        <div>
          <span className="console-kicker"><Cpu size={14} /> DGX SPARK · VERIFIED RUN RECEIPT</span>
          <h2>真实公开影像运行，不是静态“游戏面板”</h2>
          <p>{receipt.dataset} · NVIDIA FLARE FedAvg · 仅输出聚合收据</p>
        </div>
        <div className={`receipt-status ${verify.data?.passed ? "passed" : "ready"}`}>
          <ShieldCheck size={15} /> {verify.data?.passed ? "INTEGRITY VERIFIED" : "RECEIPT READY"}
        </div>
      </div>

      <div className="run-numbers">
        <div><small>PUBLIC CASES</small><strong>24</strong><span>四模态 MRI</span></div>
        <div><small>FEDERATED SITES</small><strong>3 / 3</strong><span>逻辑站点已聚合</span></div>
        <div><small>END-TO-END</small><strong>{execution.elapsed_seconds.toFixed(1)}s</strong><span>{execution.rounds} round · {execution.local_epochs} epoch</span></div>
        <div><small>GB10 GPU PEAK</small><strong>{(execution.peak_gpu_memory_mb / 1024).toFixed(2)} GiB</strong><span>CUDA 本地训练</span></div>
      </div>

      <div className="run-action-row">
        <div className="run-boundary"><ShieldCheck size={15} /><span>{receipt.boundary}</span></div>
        <div className="console-actions">
          <button className="receipt-button ghost" onClick={() => setExpanded((value) => !value)}>
            {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
            {expanded ? "收起站点收据" : "展开站点收据"}
          </button>
          <button className="receipt-button" onClick={() => verify.mutate()} disabled={verify.isPending}>
            {verify.isPending ? <RefreshCcw className="spin" size={15} /> : <PlayCircle size={15} />}
            {verify.isPending ? "正在核验文件…" : "核验本地证据哈希"}
          </button>
        </div>
      </div>

      {verify.data && (
        <div className={`verification-result ${verify.data.passed ? "passed" : "failed"}`}>
          <div><Check size={15} /><strong>{verify.data.passed ? "核验通过" : "核验失败"}</strong><small>{new Date(verify.data.verified_at).toLocaleString("zh-CN", { hour12: false })}</small></div>
          <ul>{Object.entries(verify.data.checks).map(([key, value]) => <li key={key} className={value ? "ok" : "bad"}>{value ? "✓" : "×"} {readableCheck[key] ?? key}</li>)}</ul>
        </div>
      )}

      {expanded && (
        <div className="receipt-details">
          <div className="site-receipt-grid">
            {receipt.site_receipts?.map((site) => (
              <article key={site.site_id}>
                <span>{site.site_id.toUpperCase()} · ROUND {site.round}</span>
                <strong>Dice {site.dice.toFixed(4)}</strong>
                <small>HD95 {site.hd95.toFixed(2)} · 本地训练 {site.elapsed_seconds.toFixed(2)}s</small>
              </article>
            ))}
          </div>
          <div className="receipt-footer"><FileKey2 size={14} /><span>{receipt.files?.length} 份聚合文件已登记 SHA-256；原始影像、标签、病例标识和模型权重均未返回到浏览器。</span></div>
        </div>
      )}
    </section>
  );
}
