import type { BacklinkTask } from "../types/domain";

const SETTINGS_KEY = "serverSettings";
const CURRENT_TASK_KEY = "currentTask";

export interface ServerSettings {
  baseUrl: string;
  apiToken: string;
}

const DEFAULT_SETTINGS: ServerSettings = {
  baseUrl: "",
  apiToken: "",
};

export async function loadSettings(): Promise<ServerSettings> {
  const stored = await chrome.storage.local.get(SETTINGS_KEY);
  const value = stored[SETTINGS_KEY] as Partial<ServerSettings> | undefined;
  return {
    baseUrl: value?.baseUrl ?? DEFAULT_SETTINGS.baseUrl,
    apiToken: value?.apiToken ?? DEFAULT_SETTINGS.apiToken,
  };
}

export async function saveSettings(input: {
  baseUrl: string;
  apiToken?: string;
}): Promise<ServerSettings> {
  const current = await loadSettings();
  const next: ServerSettings = {
    baseUrl: normalizeBaseUrl(input.baseUrl),
    apiToken: input.apiToken?.trim() || current.apiToken,
  };
  await chrome.storage.local.set({ [SETTINGS_KEY]: next });
  return next;
}

export function normalizeBaseUrl(value: string): string {
  const parsed = new URL(value.trim());
  const isLocal = parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1";
  const isIpAddress = /^\d{1,3}(\.\d{1,3}){3}$/.test(parsed.hostname) || parsed.hostname.includes(":");
  if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && isLocal)) {
    throw new Error("云端服务必须使用 HTTPS；只有 localhost/127.0.0.1 可使用 HTTP");
  }
  if (!isLocal && parsed.port === "8000") {
    throw new Error("云端地址应填写 Caddy 的 HTTPS 根地址，不要使用 Uvicorn 的 :8000 端口");
  }
  if (!isLocal && isIpAddress) {
    throw new Error("云端地址应使用已配置可信 HTTPS 证书的域名，不能直接填写服务器 IP");
  }
  parsed.hash = "";
  parsed.search = "";
  return parsed.toString().replace(/\/$/, "");
}

export async function getCurrentTask(): Promise<BacklinkTask | null> {
  const stored = await chrome.storage.local.get(CURRENT_TASK_KEY);
  return (stored[CURRENT_TASK_KEY] as BacklinkTask | undefined) ?? null;
}

export async function setCurrentTask(task: BacklinkTask | null): Promise<void> {
  if (task) {
    await chrome.storage.local.set({ [CURRENT_TASK_KEY]: task });
  } else {
    await chrome.storage.local.remove(CURRENT_TASK_KEY);
  }
}
