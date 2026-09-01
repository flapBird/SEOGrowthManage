export type EntityId = number;

export interface Project {
  id: EntityId;
  name: string;
  website: string;
  authorName?: string | null;
  email?: string | null;
  tagline?: string | null;
  shortDescription?: string | null;
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
}

export interface UpdateBacklinkTaskInput {
  status: Extract<BacklinkTaskStatus, "processing" | "prepared" | "completed" | "failed" | "skipped">;
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
  | "unknown";

export interface CreateSubmissionInput {
  taskId: EntityId;
  status: SubmissionStatus;
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

export interface CreateVerificationInput {
  taskId: EntityId;
  submissionId?: EntityId;
  sourceUrl: string;
  targetUrl: string;
  outcome: "active" | "pending" | "removed" | "page_404" | "link_missing" | "unknown";
  httpStatus?: number;
  anchorText?: string;
  linkRel?: string[];
  checkedAt: string;
  message?: string;
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
    requiresLogin: boolean;
    hasCaptcha: boolean;
    textareaCount: number;
    editorCount: number;
    submitButtonCount: number;
  };
  analyzedAt: string;
}
