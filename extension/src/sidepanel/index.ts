import type { PublicSettings, RuntimeRequest, RuntimeResponse } from "../messages";
import type {
  BacklinkTask,
  FillAndRecordResult,
  FormFillInput,
  FormFillResult,
  PageAnalysis,
  Project,
  Submission,
  SubmissionActionResult,
  SubmissionCheck,
  UpdateSubmissionInput,
  SubmitControlResult,
  SubmitExecutionResult,
  VerificationResult,
} from "../types/domain";
import "./styles.css";

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) throw new Error("Side Panel 根节点不存在");

app.innerHTML = `
  <main class="shell">
    <header class="header">
      <div class="brand"><div class="logo">BL</div><div><h1>Backlink Assistant</h1><p class="muted">浏览器执行端</p></div></div>
      <span id="connection-dot" class="status-dot" title="尚未连接"></span>
    </header>
    <div class="stack">
      <section class="card">
        <div class="card-head"><div><h2>云端连接</h2><p class="muted">配置 SEO Growth Console API</p></div><span id="token-badge" class="badge warning">未配置</span></div>
        <div class="fields">
          <label>服务器地址<input id="base-url" type="url" placeholder="https://seo.example.com" /></label>
          <label>Extension Token<input id="api-token" type="password" placeholder="留空则保留现有 Token" autocomplete="off" /></label>
        </div>
        <div class="actions"><button id="save-settings" class="button primary">保存配置</button><button id="test-connection" class="button">测试连接</button></div>
      </section>
      <section class="card">
        <div class="card-head"><div><h2>任务队列</h2><p class="muted">从云端领取插件任务</p></div><button id="refresh-projects" class="button">刷新项目</button></div>
        <label>当前项目<select id="project-select"><option value="">请先加载项目</option></select></label>
        <div class="actions"><button id="next-task" class="button primary" disabled>领取下一任务</button></div>
        <div id="task-content" class="empty">当前没有任务</div>
      </section>
      <section class="card">
        <div class="card-head"><div><h2>当前页面</h2><p class="muted">只检测页面，不会点击提交</p></div><button id="analyze-page" class="button primary">分析页面</button></div>
        <div id="analysis-content" class="empty">尚未分析当前页面</div>
      </section>
      <section class="card">
        <div class="card-head"><div><h2>安全预填充</h2><p class="muted">先预览映射；确认后只填写字段，绝不点击 Submit</p></div><span class="badge warning">人工确认</span></div>
        <label>评论 / 留言草稿<textarea id="comment-draft" rows="4" placeholder="评论工作流请先填写；Directory 会优先使用项目介绍"></textarea></label>
        <div class="actions"><button id="preview-form" class="button" disabled>预览字段</button><button id="fill-form" class="button primary" disabled>确认填入（不会提交）</button></div>
        <div id="fill-content" class="empty">请先领取任务并打开来源页面</div>
      </section>
      <section class="card">
        <div class="card-head"><div><h2>提交结果与验证</h2><p class="muted">只在按钮预览和二次确认后点击网页 Submit</p></div><button id="refresh-submissions" class="button">刷新历史</button></div>
        <div id="submission-content" class="empty">尚未选择 Submission</div>
        <div class="submit-control">
          <div class="actions"><button id="preview-submit" class="button" disabled>识别提交按钮</button><button id="confirm-submit" class="button primary" disabled>Confirm Submit</button></div>
          <div id="submit-content" class="empty">先完成安全预填，再识别页面提交按钮</div>
        </div>
        <div class="fields result-fields">
          <label>人工确认结果<select id="submission-status">
            <option value="submitted">已提交</option>
            <option value="pending">待审核</option>
            <option value="duplicate">重复提交</option>
            <option value="rejected">已拒绝</option>
            <option value="failed">提交失败</option>
            <option value="unknown">结果不明确</option>
          </select></label>
          <label>结果备注<textarea id="submission-note" rows="2" placeholder="例如：提交后显示 awaiting review"></textarea></label>
        </div>
        <div class="actions"><button id="save-submission-result" class="button" disabled>保存提交结果</button><button id="verify-backlink" class="button primary" disabled>验证当前页面外链</button></div>
        <p class="summary">验证只扫描当前页面中是否存在精确 Target URL，不会主动请求其他网站，也不会创建虚假的 Published 记录。</p>
        <div class="history-head"><strong>最近 Submission</strong><span class="muted">点击选择后可继续验证</span></div>
        <div id="submission-history" class="empty">选择项目后加载</div>
      </section>
    </div>
    <div id="toast" class="toast" hidden></div>
  </main>
`;

