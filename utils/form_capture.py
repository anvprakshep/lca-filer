import asyncio
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Union
from playwright.async_api import Page, ElementHandle

from utils.logger import get_logger
from utils.screenshot_manager import ScreenshotManager

logger = get_logger(__name__)


class FormCapture:
    """Captures form elements and options from the FLAG portal during navigation."""

    def __init__(self, page: Page, screenshot_manager: ScreenshotManager):
        """
        Initialize form capture utility.

        Args:
            page: Playwright page
            screenshot_manager: Screenshot manager for capturing form element state
        """
        self.page = page
        self.screenshot_manager = screenshot_manager
        self.captured_elements = {}  # Store captured elements
        self.current_section = ""

    async def capture_current_section(self) -> Dict[str, Any]:
        """
        Capture all form elements in the current section.

        Returns:
            Dictionary with captured form elements and metadata
        """
        try:
            # Find the current section title
            section_title_element = await self.page.query_selector("h1, h2")
            if section_title_element:
                self.current_section = await section_title_element.text_content() or "Unknown Section"
            else:
                self.current_section = "Unknown Section"

            logger.info(f"Capturing form elements for section: {self.current_section}")

            # Take a screenshot of the current form
            screenshot_path = await self.screenshot_manager.take_screenshot(
                self.page,
                f"form_section_{self.current_section.replace(' ', '_').lower()}"
            )

            # Capture form elements
            form_elements = []

            # Find all interactive elements
            interactive_elements = await self.page.query_selector_all(
                "input:not([type='hidden']), select, textarea, button:not([type='submit']), "
                "[role='combobox'], [role='listbox'], [role='checkbox'], [role='radio'], "
                "[role='button'], .checkbox, .radio, .select, .dropdown"
            )

            for element in interactive_elements:
                element_data = await self.capture_element(element)
                if element_data:
                    form_elements.append(element_data)

            # Save captured data for this section
            section_data = {
                "section_name": self.current_section,
                "elements": form_elements,
                "screenshot_path": screenshot_path,
                "timestamp": datetime.now().isoformat()
            }

            # Store in captured elements
            self.captured_elements[self.current_section] = section_data

            logger.info(f"Captured {len(form_elements)} form elements in section: {self.current_section}")
            return section_data

        except Exception as e:
            logger.error(f"Error capturing form elements: {str(e)}")
            screenshot_path = await self.screenshot_manager.take_screenshot(
                self.page,
                f"error_form_capture_{self.current_section.replace(' ', '_').lower()}"
            )
            return {
                "section_name": self.current_section or "Error",
                "elements": [],
                "screenshot_path": screenshot_path,
                "error": str(e)
            }

    async def capture_element(self, element: ElementHandle) -> Optional[Dict[str, Any]]:
        """
        Enhanced version of capture_element with better field detection and attributes.

        Args:
            element: Playwright element handle

        Returns:
            Dictionary with element details or None if failed
        """
        try:
            # Get basic element properties with improved attribute detection
            tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
            element_id = await element.get_attribute("id") or ""
            element_name = await element.get_attribute("name") or ""
            element_type = await element.get_attribute("type") or ""
            element_class = await element.get_attribute("class") or ""
            element_role = await element.get_attribute("role") or ""

            # Skip hidden elements
            if element_type == "hidden":
                return None

            # For selects, we don't get type
            if tag_name == "select":
                element_type = "select"

            if tag_name == "textarea":
                element_type = "textarea"

            # Better handling for non-standard input types
            if tag_name == "div" and element_role == "combobox":
                element_type = "autocomplete"

            # Find the label with improved methods
            label_text = await self._find_label_for_element_enhanced(element, element_id, element_name)

            # Get placeholder and default value
            placeholder = await element.get_attribute("placeholder") or ""

            # Get more attributes for better field rendering
            pattern = await element.get_attribute("pattern") or ""
            min_value = await element.get_attribute("min") or ""
            max_value = await element.get_attribute("max") or ""
            step = await element.get_attribute("step") or ""
            accept = await element.get_attribute("accept") or ""  # For file inputs
            maxlength = await element.get_attribute("maxlength") or ""

            # Enhanced retrieval of default value/state
            default_value = ""
            if element_type in ["radio", "checkbox"]:
                # Check if it's checked
                try:
                    is_checked = await element.evaluate("el => el.checked")
                    if element_type == "radio":
                        # For radio, only store value if checked
                        if is_checked:
                            default_value = await element.get_attribute("value") or "on"
                    else:
                        # For checkbox, store checked state
                        default_value = is_checked
                except Exception as e:
                    logger.debug(f"Could not determine checkbox/radio state: {str(e)}")
            elif element_type not in ["file"]:
                try:
                    # Get value from different properties based on element type
                    default_value = await element.evaluate("""
                        el => {
                            if (el.tagName === "SELECT") {
                                // For select, get selected option(s)
                                if (el.multiple) {
                                    return Array.from(el.selectedOptions).map(opt => opt.value);
                                } else {
                                    return el.value || '';
                                }
                            } else if (el.tagName === "DIV" && el.getAttribute("role") === "combobox") {
                                // For autocomplete divs
                                const input = el.querySelector('input');
                                return input ? input.value : '';
                            } else {
                                // For regular inputs
                                return el.value || '';
                            }
                        }
                    """)
                except Exception as e:
                    logger.debug(f"Could not get default value: {str(e)}")

            # Check if this is a required field
            is_required = await element.get_attribute("required") is not None or await element.get_attribute(
                "aria-required") == "true"
            is_readonly = await element.get_attribute("readonly") is not None or await element.get_attribute(
                "aria-readonly") == "true"
            is_disabled = await element.get_attribute("disabled") is not None or await element.get_attribute(
                "aria-disabled") == "true"

            # Get aria attributes for accessibility and potential validation messages
            aria_label = await element.get_attribute("aria-label") or ""
            aria_describedby = await element.get_attribute("aria-describedby") or ""
            aria_invalid = await element.get_attribute("aria-invalid") or ""

            # Get list attribute for datalist
            list_id = await element.get_attribute("list") or ""
            datalist_options = []

            if list_id:
                try:
                    # Get options from the datalist
                    datalist_options = await self.page.evaluate(f"""
                        () => {{
                            const list = document.getElementById('{list_id}');
                            if (!list) return [];
                            return Array.from(list.options).map(opt => ({{
                                value: opt.value,
                                label: opt.textContent || opt.value
                            }}));
                        }}
                    """)
                except Exception as e:
                    logger.debug(f"Could not get datalist options: {str(e)}")

            # Generate a unique ID if none exists
            generated_id = element_id or element_name
            if not generated_id:
                # Create a synthetic ID based on attributes
                tag_part = tag_name[:3]  # First 3 chars of tag
                type_part = element_type[:3] if element_type else ""  # First 3 chars of type
                label_part = label_text.replace(" ", "_")[:10].lower() if label_text else ""  # First 10 chars of label
                class_part = ""
                if element_class:
                    # Extract first class name
                    class_matches = re.search(r'\S+', element_class)
                    if class_matches:
                        class_part = class_matches.group(0)[:10]  # First 10 chars of first class
                # Combine parts with unique timestamp
                timestamp = int(datetime.now().timestamp() * 1000) % 100000  # Last 5 digits of current timestamp
                generated_id = f"{tag_part}_{type_part}_{label_part}_{class_part}_{timestamp}"
                generated_id = re.sub(r'[^a-zA-Z0-9_]', '', generated_id)  # Remove any invalid chars
                # Remove consecutive underscores
                generated_id = re.sub(r'_+', '_', generated_id)
                # Remove leading/trailing underscores
                generated_id = generated_id.strip('_')

                if not generated_id:
                    # Fallback if we still don't have an ID
                    generated_id = f"element_{tag_name}_{timestamp}"

            # Build the element data with enhanced properties
            element_data = {
                "id": generated_id,
                "name": element_name,
                "type": element_type,
                "tag": tag_name,
                "class": element_class,
                "role": element_role,
                "label": label_text or aria_label or element_id or element_name,
                "placeholder": placeholder,
                "default_value": default_value,
                "required": is_required,
                "disabled": is_disabled,
                "read_only": is_readonly,
                "pattern": pattern,
                "min": min_value,
                "max": max_value,
                "step": step,
                "accept": accept,
                "maxlength": maxlength,
                "aria_invalid": aria_invalid == "true"
            }

            # If we have a datalist, add options
            if datalist_options:
                element_data["datalist_options"] = datalist_options

            # Try to get description from aria-describedby
            if aria_describedby:
                try:
                    description_element = await self.page.query_selector(f"#{aria_describedby}")
                    if description_element:
                        description_text = await description_element.text_content()
                        if description_text:
                            element_data["description"] = description_text.strip()
                except Exception as e:
                    logger.debug(f"Could not get description from aria-describedby: {str(e)}")

            # Try to get any accessible description or validation message
            try:
                # Check for accessible description
                aria_desc = await element.evaluate("""
                    el => {
                        // Check for any description element that might be associated
                        if (el.getAttribute('aria-describedby')) {
                            const descId = el.getAttribute('aria-describedby');
                            const descEl = document.getElementById(descId);
                            return descEl ? descEl.textContent : null;
                        }
                        // Check for adjacent description
                        const next = el.nextElementSibling;
                        if (next && (next.classList.contains('description') || 
                                    next.classList.contains('help-text') || 
                                    next.classList.contains('hint'))) {
                            return next.textContent;
                        }
                        return null;
                    }
                """)
                if aria_desc:
                    element_data["description"] = aria_desc.strip()
            except Exception as e:
                logger.debug(f"Error getting accessible description: {str(e)}")

            # Capture validation message if available
            try:
                validation_message = await element.evaluate("el => el.validationMessage || ''")
                if validation_message:
                    element_data["validation_message"] = validation_message
            except Exception as e:
                logger.debug(f"Could not get validation message: {str(e)}")

            # Capture options for select and radio elements
            if element_type == "select" or tag_name == "select":
                element_data["options"] = await self._capture_select_options_enhanced(element)
            elif element_type == "radio":
                element_data["options"] = await self._capture_radio_options_enhanced(element)

            # Take screenshot of the element
            try:
                element_selector = None
                if element_id:
                    element_selector = f"#{element_id}"
                elif element_name:
                    element_selector = f"[name='{element_name}']"

                if element_selector:
                    screenshot_path = await self.screenshot_manager.take_element_screenshot(
                        self.page,
                        element_selector,
                        f"element_{generated_id}"
                    )
                    element_data["screenshot_path"] = screenshot_path
            except Exception as e:
                logger.debug(f"Could not take element screenshot: {str(e)}")

            return element_data

        except Exception as e:
            logger.error(f"Error capturing form element: {str(e)}")
            return None

    async def detect_interaction_required(self, expected_selectors=None) -> Optional[Dict[str, Any]]:
        """
        Enhanced version to detect when interaction is required, handling missing elements
        and elements with indeterminate values.

        Args:
            expected_selectors: Optional list of selectors that should be present, in the format:
                [{"selector": "input#field-id", "description": "Field Name", "required": True}]

        Returns:
            Dictionary with interaction data if needed, None otherwise
        """
        try:
            # Capture the current form section for context
            section_data = await self.capture_current_section()
            logger.info(f"Checking if interaction required for section: {section_data['section_name']}")

            # Always take a screenshot of the current state for reference
            screenshot_path = await self.screenshot_manager.take_screenshot(
                self.page,
                f"interaction_check_{section_data['section_name'].replace(' ', '_').lower()}"
            )

            # Step 1: Check for expected elements that are missing
            missing_elements = []
            if expected_selectors:
                logger.info(f"Checking for {len(expected_selectors)} expected elements")
                for selector_info in expected_selectors:
                    selector = selector_info.get("selector")
                    description = selector_info.get("description", selector)
                    required = selector_info.get("required", True)

                    try:
                        logger.debug(f"Looking for expected element: {selector}")
                        element = await self.page.wait_for_selector(selector, timeout=3000)
                        if not element:
                            logger.warning(f"Expected element not found: {selector} ({description})")
                            missing_elements.append({
                                "selector": selector,
                                "description": description,
                                "required": required
                            })
                    except Exception as e:
                        logger.warning(f"Error finding expected element {selector}: {str(e)}")
                        missing_elements.append({
                            "selector": selector,
                            "description": description,
                            "required": required
                        })

            # Step 2: Check for validation errors
            error_messages = await self._detect_error_messages()

            # Get all visible error texts
            error_texts = []
            for error in error_messages:
                try:
                    error_text = await error.text_content()
                    if error_text and error_text.strip():
                        if error_text.strip() not in error_texts:
                            error_texts.append(error_text.strip())
                except Exception as e:
                    logger.debug(f"Error getting error text: {str(e)}")

            has_errors = len(error_texts) > 0

            # Step 3: Check for form elements that need input
            fields_requiring_interaction = []

            # First, add fields for missing expected elements
            for missing in missing_elements:
                # Generate options for this selector
                element_options = await self._generate_options_for_selector(missing["selector"])

                # Create a field for this missing element
                field_id = missing["selector"].replace(".", "_").replace("#", "_").replace("[", "_").replace("]", "_")
                field_id = re.sub(r'[^a-zA-Z0-9_]', '_', field_id)  # Replace any remaining invalid chars
                field_id = re.sub(r'_+', '_', field_id)  # Replace consecutive underscores
                field_id = field_id.strip('_')  # Remove leading/trailing underscores

                # Determine the most appropriate field type
                field_type = "text"  # Default
                if "radio" in missing["selector"].lower():
                    field_type = "radio"
                elif "checkbox" in missing["selector"].lower():
                    field_type = "checkbox"
                elif "select" in missing["selector"].lower():
                    field_type = "select"

                fields_requiring_interaction.append({
                    "id": field_id,
                    "label": f"Select {missing['description']}",
                    "type": field_type,
                    "options": element_options,
                    "required": missing["required"],
                    "field_errors": [],
                    "description": f"The system couldn't find {missing['description']}. Please make a selection."
                })

            # Step 4: Check for required fields that are empty
            required_empty_fields = []
            for element in section_data["elements"]:
                # Check if this is a required field with no value
                if element.get("required", False) and not element.get("default_value"):
                    required_empty_fields.append(element)

                # Also check for fields with invalid attribute
                if element.get("aria_invalid") == "true":
                    if element not in required_empty_fields:
                        required_empty_fields.append(element)

            # Add required empty fields to interaction list
            for field in required_empty_fields:
                # Skip if we already have this field (might be from missing elements)
                if any(f["id"] == field["id"] for f in fields_requiring_interaction):
                    continue

                fields_requiring_interaction.append(field)

            # Step 5: Check for fields associated with errors
            error_related_fields = await self._find_fields_with_errors(error_messages, section_data["elements"])

            # Add error related fields to interaction list
            for field in error_related_fields:
                # Skip if we already have this field
                if any(f["id"] == field["id"] for f in fields_requiring_interaction):
                    continue

                fields_requiring_interaction.append(field)

            # Step 6: See if we have any other unreadable or inaccessible form elements
            problem_fields = await self._detect_problem_fields()
            for field in problem_fields:
                # Skip if we already have this field
                if any(f["id"] == field["id"] for f in fields_requiring_interaction):
                    continue

                fields_requiring_interaction.append(field)

            # If we're in a critical section and there are ANY form elements, consider adding them for verification
            if await self._is_critical_section():
                logger.info(f"In critical section, checking all form elements")
                all_critical_fields = await self._get_critical_section_fields()
                for field in all_critical_fields:
                    # Skip if we already have this field
                    if any(f["id"] == field["id"] for f in fields_requiring_interaction):
                        continue

                    fields_requiring_interaction.append(field)

            # Only request interaction if we have something to interact with
            if fields_requiring_interaction or has_errors or missing_elements:
                # Create guidance message
                guidance_message = "Please review and complete the following fields to continue processing."
                if has_errors:
                    guidance_message = "Please correct the following errors to continue processing."
                elif missing_elements:
                    guidance_message = "The automation couldn't find some elements. Please make selections based on what you see in the screenshot."

                interaction_data = {
                    "section_name": section_data["section_name"],
                    "screenshot_path": screenshot_path,
                    "fields": fields_requiring_interaction,
                    "error_messages": error_texts,
                    "has_errors": has_errors,
                    "has_missing_elements": len(missing_elements) > 0,
                    "missing_elements": missing_elements,
                    "guidance": guidance_message,
                    "timestamp": datetime.now().isoformat()
                }

                logger.info(
                    f"Human interaction required: {len(fields_requiring_interaction)} fields, {len(error_texts)} errors, {len(missing_elements)} missing elements")
                return interaction_data

            logger.info("No interaction required - form looks good to proceed automatically")
            return None

        except Exception as e:
            logger.error(f"Error detecting if interaction required: {str(e)}")

            # Take an error screenshot
            error_screenshot = await self.screenshot_manager.take_screenshot(
                self.page,
                f"error_interaction_check_{datetime.now().strftime('%H%M%S')}"
            )

            # Request human interaction due to error
            return {
                "section_name": "Error Processing Section",
                "screenshot_path": error_screenshot,
                "fields": [],
                "error_messages": [f"Error during interaction check: {str(e)}"],
                "has_errors": True,
                "has_missing_elements": False,
                "missing_elements": [],
                "guidance": "An error occurred while checking this form. Please review the screenshot and proceed manually.",
                "timestamp": datetime.now().isoformat()
            }

    async def _detect_error_messages(self) -> List[ElementHandle]:
        """Find error messages on the page"""
        error_selectors = [
            ".error-message", ".validation-error", ".field-error", ".alert-danger",
            "[role='alert']", ".error", ".invalid-feedback", ".text-danger",
            ".error-text", "div[class*='error']", ".field-validation-error",
            "[aria-invalid='true'] + .error-message", "label.error", ".has-error .help-block"
        ]

        all_errors = []
        for selector in error_selectors:
            try:
                errors = await self.page.query_selector_all(selector)
                all_errors.extend(errors)
            except Exception:
                pass

        return all_errors

    async def _find_fields_with_errors(self, error_elements, all_form_elements) -> List[Dict[str, Any]]:
        """Find form fields associated with error messages"""
        fields_with_errors = []

        for error in error_elements:
            try:
                # Try to find associated field using various techniques
                associated_field = await self._find_field_for_error(error, all_form_elements)
                if associated_field and not any(f["id"] == associated_field["id"] for f in fields_with_errors):
                    # Add error message to field
                    error_text = await error.text_content() or "Invalid value"
                    if "field_errors" not in associated_field:
                        associated_field["field_errors"] = []
                    associated_field["field_errors"].append(error_text.strip())
                    fields_with_errors.append(associated_field)
            except Exception as e:
                logger.debug(f"Error finding field for error: {str(e)}")

        return fields_with_errors

    async def _find_field_for_error(self, error_element, all_form_elements) -> Optional[Dict[str, Any]]:
        """Find which form field an error message is associated with"""
        try:
            # Method 1: Check if error is inside a field container with a single input
            container = await error_element.evaluate("""
                error => {
                    // Find closest field container
                    let container = error.closest('.form-group, .field-container, .form-field, .form-control');
                    if (container) {
                        // Check if it has exactly one input
                        let inputs = container.querySelectorAll('input, select, textarea');
                        if (inputs.length === 1) {
                            let input = inputs[0];
                            return {
                                id: input.id,
                                name: input.name,
                                type: input.type || input.tagName.toLowerCase()
                            };
                        }
                    }
                    return null;
                }
            """)

            if container:
                # Find the corresponding field in our captured elements
                for field in all_form_elements:
                    if (field["id"] == container["id"] or
                            field["name"] == container["name"]):
                        return field

            # Method 2: Check for aria-describedby relationship
            error_id = await error_element.get_attribute("id")
            if error_id:
                for field in all_form_elements:
                    aria_describedby = field.get("aria_describedby")
                    if aria_describedby and error_id in aria_describedby.split():
                        return field

            # Method 3: Check for spatial proximity (error is usually below input)
            error_rect = await error_element.bounding_box()
            if error_rect:
                closest_field = None
                closest_distance = float('inf')

                for field in all_form_elements:
                    field_id = field.get("id")
                    if not field_id:
                        continue

                    # Find element by ID
                    field_element = await self.page.query_selector(f"#{field_id}")
                    if not field_element:
                        continue

                    field_rect = await field_element.bounding_box()
                    if not field_rect:
                        continue

                    # Check if error is below field (with some margin for spacing)
                    if (abs(field_rect["x"] - error_rect["x"]) < 50 and  # X position is similar
                            error_rect["y"] > field_rect["y"] and  # Error is below field
                            error_rect["y"] - (field_rect["y"] + field_rect["height"]) < 50):  # Not too far below

                        distance = error_rect["y"] - (field_rect["y"] + field_rect["height"])
                        if distance < closest_distance:
                            closest_distance = distance
                            closest_field = field

                if closest_field:
                    return closest_field

        except Exception as e:
            logger.debug(f"Error in finding field for error: {str(e)}")

        return None

    async def _detect_problem_fields(self) -> List[Dict[str, Any]]:
        """Detect fields that might be problematic (complex widgets, custom elements)"""
        problem_fields = []

        try:
            # Look for elements that might be custom widgets or complex UI elements
            problematic_elements = await self.page.query_selector_all(
                "[role='combobox'], [role='listbox'], [role='checkbox']:not(input), "
                "[role='radio']:not(input), [role='button']:not(button), .custom-select, "
                ".custom-checkbox, .custom-radio, .select2, .chosen-container, "
                "div[contenteditable='true']"
            )

            for element in problematic_elements:
                element_data = await self.capture_element(element)
                if element_data:
                    # Add note about needing human validation
                    element_data["description"] = f"This appears to be a custom element that may need manual selection."
                    element_data["field_errors"] = ["Complex UI element - may need manual interaction"]
                    problem_fields.append(element_data)

        except Exception as e:
            logger.debug(f"Error detecting problem fields: {str(e)}")

        return problem_fields

    async def _is_critical_section(self) -> bool:
        """Determine if current section is a critical one that always needs verification"""
        try:
            # Get current section text
            section_text = self.current_section.lower()

            # List of critical section keywords
            critical_keywords = [
                "visa", "classification", "h-1b", "h1b", "declaration",
                "confirm", "submit", "review", "legal", "attestation",
                "certification", "signature", "agreement", "terms", "compliance"
            ]

            # Check for critical keywords in section name
            for keyword in critical_keywords:
                if keyword in section_text:
                    return True

            # Check for other indicators of a critical section
            indicators = await self.page.query_selector_all(
                "input[type='checkbox'][required], .required-acknowledgement, "
                "button:has-text('Submit'), button:has-text('Sign'), "
                "button:has-text('Certify'), button:has-text('Agree')"
            )

            return len(indicators) > 0

        except Exception as e:
            logger.debug(f"Error checking if critical section: {str(e)}")
            return False

    async def _get_critical_section_fields(self) -> List[Dict[str, Any]]:
        """Get fields from critical sections that need verification"""
        critical_fields = []

        try:
            # Look for acknowledgement checkboxes, signature fields, etc.
            elements = await self.page.query_selector_all(
                "input[type='checkbox'][required], input[type='radio'][required], "
                "input[name*='signature'], input[name*='confirm'], input[name*='certify'], "
                "input[name*='acknowledge'], input[name*='agree'], "
                "input[name*='declaration'], textarea[required]"
            )

            for element in elements:
                element_data = await self.capture_element(element)
                if element_data:
                    # Add note about critical verification
                    element_data["description"] = "This field requires verification in a critical section."
                    element_data["field_errors"] = ["Critical field - needs verification"]
                    critical_fields.append(element_data)

        except Exception as e:
            logger.debug(f"Error getting critical section fields: {str(e)}")

        return critical_fields

    async def _generate_options_for_selector(self, selector: str) -> List[Dict[str, str]]:
        """
        Dynamically generate options based on elements found on the page.

        Args:
            selector: The selector to find elements for

        Returns:
            List of option dictionaries with value and label
        """
        options = []
        try:
            # For radio buttons, find all options in the same group
            if "radio" in selector.lower():
                # Try to extract the name attribute from the selector
                name_match = re.search(r"name=['\"]([^'\"]+)['\"]", selector)
                name = name_match.group(1) if name_match else None

                if name:
                    # Find all radio buttons with the same name
                    radio_selector = f"input[type='radio'][name='{name}']"
                    radio_elements = await self.page.query_selector_all(radio_selector)

                    # Extract value and label for each radio button
                    for radio in radio_elements:
                        value = await radio.get_attribute("value") or ""
                        label_text = await self._find_label_for_element_enhanced(radio,
                                                                                 await radio.get_attribute("id") or "",
                                                                                 name)

                        # If no label found, try to get text near the radio
                        if not label_text:
                            label_text = await radio.evaluate("""
                                el => {
                                    // Get closest text node sibling
                                    let node = el;
                                    while (node.nextSibling) {
                                        node = node.nextSibling;
                                        if (node.nodeType === 3 && node.textContent.trim()) {
                                            return node.textContent.trim();
                                        }
                                        if (node.nodeType === 1 && node.textContent.trim() &&
                                            !node.querySelector('input, select, textarea')) {
                                            return node.textContent.trim();
                                        }
                                    }
                                    return null;
                                }
                            """)

                        # If still no label, use value as label
                        if not label_text:
                            label_text = value or f"Option {len(options) + 1}"

                        options.append({
                            "value": value,
                            "label": label_text.strip()
                        })
                else:
                    # No name found in selector, try to find any radio buttons
                    radio_elements = await self.page.query_selector_all("input[type='radio']")

                    # Group by name
                    radio_groups = {}
                    for radio in radio_elements:
                        radio_name = await radio.get_attribute("name")
                        if radio_name:
                            if radio_name not in radio_groups:
                                radio_groups[radio_name] = []
                            radio_groups[radio_name].append(radio)

                    # Try to find the most relevant group (closest to selector pattern)
                    selector_text = selector.lower()
                    best_group = None
                    best_score = -1

                    for group_name, group_radios in radio_groups.items():
                        # Calculate relevance score based on text similarity and position
                        score = 0
                        if group_name.lower() in selector_text:
                            score += 10

                        # Add options from best matching group
                        if score > best_score or not best_group:
                            best_group = group_radios
                            best_score = score

                    # Use best group or first group if available
                    if best_group:
                        for radio in best_group:
                            value = await radio.get_attribute("value") or ""
                            radio_id = await radio.get_attribute("id") or ""
                            radio_name = await radio.get_attribute("name") or ""

                            label_text = await self._find_label_for_element_enhanced(radio, radio_id, radio_name)
                            if not label_text:
                                label_text = value or f"Option {len(options) + 1}"

                            options.append({
                                "value": value,
                                "label": label_text.strip()
                            })

            # For select elements
            elif "select" in selector.lower():
                # Try to find select element
                select_element = await self.page.query_selector(selector)
                if not select_element:
                    # Try alternate selectors
                    if "#" in selector:
                        id_value = selector.split("#")[1].split(" ")[0].split("[")[0]
                        select_element = await self.page.query_selector(f"select#{id_value}")
                    elif "name=" in selector:
                        name_match = re.search(r"name=['\"]([^'\"]+)['\"]", selector)
                        if name_match:
                            name_value = name_match.group(1)
                            select_element = await self.page.query_selector(f"select[name='{name_value}']")

                if select_element:
                    # Get options from the select element
                    options_data = await select_element.evaluate("""
                        select => Array.from(select.options).map(option => ({
                            value: option.value,
                            label: option.textContent.trim() || option.value,
                            selected: option.selected,
                            disabled: option.disabled
                        }))
                    """)
                    options = options_data
                else:
                    # No select found, look for any select elements
                    all_selects = await self.page.query_selector_all("select")
                    if len(all_selects) == 1:
                        # Only one select on page, use it
                        options_data = await all_selects[0].evaluate("""
                            select => Array.from(select.options).map(option => ({
                                value: option.value,
                                label: option.textContent.trim() || option.value,
                                selected: option.selected,
                                disabled: option.disabled
                            }))
                        """)
                        options = options_data

            # For checkboxes
            elif "checkbox" in selector.lower():
                checkbox = await self.page.query_selector(selector)
                if checkbox:
                    value = await checkbox.get_attribute("value") or "true"
                    checkbox_id = await checkbox.get_attribute("id") or ""
                    checkbox_name = await checkbox.get_attribute("name") or ""

                    label_text = await self._find_label_for_element_enhanced(checkbox, checkbox_id, checkbox_name)
                    if not label_text:
                        label_text = "Yes"

                    options = [
                        {"value": value, "label": label_text},
                        {"value": "", "label": "No"}
                    ]
                else:
                    # Default options for checkbox
                    options = [
                        {"value": "true", "label": "Yes"},
                        {"value": "", "label": "No"}
                    ]

            # If we couldn't find any options but we have a complex selector
            # Let's try to extract all possible values from the page context
            if not options and selector:
                # Look for anything that might be a selectable option
                possible_options = await self.page.evaluate("""
                    () => {
                        // Find all elements that look like options
                        const allOptions = Array.from(document.querySelectorAll('input[type="radio"], input[type="checkbox"], option, button.option, li.option, [role="option"]'));

                        // Extract their values and labels
                        return allOptions.map(el => {
                            let value = el.value || el.getAttribute('data-value') || el.id || el.textContent.trim();
                            let label = el.textContent.trim() || el.getAttribute('aria-label') || el.title || value;

                            return { value, label };
                        }).filter(opt => opt.value); // Filter out empty values
                    }
                """)

                # Add any options we found
                for opt in possible_options:
                    if opt not in options:
                        options.append(opt)

            # Still no options? Try to find anything with values
            if not options:
                # Look for any elements with value attributes
                elements_with_values = await self.page.evaluate("""
                    () => {
                        // Find all elements with value attributes
                        const elements = Array.from(document.querySelectorAll('[value]'));

                        return elements.map(el => ({
                            value: el.getAttribute('value'),
                            label: el.textContent.trim() || el.getAttribute('value')
                        })).filter(opt => opt.value); // Filter out empty values
                    }
                """)

                # Add any options we found
                for opt in elements_with_values:
                    if opt not in options:
                        options.append(opt)

            # Still no options? Try to find text fragments that might be options
            if not options:
                # Look for text fragments
                text_fragments = await self.page.evaluate("""
                    () => {
                        // Find all elements with text that might be options
                        return Array.from(document.querySelectorAll('div, span, p, li'))
                            .filter(el => {
                                // Only consider visible elements with short text
                                const text = el.textContent.trim();
                                return text && text.length < 50 && 
                                       window.getComputedStyle(el).display !== 'none' &&
                                       window.getComputedStyle(el).visibility !== 'hidden';
                            })
                            .map(el => ({
                                value: el.textContent.trim(),
                                label: el.textContent.trim()
                            }));
                    }
                """)

                # Only use the first 10 options to avoid overwhelming
                for opt in text_fragments[:10]:
                    if opt not in options:
                        options.append(opt)

        except Exception as e:
            logger.warning(f"Error generating options for selector {selector}: {str(e)}")

            # Always provide at least a few generic options so the user can proceed
            if not options:
                options = [
                    {"value": "option1", "label": "Option 1"},
                    {"value": "option2", "label": "Option 2"},
                    {"value": "option3", "label": "Option 3"},
                    {"value": "custom", "label": "Other (specify in notes)"}
                ]

        return options

    async def _find_label_for_element_enhanced(self, element: ElementHandle, element_id: str, element_name: str) -> str:
        """
        Enhanced method to find the label text for a form element.

        Args:
            element: Playwright element handle
            element_id: Element ID
            element_name: Element name

        Returns:
            Label text or empty string
        """
        label_text = ""

        try:
            # Try multiple techniques to find the label

            # 1. First try aria-labelledby
            aria_labelledby = await element.get_attribute("aria-labelledby")
            if aria_labelledby:
                for label_id in aria_labelledby.split():
                    label_element = await self.page.query_selector(f"#{label_id}")
                    if label_element:
                        label_content = await label_element.text_content()
                        if label_content:
                            return label_content.strip()

            # 2. Try aria-label directly
            aria_label = await element.get_attribute("aria-label")
            if aria_label:
                return aria_label.strip()

            # 3. Try to find label by for attribute
            if element_id:
                # Try multiple selector patterns for labels
                for label_selector in [
                    f"label[for='{element_id}']",
                    f"label[for='{element_id.replace('_', '-')}']",  # Try with dashes
                    f"*[for='{element_id}']"  # Any element with for attribute
                ]:
                    label_element = await self.page.query_selector(label_selector)
                    if label_element:
                        label_text = await label_element.text_content()
                        if label_text:
                            return label_text.strip()

            # 4. Try finding by name attribute if id failed
            if element_name:
                for label_selector in [
                    f"label[for='{element_name}']",
                    f"*[for='{element_name}']"
                ]:
                    label_element = await self.page.query_selector(label_selector)
                    if label_element:
                        label_text = await label_element.text_content()
                        if label_text:
                            return label_text.strip()

            # 5. Try to find label by wrapping
            parent_label = await element.evaluate("""
                element => {
                    let parent = element.parentElement;
                    while (parent && parent.tagName !== 'LABEL' && parent.tagName !== 'BODY') {
                        parent = parent.parentElement;
                    }
                    return parent && parent.tagName === 'LABEL' ? parent.textContent : null;
                }
            """)

            if parent_label:
                return parent_label.strip()

            # 6. Try to find nearby preceding labels or text
            nearby_labels = await self.page.evaluate(f"""
                () => {{
                    const elementId = "{element_id}";
                    const elementName = "{element_name}";
                    let targetElement = elementId ? document.getElementById(elementId) : 
                                      (elementName ? document.querySelector(`[name="${{elementName}}"]`) : null);

                    if (!targetElement) return null;

                    // Get all possible label elements that might describe this field
                    const allLabels = Array.from(document.querySelectorAll('label, div.field-label, div.form-label, p.field-label, .control-label, legend, .field-name'));

                    // Find the closest preceding label
                    let closestLabel = null;
                    let minDistance = Infinity;

                    for (const label of allLabels) {{
                        // Check if this is before our element
                        const labelRect = label.getBoundingClientRect();
                        const targetRect = targetElement.getBoundingClientRect();

                        // Label should be above or to the left
                        if (labelRect.bottom <= targetRect.top + 10 || labelRect.right <= targetRect.left) {{
                            const distance = Math.sqrt(
                                Math.pow(labelRect.left - targetRect.left, 2) + 
                                Math.pow(labelRect.top - targetRect.top, 2)
                            );

                            if (distance < minDistance) {{
                                minDistance = distance;
                                closestLabel = label;
                            }}
                        }}
                    }}

                    return closestLabel ? closestLabel.textContent : null;
                }}
            """)

            if nearby_labels:
                return nearby_labels.strip()

            # 7. If still no label, check if there's a placeholder we can use
            placeholder = await element.get_attribute("placeholder")
            if placeholder:
                return placeholder

            # 8. Last resort - try to use the element ID or name
            if element_id:
                # Convert camelCase or snake_case to words
                import re
                label = re.sub(r'([A-Z])', r' \1', element_id)  # Insert space before capital letters
                label = label.replace('_', ' ')  # Replace underscores with spaces
                return label.strip().title()  # Title case the result

            if element_name:
                label = element_name.replace('_', ' ')
                return label.strip().title()

        except Exception as e:
            logger.debug(f"Error finding label: {str(e)}")

        return label_text.strip() or "Unlabeled Field"

    async def _capture_select_options_enhanced(self, select_element: ElementHandle) -> List[Dict[str, str]]:
        """
        Enhanced method to capture options from a select element.

        Args:
            select_element: Playwright element handle for select

        Returns:
            List of option dictionaries with value, label, and selected state
        """
        try:
            # Get more comprehensive option info including optgroups
            options = await select_element.evaluate("""
                select => {
                    const result = [];
                    let currentGroup = null;

                    for (const element of select.children) {
                        if (element.tagName === 'OPTGROUP') {
                            // Handle optgroup
                            currentGroup = element.label;

                            // Add options within this group
                            for (const option of element.children) {
                                if (option.tagName === 'OPTION') {
                                    result.push({
                                        value: option.value,
                                        label: option.textContent.trim() || option.value,
                                        selected: option.selected,
                                        disabled: option.disabled,
                                        group: currentGroup
                                    });
                                }
                            }
                        } else if (element.tagName === 'OPTION') {
                            // Regular option
                            result.push({
                                value: element.value,
                                label: element.textContent.trim() || element.value,
                                selected: element.selected,
                                disabled: element.disabled,
                                group: null
                            });
                        }
                    }

                    return result;
                }
            """)

            return options

        except Exception as e:
            logger.error(f"Error capturing select options: {str(e)}")

            # Fallback to simpler approach
            try:
                basic_options = await select_element.evaluate("""
                    select => Array.from(select.options).map(option => ({
                        value: option.value,
                        label: option.textContent.trim() || option.value,
                        selected: option.selected
                    }))
                """)

                return basic_options

            except Exception as e2:
                logger.error(f"Error with fallback option capture: {str(e2)}")
                return []

    async def _capture_radio_options_enhanced(self, radio_element: ElementHandle) -> List[Dict[str, str]]:
        """
        Enhanced method to capture related radio options.

        Args:
            radio_element: Playwright element handle for radio button

        Returns:
            List of option dictionaries with value, label, and checked state
        """
        try:
            # Get the name of the radio group
            radio_name = await radio_element.get_attribute("name")

            if not radio_name:
                # Single radio button
                label = await self._find_label_for_element_enhanced(radio_element,
                                                                    await radio_element.get_attribute("id") or "",
                                                                    "")
                value = await radio_element.get_attribute("value") or ""
                checked = await radio_element.evaluate("el => el.checked")

                return [{
                    "value": value,
                    "label": label,
                    "checked": checked
                }]

            # Find all radio buttons in the same group
            radio_buttons = await self.page.query_selector_all(f"input[type='radio'][name='{radio_name}']")

            options = []
            for button in radio_buttons:
                button_id = await button.get_attribute("id") or ""
                button_value = await button.get_attribute("value") or ""
                button_checked = await button.evaluate("el => el.checked")
                button_disabled = await button.get_attribute("disabled") is not None

                # Find label for this radio button
                label = await self._find_label_for_element_enhanced(button, button_id, radio_name)

                options.append({
                    "value": button_value,
                    "label": label,
                    "checked": button_checked,
                    "disabled": button_disabled
                })

            return options

        except Exception as e:
            logger.error(f"Error capturing radio options: {str(e)}")
            return []