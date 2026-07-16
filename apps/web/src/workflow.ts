import type { StudyStatus } from "./types";

export const stages: { status: StudyStatus; label: string }[] = [
  { status: "DRAFT", label: "研究问题" },
  { status: "PROTOCOL_REVIEW", label: "协议审批" },
  { status: "FEASIBILITY_RUNNING", label: "联邦统计" },
  { status: "FEASIBILITY_REVIEW", label: "可行性审查" },
  { status: "CONTRACT_LOCKED", label: "实验合同" },
  { status: "TRAINING_RUNNING", label: "联邦实验" },
  { status: "RESULTS_REVIEW", label: "结果评审" },
  { status: "PRIVACY_REVIEW", label: "隐私复核" },
  { status: "REPORT_READY", label: "研究资产" },
];

export const statusIndex = (status: StudyStatus) => {
  if (status === "FAILED_RETRYABLE" || status === "FAILED_FINAL") {
    return stages.findIndex((stage) => stage.status === "TRAINING_RUNNING");
  }
  return stages.findIndex((stage) => stage.status === status);
};