const elements = {
  baseUrl: byId<HTMLInputElement>("base-url"),
  apiToken: byId<HTMLInputElement>("api-token"),
  tokenBadge: byId<HTMLSpanElement>("token-badge"),
  connectionDot: byId<HTMLSpanElement>("connection-dot"),
  projectSelect: byId<HTMLSelectElement>("project-select"),
  nextTask: byId<HTMLButtonElement>("next-task"),
  taskContent: byId<HTMLDivElement>("task-content"),
  analysisContent: byId<HTMLDivElement>("analysis-content"),
  commentDraft: byId<HTMLTextAreaElement>("comment-draft"),
  previewForm: byId<HTMLButtonElement>("preview-form"),
  fillForm: byId<HTMLButtonElement>("fill-form"),
  fillContent: byId<HTMLDivElement>("fill-content"),
  submissionContent: byId<HTMLDivElement>("submission-content"),
  previewSubmit: byId<HTMLButtonElement>("preview-submit"),
  confirmSubmit: byId<HTMLButtonElement>("confirm-submit"),
  submitContent: byId<HTMLDivElement>("submit-content"),
  submissionStatus: byId<HTMLSelectElement>("submission-status"),
  submissionNote: byId<HTMLTextAreaElement>("submission-note"),
  saveSubmissionResult: byId<HTMLButtonElement>("save-submission-result"),
  verifyBacklink: byId<HTMLButtonElement>("verify-backlink"),
  submissionHistory: byId<HTMLDivElement>("submission-history"),
  toast: byId<HTMLDivElement>("toast"),
};

let currentTask: BacklinkTask | null = null;
let lastFillPreview: FormFillResult | null = null;
let lastSubmissionCheck: SubmissionCheck | null = null;
let currentSubmission: Submission | null = null;
let recentSubmissions: Submission[] = [];
let lastSubmitPreview: SubmitControlResult | null = null;

byId("save-settings").addEventListener("click", () => void saveConnectionSettings());
byId("test-connection").addEventListener("click", () => void testConnection());
byId("refresh-projects").addEventListener("click", () => void loadProjects());
byId("next-task").addEventListener("click", () => void claimNextTask());
byId("analyze-page").addEventListener("click", () => void analyzePage());
elements.previewForm.addEventListener("click", () => void previewForm());
elements.fillForm.addEventListener("click", () => void fillForm());
byId("refresh-submissions").addEventListener("click", () => void loadSubmissionHistory(selectedProjectId(), true));
elements.saveSubmissionResult.addEventListener("click", () => void saveSubmissionResult());
elements.verifyBacklink.addEventListener("click", () => void verifyBacklink());
elements.previewSubmit.addEventListener("click", () => void previewSubmit());
elements.confirmSubmit.addEventListener("click", () => void confirmSubmit());
elements.commentDraft.addEventListener("input", () => {
  if (!lastFillPreview) return;
  lastFillPreview = null;
  elements.fillForm.disabled = true;
  elements.fillContent.className = "empty";
  elements.fillContent.textContent = "草稿已变化，请重新预览字段";
});
elements.projectSelect.addEventListener("change", () => {
  elements.nextTask.disabled = !elements.projectSelect.value;
  const projectId = selectedProjectId();
  if (currentSubmission && currentSubmission.projectId !== projectId) {
    currentSubmission = null;
    renderSubmission(null);
  }
  void loadSubmissionHistory(projectId, false);
});

