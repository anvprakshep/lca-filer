"""
Browser Pool Manager for LCA Filing Automation System.

This module manages a pool of browser instances for the LCA Filing Automation System,
allowing efficient reuse of browser instances between filings.
"""

import asyncio
from typing import Dict, Any, List, Optional, Tuple
import time
import threading

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from utils.logger import get_logger

logger = get_logger(__name__)


class BrowserInstance:
    """Represents a single browser instance in the pool."""

    def __init__(self, browser, context):
        """Initialize browser instance."""
        self.browser = browser
        self.context = context
        self.in_use = False
        self.last_used = time.time()
        self.health_status = "ready"
        # Lock for thread-safe operations
        self.lock = threading.Lock()

    async def create_page(self) -> Page:
        """Create a new page in this browser instance."""
        return await self.context.new_page()

    async def close(self):
        """Close the browser instance."""
        with self.lock:
            try:
                if self.browser:
                    await self.browser.close()
                    self.health_status = "closed"
                    logger.info("Browser instance closed")
            except Exception as e:
                logger.error(f"Error closing browser instance: {str(e)}")
                self.health_status = "error"


class BrowserPool:
    """
    Manages a pool of browser instances for efficient reuse.

    This is a singleton class that provides browser instances for the LCA filing
    automation system. It manages the creation, allocation, and cleanup of browser
    instances to optimize resource usage.
    """

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        """Ensure singleton pattern."""
        if cls._instance is None:
            cls._instance = super(BrowserPool, cls).__new__(cls)
        return cls._instance

    def __init__(self, config: Dict[str, Any] = None, max_instances: int = 3):
        """
        Initialize browser pool.

        Args:
            config: Browser configuration
            max_instances: Maximum number of browser instances to maintain
        """
        # Only initialize once (singleton pattern)
        if BrowserPool._initialized:
            return

        self.config = config or {}
        self.max_instances = max_instances
        self.instances = []
        self.instance_lock = threading.Lock()
        self.playwright = None
        self.initialization_lock = asyncio.Lock()
        self.is_initialized = False
        self.shutdown_requested = False

        # Statistics
        self.total_instances_created = 0
        self.total_pages_created = 0
        self.allocation_failures = 0

        BrowserPool._initialized = True
        logger.info(f"Browser pool initialized with max {max_instances} instances")

    async def initialize(self) -> bool:
        """
        Initialize the browser pool.

        Returns:
            True if initialization successful, False otherwise
        """
        async with self.initialization_lock:
            if self.is_initialized:
                return True

            try:
                # Start playwright
                self.playwright = await async_playwright().start()
                self.is_initialized = True
                logger.info("Browser pool playwright initialized")
                return True
            except Exception as e:
                logger.error(f"Failed to initialize browser pool: {str(e)}")
                return False

    async def get_instance(self) -> Optional[BrowserInstance]:
        """
        Get an available browser instance from the pool.
        Creates a new instance if necessary and possible.

        Returns:
            A browser instance or None if unable to allocate
        """
        if not self.is_initialized:
            success = await self.initialize()
            if not success:
                logger.error("Cannot get browser instance - pool not initialized")
                self.allocation_failures += 1
                return None

        # Check for shutdown request
        if self.shutdown_requested:
            logger.warning("Cannot get browser instance - shutdown in progress")
            self.allocation_failures += 1
            return None

        # First try to find an available instance
        with self.instance_lock:
            for instance in self.instances:
                if not instance.in_use and instance.health_status == "ready":
                    instance.in_use = True
                    instance.last_used = time.time()
                    logger.info("Reusing existing browser instance")
                    return instance

        # If no available instance and we haven't reached max, create a new one
        with self.instance_lock:
            if len(self.instances) < self.max_instances:
                try:
                    # Launch browser
                    browser = await self.playwright.chromium.launch(
                        headless=self.config.get("headless", True)
                    )

                    # Create context with custom settings
                    context = await browser.new_context(
                        viewport=self.config.get("viewport", {"width": 1280, "height": 800}),
                        user_agent=self.config.get("user_agent", ""),
                        locale=self.config.get("locale", "en-US"),
                        timezone_id=self.config.get("timezone_id", "America/New_York")
                    )

                    # Set default timeout
                    context.set_default_timeout(self.config.get("timeout", 30000))

                    # Create new instance
                    instance = BrowserInstance(browser, context)
                    instance.in_use = True
                    instance.last_used = time.time()
                    self.instances.append(instance)
                    self.total_instances_created += 1

                    logger.info("Created new browser instance")
                    return instance
                except Exception as e:
                    logger.error(f"Failed to create new browser instance: {str(e)}")
                    self.allocation_failures += 1
                    return None

        # If we get here, all instances are in use and we've reached max
        logger.warning("All browser instances in use and at maximum capacity")
        self.allocation_failures += 1
        return None

    async def release_instance(self, instance: BrowserInstance):
        """
        Release a browser instance back to the pool.

        Args:
            instance: Browser instance to release
        """
        with self.instance_lock:
            if instance in self.instances:
                instance.in_use = False
                instance.last_used = time.time()
                logger.info("Browser instance released back to pool")
            else:
                logger.warning("Attempting to release an instance not in the pool")

    async def create_page(self) -> Optional[Tuple[BrowserInstance, Page]]:
        """
        Create a new page in an available browser instance.

        Returns:
            Tuple of (browser_instance, page) or None if unable to create
        """
        instance = await self.get_instance()
        if not instance:
            return None

        try:
            page = await instance.create_page()
            self.total_pages_created += 1
            logger.info("Created new page in browser instance")
            return instance, page
        except Exception as e:
            logger.error(f"Failed to create page: {str(e)}")
            # Mark instance as failed and release it
            instance.health_status = "error"
            await self.release_instance(instance)
            return None

    async def cleanup_idle_instances(self, max_idle_time: int = 300):
        """
        Clean up idle browser instances.

        Args:
            max_idle_time: Maximum idle time in seconds before cleanup
        """
        with self.instance_lock:
            current_time = time.time()
            instances_to_remove = []

            for instance in self.instances:
                if not instance.in_use and (current_time - instance.last_used) > max_idle_time:
                    instances_to_remove.append(instance)

            for instance in instances_to_remove:
                await instance.close()
                self.instances.remove(instance)

            if instances_to_remove:
                logger.info(f"Cleaned up {len(instances_to_remove)} idle browser instances")

    async def shutdown(self):
        """
        Shutdown the browser pool, closing all instances.
        """
        self.shutdown_requested = True

        with self.instance_lock:
            logger.info(f"Shutting down browser pool with {len(self.instances)} instances")

            for instance in self.instances:
                await instance.close()

            self.instances = []

            if self.playwright:
                await self.playwright.stop()
                self.playwright = None

            self.is_initialized = False
            logger.info("Browser pool shutdown complete")

        # Reset shutdown flag to allow reinitialization if needed
        self.shutdown_requested = False

    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the browser pool.

        Returns:
            Status dictionary
        """
        with self.instance_lock:
            active_count = sum(1 for i in self.instances if i.in_use)
            idle_count = sum(1 for i in self.instances if not i.in_use)
            healthy_count = sum(1 for i in self.instances if i.health_status == "ready")

            return {
                "initialized": self.is_initialized,
                "shutdown_requested": self.shutdown_requested,
                "total_instances": len(self.instances),
                "active_instances": active_count,
                "idle_instances": idle_count,
                "healthy_instances": healthy_count,
                "total_instances_created": self.total_instances_created,
                "total_pages_created": self.total_pages_created,
                "allocation_failures": self.allocation_failures,
                "max_instances": self.max_instances
            }