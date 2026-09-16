import { ApiClient, ApiError } from "../api/client";
import { analyzeCurrentDocument } from "../analyzers/pageAnalyzer";
import { inspectOrFillCurrentForm } from "../analyzers/formFiller";
import { inspectCurrentPageForBacklink } from "../analyzers/backlinkVerifier";
import { detectSubmissionOutcome, inspectOrClickSubmitControl } from "../analyzers/submitController";
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
    case "PREVIEW_FORM":
      return inspectActiveForm(message.input, false, message.task);
    case "CHECK_SUBMISSIONS":
      return client().then((api) => api.checkSubmissions(message.projectId, message.sourceUrl));
    case "GET_SUBMISSIONS":
      return client().then((api) => api.submissions({
        taskId: message.taskId,
        projectId: message.projectId,
        limit: message.limit,
      }));
    case "FILL_FORM": {
      const currentPreview = await inspectActiveForm(message.input, false, message.task);
      if (formFingerprint(currentPreview) !== formFingerprint(message.preview)) {
        throw new Error("页面字段或待填内容在预览后发生变化，请重新预览再确认");
      }
      const fill = await inspectActiveForm(message.input, true, message.task);
      if (!fill.canFill || fill.filledCount + fill.matchedCount === 0) {
        throw new Error("没有可安全填写或确认的字段，未创建 Submission");
      }
      const submittedContent = fill.fields.find((field) => field.kind === "comment" || field.kind === "description")?.value;
      const submission = await client().then((api) => api.createSubmission({
        taskId: message.task.id,
        status: "prepared",
        targetUrl: message.task.targetUrl,
        sourceUrl: fill.url,
        workflow: message.task.workflow,
        submittedContent,
        submittedWebsite: message.task.targetUrl,
        anchorText: message.task.anchorText || undefined,
        resultMessage: `安全预填 ${fill.filledCount} 个字段，${fill.matchedCount} 个字段已有目标值`,
        note: fill.warnings.join("；") || undefined,
      }));
      const task = await client().then((api) => api.task(message.task.id));
      await setCurrentTask(task);
      return { fill, submission, task };
    }
    case "PREVIEW_SUBMIT":
      return inspectActiveSubmit(false, message.submission);
    case "CONFIRM_SUBMIT": {
      const currentPreview = await inspectActiveSubmit(false, message.submission);
      if (submitFingerprint(currentPreview) !== submitFingerprint(message.preview)) {
        throw new Error("页面提交按钮在预览后发生变化，请重新预览再确认");
      }
      const action = await inspectActiveSubmit(true, message.submission);
      if (!action.clicked) throw new Error("没有执行任何页面提交动作");
      const selected = action.candidates.find((candidate) => candidate.selected);
      if (selected?.phase === "progress") {
        return {
          action,
          submission: message.submission,
          task: await client().then((api) => api.task(message.submission.taskId)),
          progressed: true,
        };
      }
      await waitForPageResult(1600);
      const outcome = await detectActiveSubmissionOutcome(message.submission.sourceDomain);
      const submission = await client().then((api) => api.updateSubmission(message.submission.id, {
        status: outcome.status,
        submissionUrl: outcome.url,
        resultMessage: outcome.message,
      }));
      let task = await client().then((api) => api.task(submission.taskId));
      let verification;
      if (["submitted", "pending", "unknown"].includes(submission.status)) {
        const page = await inspectActiveBacklink(submission);
        const verified = await client().then((api) => api.createVerification({
          taskId: submission.taskId,
          submissionId: submission.id,
          sourceUrl: page.sourceUrl,
          targetUrl: page.targetUrl,
          outcome: page.outcome,
          anchorText: page.anchorText,
          linkRel: page.linkRel,
          checkedAt: page.checkedAt,
          message: page.message,
        }));
        task = verified.task;
        verification = verified.verification;
        await setCurrentTask(null);
        return { action, outcome, submission: verified.submission, task, verification, progressed: false };
      }
      await setCurrentTask(null);
      return { action, outcome, submission, task, verification, progressed: false };
    }
    case "OPEN_TASK":
      await chrome.tabs.create({ url: message.task.sourceUrl, active: true });
      await setCurrentTask(message.task);
      return { opened: true };
    case "CREATE_SUBMISSION":
      return client().then((api) => api.createSubmission(message.input));
    case "UPDATE_SUBMISSION": {
      const submissionUrl = await activeUrlForDomain(message.input.submissionUrl, message.submission.sourceDomain);
      const submission = await client().then((api) => api.updateSubmission(message.submission.id, {
        ...message.input,
        submissionUrl,
      }));
      const task = await client().then((api) => api.task(submission.taskId));
      await setCurrentTask(task.status === "completed" || task.status === "failed" || task.status === "skipped" ? null : task);
      return { submission, task };
    }
    case "VERIFY_SUBMISSION": {
      const page = await inspectActiveBacklink(message.submission);
      const result = await client().then((api) => api.createVerification({
        taskId: message.submission.taskId,
        submissionId: message.submission.id,
        sourceUrl: page.sourceUrl,
        targetUrl: page.targetUrl,
        outcome: page.outcome,
        anchorText: page.anchorText,
        linkRel: page.linkRel,
        checkedAt: page.checkedAt,
        message: page.message,
      }));
      await setCurrentTask(result.task.status === "completed" || result.task.status === "failed" || result.task.status === "skipped" ? null : result.task);
      return result;
    }
    case "CREATE_VERIFICATION":
      return client().then((api) => api.createVerification(message.input));
  }
}