void initialize();

async function initialize(): Promise<void> {
  const settings = await send<PublicSettings>({ type: "GET_SETTINGS" });
  elements.baseUrl.value = settings.baseUrl;
  updateSettingsState(settings);
  currentTask = await send<BacklinkTask | null>({ type: "GET_CURRENT_TASK" });
  if (currentTask && settings.baseUrl && settings.hasApiToken) {
    try {
      currentTask = await send<BacklinkTask>({ type: "GET_TASK", taskId: currentTask.id });
      if (currentTask.status === "processing") {
        currentTask = await send<BacklinkTask>({
          type: "UPDATE_TASK",
          taskId: currentTask.id,
          input: { status: "processing" },
        });
      }
    } catch {
      currentTask = null;
      await send({ type: "SET_CURRENT_TASK", task: null });
    }
  }
  renderTask(currentTask);
  if (settings.baseUrl && settings.hasApiToken) {
    await loadProjects(false);
    if (currentTask) {
      elements.projectSelect.value = String(currentTask.projectId);
      const submissions = await send<Submission[]>({ type: "GET_SUBMISSIONS", taskId: currentTask.id, limit: 10 });
      currentSubmission = submissions[0] || null;
      renderSubmission(currentSubmission);
      await loadSubmissionHistory(currentTask.projectId, false);
    }
  }
}

async function saveConnectionSettings(): Promise<void> {
  try {
    const baseUrl = elements.baseUrl.value.trim();
    await ensureHostPermission(baseUrl);
    const settings = await send<PublicSettings>({
      type: "SAVE_SETTINGS",
      baseUrl,
      apiToken: elements.apiToken.value.trim() || undefined,
    });
    elements.apiToken.value = "";
    updateSettingsState(settings);
    showToast("服务器配置已保存");
  } catch (error) {
    showError(error);
  }
}

async function testConnection(): Promise<void> {
  try {
    const result = await send<{ connected: true; server: string }>({ type: "TEST_CONNECTION" });
    elements.connectionDot.classList.add("online");
    elements.connectionDot.title = `已连接 ${result.server}`;
    showToast("云端 API 连接成功");
  } catch (error) {
    elements.connectionDot.classList.remove("online");
    showError(error);
  }
}

async function loadProjects(showSuccess = true): Promise<void> {
  try {
    const projects = await send<Project[]>({ type: "GET_PROJECTS" });
    renderProjects(projects);
    if (showSuccess) showToast(`已加载 ${projects.length} 个项目`);
  } catch (error) {
    renderProjects([]);
    showError(error);
  }
}

async function claimNextTask(): Promise<void> {
  const projectId = Number(elements.projectSelect.value);
  if (!projectId) return;
  try {
    elements.nextTask.disabled = true;
    currentTask = await send<BacklinkTask>({ type: "CLAIM_NEXT_TASK", projectId });
    currentSubmission = null;
    renderTask(currentTask);
    renderSubmission(null);
    await loadSubmissionHistory(projectId, false);
    showToast(`已领取任务 #${currentTask.id}`);
  } catch (error) {
    showError(error);
  } finally {
    elements.nextTask.disabled = !elements.projectSelect.value;
  }
}

async function analyzePage(): Promise<void> {
  try {
    await ensureActiveTabPermission();
    elements.analysisContent.innerHTML = '<div class="empty">正在分析…</div>';
    const analysis = await send<PageAnalysis>({ type: "ANALYZE_ACTIVE_TAB" });
    renderAnalysis(analysis);
  } catch (error) {
    elements.analysisContent.innerHTML = '<div class="empty">分析失败</div>';
    showError(error);
  }
}

function renderProjects(projects: Project[]): void {
  elements.projectSelect.innerHTML = projects.length
    ? '<option value="">选择项目</option>' + projects.map((project) => `<option value="${project.id}">${escapeHtml(project.name)} · ${escapeHtml(project.website)}</option>`).join("")
    : '<option value="">没有可用项目</option>';
  elements.nextTask.disabled = true;
}

