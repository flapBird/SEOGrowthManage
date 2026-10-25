import { describe, expect, it } from "vitest";
import { detectSubmissionOutcome, inspectOrClickSubmitControl } from "./submitController";

function mountButtons(...labels: string[]): void {
  document.body.innerHTML = labels.map((label) => `<button type="button">${label}</button>`).join("");
}

function selected(result: ReturnType<typeof inspectOrClickSubmitControl>) {
  return result.candidates.find((candidate) => candidate.selected);
}

describe("inspectOrClickSubmitControl", () => {
  it('"Submit feedback" 不再因 back 子串被误判为危险按钮', () => {
    mountButtons("Submit feedback");
    const result = inspectOrClickSubmitControl(false);
    expect(result.canSubmit).toBe(true);
    expect(selected(result)?.label).toBe("Submit feedback");
    expect(selected(result)?.phase).toBe("final");
  });

  it('"Go Back" 被排除且没有可提交按钮', () => {
    mountButtons("Go Back");
    const result = inspectOrClickSubmitControl(false);
    expect(result.candidates).toHaveLength(0);
    expect(result.canSubmit).toBe(false);
    expect(result.warnings.some((warning) => warning.includes("没有识别到安全"))).toBe(true);
  });

  it('"Backlink to us" 这类非提交按钮不产生候选、不干扰选择', () => {
    mountButtons("Backlink to us", "Post comment");
    const result = inspectOrClickSubmitControl(false);
    expect(result.candidates.length).toBe(1);
    expect(selected(result)?.label).toBe("Post comment");
  });

  it("Post comment / Publish / Launch 识别为最终提交", () => {
    for (const label of ["Post comment", "Publish", "Launch your product", "提交评论"]) {
      mountButtons(label);
      const result = inspectOrClickSubmitControl(false);
      expect(result.canSubmit, label).toBe(true);
      expect(selected(result)?.phase, label).toBe("final");
    }
  });

  it("Next / Continue 识别为推进步骤而非最终提交", () => {
    mountButtons("Next");
    const result = inspectOrClickSubmitControl(false);
    expect(selected(result)?.phase).toBe("progress");
    expect(result.warnings.some((warning) => warning.includes("推进多步骤表单"))).toBe(true);
  });

  it("多个同置信度按钮时不自动选择", () => {
    mountButtons("Submit", "Submit");
    const result = inspectOrClickSubmitControl(false);
    expect(result.canSubmit).toBe(false);
    expect(result.warnings.some((warning) => warning.includes("同等置信度"))).toBe(true);
  });

  it("仅靠 type=submit 的按钮置信度不足，不自动点击", () => {
    document.body.innerHTML = '<input type="submit">';
    const result = inspectOrClickSubmitControl(false);
    expect(result.canSubmit).toBe(false);
    expect(result.candidates[0]?.confidence).toBe(62);
  });

  it("apply=true 时只点击被选中的按钮", async () => {
    mountButtons("Post comment");
    const clicked: string[] = [];
    document.querySelector("button")?.addEventListener("click", () => clicked.push("Post comment"));
    const result = inspectOrClickSubmitControl(true);
    expect(result.clicked).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(clicked).toEqual(["Post comment"]);
  });
});

describe("detectSubmissionOutcome", () => {
  it.each([
    ["Thank you! Your submission has been received.", "submitted"],
    ["Your comment is awaiting moderation", "pending"],
    ["Duplicate comment detected", "duplicate"],
    ["Your submission was marked as spam", "rejected"],
    ["Please log in to comment", "failed"],
    ["Something went wrong, please try again", "failed"],
  ])("识别 %s 为 %s", (text, status) => {
    document.body.innerHTML = `<main>${text}</main>`;
    const outcome = detectSubmissionOutcome();
    expect(outcome.status).toBe(status);
    expect(outcome.confidence).toBeGreaterThanOrEqual(90);
  });

  it("没有可靠信号时返回 unknown", () => {
    document.body.innerHTML = "<main>Welcome to our blog. Here are some posts.</main>";
    const outcome = detectSubmissionOutcome();
    expect(outcome.status).toBe("unknown");
    expect(outcome.confidence).toBeLessThan(50);
  });
});
