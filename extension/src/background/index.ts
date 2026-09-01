import { ApiClient, ApiError } from "../api/client";
import { analyzeCurrentDocument } from "../analyzers/pageAnalyzer";
import type { RuntimeRequest, RuntimeResponse } from "../messages";
import {
  getCurrentTask,
  loadSettings,
  saveSettings,
  setCurrentTask,
} from "../storage/settings";

void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

chrome.runtime.onInstalled.addListener(() => {
  void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
});

chrome.runtime.onMessage.addListener(
  (message: RuntimeRequest, _sender, sendResponse: (response: RuntimeResponse) => void) => {
    void handleMessage(message)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((error: unknown) => {
        const apiError = error instanceof ApiError ? error : null;
        sendResponse({
          ok: false,
          error: error instanceof Error ? error.message : "插件发生未知错误",
          status: apiError?.status,
        });
      });
    return true;
  },
);

async function handleMessage(message: RuntimeRequest): Promise<unknown> {
  switch (message.type) {
    case "GET_SETTINGS": {
      const settings = await loadSettings();
      return { baseUrl: settings.baseUrl, hasApiToken: Boolean(settings.apiToken) };
    }
    case "SAVE_SETTINGS": {
      const settings = await saveSettings(message);
      return { baseUrl: settings.baseUrl, hasApiToken: Boolean(settings.apiToken) };
    }
    case "TEST_CONNECTION":
      return client().then((api) => api.health());
    case "GET_PROJECTS":
      return client().then((api) => api.projects());
    case "CLAIM_NEXT_TASK": {
      const task = await client().then((api) => api.claimNextTask(message.projectId));
      await setCurrentTask(task);
      return task;
    }
    case "GET_TASK": {
      const task = await client().then((api) => api.task(message.taskId));
      await setCurrentTask(task);
      return task;
    }
    case "UPDATE_TASK": {
      const task = await client().then((api) => api.updateTask(message.taskId, message.input));
      await setCurrentTask(task.status === "skipped" || task.status === "completed" ? null : task);
      return task;
    }
    case "GET_CURRENT_TASK":
      return getCurrentTask();
    case "SET_CURRENT_TASK":
      await setCurrentTask(message.task);
      return message.task;
    case "ANALYZE_ACTIVE_TAB":
      return analyzeActiveTab();
    case "OPEN_TASK":
      await chrome.tabs.create({ url: message.task.sourceUrl, active: true });
      await setCurrentTask(message.task);
      return { opened: true };
    case "CREATE_SUBMISSION":
      return client().then((api) => api.createSubmission(message.input));
    case "CREATE_VERIFICATION":
      return client().then((api) => api.createVerification(message.input));
  }
}

async function client(): Promise<ApiClient> {
  return new ApiClient(await loadSettings());
}

async function analyzeActiveTab(): Promise<unknown> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url || !/^https?:/.test(tab.url)) {
    throw new Error("当前标签页不是可分析的 HTTP/HTTPS 页面");
  }
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: analyzeCurrentDocument,
  });
  const result = results[0]?.result;
  if (!result) {
    throw new Error("页面分析未返回结果");
  }
  return result;
}
