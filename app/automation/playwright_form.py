from typing import Any

from .base import ChannelAdapter, SubmissionResult


class PlaywrightFormAdapter(ChannelAdapter):
    """Configurable reference adapter for a conventional HTML form.

    Required config keys: form_url, target_url_selector, anchor_text_selector,
    submit_selector. Optional login and success/result selectors are documented
    in README.md.
    """

    async def submit_link(
        self,
        target_url: str,
        anchor_text: str,
        credentials: dict[str, Any],
        config: dict[str, Any],
    ) -> SubmissionResult:
        required = ("form_url", "target_url_selector", "anchor_text_selector", "submit_selector")
        missing = [key for key in required if not config.get(key)]
        if missing:
            return SubmissionResult(False, message=f"适配器缺少配置: {', '.join(missing)}")

        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=config.get("headless", True))
            page = await browser.new_page()
            try:
                await page.goto(config["form_url"], wait_until="domcontentloaded", timeout=config.get("timeout_ms", 30000))
                if config.get("username_selector") and credentials.get("username"):
                    await page.fill(config["username_selector"], credentials["username"])
                if config.get("password_selector") and credentials.get("password"):
                    await page.fill(config["password_selector"], credentials["password"])
                if config.get("login_submit_selector"):
                    await page.click(config["login_submit_selector"])
                    await page.wait_for_load_state("domcontentloaded")
                    if config.get("post_login_url"):
                        await page.goto(config["post_login_url"], wait_until="domcontentloaded")

                for field_name, selector in config.get("credential_field_selectors", {}).items():
                    if credentials.get(field_name):
                        await page.fill(selector, str(credentials[field_name]))
                await page.fill(config["target_url_selector"], target_url)
                await page.fill(config["anchor_text_selector"], anchor_text)
                await page.click(config["submit_selector"])
                await page.wait_for_load_state("domcontentloaded")

                if config.get("success_selector"):
                    await page.wait_for_selector(config["success_selector"], timeout=config.get("timeout_ms", 30000))
                if config.get("result_url_selector"):
                    locator = page.locator(config["result_url_selector"]).first
                    actual_url = await locator.get_attribute("href") or await locator.text_content()
                else:
                    actual_url = page.url
                return SubmissionResult(True, (actual_url or page.url).strip(), "表单提交成功")
            except Exception as exc:
                return SubmissionResult(False, message=f"Playwright 提交失败: {type(exc).__name__}: {exc}")
            finally:
                await browser.close()

