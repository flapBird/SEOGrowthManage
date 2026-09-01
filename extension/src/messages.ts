import type {
  BacklinkTask,
  CreateSubmissionInput,
  CreateVerificationInput,
  FillAndRecordResult,
  FormFillInput,
  FormFillResult,
  PageAnalysis,
  Project,
  SubmissionCheck,
  UpdateBacklinkTaskInput,
} from "./types/domain";

export interface PublicSettings {
  baseUrl: string;
  hasApiToken: boolean;
}

export type RuntimeRequest =
  | { type: "GET_SETTINGS" }
  | { type: "SAVE_SETTINGS"; baseUrl: string; apiToken?: string }
  | { type: "TEST_CONNECTION" }
  | { type: "GET_PROJECTS" }
  | { type: "CLAIM_NEXT_TASK"; projectId: number }
  | { type: "GET_TASK"; taskId: number }
  | { type: "UPDATE_TASK"; taskId: number; input: UpdateBacklinkTaskInput }
  | { type: "GET_CURRENT_TASK" }
  | { type: "SET_CURRENT_TASK"; task: BacklinkTask | null }
  | { type: "ANALYZE_ACTIVE_TAB" }
  | { type: "PREVIEW_FORM"; input: FormFillInput; task: BacklinkTask }
  | { type: "FILL_FORM"; input: FormFillInput; task: BacklinkTask; preview: FormFillResult }
  | { type: "CHECK_SUBMISSIONS"; projectId: number; sourceUrl: string }
  | { type: "OPEN_TASK"; task: BacklinkTask }
  | { type: "CREATE_SUBMISSION"; input: CreateSubmissionInput }
  | { type: "CREATE_VERIFICATION"; input: CreateVerificationInput };

export type RuntimeResponse<T = unknown> =
  | { ok: true; data: T }
  | { ok: false; error: string; status?: number };

export type MessageData =
  | PublicSettings
  | Project[]
  | BacklinkTask
  | PageAnalysis
  | FormFillResult
  | FillAndRecordResult
  | SubmissionCheck
  | null
  | { connected: true; server: string }
  | { opened: true };
