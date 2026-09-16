import type {
  BacklinkTask,
  CreateSubmissionInput,
  CreateVerificationInput,
  FillAndRecordResult,
  FormFillInput,
  FormFillResult,
  PageAnalysis,
  Project,
  Submission,
  SubmissionActionResult,
  SubmissionCheck,
  SubmitControlResult,
  SubmitExecutionResult,
  UpdateBacklinkTaskInput,
  UpdateSubmissionInput,
  VerificationResult,
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
  | { type: "PREVIEW_SUBMIT"; submission: Submission }
  | { type: "CONFIRM_SUBMIT"; submission: Submission; preview: SubmitControlResult }
  | { type: "CHECK_SUBMISSIONS"; projectId: number; sourceUrl: string }
  | { type: "GET_SUBMISSIONS"; taskId?: number; projectId?: number; limit?: number }
  | { type: "UPDATE_SUBMISSION"; submission: Submission; input: UpdateSubmissionInput }
  | { type: "VERIFY_SUBMISSION"; submission: Submission }
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
  | Submission[]
  | SubmissionActionResult
  | VerificationResult
  | SubmitControlResult
  | SubmitExecutionResult
  | SubmissionCheck
  | null
  | { connected: true; server: string }
  | { opened: true };
