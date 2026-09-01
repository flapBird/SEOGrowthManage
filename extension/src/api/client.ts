import type {
  BacklinkTask,
  CreateSubmissionInput,
  CreateVerificationInput,
  Project,
  UpdateBacklinkTaskInput,
} from "../types/domain";
import type { ServerSettings } from "../storage/settings";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class ApiClient {
  constructor(private readonly settings: ServerSettings) {}

  async health(): Promise<{ connected: true; server: string }> {
    await this.request<unknown>("/api/v1/health");
    return { connected: true, server: this.settings.baseUrl };
  }

  projects(): Promise<Project[]> {
    return this.request<Project[]>("/api/v1/projects");
  }

  claimNextTask(projectId: number): Promise<BacklinkTask> {
    return this.request<BacklinkTask>("/api/v1/tasks/next/claim", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ projectId }),
    });
  }

  task(taskId: number): Promise<BacklinkTask> {
    return this.request<BacklinkTask>(`/api/v1/tasks/${taskId}`);
  }

  updateTask(taskId: number, input: UpdateBacklinkTaskInput): Promise<BacklinkTask> {
    return this.request<BacklinkTask>(`/api/v1/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  }

  createSubmission(input: CreateSubmissionInput): Promise<unknown> {
    return this.request("/api/v1/submissions", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(input),
    });
  }

  createVerification(input: CreateVerificationInput): Promise<unknown> {
    return this.request("/api/v1/verifications", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(input),
    });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    if (!this.settings.baseUrl || !this.settings.apiToken) {
      throw new ApiError("请先配置服务器地址和 Extension Token");
    }
    let response: Response;
    try {
      response = await fetch(`${this.settings.baseUrl}${path}`, {
        ...init,
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${this.settings.apiToken}`,
          "Content-Type": "application/json",
          ...init.headers,
        },
      });
    } catch (error) {
      const detail = error instanceof Error ? error.message : "网络请求失败";
      throw new ApiError(
        `无法连接服务器：${detail}。请确认域名解析正确、HTTPS 证书有效、443 端口已开放且 Caddy 正在运行。`,
      );
    }
    if (!response.ok) {
      const message = await readErrorMessage(response);
      throw new ApiError(message, response.status);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    const payload = (await response.json()) as T | { data: T };
    return unwrap(payload);
  }
}

function unwrap<T>(payload: T | { data: T }): T {
  if (payload && typeof payload === "object" && "data" in payload) {
    return payload.data;
  }
  return payload;
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string; message?: string; error?: string };
    return body.detail || body.message || body.error || `服务器返回 ${response.status}`;
  } catch {
    return `服务器返回 ${response.status}`;
  }
}
