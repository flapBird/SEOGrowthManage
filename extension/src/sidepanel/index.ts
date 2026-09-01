import type { PublicSettings, RuntimeRequest, RuntimeResponse } from "../messages";
import type { BacklinkTask, PageAnalysis, Project } from "../types/domain";
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
  toast: byId<HTMLDivElement>("toast"),
};

let currentTask: BacklinkTask | null = null;

byId("save-settings").addEventListener("click", () => void saveConnectionSettings());
byId("test-connection").addEventListener("click", () => void testConnection());
byId("refresh-projects").addEventListener("click", () => void loadProjects());
byId("next-task").addEventListener("click", () => void claimNextTask());
byId("analyze-page").addEventListener("click", () => void analyzePage());
elements.projectSelect.addEventListener("change", () => {
  elements.nextTask.disabled = !elements.projectSelect.value;
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
    renderTask(currentTask);
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
  if (!task) {
    elements.taskContent.className = "empty";
    elements.taskContent.textContent = "当前没有任务";
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
      ${task.status === "processing" ? '<button id="prepare-task" class="button">标记已准备</button>' : ""}
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
  const prepareButton = document.getElementById("prepare-task");
  prepareButton?.addEventListener("click", () => void updateCurrentTask("prepared", "页面已检查，等待后续提交"));
  byId("skip-task").addEventListener("click", () => void updateCurrentTask("skipped", "用户在插件中跳过任务"));
}

async function updateCurrentTask(
  status: "prepared" | "skipped",
  note: string,
): Promise<void> {
  if (!currentTask) return;
  try {
    const updated = await send<BacklinkTask>({
      type: "UPDATE_TASK",
      taskId: currentTask.id,
      input: { status, note },
    });
    currentTask = status === "skipped" ? null : updated;
    renderTask(currentTask);
    showToast(status === "skipped" ? "任务已跳过并释放" : "任务已标记为已准备");
  } catch (error) {
    showError(error);
  }
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
