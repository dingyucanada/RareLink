import type { AgentArtifact, AuditEvent, Capabilities, Experiment, Study, TrainingJob } from "./types";

const JSON_HEADERS = { "Content-Type": "application/json" };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail ?? "RareLink request failed");
  }
  return response.json() as Promise<T>;
}

export const api = {
  capabilities: () => request<Capabilities>("/api/system/capabilities"),
  listStudies: () => request<Study[]>("/api/studies"),
  getStudy: (id: string) => request<Study>(`/api/studies/${id}`),
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
  generateReport: (studyId: string) =>
    request<Study>(`/api/studies/${studyId}/report:generate`, { method: "POST" }),
  events: (studyId: string) => request<AuditEvent[]>(`/api/studies/${studyId}/events`),
  agentArtifacts: (studyId: string) =>
    request<AgentArtifact[]>(`/api/studies/${studyId}/agent-artifacts`),
  trainingJobs: (studyId: string) =>
    request<TrainingJob[]>(`/api/studies/${studyId}/training-jobs`),
  exportUrl: (studyId: string) => `/api/studies/${studyId}/export`,
};
