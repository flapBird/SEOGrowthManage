import type { PageAnalysis, WorkflowType } from "../types/domain";

export function analyzeCurrentDocument(): PageAnalysis {
  const normalize = (value: string | null | undefined): string => (value || "").trim().toLowerCase();
  const descriptor = (element: Element): string =>
    normalize([
      element.getAttribute("name"),
      element.getAttribute("id"),
      element.getAttribute("placeholder"),
      element.getAttribute("aria-label"),
      element.getAttribute("class"),
    ].filter(Boolean).join(" "));
  const matches = (element: Element, terms: string[]): boolean => {
    const value = descriptor(element);
    return terms.some((term) => value.includes(term));
  };

  const forms = Array.from(document.querySelectorAll("form"));
  const inputs = Array.from(document.querySelectorAll("input"));
  const textareas = Array.from(document.querySelectorAll("textarea"));
  const editors = Array.from(document.querySelectorAll('[contenteditable="true"], [role="textbox"]'));
  const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"]'));
  const bodyText = normalize(document.body?.innerText).slice(0, 120_000);

  const websiteFields = inputs.filter((input) => matches(input, ["website", "web site", "homepage", "site url", "url"]));
  const emailFields = inputs.filter((input) => input.type === "email" || matches(input, ["email", "e-mail"]));
  const nameFields = inputs.filter((input) => matches(input, ["author", "display name", "your name", "username", "name"]));
  const commentTextareas = textareas.filter((textarea) => matches(textarea, ["comment", "message", "reply", "content", "body", "description"]));
  const submitButtons = buttons.filter((button) => {
    const value = normalize(`${button.textContent || ""} ${button.getAttribute("value") || ""} ${descriptor(button)}`);
    return ["submit", "post comment", "publish", "send", "reply", "提交", "发布", "评论", "回复"].some((term) => value.includes(term));
  });
  const hasCaptcha = Boolean(document.querySelector([
    'iframe[src*="recaptcha"]',
    'iframe[src*="hcaptcha"]',
    'iframe[src*="turnstile"]',
    ".g-recaptcha",
    ".h-captcha",
    "[data-sitekey]",
    '[name*="captcha"]',
  ].join(",")));
  const requiresLogin = Boolean(document.querySelector('input[type="password"]')) || [
    "log in to comment",
    "login to comment",
    "sign in to comment",
    "you must be logged in",
    "登录后评论",
    "请先登录",
  ].some((term) => bodyText.includes(term));

  const hasCommentForm = commentTextareas.length > 0 || forms.some((form) => {
    const value = normalize(`${descriptor(form)} ${form.textContent || ""}`);
    return ["comment", "reply", "评论", "回复"].some((term) => value.includes(term)) && Boolean(form.querySelector("textarea, [contenteditable=true]"));
  });

  let pageType: WorkflowType | "unknown" = "unknown";
  let confidence = 20;
  const directoryTerms = [
    "submit site",
    "add listing",
    "directory",
    "submit website",
    "submit a product",
    "submit your product",
    "launch your product",
    "add your product",
    "product listing",
    "网站目录",
    "提交网站",
    "提交产品",
  ];
  if (hasCommentForm) {
    pageType = "blog_comment";
    confidence = 70 + (websiteFields.length > 0 ? 12 : 0) + (submitButtons.length > 0 ? 8 : 0);
  } else if (directoryTerms.some((term) => bodyText.includes(term)) || (
    websiteFields.length > 0 &&
    ["submit", "add", "launch", "listing", "提交", "收录"].some((term) => bodyText.includes(term))
  )) {
    pageType = "directory";
    confidence = websiteFields.length > 0 ? 82 : 58;
  } else if (["new topic", "post reply", "forum", "discussion", "发表主题", "论坛"].some((term) => bodyText.includes(term))) {
    pageType = "forum";
    confidence = editors.length + textareas.length > 0 ? 70 : 52;
  } else if (document.querySelector("article") || document.querySelector('[itemtype*="Article"]')) {
    pageType = "article";
    confidence = 45;
  }
  confidence = Math.max(0, Math.min(100, confidence - (hasCaptcha ? 8 : 0) - (requiresLogin ? 5 : 0)));

  const summaryParts = [
    pageType === "unknown" ? "未识别工作流" : `识别为 ${pageType}`,
    hasCommentForm ? "发现评论表单" : "未发现明确评论表单",
    websiteFields.length > 0 ? "存在网站字段" : "没有网站字段",
    hasCaptcha ? "检测到验证码" : "未检测到验证码",
    requiresLogin ? "可能需要登录" : "未发现登录要求",
  ];

  return {
    url: location.href,
    domain: location.hostname,
    title: document.title,
    language: document.documentElement.lang || navigator.language || "unknown",
    pageType,
    confidence,
    summary: summaryParts.join("；"),
    signals: {
      hasCommentForm,
      hasWebsiteField: websiteFields.length > 0,
      hasEmailField: emailFields.length > 0,
      hasNameField: nameFields.length > 0,
      requiresLogin,
      hasCaptcha,
      textareaCount: textareas.length,
      editorCount: editors.length,
      submitButtonCount: submitButtons.length,
    },
    analyzedAt: new Date().toISOString(),
  };
}
