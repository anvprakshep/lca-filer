# core/navigation.py
import asyncio
import time
import re
from typing import Dict, Any, Optional, List
from playwright.async_api import Page

from config.selectors import Selectors
from utils.logger import get_logger
from utils.captcha_solver import CaptchaSolver
from utils.authenticator import TwoFactorAuth

logger = get_logger(__name__)


class Navigation:
    """Handles navigation within the FLAG portal."""

    def __init__(self, page: Page, config: Dict[str, Any], two_factor_auth: Optional[TwoFactorAuth] = None):
        """
        Initialize navigation.

        Args:
            page: Playwright page
            config: Configuration dictionary
            two_factor_auth: Two-factor authentication handler
        """
        self.page = page
        self.config = config
        self.captcha_solver = CaptchaSolver(config.get("captcha", {}))
        self.two_factor_auth = two_factor_auth

    async def goto_flag_portal(self) -> bool:
        """
        Navigate to the FLAG portal.

        Returns:
            True if successful, False otherwise
        """
        try:
            url = self.config.get("url", "https://flag.dol.gov/")
            await self.page.goto(url)

            # Wait for page to load
            await self.page.wait_for_load_state("networkidle")

            logger.info(f"Navigated to FLAG portal: {url}")
            return True

        except Exception as e:
            logger.error(f"Error navigating to FLAG portal: {str(e)}")
            return False

    async def login(self, credentials: Dict[str, str]) -> bool:
        """
        Log in to the FLAG portal with two-factor authentication.

        Args:
            credentials: Dictionary with username and password

        Returns:
            True if login successful, False otherwise
        """
        try:
            # Wait for login form
            username_selector = Selectors.get("username_field")
            await self.page.wait_for_selector(username_selector, state="visible")

            # Fill credentials
            username = credentials.get("username", "")
            password = credentials.get("password", "")

            if not username or not password:
                logger.error("Missing username or password")
                return False

            await self.page.fill(username_selector, username)
            await self.page.fill(Selectors.get("password_field"), password)

            # Handle CAPTCHA if present
            captcha_selector = Selectors.get("captcha_image")
            if await self._is_element_visible(captcha_selector):
                if not await self._handle_captcha():
                    logger.error("Failed to solve CAPTCHA")
                    return False

            # Take screenshot before clicking login
            await self.page.screenshot(path="before_login.png")

            # Click login button
            login_button = Selectors.get("login_button")
            await self.page.click(login_button)

            # Wait for login to process
            await self.page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)  # Add a short delay to ensure page is fully loaded

            # Take a screenshot after initial login
            await self.page.screenshot(path="after_initial_login.png")

            # Check for two-factor authentication page using multiple possible selectors
            totp_detected = await self._detect_and_handle_totp(username)

            if totp_detected:
                logger.info("Two-factor authentication successfully handled")

            # Check for error message
            error_selector = Selectors.get("error_message")
            if await self._is_element_visible(error_selector, timeout=6000):
                error_text = await self.page.text_content(error_selector)
                logger.error(f"Login failed: {error_text}")
                return False

            # Take screenshot after login process
            await self.page.screenshot(path="after_complete_login.png")

            # Verify successful login by checking for dashboard elements
            dashboard_selector = Selectors.get("new_lca_button")
            login_success = await self._is_element_visible(dashboard_selector, timeout=10000)

            if login_success:
                logger.info("Login successful")
                return True
            else:
                logger.error("Login failed: Dashboard elements not found")
                return False

        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            await self.page.screenshot(path=f"login_error_{int(time.time())}.png")
            return False

    async def _detect_and_handle_totp(self, username: str) -> bool:
        """
        Detect and handle TOTP authentication.

        Args:
            username: Username for TOTP

        Returns:
            True if successfully handled, False otherwise
        """
        # Check for two-factor authentication page using various possible selectors
        totp_input_selectors = [
            "input[name='code'], input[name='totp'], #totpCode",
            "input[placeholder*='verification'], input[placeholder*='authentication']",
            "input[placeholder*='code'], input[aria-label*='code']",
            "input[id*='otp'], input[id*='2fa'], input[id*='totp']",
            "input[id*='token'], input[id*='authenticator'], input[id*='verification']"
        ]

        # For each selector, check if it's visible
        totp_input = None
        for selector in totp_input_selectors:
            elements = await self.page.query_selector_all(selector)
            for element in elements:
                if await element.is_visible():
                    totp_input = element
                    logger.info(f"Found TOTP input field: {selector}")
                    break
            if totp_input:
                break

        if not totp_input:
            # Check for text cues
            totp_text_cues = [
                "two-factor", "2fa", "verification code", "authentication code",
                "security code", "totp", "authenticator app"
            ]

            page_text = await self.page.content()
            page_text_lower = page_text.lower()

            found_cue = next((cue for cue in totp_text_cues if cue in page_text_lower), None)

            if found_cue:
                logger.info(f"TOTP prompt detected via text cue: {found_cue}")

                # Look for any input fields
                inputs = await self.page.query_selector_all(
                    "input[type='text'], input[type='number'], input:not([type])")
                visible_inputs = []

                for input_el in inputs:
                    if await input_el.is_visible():
                        visible_inputs.append(input_el)

                if visible_inputs:
                    totp_input = visible_inputs[0]  # Use the first visible input
                    logger.info("Found potential TOTP input field based on text cues")

        if totp_input:
            if not self.two_factor_auth:
                logger.error("Two-factor authentication required but not configured")
                return False

            # Generate TOTP code
            totp_code = self.two_factor_auth.generate_totp_code(username)
            print("ToTP code:", totp_code)
            if not totp_code:
                logger.error("Failed to generate TOTP code")
                return False

            logger.info(f"Generated TOTP code: {totp_code}")

            # Enter TOTP code
            await totp_input.fill(totp_code)

            # Find and click verify/submit button
            verify_button_selectors = [
                "button:has-text('Verify')",
                "button:has-text('Submit')",
                "button:has-text('Confirm')",
                "button:has-text('Continue')",
                "input[type='submit']",
                "button[type='submit']",
                "form button",  # Last resort: any button in a form
                "form input[type='button']"  # Last resort: any input button in a form
            ]

            verify_button = None
            for selector in verify_button_selectors:
                elements = await self.page.query_selector_all(selector)
                for element in elements:
                    if await element.is_visible():
                        verify_button = element
                        logger.info(f"Found verify button with selector: {selector}")
                        break
                if verify_button:
                    break

            if verify_button:
                await verify_button.click()
                logger.info("Clicked verify button after entering TOTP code")

                # Wait for verification to complete
                await self.page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)  # Short delay to ensure page has updated
                return True
            else:
                logger.warning("No verify button found after entering TOTP code")

                # Check if the form auto-submits on input
                await asyncio.sleep(3)  # Wait a bit to see if auto-submit happens

                # Take a screenshot to see the current state
                await self.page.screenshot(path="after_totp_no_button.png")

                # Check if we're past the TOTP page
                if not await self._is_totp_page():
                    logger.info("TOTP page auto-submitted successfully")
                    return True

        return False

    async def _is_totp_page(self) -> bool:
        """
        Check if we're currently on a TOTP input page.

        Returns:
            True if on TOTP page, False otherwise
        """
        # Check for TOTP input fields
        totp_input_selectors = [
            "input[name='code'], input[name='totp'], #totpCode",
            "input[placeholder*='verification'], input[placeholder*='authentication']",
            "input[id*='otp'], input[id*='2fa'], input[id*='totp']"
        ]

        for selector in totp_input_selectors:
            if await self._is_element_visible(selector, timeout=3000):
                return True

        # Check for text cues
        totp_text_cues = [
            "two-factor", "2fa", "verification code", "authentication code",
            "security code", "totp", "authenticator app"
        ]

        page_text = await self.page.content()
        page_text_lower = page_text.lower()

        for cue in totp_text_cues:
            if cue in page_text_lower:
                return True

        return False

    async def navigate_to_new_lca(self) -> bool:
        """
        Navigate to the new LCA form page.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Click on the new LCA button
            new_lca_selector = Selectors.get("new_lca_button")
            await self.page.click(new_lca_selector)

            # Wait for page to load
            await self.page.wait_for_load_state("networkidle")

            logger.info("Navigated to new LCA form")
            return True

        except Exception as e:
            logger.error(f"Error navigating to new LCA form: {str(e)}")
            return False

    async def select_form_type(self, form_type: str) -> bool:
        """
        Select the type of LCA form.

        Args:
            form_type: Form type (H-1B, H-1B1, E-3)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Find the radio button for the specified form type
            form_selector = f"input[type='radio'][value='{form_type}']"

            # Wait for the selector to be visible
            await self.page.wait_for_selector(form_selector, state="visible")

            # Click the radio button
            await self.page.click(form_selector)

            # Click continue button
            continue_selector = Selectors.get("continue_button")
            await self.page.click(continue_selector)

            # Wait for the next page to load
            await self.page.wait_for_load_state("networkidle")

            logger.info(f"Selected form type: {form_type}")
            return True

        except Exception as e:
            logger.error(f"Error selecting form type: {str(e)}")
            return False

    async def save_and_continue(self) -> bool:
        """
        Save the current section and continue to the next.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Click save button if available
            save_selector = Selectors.get("save_button")
            if await self._is_element_visible(save_selector):
                await self.page.click(save_selector)

                # Wait for save to complete
                await self.page.wait_for_load_state("networkidle")

                # Check for validation errors
                error_selector = Selectors.get("error_message")
                if await self._is_element_visible(error_selector, timeout=2000):
                    error_text = await self.page.text_content(error_selector)
                    logger.warning(f"Validation error after save: {error_text}")
                    # Continue anyway, error might be handled later

            # Click continue button
            continue_selector = Selectors.get("continue_button")
            if await self._is_element_visible(continue_selector):
                await self.page.click(continue_selector)

                # Wait for next page to load
                await self.page.wait_for_load_state("networkidle")

                logger.info("Saved and continued to next section")
                return True
            else:
                logger.warning("Continue button not found")
                return False

        except Exception as e:
            logger.error(f"Error saving and continuing: {str(e)}")
            return False

    async def submit_final(self) -> bool:
        """
        Submit the final LCA form.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Click submit button
            submit_selector = Selectors.get("submit_button")
            await self.page.click(submit_selector)

            # Wait for submission to complete
            await self.page.wait_for_load_state("networkidle")

            # Handle any final confirmations
            confirm_selector = "button:has-text('Confirm')"
            if await self._is_element_visible(confirm_selector, timeout=2000):
                await self.page.click(confirm_selector)
                await self.page.wait_for_load_state("networkidle")

            # Check for confirmation number
            confirmation_selector = Selectors.get("confirmation_number")
            confirmation_visible = await self._is_element_visible(confirmation_selector, timeout=10000)

            if confirmation_visible:
                logger.info("LCA successfully submitted")
                return True
            else:
                logger.error("LCA submission failed: Confirmation number not found")
                return False

        except Exception as e:
            logger.error(f"Error submitting LCA: {str(e)}")
            return False

    async def get_confirmation_number(self) -> Optional[str]:
        """
        Get the confirmation number after submission.

        Returns:
            Confirmation number or None if not found
        """
        try:
            confirmation_selector = Selectors.get("confirmation_number")

            if await self._is_element_visible(confirmation_selector):
                confirmation = await self.page.text_content(confirmation_selector)
                return confirmation.strip()
            else:
                logger.warning("Confirmation number not found")
                return None

        except Exception as e:
            logger.error(f"Error getting confirmation number: {str(e)}")
            return None

    async def _handle_captcha(self) -> bool:
        """
        Handle CAPTCHA verification.

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Handling CAPTCHA")

            # Get CAPTCHA image
            captcha_selector = Selectors.get("captcha_image")
            captcha_img = await self.page.query_selector(captcha_selector)

            if not captcha_img:
                logger.error("CAPTCHA image not found")
                return False

            # Take screenshot of CAPTCHA
            captcha_screenshot = await captcha_img.screenshot(path="captcha.png")

            # Solve CAPTCHA
            solution = await self.captcha_solver.solve("captcha.png")

            if not solution:
                logger.error("Failed to solve CAPTCHA")
                return False

            # Enter solution
            captcha_input_selector = Selectors.get("captcha_input")
            await self.page.fill(captcha_input_selector, solution)

            logger.info("CAPTCHA solution entered")
            return True

        except Exception as e:
            logger.error(f"Error handling CAPTCHA: {str(e)}")
            return False

    async def _is_element_visible(self, selector: str, timeout: int = 5000) -> bool:
        """Check if an element is visible on the page."""
        try:
            await self.page.wait_for_selector(selector, state="visible", timeout=timeout)
            return True
        except:
            return False

    async def handle_unexpected_navigation(self) -> bool:
        """
        Handle unexpected navigation events or popups.

        Returns:
            True if handled successfully, False otherwise
        """
        # Check for common interruptions
        try:
            # Session timeout warning
            if await self._is_element_visible("text=Your session will expire", timeout=1000):
                await self.page.click("button:has-text('Continue Session')")
                logger.info("Handled session timeout warning")
                return True

            # System maintenance notification
            if await self._is_element_visible("text=System Maintenance", timeout=1000):
                await self.page.click("button:has-text('Acknowledge')")
                logger.info("Handled system maintenance notification")
                return True

            # Unexpected error message
            if await self._is_element_visible("text=An unexpected error occurred", timeout=1000):
                logger.warning("Encountered system error message")
                # Take screenshot for debugging
                await self.page.screenshot(path=f"system_error_{int(time.time())}.png")
                return False

            return False

        except Exception as e:
            logger.error(f"Error handling unexpected navigation: {str(e)}")
            return False