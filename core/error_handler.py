# core/error_handler.py
import asyncio
import time
import json
import re
from typing import Dict, Any, List, Optional, Tuple
from playwright.async_api import Page

from utils.logger import get_logger
from utils.screenshot_manager import ScreenshotManager
from core.browser_manager import BrowserManager, ElementNotFoundError
from ai.llm_client import LLMClient

logger = get_logger(__name__)


class ErrorHandler:
    """Handles error detection and recovery with improved XPath support."""

    def __init__(self,
                 page: Page,
                 llm_client: LLMClient,
                 browser_manager: BrowserManager,
                 screenshot_manager: ScreenshotManager):
        """
        Initialize error handler.

        Args:
            page: Playwright page
            llm_client: LLM client for AI-assisted error resolution
            browser_manager: Browser manager for element interactions
            screenshot_manager: Screenshot manager for capturing error state
        """
        self.page = page
        self.llm_client = llm_client
        self.browser_manager = browser_manager
        self.screenshot_manager = screenshot_manager

        # XPath selectors for error messages
        self.error_selectors = [
            "//div[contains(@class, 'error-message') or contains(@class, 'errorMessage')]",
            "//div[contains(@class, 'validation-error') or contains(@class, 'validationError')]",
            "//div[contains(@class, 'field-error') or contains(@class, 'fieldError')]",
            "//div[contains(@class, 'alert-danger') or contains(@class, 'alertDanger')]",
            "//span[contains(@class, 'error') or contains(@class, 'invalid')]",
            "//p[contains(@class, 'error') or contains(@class, 'invalid')]",
            "//div[contains(@class, 'error') or contains(@class, 'invalid')]",
            "//label[contains(@class, 'error') or contains(@class, 'invalid')]",
            "//*[contains(@aria-invalid, 'true')]"
        ]

    async def detect_errors(self) -> List[Dict[str, Any]]:
        """
        Detect errors on the current page.

        Returns:
            List of detected errors with details
        """
        errors = []

        try:
            logger.info("Searching for form errors on the page")

            # Take screenshot before error detection
            await self.screenshot_manager.take_screenshot(self.page, "before_error_detection")

            # Check each error selector
            for selector in self.error_selectors:
                try:
                    # Find all elements matching this error selector
                    elements = await self.page.query_selector_all(selector)

                    for element in elements:
                        try:
                            # Get error text
                            text = await element.text_content()
                            if not text or text.strip() == "":
                                continue

                            # Try to find associated field
                            field_id = None
                            field_type = None

                            # Method 1: Check for parent form-group with input
                            try:
                                parent = await element.evaluate("""
                                    el => {
                                        let parent = el.closest('.form-group, .field-container, .input-group');
                                        return parent ? parent.outerHTML : null;
                                    }
                                """)

                                if parent:
                                    # Parse the HTML to find input elements
                                    input_match = re.search(r'<(input|select|textarea)[^>]*id=["\']([^"\']+)["\']',
                                                            parent)
                                    if input_match:
                                        field_id = input_match.group(2)
                                        field_type = input_match.group(1)
                                    else:
                                        # Try by name attribute
                                        input_match = re.search(
                                            r'<(input|select|textarea)[^>]*name=["\']([^"\']+)["\']', parent)
                                        if input_match:
                                            field_id = input_match.group(2)
                                            field_type = input_match.group(1)
                            except Exception as e:
                                logger.debug(f"Error finding parent form group: {str(e)}")

                            # Method 2: Check for data-for or aria-describedby attributes
                            if not field_id:
                                try:
                                    data_for = await element.get_attribute("data-for") or \
                                               await element.get_attribute("aria-describedby") or \
                                               await element.get_attribute("for")

                                    if data_for:
                                        field_id = data_for
                                        # Try to find the element type
                                        try:
                                            field_element = await self.page.query_selector(f"#{data_for}")
                                            if field_element:
                                                tag_name = await field_element.evaluate(
                                                    "el => el.tagName.toLowerCase()")
                                                field_type = tag_name
                                        except:
                                            field_type = "unknown"
                                except Exception as e:
                                    logger.debug(f"Error checking data-for attribute: {str(e)}")

                            # Method 3: Check for nearby input with similar ID or name
                            if not field_id:
                                try:
                                    # Get all nearby inputs
                                    nearby_inputs = await self.page.evaluate("""
                                        (errorEl) => {
                                            // Get bounding rect of error element
                                            const errorRect = errorEl.getBoundingClientRect();

                                            // Find all form elements
                                            const inputs = Array.from(document.querySelectorAll('input, select, textarea'));

                                            // Get elements that are close to the error
                                            return inputs
                                                .filter(input => {
                                                    const inputRect = input.getBoundingClientRect();
                                                    // Check if input is above or to the left of error
                                                    return (
                                                        (Math.abs(inputRect.left - errorRect.left) < 100 && inputRect.top < errorRect.top) ||
                                                        (Math.abs(inputRect.top - errorRect.top) < 50)
                                                    );
                                                })
                                                .map(input => ({
                                                    id: input.id,
                                                    name: input.name,
                                                    type: input.type || input.tagName.toLowerCase()
                                                }));
                                        }
                                    """, element)

                                    if nearby_inputs and len(nearby_inputs) > 0:
                                        closest_input = nearby_inputs[0]
                                        field_id = closest_input.get("id") or closest_input.get("name")
                                        field_type = closest_input.get("type")
                                except Exception as e:
                                    logger.debug(f"Error finding nearby inputs: {str(e)}")

                            # Add error to list
                            error_info = {
                                "message": text.strip(),
                                "field_id": field_id,
                                "field_type": field_type,
                                "selector": selector
                            }

                            errors.append(error_info)
                            logger.warning(f"Detected error: {text.strip()} (field: {field_id})")

                            # Take screenshot of the error element
                            if field_id:
                                await self.screenshot_manager.take_element_screenshot(
                                    self.page,
                                    f"//*[@id='{field_id}']",
                                    f"error_field_{field_id}"
                                )

                        except Exception as e:
                            logger.debug(f"Error processing error element: {str(e)}")
                            continue
                except Exception as e:
                    logger.debug(f"Error querying selector {selector}: {str(e)}")
                    continue

            if errors:
                logger.warning(f"Detected {len(errors)} errors on page")
                await self.screenshot_manager.take_screenshot(self.page, "errors_detected")
            else:
                logger.info("No errors detected on page")

            return errors

        except Exception as e:
            logger.error(f"Error detecting form errors: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, "error_detection_failure")
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

            # Take screenshot before fixing
            await self.screenshot_manager.take_screenshot(self.page, "before_error_fixing")

            # Prepare data for LLM
            error_data = []
            for error in errors:
                error_info = {
                    "message": error["message"],
                    "field_id": error["field_id"],
                    "field_type": error["field_type"]
                }
                error_data.append(error_info)

            # Get AI suggestions
            ai_response = await self.llm_client.get_error_fixes(error_data, form_state)

            if not ai_response:
                logger.error("Failed to get AI suggestions for error fixes")
                return False

            # Apply fixes
            fixes_applied = 0
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

                    # Create XPath selector
                    if field_id.startswith("//"):
                        # Already an XPath
                        selector = field_id
                    else:
                        # Create XPath based on ID or name
                        selector = f"//*[@id='{field_id}' or @name='{field_id}']"

                    # Handle different field types
                    if field_type in ["checkbox", "radio"]:
                        should_check = value in [True, "true", "True", "yes", "Yes", "1"]

                        if field_type == "radio":
                            # For radio buttons, we need to find the specific option
                            option_selector = f"{selector}[@value='{value}']"
                            try:
                                await self.browser_manager.click_element(self.page, option_selector)
                                fixes_applied += 1
                            except ElementNotFoundError:
                                # Try with name-based selector for radio group
                                group_selector = f"//input[@type='radio' and @name='{field_id}' and @value='{value}']"
                                await self.browser_manager.click_element(self.page, group_selector)
                                fixes_applied += 1
                        else:
                            # For checkboxes
                            try:
                                element = await self.browser_manager.find_element(self.page, selector)
                                is_checked = await element.is_checked()

                                # Only click if we need to change state
                                if is_checked != should_check:
                                    await element.click()
                                    fixes_applied += 1
                            except ElementNotFoundError:
                                logger.warning(f"Checkbox not found: {selector}")
                    else:
                        # For text inputs, select, etc.
                        try:
                            await self.browser_manager.fill_element(self.page, selector, str(value))
                            fixes_applied += 1
                        except ElementNotFoundError:
                            logger.warning(f"Field not found: {selector}")

                    # Take screenshot after fixing field
                    await self.screenshot_manager.take_screenshot(self.page, f"after_fixing_{field_id}")

                except Exception as e:
                    logger.error(f"Error applying fix for field {field_id}: {str(e)}")

            # Check if errors were fixed
            await self.page.wait_for_timeout(1000)  # Wait for any validation to occur
            remaining_errors = await self.detect_errors()

            # Take final screenshot
            await self.screenshot_manager.take_screenshot(self.page, "after_error_fixing")

            if len(remaining_errors) < len(errors):
                logger.info(f"Fixed {len(errors) - len(remaining_errors)} errors, {len(remaining_errors)} remaining")
                return len(remaining_errors) == 0
            else:
                logger.warning("Failed to fix any errors")
                return False

        except Exception as e:
            logger.error(f"Error fixing form errors: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, "error_fixing_failure")
            return False

    async def handle_system_error(self) -> bool:
        """
        Handle system errors by refreshing and trying again.

        Returns:
            True if handled successfully, False otherwise
        """
        try:
            # Check for system error messages using XPath
            system_error_selectors = [
                "//div[contains(text(), 'system error') or contains(., 'system error')]",
                "//div[contains(text(), 'unexpected error') or contains(., 'unexpected error')]",
                "//div[contains(text(), 'technical difficulties') or contains(., 'technical difficulties')]",
                "//div[contains(text(), 'try again later') or contains(., 'try again later')]",
                "//div[contains(@class, 'system-error') or contains(@class, 'systemError')]",
                "//div[contains(@class, 'error-page') or contains(@class, 'errorPage')]"
            ]

            for selector in system_error_selectors:
                try:
                    if await self.browser_manager.is_element_visible(self.page, selector, timeout=1000):
                        logger.warning(f"System error detected: {selector}")

                        # Take screenshot for debugging
                        await self.screenshot_manager.take_screenshot(self.page, f"system_error_{int(time.time())}")

                        # Refresh and try again
                        await self.page.reload()

                        # Wait for page to load
                        await self.page.wait_for_load_state("networkidle")

                        logger.info("Refreshed page after system error")
                        await self.screenshot_manager.take_screenshot(self.page, "after_system_error_refresh")
                        return True
                except ElementNotFoundError:
                    continue

            return False

        except Exception as e:
            logger.error(f"Error handling system error: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, "system_error_handling_failure")
            return False

    async def check_for_validation_errors(self) -> Dict[str, Any]:
        """
        Check for validation errors and create a structured report.

        Returns:
            Dictionary with validation error information
        """
        errors = await self.detect_errors()

        if not errors:
            return {
                "has_errors": False,
                "count": 0,
                "errors": []
            }

        # Group errors by field
        field_errors = {}
        general_errors = []

        for error in errors:
            field_id = error.get("field_id")
            if field_id:
                if field_id not in field_errors:
                    field_errors[field_id] = []
                field_errors[field_id].append(error["message"])
            else:
                general_errors.append(error["message"])

        # Create structured report
        error_report = {
            "has_errors": True,
            "count": len(errors),
            "field_errors": field_errors,
            "general_errors": general_errors,
            "errors": errors  # Raw error data
        }

        return error_report

    async def attempt_auto_fix(self, max_attempts: int = 3) -> Dict[str, Any]:
        """
        Attempt to automatically fix errors with multiple attempts.

        Args:
            max_attempts: Maximum number of fix attempts

        Returns:
            Dictionary with fix results
        """
        results = {
            "initial_errors": 0,
            "remaining_errors": 0,
            "attempts": 0,
            "fixed": False,
            "fixed_fields": []
        }

        # Get initial errors
        initial_errors = await self.detect_errors()
        results["initial_errors"] = len(initial_errors)

        if not initial_errors:
            results["fixed"] = True
            return results

        # Get current form state
        form_state = {}
        try:
            # This would typically be provided by form_filler.get_form_state()
            # For now we'll just use empty dictionary
            form_state = {}
        except Exception as e:
            logger.error(f"Error getting form state: {str(e)}")

        # Track fixed fields across attempts
        fixed_fields = set()

        # Multiple fix attempts
        remaining_errors = initial_errors
        for attempt in range(1, max_attempts + 1):
            results["attempts"] = attempt

            if not remaining_errors:
                break

            logger.info(f"Auto-fix attempt {attempt} of {max_attempts} for {len(remaining_errors)} errors")

            # Try to fix errors
            await self.fix_errors(remaining_errors, form_state)

            # Check which errors were fixed
            new_errors = await self.detect_errors()

            # Find fixed fields in this attempt
            old_error_fields = {e.get("field_id") for e in remaining_errors if e.get("field_id")}
            new_error_fields = {e.get("field_id") for e in new_errors if e.get("field_id")}
            newly_fixed = old_error_fields - new_error_fields
            fixed_fields.update(newly_fixed)

            # Update remaining errors
            remaining_errors = new_errors

            # Take a screenshot after this attempt
            await self.screenshot_manager.take_screenshot(self.page, f"autofix_attempt_{attempt}")

            if not remaining_errors:
                logger.info(f"All errors fixed on attempt {attempt}")
                break

            logger.info(f"After attempt {attempt}: {len(remaining_errors)} errors remain")

        # Final results
        results["remaining_errors"] = len(remaining_errors)
        results["fixed"] = len(remaining_errors) == 0
        results["fixed_fields"] = list(fixed_fields)

        return results