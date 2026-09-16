export type EntityId = number;

export interface Project {
  id: EntityId;
  name: string;
  website: string;
  authorName?: string | null;
  email?: string | null;
  tagline?: string | null;
  shortDescription?: string | null;
  mediumDescription?: string | null;
  longDescription?: string | null;
  keywords?: string[];
}

export type WorkflowType =
  | "blog_comment"
  | "article"
  | "guest_post"
  | "directory"
  | "forum"
  | "other";

export type BacklinkTaskStatus =
  | "ready"
  | "processing"
  | "prepared"
  | "completed"
  | "failed"
  | "skipped";

export interface BacklinkTask {
  id: EntityId;
  projectId: EntityId;
  opportunityId: EntityId;
  workflow: WorkflowType;
  status: BacklinkTaskStatus;
  sourceUrl: string;
  sourceDomain: string;
  targetUrl: string;
  anchorText?: string | null;
  note?: string | null;
  leaseExpiresAt?: string | null;
  createdAt: string;
  updatedAt: string;
  project: Project;
}

export interface UpdateBacklinkTaskInput {
  status: Extract<BacklinkTaskStatus, "processing" | "completed" | "failed" | "skipped">;
  note?: string;
}

export type SubmissionStatus =
  | "prepared"
  | "submitted"
  | "pending"
  | "published"
  | "duplicate"
  | "rejected"
  | "failed"
  | "removed"
  | "unknown";

export interface CreateSubmissionInput {
  taskId: EntityId;
  status: "prepared";
  targetUrl: string;
  sourceUrl: string;
  workflow: WorkflowType;
  submittedContent?: string;
  submittedWebsite?: string;
  anchorText?: string;
  resultMessage?: string;
  note?: string;
  submittedAt?: string;
}

export interface UpdateSubmissionInput {
  status: Extract<SubmissionStatus, "submitted" | "pending" | "duplicate" | "rejected" | "failed" | "unknown">;
  submissionUrl?: string;
  resultMessage?: string;
  note?: string;
}

export interface Submission {
  id: EntityId;
  taskId: EntityId;
  opportunityId: EntityId;
  projectId: EntityId;
  backlinkRecordId?: EntityId | null;
  targetUrl: string;
  targetDomain: string;
  sourceUrl: string;
  sourceDomain: string;
  workflow: WorkflowType;
  submittedContent?: string | null;
  submittedWebsite?: string | null;
  anchorText?: string | null;
  submissionUrl?: string | null;
  status: SubmissionStatus;
  submittedAt?: string | null;
  verifiedAt?: string | null;
  resultMessage?: string | null;
  note?: string | null;
  preparedAt: string;
  createdAt: string;
  updatedAt: string;
}

export interface SubmissionCheck {
  exactSubmissionCount: number;
  domainSubmissionCount: number;
  domainBacklinkCount: number;
  latestStatus?: SubmissionStatus | null;
}

export type FillFieldKind = "title" | "name" | "email" | "website" | "tagline" | "description" | "comment";

export interface FormFillInput {
  workflow: WorkflowType;
  project: Project;
  targetUrl: string;
  commentDraft?: string;
}

export interface FormFieldMatch {
  kind: FillFieldKind;
  label: string;
  confidence: number;
  value: string;
  willFill: boolean;
  matchesExpected: boolean;
  reason?: string;
}

export interface FormFillResult {
  url: string;
  fields: FormFieldMatch[];
  warnings: string[];
  confidence: number;
  canFill: boolean;
  filledCount: number;
  skippedCount: number;
  matchedCount: number;
}

export interface FillAndRecordResult {
  fill: FormFillResult;
  submission: Submission;
  task: BacklinkTask;
}

export interface CreateVerificationInput {
  taskId: EntityId;
  submissionId: EntityId;
  sourceUrl: string;
  targetUrl: string;
  outcome: "active" | "pending" | "removed" | "page_404" | "link_missing" | "unknown";
  httpStatus?: number;
  anchorText?: string;
  linkRel?: string[];
  checkedAt: string;
  message?: string;
}

export type VerificationOutcome = CreateVerificationInput["outcome"];

export interface PageVerificationResult {
  sourceUrl: string;
  targetUrl: string;
  outcome: Extract<VerificationOutcome, "active" | "page_404" | "link_missing" | "unknown">;
  anchorText?: string;
  linkRel: string[];
  checkedAt: string;
  message: string;
}

export interface Verification {
  id: EntityId;
  submissionId: EntityId;
  taskId: EntityId;
  projectId: EntityId;
  backlinkRecordId?: EntityId | null;
  sourceUrl: string;
  targetUrl: string;
  outcome: VerificationOutcome;
  httpStatus?: number | null;
  anchorText?: string | null;
  linkRel: string[];
  message?: string | null;
  checkedAt: string;
  createdAt: string;
}

export interface SubmissionActionResult {
  submission: Submission;
  task: BacklinkTask;
}

export interface VerificationResult extends SubmissionActionResult {
  verification: Verification;
}

export interface SubmitButtonCandidate {
  label: string;
  phase: "progress" | "final";
  confidence: number;
  selected: boolean;
  reason?: string;
}

export interface SubmitControlResult {
  url: string;
  candidates: SubmitButtonCandidate[];
  warnings: string[];
  canSubmit: boolean;
  clicked: boolean;
}

export interface SubmissionOutcomeDetection {
  url: string;
  status: UpdateSubmissionInput["status"];
  confidence: number;
  message: string;
}

export interface SubmitExecutionResult extends SubmissionActionResult {
  action: SubmitControlResult;
  outcome?: SubmissionOutcomeDetection;
  verification?: Verification;
  progressed: boolean;
}

export interface BacklinkHistoryItem {
  id: EntityId;
  projectId: EntityId;
  projectName: string;
  channelId: EntityId;
  channelName: string;
  channelUrl: string;
  actualUrl: string;
  targetUrl: string;
  anchorText: string;
  linkRel: string[];
  status: "pending" | "live" | "removed";
  origin: "manual" | "batch" | "automation" | "extension_verified";
  publishedAt: string;
  firstSeenAt?: string | null;
  lastVerifiedAt?: string | null;
  submissionId?: EntityId | null;
}

export interface PageAnalysis {
  url: string;
  domain: string;
  title: string;
  language: string;
  pageType: WorkflowType | "unknown";
  confidence: number;
  summary: string;
  signals: {
    hasCommentForm: boolean;
    hasWebsiteField: boolean;
    hasEmailField: boolean;
    hasNameField: boolean;
    loginState: "authenticated" | "unauthenticated" | "unknown";
    accountRequirement: "required" | "not_required" | "unknown";
    hasLoginBarrier: boolean;
    authenticationEvidence: string[];
    hasCaptcha: boolean;
    textareaCount: number;
    editorCount: number;
    submitButtonCount: number;
  };
  analyzedAt: string;
}
