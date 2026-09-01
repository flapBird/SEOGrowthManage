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
  const mappedValue = (kind: FillFieldKind): string => ({
    title: input.project.name,
    name: input.project.authorName || "",
    email: input.project.email || "",
    website: input.targetUrl,
    tagline: input.project.tagline || "",
    description: chooseDescription(),
    comment: input.commentDraft || "",
  })[kind];
  const classify = (element: Fillable): { kind: FillFieldKind; confidence: number } | null => {
    const label = fieldLabel(element);
    if (element instanceof HTMLInputElement && element.type === "email") return { kind: "email", confidence: 98 };
    if (includesAny(label, ["product name", "project name", "listing name", "site name", "app name", "产品名称", "项目名称"])) return { kind: "title", confidence: 94 };
    if (includesAny(label, ["website", "web site", "homepage", "site url", "product url", "project url", "link to product", "网址", "网站地址"])) return { kind: "website", confidence: 94 };
    if (includesAny(label, ["email", "e-mail", "邮箱"])) return { kind: "email", confidence: 92 };
    if (includesAny(label, ["tagline", "tag line", "subtitle", "slogan", "一句话", "标语"])) return { kind: "tagline", confidence: 90 };
    if (includesAny(label, ["description", "about product", "about project", "summary", "details", "介绍", "描述"])) return { kind: "description", confidence: 86 };
    if (includesAny(label, ["comment", "reply", "message", "your thoughts", "评论", "回复", "留言"])) return { kind: "comment", confidence: 92 };
    if (includesAny(label, ["author name", "your name", "display name", "full name", "contact name", "姓名", "作者"])) return { kind: "name", confidence: 90 };
    if (label === "name" || label.startsWith("name ")) return { kind: input.workflow === "directory" ? "title" : "name", confidence: 68 };
    if ((element instanceof HTMLTextAreaElement || element.getAttribute("contenteditable") === "true") && input.workflow === "blog_comment") return { kind: "comment", confidence: 62 };
    if ((element instanceof HTMLTextAreaElement || element.getAttribute("contenteditable") === "true") && input.workflow === "directory") return { kind: "description", confidence: 58 };
    return null;
  };
  const setNativeValue = (element: Fillable, value: string): boolean => {
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
    'input:not([type="hidden"]):not([type="password"]):not([type="checkbox"]):not([type="radio"]):not([type="file"]), textarea, select, [contenteditable="true"]'
  )).filter((element) => isVisible(element) && isEnabled(element));
  const candidates: Candidate[] = [];
  for (const element of rawElements) {
    const classification = classify(element);
    if (!classification) continue;
    const value = mappedValue(classification.kind).trim();
    if (!value) continue;
    candidates.push({ element, ...classification, label: fieldLabel(element) || classification.kind, value });
  }

  const warnings: string[] = [];
  const selected: Candidate[] = [];
  for (const kind of ["title", "name", "email", "website", "tagline", "description", "comment"] as FillFieldKind[]) {
    const matches = candidates.filter((candidate) => candidate.kind === kind).sort((a, b) => b.confidence - a.confidence);
    const best = matches[0];
    if (!best) continue;
    const second = matches[1];
    if (second && best.confidence === second.confidence) {
      warnings.push(`${kind} 匹配到多个同置信度字段，已停止自动选择`);
      continue;
    }
    selected.push(best);
  }

  const formRoots = new Set(selected.map((candidate) => candidate.element.closest("form")).filter(Boolean));
  if (formRoots.size > 1) warnings.push("待填写字段分布在多个表单中，请人工确认");
  const hasCaptcha = Boolean(document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], .g-recaptcha, .h-captcha, [data-sitekey], [name*="captcha" i]'));
  if (hasCaptcha) warnings.push("检测到验证码，插件不会自动处理");
  const hasVisiblePassword = Array.from(document.querySelectorAll('input[type="password"]')).some(isVisible);
  if (hasVisiblePassword) warnings.push("检测到可见密码字段，可能存在登录阻断");
  const safeToApply = formRoots.size <= 1 && !hasCaptcha && !hasVisiblePassword;

  let filledCount = 0;
  let skippedCount = 0;
  let matchedCount = 0;
  const fields: FormFieldMatch[] = selected.map((candidate) => {
    const existing = valueOf(candidate.element);
    const matchesExpected = Boolean(existing) && normalize(existing) === normalize(candidate.value);
    if (matchesExpected) matchedCount += 1;
    const willFill = !existing && candidate.confidence >= 60;
    let reason = "";
    if (existing) reason = "字段已有内容，不覆盖";
    else if (candidate.confidence < 60) reason = "字段映射置信度过低";
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
