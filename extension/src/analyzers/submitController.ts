import type {
  SubmissionOutcomeDetection,
  SubmitButtonCandidate,
  SubmitControlResult,
} from "../types/domain";

export function inspectOrClickSubmitControl(apply: boolean): SubmitControlResult {
  type CandidateElement = { element: HTMLElement; candidate: SubmitButtonCandidate };
  const visible = (element: HTMLElement): boolean => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0"
      && rect.width > 0 && rect.height > 0;
  };
  const labelFor = (element: HTMLElement): string => {
    const input = element as HTMLInputElement;
    return (element.getAttribute("aria-label") || input.value || element.textContent || "")
      .trim().replace(/\s+/g, " ").slice(0, 160);
  };
  const classify = (label: string, element: HTMLElement): SubmitButtonCandidate => {
    const normalized = label.toLowerCase();
    const blocked = /(delete|remove|cancel|search|subscribe|unsubscribe|login|log in|sign in|reset|back|删除|移除|取消|搜索|订阅|登录|返回)/i.test(normalized);
    if (blocked) return { label, phase: "final", confidence: 0, selected: false, reason: "危险或非提交操作" };
    if (/(next|continue|get started|start now|下一步|继续|开始)/i.test(normalized)) {
      return { label, phase: "progress", confidence: 78, selected: false };
    }
    if (/(post\s+(comment|reply)|submit\s+(comment|review|product|listing)|publish|launch|add\s+(product|listing)|发表评论|提交评论|发布|上线)/i.test(normalized)) {
      return { label, phase: "final", confidence: 96, selected: false };
    }
    if (/^(submit|send|reply|post|提交|发送|回复)$/i.test(normalized)) {
      return { label, phase: "final", confidence: 88, selected: false };
    }
    const input = element as HTMLInputElement;
    if (input.type === "submit") {
      return { label: label || "Submit", phase: "final", confidence: 62, selected: false, reason: "仅依据 submit 类型识别" };
    }
    return { label: label || "未命名按钮", phase: "final", confidence: 0, selected: false, reason: "不是已知提交动作" };
  };
  const elements = Array.from(document.querySelectorAll<HTMLElement>(
    'button, input[type="submit"], input[type="button"], [role="button"]',
  )).filter((element) => visible(element) && !(element as HTMLButtonElement).disabled);
  const ranked: CandidateElement[] = elements
    .map((element) => ({ element, candidate: classify(labelFor(element), element) }))
    .filter(({ candidate }) => candidate.confidence > 0)
    .sort((a, b) => b.candidate.confidence - a.candidate.confidence);
  const top = ranked[0];
  const ambiguous = Boolean(top && ranked[1] && ranked[1].candidate.confidence === top.candidate.confidence);
  if (top && !ambiguous && top.candidate.confidence >= 70) top.candidate.selected = true;
  const warnings: string[] = [];
  if (!ranked.length) warnings.push("没有识别到安全的提交或下一步按钮");
  if (ambiguous) warnings.push("存在多个同等置信度按钮，无法安全选择");
  if (top?.candidate.phase === "progress") warnings.push("该按钮只推进多步骤表单，不会把 Submission 标记为已提交");
  const canSubmit = Boolean(top?.candidate.selected);
  if (apply && canSubmit && top) window.setTimeout(() => top.element.click(), 80);
  return {
    url: window.location.href,
    candidates: ranked.slice(0, 6).map(({ candidate }) => candidate),
    warnings,
    canSubmit,
    clicked: apply && canSubmit,
  };
}

export function detectSubmissionOutcome(): SubmissionOutcomeDetection {
  const visibleText = Array.from(document.querySelectorAll<HTMLElement>(
    '[role="alert"], [aria-live], .alert, .notice, .message, .success, .error, main, body',
  )).filter((element) => {
    const style = window.getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden";
  }).map((element) => (element.innerText || "").trim()).filter(Boolean).join("\n").slice(0, 12000);
  const text = visibleText.toLowerCase();
  const result = (
    status: SubmissionOutcomeDetection["status"],
    confidence: number,
    message: string,
  ): SubmissionOutcomeDetection => ({ url: window.location.href, status, confidence, message });
  if (/(awaiting moderation|pending approval|awaiting review|under review|待审核|等待审核|审核中)/i.test(text)) {
    return result("pending", 96, "页面提示正在审核或等待批准");
  }
  if (/(duplicate comment|already submitted|already exists|重复提交|已经提交)/i.test(text)) {
    return result("duplicate", 94, "页面提示内容重复或已经提交");
  }
  if (/(rejected|not approved|marked as spam|被拒绝|垃圾内容|spam detected)/i.test(text)) {
    return result("rejected", 92, "页面提示提交被拒绝或判定为 Spam");
  }
  if (/(captcha required|complete the captcha|验证码|please log in|login required|sign in to continue|must be logged in|需要登录)/i.test(text)) {
    return result("failed", 92, "页面提示需要登录或完成 CAPTCHA，提交未确认成功");
  }
  if (/(submission failed|could not submit|something went wrong|an error occurred|提交失败|发生错误)/i.test(text)) {
    return result("failed", 90, "页面提示提交失败");
  }
  if (/(thank you|successfully submitted|submission received|comment has been posted|提交成功|感谢提交|已收到)/i.test(text)) {
    return result("submitted", 90, "页面提示已成功接收提交");
  }
  return result("unknown", 35, "页面没有提供足够可靠的提交结果信号，请人工确认");
}
