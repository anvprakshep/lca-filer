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
        Enhanced method to apply human interaction results to the form, handling various field types.

        Args:
            page: Playwright page
            form_filler: Form filler instance
            interaction_result: Dictionary with interaction results
        """
        try:
            logger.info("Applying human interaction results to form")

            # Take a screenshot before applying changes
            await self.lca_filer.screenshot_manager.take_screenshot(
                page,
                "before_applying_interaction_results"
            )

            # Keep track of fields we've applied
            applied_fields = []
            failed_fields = []

            # Apply each field value
            for field_id, field_value in interaction_result.items():
                try:
                    logger.info(f"Applying value to field {field_id}: {field_value}")

                    # Find the field using multiple selector strategies
                    field_element = None
                    selectors_to_try = [
                        f"#{field_id}",  # ID selector
                        f"[name='{field_id}']",  # Name selector
                        f"[data-field-id='{field_id}']",  # Data attribute
                        f"input[id='{field_id}'], select[id='{field_id}'], textarea[id='{field_id}']",  # Input with ID
                        f"input[name='{field_id}'], select[name='{field_id}'], textarea[name='{field_id}']",
                        # Input with name
                        # Try with prefix/suffix variations
                        f"input[id$='{field_id}'], select[id$='{field_id}'], textarea[id$='{field_id}']",
                        # ID ends with
                        f"input[id^='{field_id}'], select[id^='{field_id}'], textarea[id^='{field_id}']",
                        # ID starts with
                        f"input[name$='{field_id}'], select[name$='{field_id}'], textarea[name$='{field_id}']"
                        # Name ends with
                    ]

                    # Try all selectors
                    for selector in selectors_to_try:
                        field_element = await page.query_selector(selector)
                        if field_element:
                            logger.debug(f"Found field element using selector: {selector}")
                            break

                    # If still no element found, try a more general search in case our ID/name doesn't match
                    if not field_element:
                        logger.debug(f"Field not found with direct selectors, trying broader search")

                        # Look for elements with similar id/name pattern
                        similar_elements = await page.evaluate(f"""
                            () => {{
                                const fieldId = "{field_id}";

                                // Find input elements by fuzzy id/name match
                                const allInputs = Array.from(document.querySelectorAll('input, select, textarea, [role="combobox"], [role="checkbox"], [role="radio"]'));

                                // Find elements with id/name that contains our field_id
                                const similarElements = allInputs.filter(el => {{
                                    const id = el.id && el.id.toLowerCase();
                                    const name = el.name && el.name.toLowerCase();
                                    const fieldIdLower = fieldId.toLowerCase();

                                    // Check for similarity
                                    return (id && id.includes(fieldIdLower)) || 
                                           (name && name.includes(fieldIdLower));
                                }});

                                return similarElements.map(el => {{
                                    return {{
                                        id: el.id,
                                        name: el.name,
                                        tagName: el.tagName,
                                        type: el.type || el.getAttribute('role')
                                    }};
                                }});
                            }}
                        """)

                        if similar_elements and len(similar_elements) > 0:
                            # Use the first matching element
                            most_similar = similar_elements[0]
                            logger.debug(f"Found similar element: {most_similar}")

                            if most_similar.get("id"):
                                field_element = await page.query_selector(f"#{most_similar['id']}")
                            elif most_similar.get("name"):
                                field_element = await page.query_selector(f"[name='{most_similar['name']}']")

                    # If we found the element, determine its type and populate accordingly
                    if field_element:
                        # Determine element type
                        tag_name = await field_element.evaluate("el => el.tagName.toLowerCase()")
                        field_type = await field_element.get_attribute("type") or tag_name
                        field_role = await field_element.get_attribute("role") or ""

                        # For select, explicitly set field_type
                        if tag_name == "select":
                            field_type = "select"

                        # For textarea, explicitly set field_type
                        if tag_name == "textarea":
                            field_type = "textarea"

                        # For div with role
                        if tag_name == "div" and field_role:
                            field_type = field_role

                        logger.info(f"Filling field {field_id} of type {field_type} with value: {field_value}")

                        # Handle different field types
                        if field_type == "radio":
                            # For radio buttons, need to find the one with matching value
                            radio_name = await field_element.get_attribute("name")
                            if radio_name:
                                radio_selector = f"input[type='radio'][name='{radio_name}'][value='{field_value}']"
                                radio_to_click = await page.query_selector(radio_selector)

                                if radio_to_click:
                                    await radio_to_click.click()
                                    logger.info(f"Clicked radio button with value {field_value}")
                                    applied_fields.append(field_id)
                                else:
                                    logger.warning(f"Radio button with value {field_value} not found")
                                    failed_fields.append(field_id)
                            else:
                                # Just click this radio button if it doesn't have a name
                                await field_element.click()
                                applied_fields.append(field_id)

                        elif field_type == "checkbox":
                            # For checkbox, click if value is truthy
                            current_checked = await field_element.evaluate("el => el.checked")

                            # Convert field_value to boolean
                            value_as_bool = False
                            if isinstance(field_value, bool):
                                value_as_bool = field_value
                            elif isinstance(field_value, str):
                                value_as_bool = field_value.lower() in ("yes", "true", "t", "1")

                            # Only click if current state doesn't match desired state
                            if current_checked != value_as_bool:
                                await field_element.click()
                                logger.info(f"Clicked checkbox to set checked={value_as_bool}")
                            applied_fields.append(field_id)

                        elif field_type == "select":
                            # For select dropdowns
                            await field_element.select_option(value=field_value)
                            logger.info(f"Selected option with value {field_value}")
                            applied_fields.append(field_id)

                        elif field_type in ["combobox", "listbox", "autocomplete"]:
                            # For custom dropdowns
                            # Click to open, then find and click the option
                            await field_element.click()
                            await asyncio.sleep(0.5)  # Wait for dropdown to open

                            # Try to find option by value or text content
                            option_selectors = [
                                f"li[data-value='{field_value}']",
                                f"div[data-value='{field_value}']",
                                f"option[value='{field_value}']",
                                f".option[data-value='{field_value}']",
                                f"[role='option'][data-value='{field_value}']",
                                f"li:has-text('{field_value}')",
                                f"div.option:has-text('{field_value}')",
                                f"[role='option']:has-text('{field_value}')"
                            ]

                            option_found = False
                            for option_selector in option_selectors:
                                try:
                                    option = await page.wait_for_selector(option_selector, timeout=1000)
                                    if option:
                                        await option.click()
                                        logger.info(f"Clicked option in custom dropdown: {field_value}")
                                        option_found = True
                                        break
                                except Exception:
                                    continue

                            if not option_found:
                                # If no option found, try to input text directly if there's an input
                                input_element = await field_element.query_selector("input")
                                if input_element:
                                    await input_element.fill(field_value)
                                    logger.info(f"Filled text in custom dropdown input: {field_value}")
                                    option_found = True

                            if option_found:
                                applied_fields.append(field_id)
                            else:
                                logger.warning(f"Could not set value for custom dropdown {field_id}")
                                failed_fields.append(field_id)

                        else:
                            # Default case: use fill for text inputs, textareas, etc.
                            await field_element.fill(str(field_value))
                            logger.info(f"Filled value in field {field_id}: {field_value}")
                            applied_fields.append(field_id)

                    else:
                        # Field element not found, try fallback approaches
                        logger.warning(f"Field element not found for {field_id}")

                        # For radio buttons, try looking for any radio with matching name and value
                        if isinstance(field_value, str):
                            # Try to find by field ID as name
                            radio_selector = f"input[type='radio'][name='{field_id}'][value='{field_value}']"
                            radio_element = await page.query_selector(radio_selector)

                            if radio_element:
                                await radio_element.click()
                                logger.info(f"Clicked radio button with name={field_id}, value={field_value}")
                                applied_fields.append(field_id)
                                continue

                            # Try to find any radio with the given value
                            possible_radios = await page.query_selector_all(
                                f"input[type='radio'][value='{field_value}']")
                            if possible_radios and len(possible_radios) == 1:
                                await possible_radios[0].click()
                                logger.info(f"Clicked single radio button with value={field_value}")
                                applied_fields.append(field_id)
                                continue

                        # Try to find by text or ARIA label
                        if isinstance(field_value, str):
                            selectors_by_text = [
                                f"label:has-text('{field_id}') + input, label:has-text('{field_id}') input",
                                f"input[aria-label='{field_id}']",
                                f"select[aria-label='{field_id}']",
                                f"textarea[aria-label='{field_id}']"
                            ]

                            for text_selector in selectors_by_text:
                                element = await page.query_selector(text_selector)
                                if element:
                                    await element.fill(field_value)
                                    logger.info(f"Filled value in field found by text/ARIA label {field_id}")
                                    applied_fields.append(field_id)
                                    break
                            else:
                                # If all else fails, log the issue
                                logger.warning(f"Field not found: {field_id}")
                                failed_fields.append(field_id)

                        else:
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
                # If important fields failed, try some recovery strategies
                if len(failed_fields) / max(1, len(interaction_result)) > 0.5:  # If more than 50% failed
                    logger.warning("High failure rate in applying fields, trying recovery strategies")

                    # Strategy 1: Try direct JavaScript injection
                    await self._try_direct_js_field_setting(page, interaction_result, failed_fields)

            logger.info(f"Successfully applied interaction results to {len(applied_fields)} fields")

        except Exception as e:
            logger.error(f"Error applying interaction results: {str(e)}")

            # Take error screenshot
            await self.lca_filer.screenshot_manager.take_screenshot(
                page,
                f"error_applying_interactions_{int(time.time())}"
            )

    async def _try_direct_js_field_setting(self, page, interaction_result, failed_fields):
        """
        Try to set field values directly using JavaScript as a fallback.

        Args:
            page: Playwright page
            interaction_result: Dictionary with field values
            failed_fields: List of fields that failed with normal methods
        """
        logger.info("Attempting to set field values directly with JavaScript")

        for field_id in failed_fields:
            if field_id not in interaction_result:
                continue

            field_value = interaction_result[field_id]

            try:
                # Attempt to set via various JS strategies
                result = await page.evaluate(f"""
                    () => {{
                        const fieldId = "{field_id}";
                        const fieldValue = "{field_value}";
                        let success = false;

                        // Try by ID
                        let element = document.getElementById(fieldId);

                        // Try by name if not found by ID
                        if (!element) {{
                            element = document.querySelector(`[name="${{fieldId}}"]`);
                        }}

                        // Try various other selectors
                        if (!element) {{
                            const selectors = [
                                `[data-field-id="${{fieldId}}"]`,
                                `[data-id="${{fieldId}}"]`,
                                `[id$="${{fieldId}}"]`,
                                `[name$="${{fieldId}}"]`
                            ];

                            for (const selector of selectors) {{
                                element = document.querySelector(selector);
                                if (element) break;
                            }}
                        }}

                        // If element found, set value
                        if (element) {{
                            const tagName = element.tagName.toLowerCase();
                            const type = element.type || '';

                            // Handle different element types
                            if (tagName === 'select') {{
                                // For select elements
                                for (const option of element.options) {{
                                    if (option.value === fieldValue) {{
                                        option.selected = true;
                                        element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                        success = true;
                                        break;
                                    }}
                                }}
                            }} else if (type === 'checkbox' || type === 'radio') {{
                                // For checkboxes and radios
                                if (type === 'checkbox') {{
                                    const newState = ['true', 'yes', '1'].includes(fieldValue.toLowerCase());
                                    if (element.checked !== newState) {{
                                        element.checked = newState;
                                        element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    }}
                                    success = true;
                                }} else if (type === 'radio') {{
                                    // For radio buttons, find the one with matching value
                                    const name = element.name;
                                    if (name) {{
                                        const radios = document.querySelectorAll(`input[type="radio"][name="${{name}}"]`);
                                        for (const radio of radios) {{
                                            if (radio.value === fieldValue) {{
                                                radio.checked = true;
                                                radio.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                                success = true;
                                                break;
                                            }}
                                        }}
                                    }}
                                }}
                            }} else {{
                                // For text inputs, textareas, etc.
                                element.value = fieldValue;
                                element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                success = true;
                            }}
                        }}

                        return {{ success, elementFound: !!element }};
                    }}
                """)

                if result.get("success"):
                    logger.info(f"Successfully set field {field_id} with JavaScript")
                elif result.get("elementFound"):
                    logger.warning(f"Found element for {field_id} but couldn't set value with JavaScript")
                else:
                    logger.warning(f"Could not find element for {field_id} with JavaScript")

            except Exception as e:
                logger.error(f"Error setting field {field_id} with JavaScript: {str(e)}")

    async def start_interactive_filing(self, application_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start an interactive LCA filing process with improved handling of form interactions.

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

            # Configure TOTP if needed
            await self._configure_totp_from_application(application_data)

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

            # Enhanced login attempt with better error handling
            login_success = await self._attempt_login_with_retry(navigation, credentials)
            if not login_success:
                error_msg = "Failed to login to FLAG portal after multiple attempts"
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
                # Instead of failing immediately, check if we need human interaction
                interaction_needed = await self.form_capture.detect_interaction_required()

                if interaction_needed:
                    # Handle portal navigation interaction
                    await self._handle_interaction(filing_id, interaction_needed, page, form_filler)

                    # Try again to navigate to new LCA
                    if not await navigation.navigate_to_new_lca():
                        error_msg = "Failed to navigate to new LCA form even after human interaction"
                        self.update_filing_status(filing_id, {
                            "status": "error",
                            "step": "new_lca_navigation",
                            "error": error_msg
                        })
                        result["status"] = "navigation_failed"
                        result["error"] = error_msg
                        return result
                else:
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

            # Expected selectors for form type page
            expected_selectors = [
                {"selector": "input[type='radio'][value='H-1B']", "description": "H-1B Form Type", "required": True}
            ]

            # Check if we need interaction for selecting form type
            interaction_needed = await self.form_capture.detect_interaction_required(expected_selectors)

            if interaction_needed:
                # Handle form type selection interaction
                await self._handle_interaction(filing_id, interaction_needed, page, form_filler)

                # Continue after interaction
                result["steps_completed"].append("form_type_selection")
                self.update_filing_status(filing_id, {
                    "status": "processing",
                    "step": "form_type_selection_complete",
                    "message": "Form type selected with human assistance"
                })
            else:
                # Try to select form type automatically
                if not await navigation.select_form_type("H-1B"):
                    error_msg = "Failed to select H-1B form type"
                    self.update_filing_status(filing_id, {
                        "status": "error",
                        "step": "form_type_selection",
                        "error": error_msg
                    })
                    result["status"] = "form_selection_failed"
                    result["error"] = error_msg
                    return result

                result["steps_completed"].append("form_type_selection")
                self.update_filing_status(filing_id, {
                    "status": "processing",
                    "step": "form_type_selection_complete",
                    "message": "Successfully selected H-1B form type"
                })
                logger.info("Successfully selected H-1B form type")

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

                # Check for errors or missing fields
                interaction_needed = await self.form_capture.detect_interaction_required()

                if interaction_needed:
                    # We need human input for this section
                    await self._handle_interaction(filing_id, interaction_needed, page, form_filler)
                else:
                    # No human interaction needed, check for standard errors
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

                            # Check if we need interaction after error fixing failed
                            interaction_needed = await self.form_capture.detect_interaction_required()
                            if interaction_needed:
                                await self._handle_interaction(filing_id, interaction_needed, page, form_filler)

                # Save and continue to next section
                self.update_filing_status(filing_id, {
                    "status": "processing",
                    "step": f"section_{section_count}_{section_name}_saving",
                    "message": f"Saving section {section_name} and continuing"
                })

                logger.info(f"Saving section {section_name} and continuing")
                if not await navigation.save_and_continue():
                    logger.warning(f"Error saving section {section_name}")

                    # Check if we need interaction due to save errors
                    interaction_needed = await self.form_capture.detect_interaction_required()
                    if interaction_needed:
                        # Handle interaction for save errors
                        await self._handle_interaction(filing_id, interaction_needed, page, form_filler)

                        # Try to continue again
                        if not await navigation.save_and_continue():
                            logger.warning(f"Still cannot save section {section_name} after interaction")

                            # Take screenshot and try one more time with different button
                            await self.lca_filer.screenshot_manager.take_screenshot(
                                page,
                                f"save_error_{section_name}"
                            )

                            # Try alternative continue methods
                            if not await navigation.try_alternative_continue():
                                logger.warning(f"All continue methods failed for section {section_name}")

                result["steps_completed"].append(f"section_{section_name}")
                self.update_filing_status(filing_id, {
                    "status": "processing",
                    "step": f"section_{section_count}_{section_name}_complete",
                    "message": f"Completed section: {section_name}"
                })
                logger.info(f"Completed section: {section_name}")

            # Handle review and final submission
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "review_and_submission",
                "message": "Reviewing and submitting final LCA form"
            })

            # Check if review page needs human interaction
            review_interaction = await self.form_capture.detect_interaction_required()
            if review_interaction:
                # Human verification of the final form before submission
                await self._handle_interaction(filing_id, review_interaction, page, form_filler)

            # Submit the final form
            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "submission",
                "message": "Submitting final LCA form"
            })

            logger.info("Submitting final LCA form")
            if not await navigation.submit_final():
                # Check if submission needs human interaction
                submission_interaction = await self.form_capture.detect_interaction_required()
                if submission_interaction:
                    # Handle submission interaction
                    await self._handle_interaction(filing_id, submission_interaction, page, form_filler)

                    # Try to submit again
                    if not await navigation.submit_final():
                        error_msg = "Failed to submit LCA form even after human interaction"
                        self.update_filing_status(filing_id, {
                            "status": "error",
                            "step": "submission_failed",
                            "error": error_msg
                        })
                        result["status"] = "submission_failed"
                        result["error"] = error_msg
                        return result
                else:
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
                # Try to look for confirmation information with human help
                confirmation_interaction = await self.form_capture.detect_interaction_required()
                if confirmation_interaction:
                    # Ask human to help find confirmation number
                    confirmation_interaction[
                        "guidance"] = "Please help identify the confirmation number from this page."
                    await self._handle_interaction(filing_id, confirmation_interaction, page, form_filler)

                    # Check if human provided confirmation in interaction results
                    if filing_id in self.interaction_results:
                        interaction_result = self.interaction_results[filing_id]
                        # Look for any field that might contain confirmation number
                        for field_id, field_value in interaction_result.items():
                            if "confirm" in field_id.lower() and field_value:
                                result["confirmation_number"] = field_value
                                result["status"] = "success"
                                self.update_filing_status(filing_id, {
                                    "status": "success",
                                    "step": "complete",
                                    "message": f"Successfully filed LCA, confirmation number: {field_value}",
                                    "confirmation_number": field_value
                                })
                                logger.info(
                                    f"Successfully filed LCA, confirmation number provided by human: {field_value}")
                                break
                        else:
                            # No confirmation number found in interaction results
                            result["status"] = "confirmation_failed"
                            result["error"] = "Failed to get confirmation number after submission"
                            logger.error("Failed to get confirmation number even with human assistance")

                else:
                    # No interaction needed but still no confirmation number
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

    async def _handle_interaction(self, filing_id, interaction_data, page, form_filler):
        """
        Handle required interaction from the filing process.

        Args:
            filing_id: Filing ID
            interaction_data: Interaction data dictionary
            page: Playwright page
            form_filler: Form filler instance
        """
        logger.info(f"Human interaction required for filing {filing_id}")

        self.update_filing_status(filing_id, {
            "status": "interaction_needed",
            "step": "waiting_for_human",
            "message": "Human interaction required",
            "interaction_data": {
                "section": interaction_data.get("section_name", ""),
                "fields": [field["id"] for field in interaction_data.get("fields", [])],
                "has_errors": interaction_data.get("has_errors", False),
                "has_missing_elements": interaction_data.get("has_missing_elements", False)
            }
        })

        # Add to interaction history
        # (This would be added to the result in the calling method)

        # Call interaction callback if provided
        if self.interaction_callback:
            self.filing_paused = True
            self.pending_interaction = interaction_data

            # Clear previous event
            self.interaction_completed.clear()

            # Call the callback
            self.interaction_callback(filing_id, interaction_data)

            # Wait for human interaction
            self.update_filing_status(filing_id, {
                "status": "waiting_for_input",
                "step": "waiting_for_human_input",
                "message": "Waiting for human interaction"
            })

            logger.info("Waiting for human interaction...")
            try:
                # Set a timeout for waiting for user input (e.g., 30 minutes)
                wait_timeout = 1800  # 30 minutes in seconds
                await asyncio.wait_for(self.interaction_completed.wait(), timeout=wait_timeout)
            except asyncio.TimeoutError:
                logger.error(f"Timeout waiting for human interaction after {wait_timeout} seconds")
                # Reset the paused state
                self.filing_paused = False
                # Update status to indicate timeout
                self.update_filing_status(filing_id, {
                    "status": "error",
                    "step": "interaction_timeout",
                    "message": f"Timed out waiting for human interaction after {wait_timeout / 60} minutes"
                })
                # Re-raise to be caught by caller
                raise

            self.filing_paused = False

            self.update_filing_status(filing_id, {
                "status": "processing",
                "step": "continuing_after_interaction",
                "message": "Continuing after human interaction"
            })

            # Apply the interaction results to the form
            if filing_id in self.interaction_results:
                interaction_result = self.interaction_results[filing_id]
                await self._apply_interaction_results(page, form_filler, interaction_result)
                del self.interaction_results[filing_id]
            else:
                logger.warning(f"No interaction result received for filing {filing_id}")
        else:
            # No callback provided, can't continue
            logger.error("Human interaction required but no callback provided")
            raise Exception("Human interaction required - no callback provided")

    async def _attempt_login_with_retry(self, navigation, credentials, max_attempts=3):
        """
        Attempt to login with retry logic and better error handling.

        Args:
            navigation: Navigation instance
            credentials: Login credentials
            max_attempts: Maximum number of login attempts

        Returns:
            True if login successful, False otherwise
        """
        for attempt in range(max_attempts):
            logger.info(f"Login attempt {attempt + 1}/{max_attempts}")

            try:
                # Attempt login
                login_result = await navigation.login(credentials)
                if login_result:
                    logger.info("Login successful")
                    return True

                # If login failed, check if human interaction is needed
                if self.form_capture:
                    interaction_needed = await self.form_capture.detect_interaction_required()
                    if interaction_needed:
                        # We might be on a CAPTCHA or other challenge page
                        logger.info("Login requires human interaction")

                        # Take a screenshot
                        screenshot_path = await self.lca_filer.screenshot_manager.take_screenshot(
                            navigation.page,
                            "login_interaction_required"
                        )

                        # Update interaction data with login-specific guidance
                        interaction_needed[
                            "guidance"] = "Please help complete the login process. You may need to solve a CAPTCHA or provide additional verification."
                        interaction_needed["screenshot_path"] = screenshot_path

                        # Handle the interaction
                        filing_id = "login"  # Use a generic ID for login
                        await self._handle_interaction(filing_id, interaction_needed, navigation.page, None)

                        # Check if we're logged in after interaction
                        is_logged_in = await navigation.check_if_logged_in()
                        if is_logged_in:
                            logger.info("Successfully logged in after human interaction")
                            return True
            except Exception as e:
                logger.error(f"Error during login attempt {attempt + 1}: {str(e)}")

            # Wait before retry
            if attempt < max_attempts - 1:
                logger.info(f"Waiting before retry...")
                await asyncio.sleep(2)

        logger.error("All login attempts failed")
        return False

    async def _configure_totp_from_application(self, application_data: Dict[str, Any]) -> None:
        """
        Configure TOTP from application data if needed.

        Args:
            application_data: Application data
        """
        # Check for TOTP secret in credentials
        credentials = application_data.get("credentials", {})
        username = credentials.get("username")
        totp_secret = credentials.get("totp_secret")

        if username and totp_secret:
            # Enable TOTP if it wasn't already
            if not self.lca_filer.config.get("totp", "enabled", default=False):
                self.lca_filer.config.set(True, "totp", "enabled")
                logger.info("Enabled TOTP authentication")

            # Initialize TOTP handler if not already
            if not self.lca_filer.two_factor_auth:
                totp_config = self.lca_filer.config.get("totp", {})
                # Make sure we have a 'secrets' dictionary even if it's empty
                if "secrets" not in totp_config:
                    totp_config["secrets"] = {}
                self.lca_filer.two_factor_auth = TwoFactorAuth(totp_config)
                logger.info("Two-factor authentication initialized")

            # Add or update the secret
            self.lca_filer.two_factor_auth.totp_secrets[username] = totp_secret
            self.lca_filer.config.set_totp_secret(username, totp_secret)
            logger.info(f"Configured TOTP secret for {username} from application data")

            # Test the secret
            if self.lca_filer.two_factor_auth:
                totp_code = self.lca_filer.two_factor_auth.generate_totp_code(username)
                if totp_code:
                    logger.info(f"Successfully generated TOTP code for {username}: {totp_code}")
                else:
                    logger.warning(f"Failed to generate TOTP code for {username}")

                # Test with different parameters if the default fails
                totp_test = self.lca_filer.two_factor_auth.test_totp_for_user(username)
                if totp_test["status"] == "success":
                    logger.info(f"TOTP test successful. Current code: {totp_test['current_code']}")
                elif totp_test["status"] == "partial_success":
                    # Update configuration with working parameters
                    logger.info(f"TOTP default config failed but found working alternative")
                    rec_config = totp_test["recommended_config"]
                    self.lca_filer.two_factor_auth.algorithm = rec_config["algorithm"]
                    self.lca_filer.two_factor_auth.digits = rec_config["digits"]
                    self.lca_filer.two_factor_auth.interval = rec_config["interval"]
                    logger.info(
                        f"Updated TOTP config: alg={rec_config['algorithm']}, digits={rec_config['digits']}, interval={rec_config['interval']}")
                    logger.info(f"Current code with new config: {totp_test['current_code']}")
                else:
                    logger.error(f"TOTP test failed: {totp_test['error']}")
        else:
            logger.info("No TOTP credentials provided in application data")

            # Check if username has a pre-configured TOTP secret
            if username and self.lca_filer.two_factor_auth:
                if username in self.lca_filer.two_factor_auth.totp_secrets:
                    logger.info(f"Using pre-configured TOTP secret for {username}")
                else:
                    logger.warning(f"No TOTP secret configured for {username} - login may fail if 2FA is required")
                    "