function renderTask(task: BacklinkTask | null): void {
  elements.previewForm.disabled = !task;
  elements.fillForm.disabled = true;
  lastFillPreview = null;
  lastSubmissionCheck = null;
  if (!task) {
    elements.taskContent.className = "empty";
    elements.taskContent.textContent = "当前没有任务";
    elements.fillContent.className = "empty";
    elements.fillContent.textContent = "请先领取任务并打开来源页面";
    return;
  }
  elements.taskContent.className = "";
  elements.taskContent.innerHTML = `
    <div class="details">
      <div class="detail"><span>任务</span><strong>#${task.id} · ${escapeHtml(task.workflow)}</strong></div>
      <div class="detail"><span>状态</span><strong><span class="badge">${escapeHtml(task.status)}</span></strong></div>
      <div class="detail"><span>来源</span><strong>${escapeHtml(task.sourceDomain)}</strong></div>
      <div class="detail"><span>目标</span><strong>${escapeHtml(task.targetUrl)}</strong></div>
    </div>
    <div class="actions">
      <button id="open-task" class="button primary">打开任务页面</button>
      <button id="skip-task" class="button">跳过任务</button>
    </div>
  `;
  byId("open-task").addEventListener("click", async () => {
    try {
      await send({ type: "OPEN_TASK", task });
      showToast("任务页面已打开");
    } catch (error) {
      showError(error);
    }
  });
  byId("skip-task").addEventListener("click", () => void updateCurrentTask("skipped", "用户在插件中跳过任务"));
}

async function updateCurrentTask(
  status: "skipped",
  note: string,
): Promise<void> {
  if (!currentTask) return;
  try {
    const updated = await send<BacklinkTask>({
      type: "UPDATE_TASK",
      taskId: currentTask.id,
      input: { status, note },
    });
    currentTask = null;
    renderTask(currentTask);
    showToast("任务已跳过并释放");
  } catch (error) {
    showError(error);
  }
}

function currentFillInput(): FormFillInput {
  if (!currentTask) throw new Error("请先领取插件任务");
  return {
    workflow: currentTask.workflow,
    project: currentTask.project,
    targetUrl: currentTask.targetUrl,
    commentDraft: elements.commentDraft.value.trim() || undefined,
  };
}

async function previewForm(): Promise<void> {
  if (!currentTask) return;
  try {
    await ensureActiveTabPermission();
    elements.fillContent.className = "empty";
    elements.fillContent.textContent = "正在检查可填写字段…";
    lastFillPreview = await send<FormFillResult>({ type: "PREVIEW_FORM", input: currentFillInput(), task: currentTask });
    lastSubmissionCheck = await send<SubmissionCheck>({
      type: "CHECK_SUBMISSIONS",
      projectId: currentTask.projectId,
      sourceUrl: lastFillPreview.url,
    });
    renderFillPreview(lastFillPreview, lastSubmissionCheck);
    elements.fillForm.disabled = !lastFillPreview.canFill;
  } catch (error) {
    elements.fillContent.className = "empty";
    elements.fillContent.textContent = "字段预览失败";
    showError(error);
  }
}

async function fillForm(): Promise<void> {
  if (!currentTask || !lastFillPreview?.canFill) return;
  try {
    elements.fillForm.disabled = true;
    const result = await send<FillAndRecordResult>({
      type: "FILL_FORM",
      input: currentFillInput(),
      task: currentTask,
      preview: lastFillPreview,
    });
    currentTask = result.task;
    currentSubmission = result.submission;
    renderTask(currentTask);
    renderFillCompletion(result);
    renderSubmission(currentSubmission);
    await loadSubmissionHistory(currentSubmission.projectId, false);
    showToast(`已填写 ${result.fill.filledCount} 个字段，并记录 Submission #${result.submission.id}`);
  } catch (error) {
    elements.fillForm.disabled = false;
    showError(error);
  }
}

