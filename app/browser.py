from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from .client import USER_AGENT, new_client


@dataclass
class BrowserResult:
    media_url: str
    player_url: str
    cookies: list[dict]


class BrowserResolver:
    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def _start(self) -> None:
        if self._browser:
            return
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
        )

    async def resolve(self, detail_url: str, label: str) -> BrowserResult | None:
        async with self._lock:
            await self._start()
            context = await self._browser.new_context(
                user_agent=USER_AGENT,
                locale="zh-CN",
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
            )
            page = await context.new_page()
            media: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

            async def route_handler(route):
                request = route.request
                if request.resource_type in {"image", "font", "stylesheet"}:
                    await route.abort()
                    return
                # Ad popups often navigate away from the requested SupJav tab.
                if request.is_navigation_request() and request.frame == page.main_frame:
                    host = request.url.lower()
                    if request.url != detail_url and "supjav" not in host:
                        await route.abort()
                        return
                await route.continue_()

            def observe(request):
                url = request.url
                if re.search(r"\.(?:m3u8|mp4)(?:$|[?#])", url, re.I):
                    media.put_nowait((url, request.frame.url or page.url))

            await page.route("**/*", route_handler)
            page.on("request", observe)
            try:
                await page.goto(detail_url, wait_until="domcontentloaded", timeout=30_000)
                buttons = page.locator(".btn-server, [data-link], [data-server]")
                count = await buttons.count()
                target = None
                for index in range(count):
                    button = buttons.nth(index)
                    text = (await button.inner_text()).strip().upper()
                    if label.upper() in text:
                        target = button
                        break
                if target is None and count:
                    target = buttons.first
                if target is not None:
                    try:
                        await target.click(force=True, timeout=5_000)
                    except Exception:
                        pass
                # A real site visit may require repeated play clicks after ad popups.
                for _ in range(4):
                    try:
                        url, referer = await asyncio.wait_for(media.get(), timeout=4.5)
                        cookies = await context.cookies()
                        return BrowserResult(url, referer, cookies)
                    except asyncio.TimeoutError:
                        for frame in page.frames[::-1]:
                            for selector in ("video", ".vjs-big-play-button", "button[aria-label*='Play']", ".plyr__control--overlaid"):
                                try:
                                    locator = frame.locator(selector).first
                                    if await locator.count():
                                        await locator.click(force=True, timeout=1_500)
                                        break
                                except Exception:
                                    continue
                return None
            finally:
                await context.close()


browser_resolver = BrowserResolver()


def client_from_browser(cookies: list[dict]):
    client = new_client()
    for cookie in cookies:
        try:
            client.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"), path=cookie.get("path", "/"))
        except Exception:
            continue
    return client

