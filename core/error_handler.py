import asyncio
import time
import json
import re
from typing import Dict, Any, List, Optional, Tuple
from playwright.async_api import Page

from config.selectors import Selectors
from utils.logger import get_logger
from ai.llm_client import LLMClient

logger = get_logger(__name__)


class ErrorHandler:
    """Handles error detection and recovery."""

    def __init__(self, page: Page, llm_client: LLMClient):
        """
        Initialize error handler.

        Args:
            page: Playwright page
            llm_client: LLM client for AI-assisted error resolution
        """
        self.page = page
        self.llm_client = llm_client

    async def detect_errors(self) -> List[Dict[str, Any]]:
        """
        Detect errors on the current page.

        Returns:
            List of detected errors with details
        """
        errors = []

        try:
            # Look for error messages
            error_selectors = [
                ".error-message",
                ".validation-error",
                ".field-error",
                ".alert-danger",
                "div.error",
                "span.error"
            ]

            for selector in error_selectors:
                elements = await self.page.query_selector_all(selector)

                for element in elements:
                    try:
                        # Get error text
                        text = await element.text_content()
                        if not text or text.strip() == "":
                            continue

                        # Try to find associated field
                        field_id = None
                        parent = await element.evaluate("el => el.closest('.form-group, .field-container')")

                        if parent:
                            # Try to get the field ID from an input, select, or textarea
                            field_element = await parent.evaluate("""
                                el => {
                                    const input = el.querySelector('input, select, textarea');
                                    return input ? {
                                        id: input.id || input.name,
                                        type: input.type || input.tagName.toLowerCase()
                                    } : null;
                                }
                            """)

                            if field_element:
                                field_id = field_element.get("id")
                                field_type = field_element.get("type")

                        # Add error to list
                        errors.append({
                            "message": text.strip(),
                            "field_id": field_id,
                            "field_type": field_type if field_id else None,
                            "selector": selector
                        })

                    except Exception as e:
                        logger.debug(f"Error processing error element: {str(e)}")
                        continue

            if errors:
                logger.warning(f"Detected {len(errors)} errors on page")

            return errors

        except Exception as e:
            logger.error(f"Error detecting form errors: {str(e)}")
            return []

    async def fix_errors(self, errors: List[Dict[str, Any]], form_state: Dict[str, Any]) -> bool:
        """
        Try to fix detected errors using AI.

        Args:
            errors: List of detected errors
            form_state: Current state of the form

        Returns:
            True if all errors were fixed, False otherwise
        """
        if not errors:
            return True

        try:
            logger.info(f"Attempting to fix {len(errors)} errors")

            # Prepare data for LLM
            error_data = []
            for error in errors:
                error_info = {
                    "message": error["message"],
                    "field_id": error["field_id"]
                }
                error_data.append(error_info)

            # Get AI suggestions
            ai_response = await self.llm_client.get_error_fixes(error_data, form_state)

            if not ai_response:
                logger.error("Failed to get AI suggestions for error fixes")
                return False

            # Apply fixes
            for field_id, fix_info in ai_response.items():
                try:
                    if isinstance(fix_info, dict):
                        value = fix_info.get("value", "")
                        reasoning = fix_info.get("reasoning", "")
                        logger.info(f"Fixing field {field_id}: {value} - Reason: {reasoning}")
                    else:
                        value = fix_info
                        logger.info(f"Fixing field {field_id}: {value}")

                    # Find the field type
                    field_error = next((e for e in errors if e.get("field_id") == field_id), None)
                    field_type = field_error.get("field_type", "text") if field_error else "text"

                    # Fill the field
                    selector = f"#{field_id}"

                    # Handle different field types
                    if field_type in ["checkbox", "radio"]:
                        if value in [True, "true", "True", "yes", "Yes", "1"]:
                            await self.page.check(selector)
                        else:
                            await self.page.uncheck(selector)
                    else:
                        await self.page.fill(selector, str(value))

                except Exception as e:
                    logger.error(f"Error applying fix for field {field_id}: {str(e)}")

            # Check if errors were fixed
            await self.page.wait_for_timeout(1000)  # Wait for any validation to occur
            remaining_errors = await self.detect_errors()

            if len(remaining_errors) < len(errors):
                logger.info(f"Fixed {len(errors) - len(remaining_errors)} errors, {len(remaining_errors)} remaining")
                return len(remaining_errors) == 0
            else:
                logger.warning("Failed to fix any errors")
                return False

        except Exception as e:
            logger.error(f"Error fixing form errors: {str(e)}")
            return False

    async def handle_system_error(self) -> bool:
        """
        Handle system errors by refreshing and trying again.

        Returns:
            True if handled successfully, False otherwise
        """
        try:
            # Check for system error messages
            system_error_selectors = [
                "text=system error",
                "text=unexpected error",
                "text=technical difficulties",
                "text=try again later"
            ]

            for selector in system_error_selectors:
                if await self._is_element_visible(selector, timeout=1000):
                    logger.warning(f"System error detected: {selector}")

                    # Take screenshot for debugging
                    await self.page.screenshot(path=f"system_error_{int(time.time())}.png")

                    # Refresh and try again
                    await self.page.reload()

                    # Wait for page to load
                    await self.page.wait_for_load_state("networkidle")

                    logger.info("Refreshed page after system error")
                    return True

            return False

        except Exception as e:
            logger.error(f"Error handling system error: {str(e)}")
            return False

    async def _is_element_visible(self, selector: str, timeout: int = 5000) -> bool:
        """Check if an element is visible on the page."""
        try:
            await self.page.wait_for_selector(selector, state="visible", timeout=timeout)
            return True
        except:
            return False