import type {
  FillFieldKind,
  FormFieldMatch,
  FormFillInput,
  FormFillResult,
} from "../types/domain";

export function inspectOrFillCurrentForm(input: FormFillInput, apply: boolean): FormFillResult {
  type Fillable = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | HTMLElement;
  type Candidate = { element: Fillable; kind: FillFieldKind; confidence: number; label: string; value: string };

  const normalize = (value: string | null | undefined): string => (value || "").trim().toLowerCase();
  const isVisible = (element: Element): boolean => {
    const style = getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0" && element.getClientRects().length > 0;
  };
  const isEnabled = (element: Element): boolean =>
    !element.matches(":disabled") && element.getAttribute("aria-disabled") !== "true";
  const valueOf = (element: Fillable): string => {
    if (element instanceof HTMLInputElement && element.type === "checkbox") {
      return element.checked ? "已勾选" : "";
    }
    if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) {
      return element.value.trim();
    }
    return (element.textContent || "").trim();
  };
  const fieldLabel = (element: Element): string => {
    const nativeLabels = "labels" in element
      ? Array.from((element as HTMLInputElement).labels || []).map((label) => label.textContent || "").join(" ")
      : "";
    const closestLabel = element.closest("label")?.textContent || "";
    return normalize([
      nativeLabels,
      closestLabel,
      element.getAttribute("name"),
      element.getAttribute("id"),
      element.getAttribute("placeholder"),
      element.getAttribute("aria-label"),
      element.getAttribute("data-testid"),
    ].filter(Boolean).join(" "));
  };
  const includesAny = (value: string, terms: string[]): boolean => terms.some((term) => value.includes(term));
  const chooseDescription = (): string =>
    input.project.mediumDescription || input.project.shortDescription || input.project.longDescription || input.project.tagline || "";
  const mappedValue = (kind: FillFieldKind): string => {
    const byKind: Partial<Record<FillFieldKind, string>> = {
      title: input.project.name,
      name: input.project.authorName || "",
      email: input.project.email || "",
      website: input.targetUrl,
      tagline: input.project.tagline || "",
      description: chooseDescription(),
      comment: input.commentDraft || "",
    };
    return byKind[kind] ?? "";
  };
  // category/terms/social 没有统一的项目资料：terms 恒为勾选；category 用项目关键词
  // 匹配下拉选项，匹配不到就作为人工字段展示；social 没有资料，只提示人工填写。
  const resolveValue = (kind: FillFieldKind, element: Fillable): string => {
    if (kind === "terms") return "已勾选";
    if (kind === "social") return "";
    if (kind === "category" && element instanceof HTMLSelectElement) {
      const keywords = (input.project.keywords || []).map(normalize).filter(Boolean);
      const option = Array.from(element.options).find((item) =>
        keywords.some((keyword) => normalize(item.value).includes(keyword) || normalize(item.text).includes(keyword)));
      return option?.text ?? "";
    }
    return mappedValue(kind);
  };
  const classify = (element: Fillable): { kind: FillFieldKind; confidence: number } | null => {
    if (element instanceof HTMLInputElement && element.type === "checkbox") {
      return includesAny(fieldLabel(element), ["terms", "conditions", "agree", "privacy", "policy", "guidelines", "accept", "服务条款", "使用条款", "条款", "同意", "隐私"])
        ? { kind: "terms", confidence: 88 }
        : null;
    }
    const label = fieldLabel(element);
    if (element instanceof HTMLInputElement && element.type === "email") return { kind: "email", confidence: 98 };
    if (includesAny(label, ["product name", "project name", "listing name", "site name", "app name", "产品名称", "项目名称"])) return { kind: "title", confidence: 94 };
    if (includesAny(label, ["website", "web site", "homepage", "site url", "product url", "project url", "link to product", "网址", "网站地址"])) return { kind: "website", confidence: 94 };
    if (includesAny(label, ["twitter", "x.com", "github", "linkedin", "facebook", "instagram", "youtube", "discord", "telegram", "mastodon", "社交", "微博", "推特"])) return { kind: "social", confidence: 80 };
    if (includesAny(label, ["email", "e-mail", "邮箱"])) return { kind: "email", confidence: 92 };
    if (includesAny(label, ["tagline", "tag line", "subtitle", "slogan", "一句话", "标语"])) return { kind: "tagline", confidence: 90 };
    if (includesAny(label, ["description", "about product", "about project", "summary", "details", "介绍", "描述"])) return { kind: "description", confidence: 86 };
    if (includesAny(label, ["comment", "reply", "message", "your thoughts", "评论", "回复", "留言"])) return { kind: "comment", confidence: 92 };
    if (includesAny(label, ["author name", "your name", "display name", "full name", "contact name", "姓名", "作者"])) return { kind: "name", confidence: 90 };
    if (element instanceof HTMLSelectElement && includesAny(label, ["category", "categories", "分类", "类别", "industry", "niche", "topic", "板块"])) return { kind: "category", confidence: 72 };
    if (label === "name" || label.startsWith("name ")) return { kind: input.workflow === "directory" ? "title" : "name", confidence: 68 };
    if ((element instanceof HTMLTextAreaElement || element.getAttribute("contenteditable") === "true") && input.workflow === "blog_comment") return { kind: "comment", confidence: 62 };
    if ((element instanceof HTMLTextAreaElement || element.getAttribute("contenteditable") === "true") && input.workflow === "directory") return { kind: "description", confidence: 58 };
    return null;
  };
  const setNativeValue = (element: Fillable, value: string): boolean => {
    if (element instanceof HTMLInputElement && element.type === "checkbox") {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "checked")?.set;
      if (setter) setter.call(element, true); else element.checked = true;
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
    if (element instanceof HTMLSelectElement) {
      const option = Array.from(element.options).find((item) => normalize(item.value) === normalize(value) || normalize(item.text) === normalize(value));
      if (!option) return false;
      element.value = option.value;
    } else if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
      if (setter) setter.call(element, value); else element.value = value;
    } else {
      element.focus();
      element.textContent = value;
    }
    element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    element.dispatchEvent(new FocusEvent("blur", { bubbles: true }));
    return true;
  };

  const rawElements = Array.from(document.querySelectorAll<Fillable>(
    'input:not([type="hidden"]):not([type="password"]):not([type="checkbox"]):not([type="radio"]):not([type="file"]), textarea, select, [contenteditable="true"], input[type="checkbox"]'
  )).filter((element) => isVisible(element) && isEnabled(element));
  const candidates: Candidate[] = [];
  for (const element of rawElements) {
    const classification = classify(element);
    if (!classification) continue;
    const value = resolveValue(classification.kind, element).trim();
    candidates.push({ element, ...classification, label: fieldLabel(element) || classification.kind, value });
  }

  const warnings: string[] = [];
  const selected: Candidate[] = [];
  const manual: Candidate[] = [];
  for (const kind of ["title", "name", "email", "website", "tagline", "description", "comment", "category", "terms"] as FillFieldKind[]) {
    const matches = candidates.filter((candidate) => candidate.kind === kind).sort((a, b) => b.confidence - a.confidence);
    const best = matches[0];
    if (!best) continue;
    if (kind === "category") {
      const resolved = matches.find((candidate) => candidate.value);
      const unresolved = matches.filter((candidate) => !candidate.value);
      // 匹配到关键词的照常自动选择；没匹配到的全部作为人工字段展示，避免被同置信度规则丢弃。
      if (resolved) selected.push(resolved);
      manual.push(...unresolved);
      continue;
    }
    const second = matches[1];
    if (second && best.confidence === second.confidence) {
      warnings.push(`${kind} 匹配到多个同置信度字段，已停止自动选择`);
      continue;
    }
    selected.push(best);
  }
  manual.push(...candidates.filter((candidate) => candidate.kind === "social"));

  const formRoots = new Set(selected.map((candidate) => candidate.element.closest("form")).filter(Boolean));
  if (formRoots.size > 1) warnings.push("待填写字段分布在多个表单中，请人工确认");
  const hasCaptcha = Boolean(document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], .g-recaptcha, .h-captcha, [data-sitekey], [name*="captcha" i]'));
  if (hasCaptcha) warnings.push("检测到验证码，插件不会自动处理");
  const hasVisiblePassword = Array.from(document.querySelectorAll('input[type="password"]')).some(isVisible);
  if (hasVisiblePassword) warnings.push("检测到可见密码字段，可能存在登录阻断");
  const hasFileUpload = Array.from(document.querySelectorAll('input[type="file"]')).some(isVisible);
  if (hasFileUpload) warnings.push("检测到文件上传字段（Logo/截图等），需要人工上传");
  if (manual.some((candidate) => candidate.kind === "category")) warnings.push("分类下拉未能自动匹配项目关键词，请人工选择");
  if (manual.some((candidate) => candidate.kind === "social")) warnings.push("检测到社交链接字段（Twitter/GitHub 等），插件没有对应资料，请人工填写");
  const safeToApply = formRoots.size <= 1 && !hasCaptcha && !hasVisiblePassword;

  let filledCount = 0;
  let skippedCount = 0;
  let matchedCount = 0;
  const fields: FormFieldMatch[] = [...selected, ...manual].map((candidate) => {
    const existing = valueOf(candidate.element);
    const matchesExpected = Boolean(existing) && normalize(existing) === normalize(candidate.value);
    if (matchesExpected) matchedCount += 1;
    const willFill = !existing && Boolean(candidate.value) && candidate.confidence >= 60;
    let reason = "";
    if (!candidate.value) {
      reason = candidate.kind === "category" ? "未匹配到项目关键词对应的分类，请人工选择" : "插件没有该字段的项目资料，请人工填写";
    } else if (existing) {
      reason = "字段已有内容，不覆盖";
    } else if (candidate.confidence < 60) {
      reason = "字段映射置信度过低";
    }
    if (apply && willFill && safeToApply) {
      if (setNativeValue(candidate.element, candidate.value)) filledCount += 1;
      else { skippedCount += 1; reason = "没有可安全匹配的选项"; }
    } else if (!willFill) {
      skippedCount += 1;
    }
    return {
      kind: candidate.kind,
      label: candidate.label.slice(0, 120),
      confidence: candidate.confidence,
      value: candidate.value,
      willFill,
      matchesExpected,
      reason: reason || undefined,
    };
  });
  const confidence = fields.length ? Math.round(fields.reduce((sum, field) => sum + field.confidence, 0) / fields.length) : 0;
  const canFill = fields.some((field) => field.willFill || field.matchesExpected) && confidence >= 60 && safeToApply;
  return { url: location.href, fields, warnings, confidence, canFill, filledCount, skippedCount, matchedCount };
}
