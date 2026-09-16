import type { PageVerificationResult } from "../types/domain";

export function inspectCurrentPageForBacklink(targetUrl: string): PageVerificationResult {
  const normalize = (value: string): string | null => {
    try {
      const parsed = new URL(value, window.location.href);
      if (!/^https?:$/.test(parsed.protocol)) return null;
      parsed.hash = "";
      parsed.hostname = parsed.hostname.toLowerCase();
      if (parsed.pathname !== "/") parsed.pathname = parsed.pathname.replace(/\/+$/, "");
      return parsed.toString();
    } catch {
      return null;
    }
  };
  const visible = (element: HTMLElement): boolean => {
    const style = window.getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
  };
  const expected = normalize(targetUrl);
  if (!expected) {
    return {
      sourceUrl: window.location.href,
      targetUrl,
      outcome: "unknown",
      linkRel: [],
      checkedAt: new Date().toISOString(),
      message: "Target URL 无效，无法验证",
    };
  }
  const expectedHost = new URL(expected).hostname.replace(/^www\./, "");
  const anchors = Array.from(document.querySelectorAll<HTMLAnchorElement>("a[href]"))
    .filter((anchor) => visible(anchor));
  const exact = anchors.find((anchor) => normalize(anchor.href) === expected);
  if (exact) {
    const rel = (exact.getAttribute("rel") || "").split(/\s+/).filter(Boolean);
    return {
      sourceUrl: window.location.href,
      targetUrl,
      outcome: "active",
      anchorText: (exact.textContent || "").trim().replace(/\s+/g, " ").slice(0, 500) || undefined,
      linkRel: rel,
      checkedAt: new Date().toISOString(),
      message: `当前页面发现指向 Target URL 的可见链接${rel.length ? `（rel=${rel.join(" ")}）` : ""}`,
    };
  }
  const title = document.title.toLowerCase();
  const bodyText = (document.body?.innerText || "").trim().toLowerCase();
  const looks404 = /(^|\b)(404|page not found|not found|页面不存在|找不到页面)(\b|$)/i.test(`${title} ${bodyText.slice(0, 1200)}`)
    && bodyText.length < 5000;
  if (looks404) {
    return {
      sourceUrl: window.location.href,
      targetUrl,
      outcome: "page_404",
      linkRel: [],
      checkedAt: new Date().toISOString(),
      message: "当前页面呈现 404 / Not Found 特征，未发现目标链接",
    };
  }
  const sameDomainCount = anchors.filter((anchor) => {
    const normalized = normalize(anchor.href);
    return normalized ? new URL(normalized).hostname.replace(/^www\./, "") === expectedHost : false;
  }).length;
  return {
    sourceUrl: window.location.href,
    targetUrl,
    outcome: "link_missing",
    linkRel: [],
    checkedAt: new Date().toISOString(),
    message: sameDomainCount
      ? `未发现精确 Target URL；页面中有 ${sameDomainCount} 个指向同域其他地址的链接`
      : "当前页面未发现指向 Target URL 的可见链接",
  };
}
