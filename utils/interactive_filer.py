import asyncio
import time
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime

from utils.logger import get_logger
from utils.form_capture import FormCapture
from core.browser_manager import BrowserManager
from core.navigation import Navigation
from core.form_filler import FormFiller
from core.error_handler import ErrorHandler
from ai.decision_maker import DecisionMaker

logger = get_logger(__name__)


class InteractiveFiler:
    """
    Handles interactive LCA filing with human input when needed.
    This extends the base LCAFiler to add interaction capabilities.
    """

    def __init__(self, lca_filer, interaction_callback: Callable = None):
        """
        Initialize interactive filer.

        Args:
            lca_filer: Base LCA filer instance
            interaction_callback: Callback function to handle required interactions
        """
        self.lca_filer = lca_filer
        self.interaction_callback = interaction_callback
        self.form_capture = None  # Will be created when needed
        self.pending_interaction = None
        self.interaction_results = {}
        self.interaction_completed = asyncio.Event()
        self.filing_paused = False

    async def start_interactive_filing(self, application_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start an interactive LCA filing process.

        Args:
            application_data: Application data

        Returns:
            Result dictionary
        """
        logger.info(f"Starting interactive LCA filing for application {application_data.get('id', 'unknown')}")

        # Initialize result
        filing_id = application_data.get('id', f"app_{int(time.time())}")
        result = {
            "application_id": filing_id,
            "generation_id": self.lca_filer.generation_id,
            "status": "started",
            "timestamp": datetime.now().isoformat(),
            "steps_completed": [],
            "interactions": []
        }

        try:
            # Create a new page
            page = await self.lca_filer.browser_manager.new_page()
            logger.info("Browser page created for interactive filing")

            # Initialize components
            navigation = Navigation(
                page,
                self.lca_filer.config.get("flag_portal"),
                self.lca_filer.browser_manager,
                self.lca_filer.two_factor_auth
            )
            form_filler = FormFiller(page, self.lca_filer.browser_manager, self.lca_filer.screenshot_manager)
            error_handler = ErrorHandler(
                page,
                self.lca_filer.llm_client,
                self.lca_filer.browser_manager,
                self.lca_filer.screenshot_manager
            )

            # Initialize form capture
            self.form_capture = FormCapture(page, self.lca_filer.screenshot_manager)

            # Navigate to FLAG portal
            logger.info("Navigating to FLAG portal")
            if not await navigation.goto_flag_portal():
                result["status"] = "navigation_failed"
                result["error"] = "Failed to navigate to FLAG portal"
                return result

            result["steps_completed"].append("navigation")
            logger.info("Successfully navigated to FLAG portal")

            # Login with 2FA if needed
            logger.info("Attempting login to FLAG portal")
            credentials = application_data.get("credentials",
                                               self.lca_filer.config.get("flag_portal", "credentials", default={}))

            if not await navigation.login(credentials):
                result["status"] = "login_failed"
                result["error"] = "Failed to login to FLAG portal"
                return result

            result["steps_completed"].append("login")
            logger.info("Successfully logged in to FLAG portal")

            # Navigate to new LCA form
            logger.info("Navigating to new LCA form")
            if not await navigation.navigate_to_new_lca():
                result["status"] = "navigation_failed"
                result["error"] = "Failed to navigate to new LCA form"
                return result

            result["steps_completed"].append("new_lca_navigation")
            logger.info("Successfully navigated to new LCA form")

            # Capture form elements on the first page
            first_page_elements = await self.form_capture.capture_current_section()
            logger.info(f"Captured {len(first_page_elements.get('elements', []))} elements on first page")

            # Select H-1B form type
            logger.info("Selecting H-1B form type")
            if not await navigation.select_form_type("H-1B"):
                result["status"] = "form_selection_failed"
                result["error"] = "Failed to select H-1B form type"
                return result

            result["steps_completed"].append("form_type_selection")
            logger.info("Successfully selected H-1B form type")

            # Now proceed through each section of the form
            # This will be similar to the base LCAFiler.file_lca method, but with interaction handling

            # Get decision maker for AI decisions
            decision_maker = self.lca_filer.decision_maker

            # Process each section with possible human interaction
            while True:
                # Check if we've reached the end (submission)
                if await self._check_if_submission_page(page):
                    logger.info("Reached submission page")
                    break

                # Capture current section
                section_data = await self.form_capture.capture_current_section()
                current_section = section_data["section_name"]
                logger.info(f"Processing section: {current_section}")

                # Check if this section requires human interaction
                interaction_needed = await self.form_capture.detect_interaction_required()
                if interaction_needed:
                    # We need human input for this section
                    logger.info(f"Human interaction required for section: {current_section}")

                    # Add to result history
                    result["interactions"].append({
                        "section": current_section,
                        "timestamp": datetime.now().isoformat(),
                        "fields": [field["id"] for field in interaction_needed["fields"]]
                    })

                    # Call interaction callback if provided
                    if self.interaction_callback:
                        self.filing_paused = True
                        self.pending_interaction = interaction_needed

                        # Clear previous event
                        self.interaction_completed.clear()

                        # Call the callback
                        self.interaction_callback(filing_id, interaction_needed)

                        # Wait for interaction to complete
                        logger.info("Waiting for human interaction...")
                        await self.interaction_completed.wait()
                        self.filing_paused = False

                        # Apply the interaction results to the form
                        if filing_id in self.interaction_results:
                            interaction_result = self.interaction_results[filing_id]
                            await self._apply_interaction_results(page, form_filler, interaction_result)
                            del self.interaction_results[filing_id]
                    else:
                        # No callback provided, can't continue
                        result["status"] = "interaction_required"
                        result["error"] = f"Human interaction required for section: {current_section}"
                        return result
                else:
                    # No interaction needed, use AI to fill the section
                    logger.info(f"Using AI to fill section: {current_section}")

                    # Get current form state
                    form_state = await self.form_capture.extract_form_state()

                    # Find corresponding section in form structure
                    # This is a simplified approach - in practice, you'd need to map
                    # the detected section to your form structure more robustly
                    from config.form_structure import FormStructure
                    section_def = None
                    for section in FormStructure.get_h1b_structure()["sections"]:
                        if current_section.lower() in section["name"].lower():
                            section_def = section
                            break

                    if not section_def:
                        logger.warning(f"Could not find section definition for: {current_section}")
                        # Create a generic section definition based on captured fields
                        section_def = {
                            "name": current_section,
                            "fields": [
                                {
                                    "id": element["id"],
                                    "type": element["type"],
                                    "required": element["required"]
                                }
                                for element in section_data["elements"]
                            ]
                        }

                    # Get AI decisions for this section
                    decisions = await decision_maker.get_decisions_for_section(section_def["name"], application_data)

                    # Fill the section
                    await form_filler.fill_section(section_def, decisions)

                # Check for errors
                errors = await error_handler.detect_errors()
                if errors:
                    logger.warning(f"Detected {len(errors)} errors in section {current_section}")

                    # Try to fix errors
                    form_state = await form_filler.get_form_state()
                    fixed = await error_handler.fix_errors(errors, form_state)

                    if not fixed:
                        # If errors couldn't be fixed, we need human interaction
                        logger.warning(f"Could not automatically fix errors in section {current_section}")

                        # Capture interaction data
                        interaction_needed = {
                            "section_name": current_section,
                            "screenshot_path": await self.lca_filer.screenshot_manager.take_screenshot(
                                page, f"errors_{current_section.lower().replace(' ', '_')}"
                            ),
                            "fields": section_data["elements"],
                            "error_messages": [error["message"] for error in errors],
                            "has_errors": True,
                            "guidance": "Please correct the following errors to continue processing."
                        }

                        # Add to result history
                        result["interactions"].append({
                            "section": current_section,
                            "timestamp": datetime.now().isoformat(),
                            "fields": [field["id"] for field in section_data["elements"]],
                            "errors": [error["message"] for error in errors]
                        })

                        # Call interaction callback if provided
                        if self.interaction_callback:
                            self.filing_paused = True
                            self.pending_interaction = interaction_needed

                            # Clear previous event
                            self.interaction_completed.clear()

                            # Call the callback
                            self.interaction_callback(filing_id, interaction_needed)

                            # Wait for interaction to complete
                            logger.info("Waiting for human interaction to fix errors...")
                            await self.interaction_completed.wait()
                            self.filing_paused = False

                            # Apply the interaction results to the form
                            if filing_id in self.interaction_results:
                                interaction_result = self.interaction_results[filing_id]
                                await self._apply_interaction_results(page, form_filler, interaction_result)
                                del self.interaction_results[filing_id]
                        else:
                            # No callback provided, can't continue
                            result["status"] = "error_correction_required"
                            result["error"] = f"Human interaction required to fix errors in section: {current_section}"
                            return result

                # Save and continue to next section
                logger.info(f"Saving section {current_section} and continuing")
                if not await navigation.save_and_continue():
                    logger.warning(f"Error saving section {current_section}")

                    # Check if there are validation errors
                    validation_error = await self._check_for_validation_errors(page)
                    if validation_error:
                        # Need human intervention
                        result["status"] = "validation_error"
                        result["error"] = f"Validation error in section {current_section}: {validation_error}"
                        return result

                    # Try to continue anyway
                    # You may want to implement additional recovery logic here

                result["steps_completed"].append(f"section_{current_section}")
                logger.info(f"Completed section: {current_section}")

            # Submit the final form
            logger.info("Submitting final LCA form")
            if not await navigation.submit_final():
                result["status"] = "submission_failed"
                result["error"] = "Failed to submit LCA form"
                return result

            result["steps_completed"].append("submission")
            logger.info("LCA form submitted successfully")

            # Get confirmation number
            confirmation_number = await navigation.get_confirmation_number()
            if confirmation_number:
                result["confirmation_number"] = confirmation_number
                result["status"] = "success"
                logger.info(f"Successfully filed LCA, confirmation number: {confirmation_number}")
            else:
                result["status"] = "confirmation_failed"
                result["error"] = "Failed to get confirmation number"
                logger.error("Failed to get confirmation number after submission")

            return result

        except Exception as e:
            logger.error(f"Error in interactive filing: {str(e)}")
            result["status"] = "error"
            result["error"] = str(e)
            return result

    def set_interaction_result(self, filing_id: str, interaction_result: Dict[str, Any]) -> None:
        """
        Set the result of a human interaction.

        Args:
            filing_id: Filing ID
            interaction_result: Dictionary with interaction results
        """
        logger.info(f"Received interaction result for filing {filing_id}")
        self.interaction_results[filing_id] = interaction_result
        self.interaction_completed.set()

    async def _apply_interaction_results(self, page, form_filler, interaction_result: Dict[str, Any]) -> None:
        """
        Apply human interaction results to the form.

        Args:
            page: Playwright page
            form_filler: Form filler instance
            interaction_result: Dictionary with interaction results
        """
        try:
            logger.info("Applying human interaction results to form")

            # Apply each field value
            for field_id, field_value in interaction_result.items():
                # Find the field type
                field_element = await page.query_selector(f"#{field_id}, [name='{field_id}']")
                if not field_element:
                    logger.warning(f"Field not found: {field_id}")
                    continue

                tag_name = await field_element.evaluate("el => el.tagName.toLowerCase()")
                field_type = await field_element.get_attribute("type") or tag_name

                # Fill the field
                await form_filler.fill_field(field_id, field_value, field_type)

            logger.info("Successfully applied interaction results")

        except Exception as e:
            logger.error(f"Error applying interaction results: {str(e)}")

    async def _check_if_submission_page(self, page) -> bool:
        """
        Check if the current page is the submission page.

        Args:
            page: Playwright page

        Returns:
            True if submission page, False otherwise
        """
        try:
            # Look for submission button or confirmation text
            submit_button = await page.query_selector("button:has-text('Submit'), button:has-text('Confirm')")
            if submit_button:
                # Check if there's text indicating this is the final review page
                review_indicators = [
                    "Review and Submit",
                    "Final Review",
                    "Submission",
                    "Declaration",
                    "Submit LCA"
                ]

                page_text = await page.content()
                if any(indicator in page_text for indicator in review_indicators):
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking if submission page: {str(e)}")
            return False

    async def _check_for_validation_errors(self, page) -> Optional[str]:
        """
        Check for validation errors on the page.

        Args:
            page: Playwright page

        Returns:
            Error message if found, None otherwise
        """
        try:
            # Look for error messages
            error_selectors = [
                ".error-message",
                ".validation-error",
                ".alert-danger",
                "[role='alert']",
                ".error-text"
            ]

            for selector in error_selectors:
                error_element = await page.query_selector(selector)
                if error_element:
                    error_text = await error_element.text_content()
                    if error_text:
                        return error_text.strip()

            return None

        except Exception as e:
            logger.error(f"Error checking for validation errors: {str(e)}")
            return None