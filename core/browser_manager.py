import asyncio
from typing import Dict, Any, Optional, Tuple
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from utils.logger import get_logger

logger = get_logger(__name__)


class BrowserManager:
    """Manages browser instances for automation."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize browser manager.

        Args:
            config: Browser configuration
        """
        self.config = config
        self.browser = None
        self.context = None

    async def initialize(self) -> None:
        """Initialize browser and context."""
        playwright = await async_playwright().start()

        try:
            # Launch browser
            self.browser = await playwright.chromium.launch(
                headless=self.config.get("headless", True)
            )

            # Create context with custom settings
            self.context = await self.browser.new_context(
                viewport=self.config.get("viewport", {"width": 1280, "height": 800}),
                user_agent=self.config.get("user_agent", ""),
                locale=self.config.get("locale", "en-US"),
                timezone_id=self.config.get("timezone_id", "America/New_York")
            )

            # Set default timeout
            self.context.set_default_timeout(self.config.get("timeout", 30000))

            logger.info("Browser and context initialized")

        except Exception as e:
            logger.error(f"Error initializing browser: {str(e)}")
            await playwright.stop()
            raise

    async def new_page(self) -> Page:
        """
        Create a new page in the current context.

        Returns:
            Playwright page object

        Raises:
            RuntimeError: If browser manager is not initialized
        """
        if not self.context:
            raise RuntimeError("Browser manager not initialized. Call initialize() first.")

        return await self.context.new_page()

    async def close(self) -> None:
        """Close browser and release resources."""
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
                self.context = None
                logger.info("Browser closed")
        except Exception as e:
            logger.error(f"Error closing browser: {str(e)}")

    async def take_screenshot(self, page: Page, name: str) -> str:
        """
        Take a screenshot of the current page.

        Args:
            page: Playwright page
            name: Screenshot name

        Returns:
            Path to the screenshot file
        """
        import os
        import time

        # Create screenshots directory if it doesn't exist
        os.makedirs("screenshots", exist_ok=True)

        # Generate unique filename
        timestamp = int(time.time())
        filename = f"screenshots/{name}_{timestamp}.png"

        # Take screenshot
        await page.screenshot(path=filename)
        logger.info(f"Screenshot saved: {filename}")

        return filename