function renderFillPreview(preview: FormFillResult, check: SubmissionCheck): void {
  const warnings = [
    ...preview.warnings,
    ...(check.exactSubmissionCount ? [`当前 URL 已有 ${check.exactSubmissionCount} 次 Submission`] : []),
    ...(check.domainSubmissionCount ? [`当前域名已有 ${check.domainSubmissionCount} 次 Submission`] : []),
    ...(check.domainBacklinkCount ? [`当前域名已有 ${check.domainBacklinkCount} 条正式外链`] : []),
  ];
  elements.fillContent.className = "";
  elements.fillContent.innerHTML = `
    <div class="details">
      <div class="detail"><span>映射置信度</span><strong>${preview.confidence}%</strong></div>
      ${preview.fields.map((field) => `<div class="field-preview"><div><strong>${escapeHtml(field.kind)}</strong><span>${escapeHtml(field.label)}</span></div><code>${escapeHtml(field.value)}</code><small>${field.matchesExpected ? "已有目标值" : field.willFill ? `将填入 · ${field.confidence}%` : escapeHtml(field.reason || "跳过")}</small></div>`).join("")}
    </div>
    ${warnings.length ? `<div class="warning-list">${warnings.map((warning) => `<p>⚠ ${escapeHtml(warning)}</p>`).join("")}</div>` : ""}
    ${preview.canFill ? '<p class="summary">确认填入只会写入上面列出的空字段；现有内容不会覆盖，页面提交按钮不会被点击。</p>' : '<p class="summary danger-text">当前页面不满足安全填入条件，请人工处理。</p>'}
  `;
}

function renderFillCompletion(result: FillAndRecordResult): void {
  elements.fillContent.className = "";
  elements.fillContent.innerHTML = `<p class="summary">已安全填入 ${result.fill.filledCount} 个字段，${result.fill.matchedCount} 个字段原本已有目标值。Submission #${result.submission.id} 状态为 prepared；页面尚未提交。</p>`;
}

function selectedProjectId(): number | undefined {
  const value = Number(elements.projectSelect.value || currentSubmission?.projectId || currentTask?.projectId);
  return value || undefined;
}

async function loadSubmissionHistory(projectId?: number, showSuccess = false): Promise<void> {
  if (!projectId) {
    recentSubmissions = [];
    renderSubmissionHistory();
    return;
  }
  try {
    recentSubmissions = await send<Submission[]>({ type: "GET_SUBMISSIONS", projectId, limit: 20 });
    renderSubmissionHistory();
    if (showSuccess) showToast(`已加载 ${recentSubmissions.length} 条 Submission`);
  } catch (error) {
    recentSubmissions = [];
    renderSubmissionHistory();
    showError(error);
  }
}

