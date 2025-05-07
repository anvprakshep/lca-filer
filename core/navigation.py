# core/navigation.py
import asyncio
import time
import re
from typing import Dict, Any, Optional, List
from playwright.async_api import Page, TimeoutError

from utils.logger import get_logger
from utils.captcha_solver import CaptchaSolver
from utils.authenticator import TwoFactorAuth
from utils.screenshot_manager import ScreenshotManager
from core.browser_manager import BrowserManager, ElementNotFoundError

logger = get_logger(__name__)


class Navigation:
    """Handles navigation within the FLAG portal with Login.gov support."""

    def __init__(self,
                 page: Page,
                 config: Dict[str, Any],
                 browser_manager: BrowserManager,
                 two_factor_auth: Optional[TwoFactorAuth] = None):
        """
        Initialize navigation.

        Args:
            page: Playwright page
            config: Configuration dictionary
            browser_manager: Browser manager for element handling
            two_factor_auth: Two-factor authentication handler
        """
        self.page = page
        self.config = config
        self.browser_manager = browser_manager
        self.captcha_solver = CaptchaSolver(config.get("captcha", {}))
        self.two_factor_auth = two_factor_auth
        self.screenshot_manager = ScreenshotManager()

        # XPath Selectors
        self.selectors = {
            # FLAG portal selectors - specific exact XPath for Sign In button
            "sign_in_button": "/html/body/div[1]/header/div[1]/div/div[2]/div/div/div/button[2]",
            "sign_in_button_alt": "//button[contains(text(), 'Sign In') or contains(@class, 'sign-in')]",

            # Login.gov selectors
            "login_gov_email": "//input[@id='user_email' or @name='user[email]']",
            "login_gov_password": "//input[@id='password' or @name='user[password]' or contains(@class, 'password-toggle__input')]",
            "login_gov_submit": "//button[@type='submit' or contains(text(), 'Sign in')]",
            "login_gov_totp_code": "//input[contains(@id, 'code') or contains(@name, 'code')]",
            "login_gov_totp_submit": "//button[@type='submit' or contains(text(), 'Submit')]",

            # FLAG portal navigation
            "new_application_button": "/html/body/div[1]/div/div[4]/div/aside/ul/li[1]/a",
            "new_lca_button": "#main-content > div > div > div > div.usa-application-container > div:nth-child(3) > div:nth-child(3) > p.usa-link > a",
            "new_lca_option": "#simple-modal > div.acknowledge-modal > div > div > button.usa-button.usa-button-outline-cancel",
            "continue_button": "//button[contains(text(), 'Continue')]",
            "save_button": "//button[contains(text(), 'Save')]",
            "submit_button": "//button[contains(text(), 'Submit')]",
            "confirm_button": "//button[contains(text(), 'Confirm')]",

            # Form type selection
            "h1b_radio": "//input[@type='radio' and @value='H-1B']",

            # Error messages
            "error_message": "//div[contains(@class, 'error') or contains(@class, 'alert')]",

            # Confirmation number
            "confirmation_number": "//span[contains(@id, 'confirmation') or contains(@class, 'confirmation')]"
        }

    async def goto_flag_portal(self) -> bool:
        """
        Navigate to the FLAG portal.

        Returns:
            True if successful, False otherwise
        """
        try:
            url = self.config.get("url", "https://flag.dol.gov/")

            # Check if page is still valid
            if self.page.is_closed():
                logger.error("Page is closed before navigation")
                return False

            # Add explicit wait before navigation
            await asyncio.sleep(1)

            # Use a longer timeout for initial navigation (30 seconds)
            await self.page.goto(url, timeout=30000, wait_until="load")

            # Wait for page to fully load
            try:
                await self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception as e:
                logger.warning(f"Timeout waiting for networkidle (continuing anyway): {str(e)}")

            # Take screenshot
            try:
                await self.screenshot_manager.take_screenshot(self.page, "flag_portal_home")
            except Exception as e:
                logger.warning(f"Error taking screenshot after navigation: {str(e)}")

            logger.info(f"Navigated to FLAG portal: {url}")
            return True

        except Exception as e:
            logger.error(f"Error navigating to FLAG portal: {str(e)}")
            try:
                await self.screenshot_manager.take_screenshot(self.page, "flag_portal_navigation_error")
            except Exception as screenshot_e:
                logger.warning(f"Could not take error screenshot: {str(screenshot_e)}")
            return False

    async def login(self, credentials: Dict[str, str]) -> bool:
        """
        Log in to the FLAG portal through Login.gov with two-factor authentication.

        Args:
            credentials: Dictionary with username and password

        Returns:
            True if login successful, False otherwise
        """
        try:
            # Look for the Sign In button
            logger.info("Looking for Sign In button on FLAG portal")
            await self.screenshot_manager.take_screenshot(self.page, "before_signin")

            # First try the exact XPath, then fallback to alternatives
            sign_in_clicked = False
            sign_in_selectors = [
                self.selectors["sign_in_button"],
                self.selectors["sign_in_button_alt"],
                "//button[contains(text(), 'Sign In')]",
                "//a[contains(text(), 'Sign In')]",
                "//button[contains(@class, 'sign-in')]",
                "//a[contains(@class, 'sign-in')]"
            ]

            for selector in sign_in_selectors:
                try:
                    if await self.browser_manager.is_element_visible(self.page, selector, timeout=2000):
                        await self.browser_manager.click_element(self.page, selector)
                        sign_in_clicked = True
                        logger.info(f"Clicked Sign In button using selector: {selector}")
                        break
                except Exception as e:
                    logger.debug(f"Error clicking sign-in with selector {selector}: {str(e)}")
                    continue

            if not sign_in_clicked:
                logger.warning("Could not find or click Sign In button - we might already be at login page")
                # Continue anyway - we might already be at the login page

            # Wait for page load
            await self.page.wait_for_load_state("networkidle")
            await self.screenshot_manager.take_screenshot(self.page, "after_signin_click")

            # Check if we need to log in - look for the login form
            email_field_visible = False
            try:
                email_field_visible = await self.browser_manager.is_element_visible(
                    self.page, self.selectors["login_gov_email"], timeout=5000
                )
            except Exception as e:
                logger.warning(f"Error checking for email field: {str(e)}")

            # If we're already logged in, we might be at the dashboard
            if not email_field_visible:
                # Check if we're already logged in
                dashboard_indicators = [
                    "//a[contains(text(), 'Dashboard')]",
                    "//h1[contains(text(), 'Dashboard')]",
                    "//div[contains(@class, 'dashboard')]",
                    self.selectors["new_lca_button"],
                    "//a[contains(text(), 'New Application')]"
                ]

                for indicator in dashboard_indicators:
                    try:
                        if await self.browser_manager.is_element_visible(self.page, indicator, timeout=2000):
                            logger.info("Already logged in and at dashboard")
                            await self.screenshot_manager.take_screenshot(self.page, "already_logged_in")
                            return True
                    except Exception:
                        continue

                # If we're not at the login page or dashboard, something's wrong
                logger.error("Not at login page or dashboard")
                await self.screenshot_manager.take_screenshot(self.page, "login_error_unknown_page")
                return False

            # We need to log in - extract credentials
            username = credentials.get("username", "")
            password = credentials.get("password", "")

            if not username or not password:
                logger.error("Missing username or password")
                return False

            # Fill email and password
            logger.info(f"Filling login credentials for {username}")
            try:
                await self.browser_manager.fill_element(self.page, self.selectors["login_gov_email"], username)
                await asyncio.sleep(0.5)  # Wait briefly for animations
                await self.browser_manager.fill_element(self.page, self.selectors["login_gov_password"], password)
            except Exception as e:
                logger.error(f"Error filling credentials: {str(e)}")
                await self.screenshot_manager.take_screenshot(self.page, "credential_fill_error")
                return False

            # Take screenshot before clicking login
            await self.screenshot_manager.take_screenshot(self.page, "before_login_submit")

            # Click login button
            login_button_clicked = False
            try:
                await self.browser_manager.click_element(self.page, self.selectors["login_gov_submit"])
                login_button_clicked = True
            except Exception as e:
                logger.warning(f"Error clicking login button: {str(e)}")
                # Try pressing Enter as fallback
                try:
                    await self.page.keyboard.press("Enter")
                    login_button_clicked = True
                    logger.info("Used Enter key to submit login")
                except Exception as enter_e:
                    logger.error(f"Error pressing Enter key: {str(enter_e)}")

            if not login_button_clicked:
                logger.error("Failed to submit login form")
                await self.screenshot_manager.take_screenshot(self.page, "login_submit_error")
                return False

            logger.info("Submitted login credentials")

            # Wait for login to process
            try:
                await self.page.wait_for_load_state("networkidle", timeout=10000)
                await asyncio.sleep(2)  # Additional wait for stability
            except Exception as e:
                logger.warning(f"Wait timeout after login (may be normal): {str(e)}")

            # Take a screenshot after login submission
            await self.screenshot_manager.take_screenshot(self.page, "after_login_submit")

            # Check for two-factor authentication
            logger.info("Checking for TOTP authentication")
            totp_detected = await self._detect_and_handle_totp(username)

            if totp_detected:
                logger.info("Two-factor authentication successfully handled")
            else:
                logger.info("No TOTP required or TOTP handling failed")

            # Take screenshot after complete login process
            await self.screenshot_manager.take_screenshot(self.page, "after_complete_login")

            # Check for successful login
            logger.info("Verifying successful login")

            # Check URL first
            if "flag.dol.gov" in self.page.url:
                logger.info(f"URL indicates successful login: {self.page.url}")
                return True

            # Look for dashboard elements as backup
            dashboard_indicators = [
                "//a[contains(text(), 'Dashboard')]",
                "//h1[contains(text(), 'Dashboard')]",
                "//div[contains(@class, 'dashboard')]",
                self.selectors["new_lca_button"],
                "//a[contains(text(), 'New Application')]",
                "//button[contains(text(), 'Log Out')]"
            ]

            for indicator in dashboard_indicators:
                try:
                    if await self.browser_manager.is_element_visible(self.page, indicator, timeout=2000):
                        logger.info(f"Found dashboard element: {indicator}")
                        return True
                except Exception:
                    continue

            # If we get here, login probably failed
            logger.error("Login verification failed - could not find dashboard elements")
            await self.screenshot_manager.take_screenshot(self.page, "login_verification_failed")
            return False

        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, f"login_error_{int(time.time())}")
            return False

    async def _detect_and_handle_totp(self, username: str) -> bool:
        """
        Detect and handle TOTP authentication.

        Args:
            username: Username for TOTP

        Returns:
            True if successfully handled, False otherwise
        """
        logger.info("Checking for TOTP authentication screen")

        # Take screenshot to help with debugging
        await self.screenshot_manager.take_screenshot(self.page, "before_totp_detection")

        # Wait for potential TOTP input field with a longer timeout (10 seconds)
        totp_input_visible = False
        totp_selectors = [
            self.selectors["login_gov_totp_code"],
            "//input[@id='code' or contains(@id, 'totp') or contains(@name, 'code')]",
            "//input[contains(@placeholder, 'code') or contains(@aria-label, 'code')]",
            "//input[contains(@class, 'mfa') or contains(@class, 'totp')]"
        ]

        # Try multiple possible selectors for TOTP input
        for selector in totp_selectors:
            try:
                totp_input_visible = await self.browser_manager.is_element_visible(
                    self.page, selector, timeout=2000
                )
                if totp_input_visible:
                    totp_input = await self.browser_manager.find_element(self.page, selector)
                    logger.info(f"Found TOTP input field with selector: {selector}")
                    break
            except Exception as e:
                logger.debug(f"Error checking selector {selector}: {str(e)}")
                continue

        if not totp_input_visible:
            # Check for text indicators of 2FA
            page_content = await self.page.content()
            page_text = await self.page.evaluate("() => document.body.textContent")

            # Log what we're seeing on the page for debugging
            logger.info(f"Current page URL: {self.page.url}")
            await self.screenshot_manager.take_screenshot(self.page, "possible_totp_page")

            totp_indicators = [
                "two-factor", "2fa", "verification code", "authentication code",
                "security code", "one-time code", "one time password", "authenticator",
                "enter the code", "6-digit code", "6 digit code", "enter code"
            ]

            has_totp_indicator = any(indicator.lower() in page_text.lower() for indicator in totp_indicators)

            if has_totp_indicator:
                logger.info("Found TOTP indicators in page text")
                # Try to find any input field if TOTP indicators are present
                try:
                    totp_input = await self.browser_manager.find_element(
                        self.page,
                        "//input[@type='text' or @type='number' or @type='tel' or not(@type)]"
                    )
                    totp_input_visible = True
                    logger.info("Found potential TOTP input field based on page content")
                except Exception as e:
                    logger.warning(f"TOTP indicators found but no input field detected: {str(e)}")
                    await self.screenshot_manager.take_screenshot(self.page, "totp_indicators_no_field")
                    return False
            else:
                logger.info("No TOTP authentication detected")
                return False

        # Generate TOTP code
        if not self.two_factor_auth:
            logger.error("Two-factor authentication required but not configured")
            await self.screenshot_manager.take_screenshot(self.page, "totp_required_not_configured")
            return False

        totp_code = self.two_factor_auth.generate_totp_code(username)
        if not totp_code:
            logger.error(f"Failed to generate TOTP code for username: {username}")
            await self.screenshot_manager.take_screenshot(self.page, "totp_generation_failed")
            return False

        logger.info(f"Generated TOTP code: {totp_code}")

        # Fill TOTP code
        try:
            await totp_input.fill(totp_code)
            logger.info("Filled in TOTP code")
            await self.screenshot_manager.take_screenshot(self.page, "totp_code_entered")
        except Exception as e:
            logger.error(f"Error filling TOTP input: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, "totp_fill_error")
            return False

        # Look for submit button with multiple possible selectors
        submit_selectors = [
            self.selectors["login_gov_totp_submit"],
            "//button[@type='submit']",
            "//button[contains(text(), 'Submit') or contains(text(), 'Verify') or contains(text(), 'Continue')]",
            "//input[@type='submit']"
        ]

        submit_button = None
        for selector in submit_selectors:
            try:
                if await self.browser_manager.is_element_visible(self.page, selector, timeout=1000):
                    submit_button = await self.browser_manager.find_element(self.page, selector)
                    logger.info(f"Found submit button with selector: {selector}")
                    break
            except Exception as e:
                logger.debug(f"Error checking submit button selector {selector}: {str(e)}")
                continue

        if submit_button:
            # Click submit button
            try:
                await submit_button.click()
                logger.info("Clicked TOTP submit button")
            except Exception as e:
                logger.error(f"Error clicking submit button: {str(e)}")
                await self.screenshot_manager.take_screenshot(self.page, "totp_submit_click_error")
                # Try pressing Enter key as fallback
                try:
                    await self.page.keyboard.press("Enter")
                    logger.info("Pressed Enter key to submit TOTP")
                except Exception as enter_e:
                    logger.error(f"Error pressing Enter key: {str(enter_e)}")
                    return False
        else:
            # Some Login.gov flows might auto-submit on input
            logger.info("No explicit TOTP submit button found, trying Enter key")
            try:
                await self.page.keyboard.press("Enter")
                logger.info("Pressed Enter key to submit TOTP")
            except Exception as e:
                logger.error(f"Error pressing Enter key: {str(e)}")
                # Still continue as some forms auto-submit

        # Wait for processing with longer timeout (15 seconds)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as e:
            logger.warning(f"Wait for load state timeout (may be normal): {str(e)}")

        # Add an additional wait to ensure the page has time to process
        await asyncio.sleep(5)

        # Take screenshot
        await self.screenshot_manager.take_screenshot(self.page, "after_totp_submission")

        # Check if we're still on the TOTP page
        still_on_totp = False
        for selector in totp_selectors:
            try:
                still_on_totp = await self.browser_manager.is_element_visible(
                    self.page, selector, timeout=2000
                )
                if still_on_totp:
                    break
            except Exception:
                continue

        if still_on_totp:
            logger.error("Still on TOTP page after submission, may have failed")
            await self.screenshot_manager.take_screenshot(self.page, "totp_submission_failed")
            return False

        logger.info("TOTP authentication successfully completed")
        return True

    async def navigate_to_new_lca(self) -> bool:
        """
        Navigate to the new LCA form page.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Click on the new LCA button
            await self.browser_manager.click_element(self.page, self.selectors["new_lca_button"])

            if await self.browser_manager.is_element_visible(self.page, self.selectors["new_lca_option"], timeout=2000):
                await self.browser_manager.click_element(self.page, self.selectors["new_lca_option"])
                await self.page.wait_for_load_state("networkidle")
                await self.screenshot_manager.take_screenshot(self.page, "new_lca_option")

            # Wait for page to load
            await self.page.wait_for_load_state("networkidle")
            await self.screenshot_manager.take_screenshot(self.page, "new_lca_page")

            logger.info("Navigated to new LCA form")
            return True

        except Exception as e:
            logger.error(f"Error navigating to new LCA form: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, "new_lca_navigation_error")
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
            radio_selector = f"//input[@type='radio' and @value='{form_type}']"

            # Wait for the selector to be visible
            await self.browser_manager.click_element(self.page, radio_selector)
            await self.screenshot_manager.take_screenshot(self.page, "form_type_selected")

            # Click continue button
            await self.browser_manager.click_element(self.page, self.selectors["continue_button"])

            # Wait for the next page to load
            await self.page.wait_for_load_state("networkidle")
            await self.screenshot_manager.take_screenshot(self.page, "after_form_type_selection")

            logger.info(f"Selected form type: {form_type}")
            return True

        except Exception as e:
            logger.error(f"Error selecting form type: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, "form_type_selection_error")
            return False

    async def save_and_continue(self) -> bool:
        """
        Save the current section and continue to the next.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Click save button if available
            if await self.browser_manager.is_element_visible(self.page, self.selectors["save_button"]):
                await self.browser_manager.click_element(self.page, self.selectors["save_button"])

                # Wait for save to complete
                await self.page.wait_for_load_state("networkidle")
                await self.screenshot_manager.take_screenshot(self.page, "after_save")

                # Check for validation errors
                if await self.browser_manager.is_element_visible(self.page, self.selectors["error_message"],
                                                                 timeout=2000):
                    error_element = await self.browser_manager.find_element(self.page, self.selectors["error_message"])
                    error_text = await error_element.text_content()
                    logger.warning(f"Validation error after save: {error_text}")
                    await self.screenshot_manager.take_screenshot(self.page, "validation_error_after_save")
                    # Continue anyway, error might be handled later

            # Click continue button
            if await self.browser_manager.is_element_visible(self.page, self.selectors["continue_button"]):
                await self.browser_manager.click_element(self.page, self.selectors["continue_button"])

                # Wait for next page to load
                await self.page.wait_for_load_state("networkidle")
                await self.screenshot_manager.take_screenshot(self.page, "after_continue")

                logger.info("Saved and continued to next section")
                return True
            else:
                logger.warning("Continue button not found")
                await self.screenshot_manager.take_screenshot(self.page, "continue_button_not_found")
                return False

        except Exception as e:
            logger.error(f"Error saving and continuing: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, "save_continue_error")
            return False

    async def submit_final(self) -> bool:
        """
        Submit the final LCA form.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Click submit button
            await self.browser_manager.click_element(self.page, self.selectors["submit_button"])

            # Wait for submission to complete
            await self.page.wait_for_load_state("networkidle")
            await self.screenshot_manager.take_screenshot(self.page, "after_submit")

            # Handle any final confirmations
            if await self.browser_manager.is_element_visible(self.page, self.selectors["confirm_button"], timeout=2000):
                await self.browser_manager.click_element(self.page, self.selectors["confirm_button"])
                await self.page.wait_for_load_state("networkidle")
                await self.screenshot_manager.take_screenshot(self.page, "after_confirm")

            # Check for confirmation number
            confirmation_visible = await self.browser_manager.is_element_visible(
                self.page,
                self.selectors["confirmation_number"],
                timeout=10000
            )

            if confirmation_visible:
                logger.info("LCA successfully submitted")
                await self.screenshot_manager.take_screenshot(self.page, "submission_success")
                return True
            else:
                logger.error("LCA submission failed: Confirmation number not found")
                await self.screenshot_manager.take_screenshot(self.page, "submission_failure")
                return False

        except Exception as e:
            logger.error(f"Error submitting LCA: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, "submission_error")
            return False

    async def get_confirmation_number(self) -> Optional[str]:
        """
        Get the confirmation number after submission.

        Returns:
            Confirmation number or None if not found
        """
        try:
            if await self.browser_manager.is_element_visible(self.page, self.selectors["confirmation_number"]):
                element = await self.browser_manager.find_element(self.page, self.selectors["confirmation_number"])
                confirmation = await element.text_content()
                return confirmation.strip()
            else:
                logger.warning("Confirmation number not found")
                await self.screenshot_manager.take_screenshot(self.page, "no_confirmation_number")
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
            captcha_selector = "//img[contains(@alt, 'CAPTCHA') or contains(@src, 'captcha')]"

            try:
                captcha_img = await self.browser_manager.find_element(self.page, captcha_selector)
            except ElementNotFoundError:
                logger.error("CAPTCHA image not found")
                await self.screenshot_manager.take_screenshot(self.page, "captcha_not_found")
                return False

            # Take screenshot of CAPTCHA
            captcha_screenshot = await captcha_img.screenshot(path="captcha.png")

            # Solve CAPTCHA
            solution = await self.captcha_solver.solve("captcha.png")

            if not solution:
                logger.error("Failed to solve CAPTCHA")
                return False

            # Enter solution
            captcha_input_selector = "//input[contains(@id, 'captcha') or contains(@name, 'captcha')]"
            await self.browser_manager.fill_element(self.page, captcha_input_selector, solution)

            logger.info("CAPTCHA solution entered")
            await self.screenshot_manager.take_screenshot(self.page, "captcha_solution_entered")
            return True

        except Exception as e:
            logger.error(f"Error handling CAPTCHA: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, "captcha_error")
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
            session_timeout_selector = "//div[contains(text(), 'Your session will expire') or contains(., 'Session timeout')]"
            if await self.browser_manager.is_element_visible(self.page, session_timeout_selector, timeout=1000):
                continue_session_selector = "//button[contains(text(), 'Continue Session')]"
                await self.browser_manager.click_element(self.page, continue_session_selector)
                logger.info("Handled session timeout warning")
                await self.screenshot_manager.take_screenshot(self.page, "session_timeout_handled")
                return True

            # System maintenance notification
            maintenance_selector = "//div[contains(text(), 'System Maintenance') or contains(., 'maintenance')]"
            if await self.browser_manager.is_element_visible(self.page, maintenance_selector, timeout=1000):
                acknowledge_selector = "//button[contains(text(), 'Acknowledge') or contains(text(), 'OK')]"
                await self.browser_manager.click_element(self.page, acknowledge_selector)
                logger.info("Handled system maintenance notification")
                await self.screenshot_manager.take_screenshot(self.page, "maintenance_notification_handled")
                return True

            # Unexpected error message
            error_selector = "//div[contains(text(), 'unexpected error') or contains(., 'system error')]"
            if await self.browser_manager.is_element_visible(self.page, error_selector, timeout=1000):
                logger.warning("Encountered system error message")
                await self.screenshot_manager.take_screenshot(self.page, f"system_error_{int(time.time())}")
                return False

            return False

        except Exception as e:
            logger.error(f"Error handling unexpected navigation: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, "unexpected_navigation_error")
            return False