import { describe, expect, it } from "vitest";
import { inspectOrFillCurrentForm } from "./formFiller";
import type { FormFillInput, FormFillResult, Project } from "../types/domain";

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 1,
    name: "Acme AI",
    website: "https://acme.example.com",
    authorName: "Lee",
    email: "lee@example.com",
    tagline: "AI powered SEO helper",
    shortDescription: "Short description",
    mediumDescription: "Medium description",
    longDescription: "Long description",
    keywords: ["SEO", "AI"],
    ...overrides,
  };
}

function makeInput(overrides: Partial<FormFillInput> = {}): FormFillInput {
  return {
    workflow: "directory",
    project: makeProject(),
    targetUrl: "https://acme.example.com",
    ...overrides,
  };
}

function mount(html: string): void {
  document.body.innerHTML = html;
}

const DIRECTORY_FORM = `
  <form>
    <label>Product name<input name="product_name" type="text"></label>
    <label>Website URL<input name="url" type="url"></label>
    <label>Email<input name="email" type="email"></label>
    <label>Tagline<input name="tagline" type="text"></label>
    <label>Description<textarea name="description"></textarea></label>
    <button type="submit">Submit product</button>
  </form>
`;

function fieldKinds(result: FormFillResult): string[] {
  return result.fields.map((field) => field.kind);
}

function fieldOf(result: FormFillResult, kind: string) {
  return result.fields.find((field) => field.kind === kind);
}

describe("inspectOrFillCurrentForm（directory 工作流）", () => {
  it("识别名称/网址/邮箱/标语/描述并安全填入", () => {
    mount(DIRECTORY_FORM);
    const preview = inspectOrFillCurrentForm(makeInput(), false);
    expect(fieldKinds(preview)).toEqual(["title", "email", "website", "tagline", "description"]);
    expect(preview.canFill).toBe(true);
    expect(preview.fields.every((field) => field.willFill)).toBe(true);

    const fill = inspectOrFillCurrentForm(makeInput(), true);
    expect(fill.filledCount).toBe(5);
    const values = Object.fromEntries(
      Array.from(document.querySelectorAll("input, textarea")).map((element) => [
        element.getAttribute("name") || "",
        (element as HTMLInputElement).value,
      ]),
    );
    expect(values.product_name).toBe("Acme AI");
    expect(values.url).toBe("https://acme.example.com");
    expect(values.email).toBe("lee@example.com");
    expect(values.tagline).toBe("AI powered SEO helper");
    expect(values.description).toBe("Medium description");
  });

  it("已有内容的字段不覆盖且计入 matchedCount", () => {
    mount(`
      <form>
        <label>Product name<input name="product_name"></label>
        <label>Website<input name="url" value="https://acme.example.com"></label>
      </form>
    `);
    const result = inspectOrFillCurrentForm(makeInput(), true);
    expect(fieldOf(result, "website")?.matchesExpected).toBe(true);
    expect(result.matchedCount).toBe(1);
    expect(result.filledCount).toBe(1);
    expect(document.querySelector<HTMLInputElement>("[name=url]")?.value).toBe("https://acme.example.com");
  });

  it("同置信度重复字段触发警告并放弃自动选择", () => {
    mount(`
      <form>
        <label>Product name<input name="product_name"></label>
        <label>Email<input name="email1" type="text"></label>
        <label>Email<input name="email2" type="text"></label>
      </form>
    `);
    const result = inspectOrFillCurrentForm(makeInput(), false);
    expect(fieldKinds(result)).not.toContain("email");
    expect(result.warnings.some((warning) => warning.includes("email"))).toBe(true);
  });

  it("检测到 reCAPTCHA 时不允许自动填写", () => {
    mount(`
      <form><label>Product name<input name="product_name"></label></form>
      <iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>
    `);
    const result = inspectOrFillCurrentForm(makeInput(), true);
    expect(result.warnings.some((warning) => warning.includes("验证码"))).toBe(true);
    expect(result.canFill).toBe(false);
    expect(result.filledCount).toBe(0);
  });

  it("检测到可见密码字段时警告并禁止自动填写", () => {
    mount(`
      <form>
        <label>Product name<input name="product_name"></label>
        <label>Password<input name="password" type="password"></label>
      </form>
    `);
    const result = inspectOrFillCurrentForm(makeInput(), true);
    expect(result.warnings.some((warning) => warning.includes("密码"))).toBe(true);
    expect(result.canFill).toBe(false);
  });

  it("填入时触发 input/change/blur 事件（React/Vue 兼容）", () => {
    mount(`<form><label>Product name<input name="product_name"></label></form>`);
    const element = document.querySelector<HTMLInputElement>("[name=product_name]");
    const events: string[] = [];
    for (const type of ["input", "change", "blur"]) {
      element?.addEventListener(type, () => events.push(type));
    }
    inspectOrFillCurrentForm(makeInput(), true);
    expect(events).toEqual(["input", "change", "blur"]);
  });
});

describe("inspectOrFillCurrentForm（blog_comment 工作流）", () => {
  it("无标签 textarea 按草稿识别为 comment 并填入", () => {
    mount(`<form><textarea placeholder="Join the discussion"></textarea></form>`);
    const result = inspectOrFillCurrentForm(
      makeInput({ workflow: "blog_comment", commentDraft: "Great article!" }),
      true,
    );
    const comment = fieldOf(result, "comment");
    expect(comment?.willFill).toBe(true);
    expect(document.querySelector("textarea")?.value).toBe("Great article!");
  });

  it("没有草稿时 comment 字段不可填", () => {
    mount(`<form><textarea placeholder="Join the discussion"></textarea></form>`);
    const result = inspectOrFillCurrentForm(makeInput({ workflow: "blog_comment" }), false);
    expect(fieldKinds(result)).not.toContain("comment");
  });
});