function renderSubmissionHistory(): void {
  if (!recentSubmissions.length) {
    elements.submissionHistory.className = "empty";
    elements.submissionHistory.textContent = "当前项目还没有 Submission";
    return;
  }
  elements.submissionHistory.className = "history-list";
  elements.submissionHistory.innerHTML = recentSubmissions.map((submission) => `
    <article class="history-item ${currentSubmission?.id === submission.id ? "selected" : ""}">
      <div><strong>#${submission.id} · ${escapeHtml(submission.status)}</strong><span>${escapeHtml(submission.sourceDomain)}</span><small>${escapeHtml(formatTime(submission.updatedAt))}${submission.backlinkRecordId ? ` · Backlink #${submission.backlinkRecordId}` : ""}</small></div>
      <button class="button select-submission" data-submission-id="${submission.id}">选择</button>
    </article>
  `).join("");
  elements.submissionHistory.querySelectorAll<HTMLButtonElement>(".select-submission").forEach((button) => {
    button.addEventListener("click", () => {
      currentSubmission = recentSubmissions.find((item) => item.id === Number(button.dataset.submissionId)) || null;
      renderSubmission(currentSubmission);
      renderSubmissionHistory();
    });
  });
}

function renderSubmission(submission: Submission | null): void {
  const canUpdate = Boolean(submission && submission.status !== "published" && submission.status !== "removed");
  const canVerify = Boolean(submission && submission.status !== "prepared");
  lastSubmitPreview = null;
  elements.previewSubmit.disabled = !submission || submission.status !== "prepared";
  elements.confirmSubmit.disabled = true;
  elements.submitContent.className = "empty";
  elements.submitContent.textContent = submission?.status === "prepared"
    ? "点击“识别提交按钮”，确认插件准备点击的控件"
    : "只有 prepared Submission 可以触发页面 Submit；其他状态可人工记录或验证";
  elements.saveSubmissionResult.disabled = !canUpdate;
  elements.verifyBacklink.disabled = !canVerify;
  if (!submission) {
    elements.submissionContent.className = "empty";
    elements.submissionContent.textContent = "完成安全预填或从历史中选择一条 Submission";
    return;
  }
  elements.submissionContent.className = "details submission-current";
  elements.submissionContent.innerHTML = `
    <div class="detail"><span>Submission</span><strong>#${submission.id}</strong></div>
    <div class="detail"><span>状态</span><strong><span class="badge ${submission.status === "published" ? "success" : submission.status === "failed" || submission.status === "rejected" || submission.status === "removed" ? "danger" : "warning"}">${escapeHtml(submission.status)}</span></strong></div>
    <div class="detail"><span>实际页面</span><strong>${escapeHtml(submission.submissionUrl || submission.sourceUrl)}</strong></div>
    <div class="detail"><span>正式 Backlink</span><strong>${submission.backlinkRecordId ? `#${submission.backlinkRecordId}` : "尚未创建"}</strong></div>
  `;
  if (canUpdate && ["submitted", "pending", "duplicate", "rejected", "failed", "unknown"].includes(submission.status)) {
    elements.submissionStatus.value = submission.status;
  } else if (submission.status === "prepared") {
    elements.submissionStatus.value = "submitted";
  }
  elements.submissionNote.value = submission.note || "";
}

async function previewSubmit(): Promise<void> {
  if (!currentSubmission || currentSubmission.status !== "prepared") return;
  try {
    await ensureActiveTabPermission();
    elements.submitContent.className = "empty";
    elements.submitContent.textContent = "正在识别安全提交控件…";
    lastSubmitPreview = await send<SubmitControlResult>({
      type: "PREVIEW_SUBMIT",
      submission: currentSubmission,
    });
    renderSubmitPreview(lastSubmitPreview);
    elements.confirmSubmit.disabled = !lastSubmitPreview.canSubmit;
  } catch (error) {
    lastSubmitPreview = null;
    elements.confirmSubmit.disabled = true;
    elements.submitContent.className = "empty";
    elements.submitContent.textContent = "提交控件识别失败";
    showError(error);
  }
}

function renderSubmitPreview(preview: SubmitControlResult): void {
  const selected = preview.candidates.find((candidate) => candidate.selected);
  elements.submitContent.className = "submit-preview";
  elements.submitContent.innerHTML = `
    ${preview.candidates.map((candidate) => `<div class="submit-candidate ${candidate.selected ? "selected" : ""}"><div><strong>${escapeHtml(candidate.label)}</strong><span class="badge ${candidate.phase === "final" ? "warning" : ""}">${candidate.phase === "final" ? "最终提交" : "推进步骤"}</span></div><small>${candidate.confidence}%${candidate.reason ? ` · ${escapeHtml(candidate.reason)}` : ""}</small></div>`).join("") || '<div class="empty">没有候选按钮</div>'}
    ${preview.warnings.length ? `<div class="warning-list">${preview.warnings.map((warning) => `<p>⚠ ${escapeHtml(warning)}</p>`).join("")}</div>` : ""}
    ${selected ? `<p class="summary">Confirm Submit 将只点击“${escapeHtml(selected.label)}”。点击后才会识别结果并回写云端。</p>` : '<p class="summary danger-text">没有唯一且足够可信的按钮，已禁止执行。</p>'}
  `;
}

async function confirmSubmit(): Promise<void> {
  if (!currentSubmission || !lastSubmitPreview?.canSubmit) return;
  const selected = lastSubmitPreview.candidates.find((candidate) => candidate.selected);
  if (!selected) return;
  const accepted = window.confirm(
    selected.phase === "progress"
      ? `确认点击“${selected.label}”推进到下一步？这不会标记为已提交。`
      : `确认点击网页上的“${selected.label}”执行最终提交？该操作可能无法撤销。`,
  );
  if (!accepted) return;
  try {
    elements.confirmSubmit.disabled = true;
    const result = await send<SubmitExecutionResult>({
      type: "CONFIRM_SUBMIT",
      submission: currentSubmission,
      preview: lastSubmitPreview,
    });
    currentSubmission = result.submission;
    currentTask = ["completed", "failed", "skipped"].includes(result.task.status) ? null : result.task;
    if (result.progressed) {
      lastSubmitPreview = null;
      elements.confirmSubmit.disabled = true;
      elements.submitContent.className = "submit-preview";
      elements.submitContent.innerHTML = '<p class="summary">已推进到下一步，Submission 仍为 prepared。请检查新页面，必要时再次预填和识别提交按钮。</p>';
      showToast(`已点击“${selected.label}”，请继续处理下一步`);
      return;
    }
    renderTask(currentTask);
    renderSubmission(currentSubmission);
    elements.submitContent.className = "submit-preview";
    elements.submitContent.innerHTML = `<p class="summary">页面动作已执行。结果：${escapeHtml(result.outcome?.message || "未识别")}；Submission 状态：${escapeHtml(currentSubmission.status)}${result.verification?.outcome === "active" ? `；已验证 Backlink #${currentSubmission.backlinkRecordId}` : ""}。</p>`;
    await loadSubmissionHistory(currentSubmission.projectId, false);
    showToast(result.verification?.outcome === "active" ? "提交并验证成功" : `提交结果：${currentSubmission.status}`);
  } catch (error) {
    elements.confirmSubmit.disabled = false;
    showError(error);
  }
}

async function saveSubmissionResult(): Promise<void> {
  if (!currentSubmission) return;
  try {
    await ensureActiveTabPermission();
    elements.saveSubmissionResult.disabled = true;
    const status = elements.submissionStatus.value as UpdateSubmissionInput["status"];
    const result = await send<SubmissionActionResult>({
      type: "UPDATE_SUBMISSION",
      submission: currentSubmission,
      input: {
        status,
        resultMessage: `用户人工确认提交结果：${status}`,
        note: elements.submissionNote.value.trim() || undefined,
      },
    });
    currentSubmission = result.submission;
    currentTask = ["completed", "failed", "skipped"].includes(result.task.status) ? null : result.task;
    renderTask(currentTask);
    renderSubmission(currentSubmission);
    await loadSubmissionHistory(currentSubmission.projectId, false);
    showToast(`Submission #${currentSubmission.id} 已更新为 ${currentSubmission.status}`);
  } catch (error) {
    renderSubmission(currentSubmission);
    showError(error);
  }
}

