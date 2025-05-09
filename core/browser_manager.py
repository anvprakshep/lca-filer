# core/browser_manager.py
import asyncio
import threading
from typing import Dict, Any, Optional, Tuple, List, Union
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError, Error

from utils.logger import get_logger, log_exception
from utils.screenshot_manager import ScreenshotManager

logger = get_logger(__name__)


class ElementNotFoundError(Exception):
    """Exception raised when an element is not found on the page."""
    pass


class BrowserManager:
    """Manages browser instances with robust error handling and XPath support."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize browser manager.

        Args:
            config: Browser configuration
        """
        self.config = config
        self.browser = None
        self.context = None
        self.screenshot_manager = None  # Will be set in initialize()
        self._lock = threading.Lock()  # Add this line

        # Default timeout in milliseconds
        self.default_timeout = config.get("timeout", 30000)

    async def initialize(self) -> bool:
        """Initialize browser, context and screenshot manager."""
        with self._lock:  # Add this line
            try:
                # Check if already initialized
                if self.browser and self.context:
                    logger.info("Browser manager already initialized")
                    return True

                logger.info("Initializing browser manager")

                # Create screenshot manager
                self.screenshot_manager = ScreenshotManager()

                # Start playwright
                playwright = await async_playwright().start()

                # Launch browser
                self.browser = await playwright.chromium.launch(
                    headless=False
                )

                # Create context with custom settings
                self.context = await self.browser.new_context(
                    viewport=self.config.get("viewport", {"width": 1280, "height": 800}),
                    user_agent=self.config.get("user_agent", ""),
                    locale=self.config.get("locale", "en-US"),
                    timezone_id=self.config.get("timezone_id", "America/New_York")
                )

                # Set default timeout
                self.context.set_default_timeout(self.default_timeout)

                logger.info("Browser and context initialized successfully")
                return True

            except Exception as e:
                log_exception(e, __name__)
                logger.error(f"Failed to initialize browser: {str(e)}")
                return False

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

        try:
            page = await self.context.new_page()
            logger.info("Created new browser page")
            return page
        except Exception as e:
            log_exception(e, __name__)
            logger.error(f"Failed to create new page: {str(e)}")
            raise

    async def close(self) -> None:
        """Close browser and release resources."""
        with self._lock:  # Add this line
            try:
                if self.browser:
                    await self.browser.close()
                    self.browser = None
                    self.context = None
                    logger.info("Browser closed successfully")
            except Exception as e:
                log_exception(e, __name__)
                logger.error(f"Error closing browser: {str(e)}")

    async def find_element(self,
                           page: Page,
                           selector: str,
                           timeout: int = 5000,
                           state: str = "visible") -> Any:
        """
        Find an element on the page, with support for XPath selectors.

        Args:
            page: Playwright page
            selector: XPath or CSS selector
            timeout: Timeout in milliseconds
            state: Element state to wait for ("attached", "detached", "visible", "hidden")

        Returns:
            Found element

        Raises:
            ElementNotFoundError: If element is not found
        """
        try:
            # Determine if this is an XPath selector
            is_xpath = selector.startswith('//') or selector.startswith('xpath=')

            # Create the appropriate selector string
            if is_xpath:
                clean_selector = selector.replace('xpath=', '')
                full_selector = f"xpath={clean_selector}"
            else:
                full_selector = selector

            # Wait for and return the element
            element = await page.wait_for_selector(
                full_selector,
                state=state,
                timeout=timeout
            )

            if not element:
                logger.warning(f"Element not found with selector: {selector}")
                raise ElementNotFoundError(f"Element not found: {selector}")

            return element

        except TimeoutError:
            logger.warning(f"Timeout waiting for element: {selector}")
            if self.screenshot_manager:
                await self.screenshot_manager.take_screenshot(
                    page,
                    f"element_timeout_{selector.replace('/', '_').replace('=', '_')}"
                )
            raise ElementNotFoundError(f"Timeout waiting for element: {selector}")

        except Error as e:
            logger.warning(f"Playwright error finding element {selector}: {str(e)}")
            if self.screenshot_manager:
                await self.screenshot_manager.take_screenshot(
                    page,
                    f"element_error_{selector.replace('/', '_').replace('=', '_')}"
                )
            raise ElementNotFoundError(f"Error finding element {selector}: {str(e)}")

    async def click_element(self,
                            page: Page,
                            selector: str,
                            timeout: int = 5000,
                            force: bool = False,
                            retry_count: int = 1) -> None:
        """
        Click an element on the page with retry logic.

        Args:
            page: Playwright page
            selector: XPath or CSS selector
            timeout: Timeout in milliseconds
            force: Whether to force the click
            retry_count: Number of retries if click fails

        Raises:
            ElementNotFoundError: If element is not found
        """
        for attempt in range(retry_count + 1):
            try:
                # Find the element first
                element = await self.find_element(page, selector, timeout)

                # Try to click it
                await element.click(force=force, timeout=timeout)
                return

            except ElementNotFoundError:
                # If this was the last attempt, re-raise
                if attempt == retry_count:
                    raise
                logger.warning(f"Retrying click on element {selector} (attempt {attempt + 1}/{retry_count + 1})")
                await asyncio.sleep(1)  # Brief pause before retry

            except Exception as e:
                # For other errors, also retry if not last attempt
                if attempt == retry_count:
                    logger.error(f"Failed to click element {selector} after {retry_count + 1} attempts: {str(e)}")
                    if self.screenshot_manager:
                        await self.screenshot_manager.take_screenshot(
                            page,
                            f"click_error_{selector.replace('/', '_').replace('=', '_')}"
                        )
                    raise ElementNotFoundError(f"Error clicking element {selector}: {str(e)}")

                logger.warning(f"Retrying click on element {selector} after error: {str(e)}")
                await asyncio.sleep(1)  # Brief pause before retry

    async def fill_element(self,
                           page: Page,
                           selector: str,
                           value: str,
                           timeout: int = 5000,
                           retry_count: int = 1) -> None:
        """
        Fill a form element on the page with retry logic.

        Args:
            page: Playwright page
            selector: XPath or CSS selector
            value: Value to fill
            timeout: Timeout in milliseconds
            retry_count: Number of retries if fill fails

        Raises:
            ElementNotFoundError: If element is not found
        """
        for attempt in range(retry_count + 1):
            try:
                # Find the element first
                element = await self.find_element(page, selector, timeout)

                # Clear the field first (for better reliability)
                await element.click()
                await element.fill("")

                # Now fill with the value
                await element.fill(value, timeout=timeout)
                return

            except ElementNotFoundError:
                # If this was the last attempt, re-raise
                if attempt == retry_count:
                    raise
                logger.warning(f"Retrying fill on element {selector} (attempt {attempt + 1}/{retry_count + 1})")
                await asyncio.sleep(1)  # Brief pause before retry

            except Exception as e:
                # For other errors, also retry if not last attempt
                if attempt == retry_count:
                    logger.error(f"Failed to fill element {selector} after {retry_count + 1} attempts: {str(e)}")
                    if self.screenshot_manager:
                        await self.screenshot_manager.take_screenshot(
                            page,
                            f"fill_error_{selector.replace('/', '_').replace('=', '_')}"
                        )
                    raise ElementNotFoundError(f"Error filling element {selector}: {str(e)}")

                logger.warning(f"Retrying fill on element {selector} after error: {str(e)}")
                await asyncio.sleep(1)  # Brief pause before retry

    async def is_element_visible(self,
                                 page: Page,
                                 selector: str,
                                 timeout: int = 5000) -> bool:
        """
        Check if an element is visible on the page.

        Args:
            page: Playwright page
            selector: XPath or CSS selector
            timeout: Timeout in milliseconds

        Returns:
            True if element is visible, False otherwise
        """
        try:
            await self.find_element(page, selector, timeout=timeout, state="visible")
            return True
        except ElementNotFoundError:
            return False
        except Exception as e:
            logger.debug(f"Error checking if element {selector} is visible: {str(e)}")
            return False

    async def get_element_text(self,
                               page: Page,
                               selector: str,
                               timeout: int = 5000) -> Optional[str]:
        """
        Get text content of an element.

        Args:
            page: Playwright page
            selector: XPath or CSS selector
            timeout: Timeout in milliseconds

        Returns:
            Text content or None if element not found
        """
        try:
            element = await self.find_element(page, selector, timeout)
            return await element.text_content()
        except ElementNotFoundError:
            return None
        except Exception as e:
            logger.warning(f"Error getting text from element {selector}: {str(e)}")
            return None

    async def find_elements(self,
                            page: Page,
                            selector: str,
                            timeout: int = 5000) -> List[Any]:
        """
        Find all elements matching a selector.

        Args:
            page: Playwright page
            selector: XPath or CSS selector
            timeout: Timeout in milliseconds

        Returns:
            List of found elements (empty list if none found)
        """
        try:
            # Determine if this is an XPath selector
            is_xpath = selector.startswith('//') or selector.startswith('xpath=')

            # Create the appropriate selector string
            if is_xpath:
                clean_selector = selector.replace('xpath=', '')
                full_selector = f"xpath={clean_selector}"
            else:
                full_selector = selector

            # First check if at least one exists to respect the timeout
            try:
                await page.wait_for_selector(full_selector, timeout=timeout)
            except:
                return []

            # Now get all matching elements
            elements = await page.query_selector_all(full_selector)
            return elements

        except Exception as e:
            logger.debug(f"Error finding elements with selector {selector}: {str(e)}")
            return []