# utils/screenshot_manager.py
import os
import time
import json
import shutil
from datetime import datetime
from typing import Optional, Dict, Union
from pathlib import Path
from playwright.async_api import Page
import threading
import re

from utils.logger import get_logger, get_context

logger = get_logger(__name__)


class ScreenshotManager:
    """
    Manages screenshots with strict global sequential ordering and robust error handling.
    Ensures screenshots are properly named, sequenced, and organized by generation/application.
    """

    def __init__(self, base_dir: str = "screenshots"):
        """
        Initialize screenshot manager.

        Args:
            base_dir: Base directory for screenshots
        """
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

        # Global counter with lock for absolute ordering across threads
        self._global_lock = threading.Lock()
        self._global_counter = 0

        # Counter state file to ensure persistence across runs
        self._state_file = os.path.join(base_dir, ".screenshot_state")
        self._load_state()

        # For sanitizing filenames - remove problematic characters
        self._invalid_chars_pattern = re.compile(r'[\\/*?:"<>|\']')

    def _load_state(self) -> None:
        """Load counter state from file if it exists"""
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, 'r') as f:
                    state = json.load(f)
                    self._global_counter = state.get('global_counter', 0)
                    logger.info(f"Loaded screenshot counter state: {self._global_counter}")
        except Exception as e:
            logger.warning(f"Could not load screenshot counter state: {e}")
            # If we can't load state, default to 0 and save it
            self._save_state()

    def _save_state(self) -> None:
        """Save counter state to file"""
        try:
            with open(self._state_file, 'w') as f:
                json.dump({'global_counter': self._global_counter,
                           'timestamp': datetime.now().isoformat()}, f)
        except Exception as e:
            logger.warning(f"Could not save screenshot counter state: {e}")

    def _sanitize_filename(self, name: str) -> str:
        """
        Sanitize filename to remove invalid characters.

        Args:
            name: Original filename

        Returns:
            Sanitized filename
        """
        if not name:
            return "unnamed"

        # Replace invalid characters with underscore
        sanitized = self._invalid_chars_pattern.sub('_', name)

        # Replace spaces with underscores
        sanitized = sanitized.replace(' ', '_')

        # Limit length to avoid excessively long filenames
        max_length = 40
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]

        return sanitized

    def _get_next_index(self) -> int:
        """
        Get the next global sequential index for screenshots.
        Ensures strict ordering across all screenshots.

        Returns:
            Next sequential index
        """
        # Thread-safe access to the counter
        with self._global_lock:
            self._global_counter += 1
            # Save state periodically (every 5 screenshots)
            if self._global_counter % 5 == 0:
                self._save_state()
            return self._global_counter

    def get_screenshot_dir(self, generation_id: Optional[str] = None, application_id: Optional[str] = None) -> str:
        """
        Get the screenshot directory for the given context.
        Creates the directory if it doesn't exist.

        Args:
            generation_id: Generation/batch ID
            application_id: Application ID

        Returns:
            Path to screenshot directory
        """
        # Use provided IDs or get from current context
        context = get_context()
        gen_id = generation_id or context.get('generation_id', 'global')
        app_id = application_id or context.get('application_id', 'global')

        # Create directory structure
        screenshot_dir = f"{self.base_dir}/{gen_id}/{app_id}"
        os.makedirs(screenshot_dir, exist_ok=True)

        return screenshot_dir

    async def take_screenshot(self,
                              page: Page,
                              name: str,
                              generation_id: Optional[str] = None,
                              application_id: Optional[str] = None) -> str:
        """
        Take a screenshot and save it to the appropriate directory.

        Args:
            page: Playwright page
            name: Screenshot name
            generation_id: Optional override for generation ID
            application_id: Optional override for application ID

        Returns:
            Path to the screenshot file
        """
        try:
            # Get the appropriate directory
            context = get_context()
            gen_id = generation_id or context.get('generation_id', 'global')
            app_id = application_id or context.get('application_id', 'global')
            screenshot_dir = self.get_screenshot_dir(gen_id, app_id)

            # Sanitize the name
            sanitized_name = self._sanitize_filename(name)

            # Get the next sequential index (global across all applications)
            index = self._get_next_index()

            # Format index with leading zeros (5 digits: 00001, 00002, etc.)
            index_str = f"{index:05d}"

            # Generate unique filename with index and timestamp
            timestamp = int(time.time())
            filename = f"{screenshot_dir}/{index_str}_{sanitized_name}_{timestamp}.png"

            # Make sure we wait for any pending navigations (with a short timeout)
            try:
                await page.wait_for_load_state("networkidle", timeout=2000)
            except Exception as e:
                # This is often normal, so debug level only
                logger.debug(f"Wait for load state timeout (normal during processing): {str(e)}")

            # Take screenshot
            await page.screenshot(path=filename, full_page=True)
            logger.info(f"Screenshot {index_str} saved: {sanitized_name}")

            return filename

        except Exception as e:
            logger.error(f"Error taking screenshot '{name}': {str(e)}")
            # Try one more time with a simpler approach
            try:
                error_filename = f"{self.base_dir}/error_{int(time.time())}.png"
                await page.screenshot(path=error_filename)
                return error_filename
            except:
                return ""

    async def take_full_page_screenshot(self,
                                        page: Page,
                                        name: str,
                                        generation_id: Optional[str] = None,
                                        application_id: Optional[str] = None) -> str:
        """
        Take a full page screenshot and save it to the appropriate directory.

        Args:
            page: Playwright page
            name: Screenshot name
            generation_id: Optional override for generation ID
            application_id: Optional override for application ID

        Returns:
            Path to the screenshot file
        """
        try:
            # Get the appropriate directory
            context = get_context()
            gen_id = generation_id or context.get('generation_id', 'global')
            app_id = application_id or context.get('application_id', 'global')
            screenshot_dir = self.get_screenshot_dir(gen_id, app_id)

            # Sanitize the name
            sanitized_name = self._sanitize_filename(name)

            # Get the next sequential index (global across all applications)
            index = self._get_next_index()

            # Format index with leading zeros (5 digits: 00001, 00002, etc.)
            index_str = f"{index:05d}"

            # Generate unique filename with index and timestamp
            timestamp = int(time.time())
            filename = f"{screenshot_dir}/{index_str}_{sanitized_name}_full_{timestamp}.png"

            # Make sure we wait for any pending navigations (with a short timeout)
            try:
                await page.wait_for_load_state("networkidle", timeout=2000)
            except Exception as e:
                logger.debug(f"Wait for load state timeout (normal during processing): {str(e)}")

            # Take full page screenshot
            await page.screenshot(path=filename, full_page=True)
            logger.info(f"Full page screenshot {index_str} saved: {sanitized_name}")

            return filename

        except Exception as e:
            logger.error(f"Error taking full page screenshot '{name}': {str(e)}")
            # Try a simpler approach
            try:
                error_filename = f"{self.base_dir}/error_full_{int(time.time())}.png"
                await page.screenshot(path=error_filename)
                return error_filename
            except:
                return ""

    async def take_element_screenshot(self,
                                      page: Page,
                                      selector: str,
                                      name: str,
                                      generation_id: Optional[str] = None,
                                      application_id: Optional[str] = None) -> str:
        """
        Take a screenshot of a specific element and save it.
        If element not found, takes a fallback full page screenshot.

        Args:
            page: Playwright page
            selector: Element selector (XPath or CSS)
            name: Screenshot name
            generation_id: Optional override for generation ID
            application_id: Optional override for application ID

        Returns:
            Path to the screenshot file
        """
        # Get the next sequential index (global across all applications)
        index = self._get_next_index()
        index_str = f"{index:05d}"

        try:
            # Get the appropriate directory
            context = get_context()
            gen_id = generation_id or context.get('generation_id', 'global')
            app_id = application_id or context.get('application_id', 'global')
            screenshot_dir = self.get_screenshot_dir(gen_id, app_id)

            # Sanitize the name and selector for filename
            sanitized_name = self._sanitize_filename(name)

            # Generate unique filename with index and timestamp
            timestamp = int(time.time())
            filename = f"{screenshot_dir}/{index_str}_{sanitized_name}_element_{timestamp}.png"

            # Try to find the element using XPath or CSS
            element = None
            try:
                if selector.startswith("//") or selector.startswith("xpath="):
                    clean_selector = selector.replace("xpath=", "")
                    element = await page.wait_for_selector(f"xpath={clean_selector}", state="visible", timeout=2000)
                else:
                    # Fall back to CSS selector
                    element = await page.wait_for_selector(selector, state="visible", timeout=2000)
            except Exception as e:
                logger.info(f"Element not found for screenshot: {selector} ({str(e)})")

            if element:
                # Take element screenshot
                await element.screenshot(path=filename)
                logger.info(f"Element screenshot {index_str} saved: {sanitized_name}")
                return filename

            # If we get here, the element was not found - take a full page screenshot instead
            fallback_filename = f"{screenshot_dir}/{index_str}_{sanitized_name}_fallback_{timestamp}.png"
            await page.screenshot(path=fallback_filename)
            logger.info(f"Element not found, took fallback screenshot {index_str}: {sanitized_name}")
            return fallback_filename

        except Exception as e:
            logger.error(f"Error taking element screenshot '{name}': {str(e)}")

            try:
                # Last-resort fallback - take a full page screenshot with error indication
                error_filename = f"{self.base_dir}/error_element_{int(time.time())}.png"
                await page.screenshot(path=error_filename)
                return error_filename
            except:
                return ""

    def archive_screenshots(self, generation_id: str, target_dir: Optional[str] = None) -> bool:
        """
        Archive screenshots for a specific generation.

        Args:
            generation_id: Generation ID to archive
            target_dir: Optional target directory, defaults to 'archives'

        Returns:
            True if successful, False otherwise
        """
        try:
            source_dir = f"{self.base_dir}/{generation_id}"

            if not os.path.exists(source_dir):
                logger.warning(f"No screenshots found for generation {generation_id}")
                return False

            if not target_dir:
                target_dir = f"archives/{generation_id}_{int(time.time())}"

            os.makedirs(target_dir, exist_ok=True)

            # Copy all files to the archive
            shutil.copytree(source_dir, f"{target_dir}/screenshots", dirs_exist_ok=True)

            logger.info(f"Archived screenshots for generation {generation_id} to {target_dir}")
            return True

        except Exception as e:
            logger.error(f"Error archiving screenshots: {str(e)}")
            return False

    async def take_screenshot_safely(self, page, name, **kwargs):
        """
        Safely take a screenshot, handling errors gracefully.

        Args:
            page: Playwright page
            name: Screenshot name
            **kwargs: Additional arguments for take_screenshot

        Returns:
            Path to screenshot or empty string if failed
        """
        try:
            # Check if page is still open
            if page.is_closed():
                logger.warning(f"Cannot take screenshot '{name}': Page is closed")
                return ""

            # Try to take screenshot
            return await self.take_screenshot(page, name, **kwargs)
        except Exception as e:
            logger.warning(f"Error taking screenshot '{name}': {str(e)}")
            return ""