async function verifyBacklink(): Promise<void> {
  if (!currentSubmission || currentSubmission.status === "prepared") return;
  try {
    await ensureActiveTabPermission();
    elements.verifyBacklink.disabled = true;
    const result = await send<VerificationResult>({ type: "VERIFY_SUBMISSION", submission: currentSubmission });
    currentSubmission = result.submission;
    currentTask = ["completed", "failed", "skipped"].includes(result.task.status) ? null : result.task;
    renderTask(currentTask);
    renderSubmission(currentSubmission);
    await loadSubmissionHistory(currentSubmission.projectId, false);
    const message = result.verification.outcome === "active"
      ? `验证成功，已创建/关联 Backlink #${result.submission.backlinkRecordId}`
      : `验证结果：${result.verification.outcome}，未创建正式 Backlink`;
    showToast(message, result.verification.outcome !== "active");
  } catch (error) {
    renderSubmission(currentSubmission);
    showError(error);
  }
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN", { hour12: false });
}

function renderAnalysis(analysis: PageAnalysis): void {
  const confidenceClass = analysis.confidence < 50 ? "danger" : analysis.confidence < 75 ? "warning" : "";
  elements.analysisContent.className = "";
  elements.analysisContent.innerHTML = `
    <div class="details">
      <div class="detail"><span>页面类型</span><strong><span class="badge ${confidenceClass}">${escapeHtml(analysis.pageType)}</span></strong></div>
      <div class="detail"><span>置信度</span><strong>${analysis.confidence}%</strong></div>
      <div class="detail"><span>评论表单</span><strong>${yesNo(analysis.signals.hasCommentForm)}</strong></div>
      <div class="detail"><span>网站字段</span><strong>${yesNo(analysis.signals.hasWebsiteField)}</strong></div>
      <div class="detail"><span>登录状态</span><strong>${loginStateLabel(analysis.signals.loginState)}</strong></div>
      <div class="detail"><span>账号要求</span><strong>${accountRequirementLabel(analysis.signals.accountRequirement)}</strong></div>
      <div class="detail"><span>登录阻断</span><strong>${yesNo(analysis.signals.hasLoginBarrier)}</strong></div>
      <div class="detail"><span>验证码</span><strong>${yesNo(analysis.signals.hasCaptcha)}</strong></div>
      <div class="detail"><span>文本区域/编辑器</span><strong>${analysis.signals.textareaCount} / ${analysis.signals.editorCount}</strong></div>
    </div>
    <p class="summary">${escapeHtml(analysis.summary)}</p>
  `;
}

