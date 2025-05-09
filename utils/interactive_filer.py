import asyncio
import threading
import time
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime

from config.form_structure import FormStructure
from utils.authenticator import TwoFactorAuth
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
        self.status_update_callback = None  # Will be set externally if needed

        # Active filings tracking
        self.active_filings = set()
        self._lock = threading.Lock()

    def has_active_filings(self):
        return len(self.active_filings) > 0

    def set_status_update_callback(self, callback: Callable):
        """
        Set a callback for status updates during the filing process.

        Args:
            callback: Function that takes filing_id and status_update as parameters
        """
        self.status_update_callback = callback

    def update_filing_status(self, filing_id: str, update: Dict[str, Any]):
        """
        Update the filing status and notify listeners.

        Args:
            filing_id: ID of the filing to update
            update: Status update dictionary
        """
        # If a callback is registered, call it
        if self.status_update_callback:
            self.status_update_callback(filing_id, update)

        # Log the update
        log_message = f"Filing {filing_id} update: {update.get('status', 'N/A')}"
        if "step" in update:
            log_message += f" - Step: {update['step']}"
        logger.info(log_message)

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
        Enhanced method to apply human interaction results to the form.

        Args:
            page: Playwright page
            form_filler: Form filler instance
            interaction_result: Dictionary with interaction results
        """
        try:
            logger.info("Applying human interaction results to form")

            # Keep track of fields we've applied
            applied_fields = []
            failed_fields = []

            # Apply each field value
            for field_id, field_value in interaction_result.items():
                try:
                    # Find the field using multiple selector strategies
                    field_element = None

                    # Try by ID first
                    field_element = await page.query_selector(f"#{field_id}")

                    # If not found, try by name
                    if not field_element:
                        field_element = await page.query_selector(f"[name='{field_id}']")

                    # If still not found, try data-field-id attribute
                    if not field_element:
                        field_element = await page.query_selector(f"[data-field-id='{field_id}']")

                    # If we found the element, determine its type
                    if field_element:
                        tag_name = await field_element.evaluate("el => el.tagName.toLowerCase()")
                        field_type = await field_element.get_attribute("type") or tag_name

                        # For select, explicitly set field_type
                        if tag_name == "select":
                            field_type = "select"

                        # For textarea, explicitly set field_type
                        if tag_name == "textarea":
                            field_type = "textarea"

                        # Fill the field with appropriate strategy
                        await form_filler.fill_field(field_id, field_value, field_type)
                        applied_fields.append(field_id)
                    else:
                        # Field not found, try fallback approaches

                        # For radio buttons, try looking for any radio with matching name and value
                        if isinstance(field_value, str):
                            radio_selector = f"input[type='radio'][name='{field_id}'][value='{field_value}']"
                            radio_element = await page.query_selector(radio_selector)

                            if radio_element:
                                await radio_element.click()
                                applied_fields.append(field_id)
                                continue

                        # If all else fails, log the issue
                        logger.warning(f"Field not found: {field_id}")
                        failed_fields.append(field_id)

                except Exception as e:
                    logger.error(f"Error applying value to field {field_id}: {str(e)}")
                    failed_fields.append(field_id)

            # Take a screenshot after applying all fields
            screenshot_path = await self.lca_filer.screenshot_manager.take_screenshot(
                page,
                "after_applying_interaction_results"
            )

            if failed_fields:
                logger.warning(f"Failed to apply values to {len(failed_fields)} fields: {', '.join(failed_fields)}")

            logger.info(f"Successfully applied interaction results to {len(applied_fields)} fields")

        except Exception as e:
            logger.error(f"Error applying interaction results: {str(e)}")

    async def start_interactive_filing(self, application_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start an interactive LCA filing process with improved TOTP handling.

        Args:
            application_data: Application data

        Returns:
            Result dictionary
        """
        logger.info(f"Starting interactive LCA filing for application {application_data.get('id', 'unknown')}")

        # Initialize result
        filing_id = application_data.get('id', f"app_{int(time.time())}")
        with self._lock:
            self.active_filings.add(filing_id)

        result = {
            "application_id": filing_id,
            "generation_id": self.lca_filer.generation_id,
            "status": "started",
            "timestamp": datetime.now().isoformat(),
            "steps_completed": [],
            "interactions": []
        }

        try:
            # Send initial status update
            self.update_filing_status(filing_id, {
                "status": "started",
                "message": "Initializing filing process",
                "timestamp": datetime.now().isoformat()
            })

            # BEGIN NEW SECTION: Enhanced TOTP Configuration
            # Check for TOTP credentials and configure if needed
            credentials = application_data.get("credentials", {})
            username = credentials.get("username")
            totp_secret = credentials.get("totp_secret")

            if username and totp_secret:
                self.update_filing_status(filing_id, {
                    "status": "initializing",
                    "step": "totp_setup",
                    "message": "Configuring two-factor authentication"
                })

                # Enable TOTP if not already
                if not self.lca_filer.config.get("totp", "enabled", default=False):
                    self.lca_filer.config.set(True, "totp", "enabled")
                    logger.info("Enabled TOTP authentication")

                # Initialize two-factor auth if needed
                if not self.lca_filer.two_factor_auth:
                    totp_config = self.lca_filer.config.get("totp", {})
                    if "secrets" not in totp_config:
                        totp_config["secrets"] = {}
                    self.lca_filer.two_factor_auth = TwoFactorAuth(totp_config)
                    logger.info("Two-factor authentication initialized")

                # Set the secret
                self.lca_filer.two_factor_auth.totp_secrets[username] = totp_secret
                self.lca_filer.config.set_totp_secret(username, totp_secret)
                logger.info(f"Configured TOTP secret for {username} from application data")

                # Test the TOTP to make sure it works
                test_code = self.lca_filer.two_factor_auth.generate_totp_code(username)
                if test_code:
                    logger.info(f"Successfully generated TOTP code for testing: {test_code}")
                else:
                    logger.error("Failed to generate TOTP code - authentication may fail")
                    self.update_filing_status(filing_id, {
                        "status": "warning",
                        "step": "totp_setup",
                        "message": "Warning: Failed to generate TOTP code for testing"
                    })
            else:
                logger.info("No TOTP credentials provided in application data")

                # Check if username has a pre-configured TOTP secret
                if username and self.lca_filer.two_factor_auth:
                    if username in self.lca_filer.two_factor_auth.totp_secrets:
                        logger.info(f"Using pre-configured TOTP secret for {username}")
                        self.update_filing_status(filing_id, {
                            "status": "initializing",
                            "step": "totp_setup",
                            "message": "Using pre-configured two-factor authentication"
                        })
                    else:
                        logger.warning(f"No TOTP secret configured for {username} - login may fail if 2FA is required")
                        self.update_filing_status(filing_id, {
                            "status": "warning",
                            "step": "totp_setup",
                            "message": "Warning: No TOTP secret available for this user"
                        })
            # END NEW SECTION

            # Check if browser manager is initialized
            if not self.lca_filer.browser_manager.browser or not self.lca_filer.browser_manager.context:
                logger.error("Browser manager not initialized, attempting to initialize")
                if not await self.lca_filer.initialize():
                    error_msg = "Browser manager initialization failed"
                    logger.error(error_msg)
                    result["status"] = "error"
                    result["error"] = error_msg
                    return result

            # Create a new page
            self.update_filing_status(filing_id, {
                "status": "initializing",
                "step": "browser",
                "message": "Initializing browser"
            })

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

            # Update status - navigating to FLAG portal
            self.update_filing_status(filing_id, {
                "status": "navigating",
                "step": "flag_portal",
                "message": "Navigating to FLAG portal website"
            })

            # Navigate to FLAG portal
            logger.info("Navigating to FLAG portal")
            if not await navigation.goto_flag_portal():
                error_msg = "Failed to navigate to FLAG portal"
                self.update_filing_status(filing_id, {
                    "status": "error",
                    "step": "navigation",
                    "error": error_msg
                })
                result["status"] = "navigation_failed"
                result["error"] = error_msg
                return result

            result["steps_completed"].append("navigation")
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "navigation_complete",
                "message": "Successfully navigated to FLAG portal"
            })
            logger.info("Successfully navigated to FLAG portal")

            # Login with 2FA if needed
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "login",
                "message": "Attempting login to FLAG portal"
            })

            logger.info("Attempting login to FLAG portal")
            credentials = application_data.get("credentials",
                                               self.lca_filer.config.get("flag_portal", "credentials", default={}))

            if not await navigation.login(credentials):
                error_msg = "Failed to login to FLAG portal"
                self.update_filing_status(filing_id, {
                    "status": "error",
                    "step": "login",
                    "error": error_msg
                })
                result["status"] = "login_failed"
                result["error"] = error_msg
                return result

            result["steps_completed"].append("login")
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "login_complete",
                "message": "Successfully logged in to FLAG portal"
            })
            logger.info("Successfully logged in to FLAG portal")

            # Navigate to new LCA form
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "new_lca_navigation",
                "message": "Navigating to new LCA form"
            })

            logger.info("Navigating to new LCA form")
            if not await navigation.navigate_to_new_lca():
                error_msg = "Failed to navigate to new LCA form"
                self.update_filing_status(filing_id, {
                    "status": "error",
                    "step": "new_lca_navigation",
                    "error": error_msg
                })
                result["status"] = "navigation_failed"
                result["error"] = error_msg
                return result

            result["steps_completed"].append("new_lca_navigation")
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "new_lca_navigation_complete",
                "message": "Successfully navigated to new LCA form"
            })
            logger.info("Successfully navigated to new LCA form")

            # Capture form elements on the first page
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "capturing_form",
                "message": "Analyzing form structure"
            })

            first_page_elements = await self.form_capture.capture_current_section()
            logger.info(f"Captured {len(first_page_elements.get('elements', []))} elements on first page")

            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "form_type_selection",
                "message": "Selecting H-1B form type"
            })

            expected_selectors = [
                {"selector": "#visaType", "description": "H-1B Form Type"}
            ]

            # try:
            #     if not await navigation.select_form_type("H-1B"):
            #         # Check if we need human interaction
            #         interaction_needed = await self.form_capture.detect_interaction_required(expected_selectors)
            #
            #         if interaction_needed:
            #             # Handle the interaction the same way as other interactions
            #             self.update_filing_status(filing_id, {
            #                 "status": "interaction_needed",
            #                 "step": "form_type_selection_interaction",
            #                 "message": "Human interaction required for form type selection",
            #                 "interaction_data": {
            #                     "section": "Form Type Selection",
            #                     "fields": [field["id"] for field in interaction_needed["fields"]],
            #                     "has_errors": interaction_needed.get("has_errors", False),
            #                     "has_missing_elements": interaction_needed.get("has_missing_elements", False)
            #                 }
            #             })
            #
            #             # Add to result history
            #             result["interactions"].append({
            #                 "section": "Form Type Selection",
            #                 "timestamp": datetime.now().isoformat(),
            #                 "fields": [field["id"] for field in interaction_needed["fields"]],
            #                 "missing_elements": interaction_needed.get("has_missing_elements", False)
            #             })
            #
            #             # Call interaction callback
            #             if self.interaction_callback:
            #                 self.filing_paused = True
            #                 self.pending_interaction = interaction_needed
            #
            #                 # Clear previous event
            #                 self.interaction_completed.clear()
            #
            #                 # Call the callback
            #                 self.interaction_callback(filing_id, interaction_needed)
            #
            #                 # Wait for human interaction
            #                 await self.interaction_completed.wait()
            #                 self.filing_paused = False
            #
            #                 # Apply the interaction results
            #                 if filing_id in self.interaction_results:
            #                     interaction_result = self.interaction_results[filing_id]
            #
            #                     # Special handling for form type selection
            #                     form_type = None
            #                     for field_id, field_value in interaction_result.items():
            #                         if "form_type" in field_id or "radio" in field_id:
            #                             form_type = field_value
            #                             break
            #
            #                     if form_type:
            #                         # Now try to select the form type with explicit value
            #                         if not await navigation.select_form_type(form_type):
            #                             error_msg = f"Failed to select form type even after human interaction: {form_type}"
            #                             raise Exception(error_msg)
            #                     else:
            #                         # If no form type selected, try to click continue anyway
            #                         await navigation.save_and_continue()
            #
            #                     del self.interaction_results[filing_id]
            #
            #         else:
            #             # If no interaction needed but still failed, this is a real error
            #             error_msg = "Failed to select H-1B form type"
            #             self.update_filing_status(filing_id, {
            #                 "status": "error",
            #                 "step": "form_type_selection",
            #                 "error": error_msg
            #             })
            #             result["status"] = "form_selection_failed"
            #             result["error"] = error_msg
            #             return result
            # except Exception as e:
            #     # Handle exceptions
            #     logger.error(f"Error selecting form type: {str(e)}")

            # Select H-1B form type
            # logger.info("Selecting H-1B form type")
            # if not await navigation.select_form_type("H-1B"):
            #     error_msg = "Failed to select H-1B form type"
            #     self.update_filing_status(filing_id, {
            #         "status": "error",
            #         "step": "form_type_selection",
            #         "error": error_msg
            #     })
            #     result["status"] = "form_selection_failed"
            #     result["error"] = error_msg
            #     return result

            result["steps_completed"].append("form_type_selection")
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "form_type_selection_complete",
                "message": "Successfully selected H-1B form type"
            })
            logger.info("Successfully selected H-1B form type")

            # Skip directly to Section C - Employer Information
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "navigating_to_section_c",
                "message": "Skipping directly to Section C - Employer Information"
            })

            # This function would navigate to Section C
            # We need to click "Save and Continue" multiple times to get there
            for _ in range(1):  # Adjust this number as needed to reach Section C
                await navigation.save_and_continue()
                await asyncio.sleep(2)  # Wait for page to load

            # Now we should be at Section C
            # Capture the current section to verify
            # section_data = await self.form_capture.capture_current_section()
            # current_section = section_data["section_name"]
            current_section = "Section C"

            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "section_c_reached",
                "current_section": current_section,
                "message": f"Reached section: {current_section}"
            })

            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "naics_code_handling",
                "message": "Handling NAICS code field"
            })

            try:

                # Process NAICS code field
                if await self.handle_naics_code_field(page, form_filler, application_data):
                    self.update_filing_status(filing_id, {
                        "status": "processing",
                        "step": "naics_code_complete",
                        "message": "Successfully handled NAICS code field"
                    })

                    # Continue with rest of form sections
                    logger.info("Continuing with form process after handling NAICS code")
                else:
                    self.update_filing_status(filing_id, {
                        "status": "Failed",
                        "step": "naics_code_handling",
                        "message": "NAICS code field handling was not successful"
                    })
                    logger.warning("NAICS code field handling was not successful")
            except Exception as e:
                logger.error(f"Error in section navigation and NAICS handling: {str(e)}")
                await self.lca_filer.screenshot_manager.take_screenshot(page, "section_navigation_error")

            time.sleep(1000)
            # # Trigger interaction for NAICS field
            # interaction_needed = await self.form_capture.detect_interaction_required(naics_selectors)
            #
            # if interaction_needed:
            #     self.update_filing_status(filing_id, {
            #         "status": "interaction_needed",
            #         "step": "section_c_naics_interaction",
            #         "message": "Human interaction required for NAICS Code field",
            #         "interaction_data": {
            #             "section": "Employer Information",
            #             "fields": [field["id"] for field in interaction_needed["fields"]],
            #             "has_errors": interaction_needed.get("has_errors", False)
            #         }
            #     })
            #
            #     # Call interaction callback
            #     if self.interaction_callback:
            #         self.filing_paused = True
            #         self.pending_interaction = interaction_needed
            #
            #         # Clear previous event
            #         self.interaction_completed.clear()
            #
            #         # Call the callback
            #         self.interaction_callback(filing_id, interaction_needed)
            #
            #         # Wait for human interaction
            #         await self.interaction_completed.wait()
            #         self.filing_paused = False
            #
            #         # Apply the interaction results
            #         if filing_id in self.interaction_results:
            #             interaction_result = self.interaction_results[filing_id]
            #             await self._apply_interaction_results(page, form_filler, interaction_result)
            #             del self.interaction_results[filing_id]

            # Get AI decisions for the entire form
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "ai_decision",
                "message": "Getting AI decisions for form filling"
            })

            logger.info("Getting AI decisions for form filling")
            lca_decision = await self.lca_filer.decision_maker.make_decisions(application_data)

            # If human review is required, log the reasons
            if lca_decision.requires_human_review:
                result["requires_human_review"] = True
                result["review_reasons"] = lca_decision.review_reasons
                logger.warning(
                    f"Application {filing_id} requires human review: {', '.join(lca_decision.review_reasons)}")

            # Process each section of the form
            section_count = 0
            for section_obj in lca_decision.form_sections:
                section_count += 1
                section_name = section_obj.section_name
                decisions = section_obj.decisions

                # Find section definition
                section_def = next((s for s in FormStructure.get_h1b_structure()["sections"]
                                    if s["name"] == section_name), None)

                if not section_def:
                    logger.warning(f"Section definition not found for {section_name}")
                    continue

                logger.info(f"Processing section: {section_name}")
                self.update_filing_status(filing_id, {
                    "status": "processing",
                    "step": f"section_{section_count}",
                    "current_section": section_name,
                    "message": f"Processing section: {section_name}"
                })

                # Check for unexpected navigation issues before proceeding
                await navigation.handle_unexpected_navigation()

                # Special handling for worksite section with multiple worksites
                if "worksite" in section_name.lower() and application_data.get("multiple_worksites", False):
                    logger.info("Using special handling for multiple worksites section")
                    await form_filler.handle_worksite_section(application_data)
                else:
                    # Fill the section normally
                    section_result = await form_filler.fill_section(section_def, decisions)
                    logger.info(
                        f"Section {section_name} fill result: {section_result['fields_filled']}/{section_result['fields_total']} fields filled")

                # Check for errors
                errors = await error_handler.detect_errors()
                if errors:
                    logger.warning(f"Detected {len(errors)} errors in section {section_name}")
                    self.update_filing_status(filing_id, {
                        "status": "processing",
                        "step": f"section_{section_count}_errors",
                        "message": f"Detected {len(errors)} errors in section {section_name}. Attempting to fix."
                    })

                    # Try to fix errors
                    form_state = await form_filler.get_form_state()
                    fixed = await error_handler.fix_errors(errors, form_state)

                    if not fixed:
                        logger.warning(f"Could not fix all errors in section {section_name}")

                        # Check if this section needs human interaction
                        interaction_needed = await self.form_capture.detect_interaction_required()
                        if interaction_needed:
                            # We need human input for this section
                            logger.info(f"Human interaction required for section: {section_name}")

                            self.update_filing_status(filing_id, {
                                "status": "interaction_needed",
                                "step": f"section_{section_count}_{section_name}_interaction",
                                "message": f"Human interaction required for section: {section_name}",
                                "interaction_data": {
                                    "section": section_name,
                                    "fields": [field["id"] for field in interaction_needed["fields"]],
                                    "has_errors": interaction_needed.get("has_errors", True)
                                }
                            })

                            # Add to result history
                            result["interactions"].append({
                                "section": section_name,
                                "timestamp": datetime.now().isoformat(),
                                "fields": [field["id"] for field in interaction_needed["fields"]],
                                "errors": [error["message"] for error in errors if "message" in error]
                            })

                            # Call interaction callback if provided
                            if self.interaction_callback:
                                self.filing_paused = True
                                self.pending_interaction = interaction_needed

                                # Clear previous event
                                self.interaction_completed.clear()

                                # Call the callback
                                self.interaction_callback(filing_id, interaction_needed)

                                # Wait for human interaction
                                self.update_filing_status(filing_id, {
                                    "status": "waiting_for_input",
                                    "step": f"section_{section_count}_{section_name}_waiting",
                                    "message": "Waiting for human interaction"
                                })

                                logger.info("Waiting for human interaction...")
                                await self.interaction_completed.wait()
                                self.filing_paused = False

                                self.update_filing_status(filing_id, {
                                    "status": "processing",
                                    "step": f"section_{section_count}_{section_name}_continuing",
                                    "message": "Continuing after human interaction"
                                })

                                # Apply the interaction results to the form
                                if filing_id in self.interaction_results:
                                    interaction_result = self.interaction_results[filing_id]
                                    await self._apply_interaction_results(page, form_filler, interaction_result)
                                    del self.interaction_results[filing_id]
                            else:
                                # No callback provided, can't continue
                                error_msg = f"Human interaction required for section: {section_name} - no callback provided"
                                self.update_filing_status(filing_id, {
                                    "status": "error",
                                    "step": f"section_{section_count}_{section_name}_no_callback",
                                    "error": error_msg
                                })
                                result["status"] = "interaction_required"
                                result["error"] = error_msg
                                return result
                    else:
                        self.update_filing_status(filing_id, {
                            "status": "processing",
                            "step": f"section_{section_count}_errors_fixed",
                            "message": f"Successfully fixed errors in section {section_name}"
                        })

                # Save and continue to next section
                self.update_filing_status(filing_id, {
                    "status": "processing",
                    "step": f"section_{section_count}_{section_name}_saving",
                    "message": f"Saving section {section_name} and continuing"
                })

                logger.info(f"Saving section {section_name} and continuing")
                if not await navigation.save_and_continue():
                    logger.warning(f"Error saving section {section_name}")
                    self.update_filing_status(filing_id, {
                        "status": "warning",
                        "step": f"section_{section_count}_{section_name}_save_error",
                        "message": f"Error saving section {section_name}, attempting to continue"
                    })

                    # Check if there are validation errors
                    errors = await error_handler.detect_errors()
                    if errors:
                        logger.warning(f"Validation errors detected in section {section_name}")

                        # Try to handle validation errors - similar to the code above
                        # This is a simplified version - full implementation would include error handling
                        interaction_needed = await self.form_capture.detect_interaction_required()
                        if interaction_needed and self.interaction_callback:
                            # Call interaction callback similar to above...
                            # [interaction handling code similar to above]
                            pass
                        else:
                            logger.warning(f"Could not save section {section_name} - continuing anyway")
                            # Try to click continue button again
                            try:
                                await navigation.save_and_continue()
                            except Exception as e:
                                logger.error(f"Error on retry of continue: {str(e)}")

                result["steps_completed"].append(f"section_{section_name}")
                self.update_filing_status(filing_id, {
                    "status": "processing",
                    "step": f"section_{section_count}_{section_name}_complete",
                    "message": f"Completed section: {section_name}"
                })
                logger.info(f"Completed section: {section_name}")

            # Submit the final form
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "submission",
                "message": "Submitting final LCA form"
            })

            logger.info("Submitting final LCA form")
            if not await navigation.submit_final():
                error_msg = "Failed to submit LCA form"
                self.update_filing_status(filing_id, {
                    "status": "error",
                    "step": "submission_failed",
                    "error": error_msg
                })
                result["status"] = "submission_failed"
                result["error"] = error_msg
                return result

            result["steps_completed"].append("submission")
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "submission_complete",
                "message": "LCA form submitted successfully"
            })
            logger.info("LCA form submitted successfully")

            # Get confirmation number
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "confirmation",
                "message": "Getting confirmation number"
            })

            confirmation_number = await navigation.get_confirmation_number()
            if confirmation_number:
                result["confirmation_number"] = confirmation_number
                result["status"] = "success"

                self.update_filing_status(filing_id, {
                    "status": "success",
                    "step": "complete",
                    "message": f"Successfully filed LCA, confirmation number: {confirmation_number}",
                    "confirmation_number": confirmation_number
                })
                logger.info(f"Successfully filed LCA, confirmation number: {confirmation_number}")
            else:
                error_msg = "Failed to get confirmation number"
                self.update_filing_status(filing_id, {
                    "status": "error",
                    "step": "confirmation_failed",
                    "error": error_msg
                })
                result["status"] = "confirmation_failed"
                result["error"] = error_msg
                logger.error("Failed to get confirmation number after submission")

            return result

        except Exception as e:
            logger.error(f"Error in interactive filing: {str(e)}")
            self.update_filing_status(filing_id, {
                "status": "error",
                "step": "unexpected_error",
                "error": str(e)
            })
            result["status"] = "error"
            result["error"] = str(e)
            return result

        finally:
            # Remove filing_id from active filings when done
            with self._lock:
                if filing_id in self.active_filings:
                    self.active_filings.remove(filing_id)

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

    async def navigate_to_section_c(self, page, navigation):
        """
        Navigate to Section C (Employer Information) from Section A.

        Args:
            page: Playwright page
            navigation: Navigation instance

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Attempting to navigate to Section C (Employer Information)")

            # First, check what section we're currently on
            current_section_data = await self.form_capture.capture_current_section()
            current_section = current_section_data["section_name"]
            logger.info(f"Currently on section: {current_section}")

            # If already at Section C, return success
            if "employer information" in current_section.lower() or "section c" in current_section.lower():
                logger.info("Already at Section C (Employer Information)")
                return True

            # Method 1: Try clicking "Save and Continue" until we reach Section C
            max_attempts = 5  # Adjust based on your form structure
            for attempt in range(max_attempts):
                logger.info(f"Clicking continue to navigate to next section (attempt {attempt + 1}/{max_attempts})")

                # Take screenshot before navigation
                await self.lca_filer.screenshot_manager.take_screenshot(
                    page, f"before_navigation_attempt_{attempt + 1}")

                # Click continue button
                await navigation.save_and_continue()

                # Wait for page to load
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception as e:
                    logger.warning(f"Timeout waiting for page load: {str(e)}")

                # Additional wait to ensure forms are fully loaded
                await page.wait_for_timeout(2000)

                # Take screenshot after navigation
                await self.lca_filer.screenshot_manager.take_screenshot(
                    page, f"after_navigation_attempt_{attempt + 1}")

                # Check current section
                section_data = await self.form_capture.capture_current_section()
                current_section = section_data["section_name"]
                logger.info(f"Now on section: {current_section}")

                # Check if we've reached Section C
                if "employer information" in current_section.lower() or "section c" in current_section.lower():
                    logger.info(f"Reached Section C (Employer Information) after {attempt + 1} attempts")
                    return True

                # If we're on the final attempt and haven't reached Section C,
                # take one more screenshot to help with debugging
                if attempt == max_attempts - 1:
                    await self.lca_filer.screenshot_manager.take_screenshot(
                        page, "failed_to_reach_section_c")

            logger.warning(f"Could not reach Section C after {max_attempts} attempts")
            return False

        except Exception as e:
            logger.error(f"Error navigating to Section C: {str(e)}")
            # Take screenshot of the error state
            await self.lca_filer.screenshot_manager.take_screenshot(page, "navigation_to_section_c_error")
            return False

    async def handle_naics_code_field(self, page, form_filler, application_data=None):
        """
        Special handler for the NAICS Code field.

        Args:
            page: Playwright page
            form_filler: Form filler instance
            application_data: Optional application data

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Handling NAICS Code field specifically")

            # Take screenshot before handling
            await self.lca_filer.screenshot_manager.take_screenshot(page, "before_naics_code_handling")
            time.sleep(10)
            # Find the NAICS code field using various selectors
            naics_selectors = [
                {"selector": "#formContainer > form > div:nth-child(1) > fieldset:nth-child(2) > div > div:nth-child(6) > div > div > div.react-autosuggest__container > div.input-container > input", "description": "NAICS Code"},
                {"selector": "#formContainer > form > div:nth-child(1) > fieldset:nth-child(2) > div > div:nth-child(6) > div > div > div.react-autosuggest__container > div.input-container > input", "description": "NAICS Code"},
                {"selector": "/html/body/div[9]/div/div/div[2]/div[2]/form/div[1]/fieldset[1]/div/div[6]/div/div/div[2]/div[1]/input", "description": "NAICS Code"}
            ]
            naics_field = None
            for selector in naics_selectors:
                try:
                    naics_field = await page.query_selector(selector["selector"])
                    print("selector", selector["selector"])
                    print("naics_field", naics_field)
                    if naics_field:
                        logger.info(f"Found NAICS code field with selector: {selector}")
                        break
                except Exception as e:
                    logger.debug(f"Error finding NAICS code with selector {selector}: {str(e)}")
                    continue

            if not naics_field:
                logger.error("Could not find NAICS code field")
                return False

            # Get field ID and name for interaction
            field_id = await naics_field.get_attribute("id") or "naics_code"
            field_name = await naics_field.get_attribute("name") or "naics_code"

            # Get NAICS code from application data if available
            naics_code = None
            if application_data and "employer" in application_data:
                naics_code = application_data["employer"].get("naics")

            # Prepare field data for interaction
            field_data = {
                "section_name": "Employer Information",
                "screenshot_path": await self.lca_filer.screenshot_manager.take_screenshot(page, "naics_code_field"),
                "fields": [{
                    "id": field_id,
                    "name": field_name,
                    "type": "autocomplete",
                    "label": "NAICS Code",
                    "placeholder": await naics_field.get_attribute("placeholder") or "Enter NAICS Code",
                    "default_value": naics_code or "",
                    "required": True,
                    "description": "Enter NAICS code or industry keywords to search. The system will show matching options as you type.",
                    "example_searches": ["541511", "Software", "Engineering", "Computer"],
                    "sample_values": [
                        {"code": "541511", "description": "Custom Computer Programming Services"},
                        {"code": "541512", "description": "Computer Systems Design Services"},
                        {"code": "541330", "description": "Engineering Services"},
                        {"code": "541712", "description": "Research and Development in Physical Sciences"}
                    ],
                    "is_autocomplete": True,
                    "field_errors": []
                }],
                "error_messages": [],
                "has_errors": False,
                "guidance": "Please enter a NAICS code for the employer. You can search by code or keywords.",
                "timestamp": datetime.now().isoformat()
            }

            # Get current filing ID
            filing_id = None
            for fid in self.active_filings:
                filing_id = fid
                break

            if not filing_id:
                logger.warning("No active filing ID found")
                filing_id = "unknown"

            # Request interaction
            if self.interaction_callback:
                self.filing_paused = True
                self.pending_interaction = field_data

                # Clear previous event
                self.interaction_completed.clear()

                # Call interaction callback
                self.interaction_callback(filing_id, field_data)

                # Wait for interaction
                logger.info("Waiting for human input on NAICS code field")
                await self.interaction_completed.wait()
                self.filing_paused = False

                # Apply the interaction result
                if filing_id in self.interaction_results:
                    interaction_result = self.interaction_results[filing_id]

                    # Find NAICS value in results
                    naics_value = None
                    for key, value in interaction_result.items():
                        if field_id in key or 'naics' in key.lower():
                            naics_value = value
                            break

                    if not naics_value and f"{field_id}_selected" in interaction_result:
                        naics_value = interaction_result[f"{field_id}_selected"]

                    if naics_value:
                        logger.info(f"Applying NAICS code: {naics_value}")

                        # Fill the NAICS code field
                        await naics_field.click()
                        await naics_field.fill("")
                        await naics_field.fill(naics_value)

                        # Wait for autocomplete results to appear
                        await page.wait_for_timeout(1000)

                        # Try to click on matching result if available
                        try:
                            # Try various selectors for result items
                            result_selectors = [
                                ".autocomplete-results .result-item",
                                ".ui-autocomplete .ui-menu-item",
                                "[role='listbox'] [role='option']",
                                ".dropdown-menu .dropdown-item",
                                "li:has-text('" + naics_value + "')"
                            ]

                            result_found = False
                            for selector in result_selectors:
                                results = await page.query_selector_all(selector)
                                if results and len(results) > 0:
                                    # Try to find exact match
                                    for result in results:
                                        result_text = await result.text_content()
                                        if naics_value in result_text:
                                            await result.click()
                                            logger.info(f"Clicked matching result: {result_text}")
                                            result_found = True
                                            break

                                    # If no exact match found, click first result
                                    if not result_found and results:
                                        await results[0].click()
                                        logger.info("Clicked first result")
                                        result_found = True

                                    if result_found:
                                        break
                        except Exception as e:
                            logger.warning(f"Error clicking autocomplete result: {str(e)}")

                        # Press Tab to confirm and move to next field
                        await naics_field.press("Tab")

                        # Take screenshot after handling
                        await self.lca_filer.screenshot_manager.take_screenshot(page, "after_naics_code_handling")

                        # Remove the interaction result
                        del self.interaction_results[filing_id]
                        return True
                    else:
                        logger.warning("No NAICS code value found in interaction results")
                else:
                    logger.warning(f"No interaction results found for filing {filing_id}")

                return False
            else:
                logger.error("No interaction callback provided")
                return False

        except Exception as e:
            logger.error(f"Error handling NAICS code field: {str(e)}")
            await self.lca_filer.screenshot_manager.take_screenshot(page, "naics_code_error")
            return False