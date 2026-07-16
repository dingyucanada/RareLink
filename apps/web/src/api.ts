import type { AgentArtifact, AuditEvent, Capabilities, Experiment, ImagingPreview, Study, SystemEvidence, TrainingJob } from "./types";

const DEMO_TOKEN = import.meta.env.VITE_RARELINK_DEMO_TOKEN as string | undefined;
const JSON_HEADERS = { "Content-Type": "application/json" };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (DEMO_TOKEN) headers.set("X-RareLink-Demo-Token", DEMO_TOKEN);
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
        parameters: strategy === "fedprox" ? { mu: 0.01 } : {},
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
  exportUrl: (studyId: string) => {
    const query = DEMO_TOKEN ? `?access_token=${encodeURIComponent(DEMO_TOKEN)}` : "";
    return `/api/studies/${studyId}/export${query}`;
  },
};