function updateSettingsState(settings: PublicSettings): void {
  elements.tokenBadge.textContent = settings.hasApiToken ? "Token 已配置" : "未配置";
  elements.tokenBadge.className = settings.hasApiToken ? "badge" : "badge warning";
}

async function ensureHostPermission(baseUrl: string): Promise<void> {
  const url = new URL(baseUrl);
  const pattern = `${url.protocol}//${url.host}/*`;
  const granted = await chrome.permissions.contains({ origins: [pattern] }) ||
    await chrome.permissions.request({ origins: [pattern] });
  if (!granted) throw new Error("需要服务器域名访问权限才能连接 API");
}

async function ensureActiveTabPermission(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/^https?:/.test(tab.url)) throw new Error("当前页面无法分析");
  const url = new URL(tab.url);
  const pattern = `${url.protocol}//${url.host}/*`;
  const granted = await chrome.permissions.contains({ origins: [pattern] }) ||
    await chrome.permissions.request({ origins: [pattern] });
  if (!granted) throw new Error("需要当前网站访问权限才能分析页面");
}

async function send<T = unknown>(message: RuntimeRequest): Promise<T> {
  const response = await chrome.runtime.sendMessage<RuntimeRequest, RuntimeResponse<T>>(message);
  if (!response.ok) throw new Error(response.error);
  return response.data;
}

function byId<T extends HTMLElement = HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`缺少界面元素: ${id}`);
  return element as T;
}

function showToast(message: string, error = false): void {
  elements.toast.textContent = message;
  elements.toast.className = error ? "toast error" : "toast";
  elements.toast.hidden = false;
  window.setTimeout(() => { elements.toast.hidden = true; }, 3500);
}

function showError(error: unknown): void {
  showToast(error instanceof Error ? error.message : "发生未知错误", true);
}

function yesNo(value: boolean): string {
  return value ? "是" : "否";
}

function loginStateLabel(value: PageAnalysis["signals"]["loginState"]): string {
  return value === "authenticated" ? "已登录" : value === "unauthenticated" ? "未登录" : "未知";
}

function accountRequirementLabel(value: PageAnalysis["signals"]["accountRequirement"]): string {
  return value === "required" ? "需要账号" : value === "not_required" ? "无需账号" : "未知";
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character] || character);
}