async function activeUrlForDomain(providedUrl?: string, expectedDomain?: string): Promise<string> {
  if (providedUrl) {
    if (expectedDomain) assertTaskPage({ sourceDomain: expectedDomain }, providedUrl);
    return providedUrl;
  }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/^https?:/.test(tab.url)) throw new Error("当前标签页不是 HTTP/HTTPS 页面");
  if (expectedDomain) assertTaskPage({ sourceDomain: expectedDomain }, tab.url);
  return tab.url;
}

async function inspectActiveBacklink(submission: { sourceDomain: string; targetUrl: string }) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url || !/^https?:/.test(tab.url)) {
    throw new Error("当前标签页不是可验证的 HTTP/HTTPS 页面");
  }
  assertTaskPage({ sourceDomain: submission.sourceDomain }, tab.url);
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: inspectCurrentPageForBacklink,
    args: [submission.targetUrl],
  });
  const result = results[0]?.result;
  if (!result) throw new Error("页面 Backlink 验证未返回结果");
  return result;
}

async function inspectActiveSubmit(apply: boolean, submission: { sourceDomain: string }) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url || !/^https?:/.test(tab.url)) {
    throw new Error("当前标签页不是可提交的 HTTP/HTTPS 页面");
  }
  assertTaskPage({ sourceDomain: submission.sourceDomain }, tab.url);
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: inspectOrClickSubmitControl,
    args: [apply],
  });
  const result = results[0]?.result;
  if (!result) throw new Error("页面提交控件检查未返回结果");
  return result;
}

async function detectActiveSubmissionOutcome(expectedDomain: string) {
  let lastError: unknown;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab?.id || !tab.url || !/^https?:/.test(tab.url)) {
        throw new Error("提交后页面不可访问");
      }
      assertTaskPage({ sourceDomain: expectedDomain }, tab.url);
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: detectSubmissionOutcome,
      });
      const result = results[0]?.result;
      if (result) return result;
      throw new Error("提交结果识别未返回结果");
    } catch (error) {
      lastError = error;
      if (attempt < 2) await waitForPageResult(700);
    }
  }
  const detail = lastError instanceof Error ? lastError.message : "页面状态未知";
  throw new Error(`提交动作已经触发，但结果页暂时无法识别：${detail}。请从 Submission 历史中人工记录结果`);
}

function submitFingerprint(result: {
  url: string;
  canSubmit: boolean;
  candidates: Array<{ label: string; phase: string; confidence: number; selected: boolean }>;
}): string {
  return JSON.stringify({ url: result.url, canSubmit: result.canSubmit, candidates: result.candidates });
}

function waitForPageResult(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
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

async function inspectActiveForm(
  input: Parameters<typeof inspectOrFillCurrentForm>[0],
  apply: boolean,
  task: Parameters<typeof assertTaskPage>[0],
) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url || !/^https?:/.test(tab.url)) {
    throw new Error("当前标签页不是可处理的 HTTP/HTTPS 页面");
  }
  assertTaskPage(task, tab.url);
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: inspectOrFillCurrentForm,
    args: [input, apply],
  });
  const result = results[0]?.result;
  if (!result) throw new Error("页面表单检查未返回结果");
  return result;
}

function assertTaskPage(task: { sourceDomain: string }, activeUrl: string): void {
  const host = new URL(activeUrl).hostname.toLowerCase().replace(/^www\./, "");
  const expected = task.sourceDomain.toLowerCase().replace(/^www\./, "");
  if (host !== expected && !host.endsWith(`.${expected}`)) {
    throw new Error(`当前页面域名 ${host} 与任务来源 ${expected} 不一致，已停止预填`);
  }
}

function formFingerprint(result: {
  url: string;
  canFill: boolean;
  fields: Array<{ kind: string; label: string; value: string; confidence: number; willFill: boolean; matchesExpected: boolean }>;
}): string {
  return JSON.stringify({ url: result.url, canFill: result.canFill, fields: result.fields });
}
