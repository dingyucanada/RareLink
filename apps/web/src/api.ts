import type { AgentArtifact, AuditEvent, Capabilities, Experiment, ImagingPreview, MsdRunReceipt, MsdRunVerification, PhysicalAuditSummary, PhysicalFederationJob, PhysicalReviewReadiness, PhysicalSite, Study, SystemEvidence, TrainingJob } from "./types";

const DEMO_TOKEN = import.meta.env.VITE_RARELINK_DEMO_TOKEN as string | undefined;
const JSON_HEADERS = { "Content-Type": "application/json" };

function authenticatedHeaders(input?: HeadersInit): Headers {
  const headers = new Headers(input);
  const oidcToken = sessionStorage.getItem("rarelink_oidc_access_token");
  if (oidcToken) headers.set("Authorization", `Bearer ${oidcToken}`);
  else if (DEMO_TOKEN) headers.set("X-RareLink-Demo-Token", DEMO_TOKEN);
  return headers;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = authenticatedHeaders(init?.headers);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail ?? "RareLink request failed");
  }
  return response.json() as Promise<T>;
}

export const api = {
  capabilities: () => request<Capabilities>("/api/system/capabilities"),
  systemEvidence: () => request<SystemEvidence>("/api/system/evidence"),
  msdRun: () => request<MsdRunReceipt>("/api/system/msd-run"),
  verifyMsdRun: () => request<MsdRunVerification>("/api/system/msd-run:verify", { method: "POST" }),
  listStudies: () => request<Study[]>("/api/studies"),
  getStudy: (id: string) => request<Study>(`/api/studies/${id}`),
  imagingPreview: (studyId: string, siteId: string) =>
    request<ImagingPreview>(`/api/studies/${studyId}/imaging-preview?site_id=${encodeURIComponent(siteId)}`),
  createStudy: () =>
    request<Study>("/api/studies", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({
        title: "小儿高级别胶质瘤多站点 MRI 分割可行性研究",
        research_question:
          "在固定计算预算下，联邦学习能否改善三个非独立同分布站点的肿瘤分割，同时不降低最差站点表现？",
        disease_area: "pediatric high-grade glioma",
      }),
    }),
  generateProtocol: (id: string) =>
    request<Study>(`/api/studies/${id}/protocol:generate`, { method: "POST" }),
  approve: (id: string, note: string) =>
    request<Study>(`/api/studies/${id}/approve`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ approved_by: "Competition PI", note }),
    }),
  runFeasibility: (id: string) =>
    request<Study>(`/api/studies/${id}/feasibility:run`, { method: "POST" }),
  proposeContract: (id: string) =>
    request<AgentArtifact>(`/api/studies/${id}/contract:propose`, { method: "POST" }),
  lockContract: (id: string, proposal: Record<string, unknown>) =>
    request<Study>(`/api/studies/${id}/contract:lock`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({
        ...proposal,
        contract_id: `contract-${id}`,
        // The public click-through path is intentionally short and visibly
        // interactive. Full DP-SGD/five-round comparisons remain available
        // through the reproducible research workflow, not this shared demo.
        strategies: ["local", "fedavg", "fedprox"],
        rounds: 1,
        max_trials: 3,
        raw_data_egress: false,
        llm_raw_data_access: false,
        approved_by: "Competition PI",
      }),
    }),
  createExperiment: (studyId: string, strategy: string) =>
    request<Experiment>(`/api/studies/${studyId}/experiments`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({
        strategy,
        hypothesis: `${strategy} is evaluated under the locked benchmark contract`,
        parameters: strategy === "fedprox"
          ? { mu: 0.01 }
          : strategy === "fedavg_dpsgd"
            ? { noise_multiplier: 1.2, max_grad_norm: 1.0, delta: 0.00001 }
            : {},
      }),
    }),
  runExperiment: (id: string) =>
    request<Experiment>(`/api/experiments/${id}:run`, { method: "POST" }),
  experiments: (studyId: string) =>
    request<Experiment[]>(`/api/studies/${studyId}/experiments`),
  generateReview: (studyId: string) =>
    request<Study>(`/api/studies/${studyId}/review:generate`, { method: "POST" }),
  generateEvidenceBrief: (studyId: string) =>
    request<AgentArtifact>(`/api/studies/${studyId}/evidence-brief:generate`, { method: "POST" }),
  generateReport: (studyId: string) =>
    request<Study>(`/api/studies/${studyId}/report:generate`, { method: "POST" }),
  events: (studyId: string) => request<AuditEvent[]>(`/api/studies/${studyId}/events`),
  agentArtifacts: (studyId: string) =>
    request<AgentArtifact[]>(`/api/studies/${studyId}/agent-artifacts`),
  trainingJobs: (studyId: string) =>
    request<TrainingJob[]>(`/api/studies/${studyId}/training-jobs`),
  physicalSites: () => request<PhysicalSite[]>("/api/physical/sites"),
  physicalJobs: () => request<PhysicalFederationJob[]>("/api/physical/jobs"),
  physicalSubmit: (jobId: string, note: string, submitToken: string) =>
    request<PhysicalFederationJob>(`/api/physical/jobs/${jobId}:submit`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ note, submit_token: submitToken }),
    }),
  physicalSync: (jobId: string) =>
    request<PhysicalFederationJob>(`/api/physical/jobs/${jobId}:sync`, {
      method: "POST",
    }),
  physicalAbort: (jobId: string) =>
    request<PhysicalFederationJob>(`/api/physical/jobs/${jobId}:abort`, {
      method: "POST",
    }),
  physicalRetry: (jobId: string, note: string, submitToken: string) =>
    request<PhysicalFederationJob>(`/api/physical/jobs/${jobId}:retry`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ note, submit_token: submitToken }),
    }),
  physicalResume: (jobId: string, note: string, submitToken: string) =>
    request<PhysicalFederationJob>(`/api/physical/jobs/${jobId}:resume`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ note, submit_token: submitToken }),
    }),
  physicalArchiveResults: (jobId: string, expectedModelSha256: string) =>
    request<Record<string, unknown>>(`/api/physical/jobs/${jobId}:archive-results`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ expected_model_sha256: expectedModelSha256 }),
    }),
  physicalReviewReadiness: (jobId: string) =>
    request<PhysicalReviewReadiness>(
      `/api/physical/jobs/${jobId}/review-readiness`,
    ),
  physicalSignModelRelease: (jobId: string, expectedModelSha256: string) =>
    request<Record<string, unknown>>(`/api/physical/jobs/${jobId}:sign-model-release`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({
        attestation: "GLOBAL_MODEL_HASH_AND_RELEASE_REVIEWED",
        expected_model_sha256: expectedModelSha256,
      }),
    }),
  physicalEventStream: async (
    jobId: string,
    onEvent: (event: Record<string, unknown>) => void,
    signal: AbortSignal,
    lastEventId?: string,
  ) => {
    const headers = authenticatedHeaders(
      lastEventId ? { "Last-Event-ID": lastEventId } : undefined,
    );
    headers.set("Accept", "text/event-stream");
    const response = await fetch(
      `/api/physical/events/stream?job_id=${encodeURIComponent(jobId)}`,
      { headers, signal },
    );
    if (!response.ok || !response.body) {
      const payload = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(payload.detail ?? "RareLink event stream failed");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffered = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffered += decoder.decode(value, { stream: true });
      const frames = buffered.split("\n\n");
      buffered = frames.pop() ?? "";
      for (const frame of frames) {
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n");
        if (data) onEvent(JSON.parse(data) as Record<string, unknown>);
      }
    }
  },
  physicalAuditSummary: () =>
    request<PhysicalAuditSummary>("/api/physical/audit-summary"),
  exportUrl: (studyId: string) => {
    const query = DEMO_TOKEN ? `?access_token=${encodeURIComponent(DEMO_TOKEN)}` : "";
    return `/api/studies/${studyId}/export${query}`;
  },
};
