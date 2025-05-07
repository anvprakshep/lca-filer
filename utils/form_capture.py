import asyncio
from typing import Dict, Any, List, Optional, Tuple
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

            # Capture input fields
            input_elements = await self.page.query_selector_all("input:not([type='hidden']), select, textarea")

            for element in input_elements:
                element_data = await self.capture_element(element)
                if element_data:
                    form_elements.append(element_data)

            # Save captured data for this section
            section_data = {
                "section_name": self.current_section,
                "elements": form_elements,
                "screenshot_path": screenshot_path
            }

            # Store in captured elements
            self.captured_elements[self.current_section] = section_data

            logger.info(f"Captured {len(form_elements)} form elements in section: {self.current_section}")
            return section_data

        except Exception as e:
            logger.error(f"Error capturing form elements: {str(e)}")
            return {
                "section_name": self.current_section or "Error",
                "elements": [],
                "error": str(e)
            }

    async def capture_element(self, element: ElementHandle) -> Optional[Dict[str, Any]]:
        """
        Capture details of a form element.

        Args:
            element: Playwright element handle

        Returns:
            Dictionary with element details
        """
        try:
            # Get basic element properties
            tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
            element_id = await element.get_attribute("id") or ""
            element_name = await element.get_attribute("name") or ""
            element_type = await element.get_attribute("type") or ""

            # Skip hidden elements
            if element_type == "hidden":
                return None

            # For selects, we don't get type
            if tag_name == "select":
                element_type = "select"

            if tag_name == "textarea":
                element_type = "textarea"

            # Find the label
            label_text = await self._find_label_for_element(element, element_id, element_name)

            # Get placeholder and default value
            placeholder = await element.get_attribute("placeholder") or ""

            default_value = ""
            if element_type not in ["radio", "checkbox", "file"]:
                default_value = await element.evaluate("el => el.value") or ""

            # Build the element data
            element_data = {
                "id": element_id or element_name or f"element_{tag_name}_{await element.evaluate('el => el.textContent')}",
                "name": element_name,
                "type": element_type,
                "tag": tag_name,
                "label": label_text,
                "placeholder": placeholder,
                "default_value": default_value,
                "required": await element.get_attribute("required") is not None,
                "disabled": await element.get_attribute("disabled") is not None,
                "read_only": await element.get_attribute("readonly") is not None,
            }

            # Capture options for select and radio elements
            if element_type == "select" or tag_name == "select":
                element_data["options"] = await self._capture_select_options(element)
            elif element_type == "radio":
                element_data["options"] = await self._capture_radio_options(element)

            # Take screenshot of the element
            if element_id:
                element_selector = f"#{element_id}"
            elif element_name:
                element_selector = f"[name='{element_name}']"
            else:
                # Use the element handle directly
                element_selector = element

            try:
                screenshot_path = await self.screenshot_manager.take_element_screenshot(
                    self.page,
                    element_selector,
                    f"element_{element_id or element_name or element_type}"
                )
                element_data["screenshot_path"] = screenshot_path
            except Exception as e:
                logger.debug(f"Could not take element screenshot: {str(e)}")

            return element_data

        except Exception as e:
            logger.error(f"Error capturing form element: {str(e)}")
            return None

    async def _find_label_for_element(self, element: ElementHandle, element_id: str, element_name: str) -> str:
        """
        Find the label text for a form element.

        Args:
            element: Playwright element handle
            element_id: Element ID
            element_name: Element name

        Returns:
            Label text or empty string
        """
        label_text = ""

        try:
            # Try to find label by for attribute
            if element_id:
                label_element = await self.page.query_selector(f"label[for='{element_id}']")
                if label_element:
                    label_text = await label_element.text_content() or ""
                    return label_text.strip()

            # Try to find label by wrapping
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

            # Try to find nearest preceding label or div with description
            preceding_elements = await self.page.evaluate(f"""
                element => {{
                    const elementId = "{element_id}";
                    const elementName = "{element_name}";
                    let targetElement = elementId ? document.getElementById(elementId) : 
                                       (elementName ? document.querySelector(`[name="${{elementName}}"]`) : null);

                    if (!targetElement) return null;

                    // Get all possible label elements that might describe this field
                    const allLabels = Array.from(document.querySelectorAll('label, div.field-label, div.form-label, p.field-label, .control-label'));

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

            if preceding_elements:
                return preceding_elements.strip()

            # If still no label, check if there's a placeholder we can use
            placeholder = await element.get_attribute("placeholder")
            if placeholder:
                return placeholder

            # Last resort - try to use the element ID or name
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

    async def _capture_select_options(self, select_element: ElementHandle) -> List[Dict[str, str]]:
        """
        Capture options from a select element.

        Args:
            select_element: Playwright element handle for select

        Returns:
            List of option dictionaries with value and label
        """
        try:
            options = await select_element.evaluate("""
                select => Array.from(select.options).map(option => ({
                    value: option.value,
                    label: option.textContent,
                    selected: option.selected
                }))
            """)

            return options
        except Exception as e:
            logger.error(f"Error capturing select options: {str(e)}")
            return []

    async def _capture_radio_options(self, radio_element: ElementHandle) -> List[Dict[str, str]]:
        """
        Capture related radio options.

        Args:
            radio_element: Playwright element handle for radio button

        Returns:
            List of option dictionaries with value and label
        """
        try:
            # Get the name of the radio group
            radio_name = await radio_element.get_attribute("name")

            if not radio_name:
                # Single radio button
                label = await self._find_label_for_element(radio_element,
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

                # Find label for this radio button
                label = await self._find_label_for_element(button, button_id, radio_name)

                options.append({
                    "value": button_value,
                    "label": label,
                    "checked": button_checked
                })

            return options

        except Exception as e:
            logger.error(f"Error capturing radio options: {str(e)}")
            return []

    async def detect_interaction_required(self) -> Optional[Dict[str, Any]]:
        """
        Detect if the current page requires human interaction.

        This looks for complex fields, validation errors, or fields
        specifically marked for human review.

        Returns:
            Dictionary with interaction details if required, None otherwise
        """
        try:
            # Capture the current form section
            section_data = await self.capture_current_section()

            # Detect error messages
            error_messages = await self.page.query_selector_all(".error-message, .validation-error, .field-error")
            has_errors = len(error_messages) > 0

            error_texts = []
            for error in error_messages:
                error_text = await error.text_content()
                if error_text:
                    error_texts.append(error_text.strip())

            # Look for fields that might need human review
            fields_requiring_interaction = []

            for element in section_data["elements"]:
                # Check if field is complex or has special flags
                needs_review = False

                # Check for error messages related to this field
                if element.get("id") or element.get("name"):
                    field_id = element.get("id") or ""
                    field_name = element.get("name") or ""

                    # Look for error messages specifically for this field
                    field_errors = []
                    for error in error_messages:
                        error_id = await error.evaluate("""
                            error => {
                                // Try to find associated input
                                const fieldId = error.getAttribute('data-field-id') || 
                                               error.getAttribute('for') || 
                                               error.id.replace('-error', '');

                                // Check if parent has form-group and contains our target input
                                let parent = error.closest('.form-group');
                                let containsTarget = parent ? 
                                    (parent.querySelector(`#${fieldId}`) || 
                                     parent.querySelector(`[name="${fieldId}"]`)) != null : false;

                                return fieldId || (containsTarget ? 'related' : null);
                            }
                        """)

                        if error_id == field_id or error_id == field_name or error_id == 'related':
                            error_content = await error.text_content()
                            if error_content:
                                field_errors.append(error_content.strip())

                    if field_errors:
                        element["field_errors"] = field_errors
                        needs_review = True

                # Some fields ALWAYS need human review
                field_type = element.get("type")
                if field_type in ["file", "captcha"]:
                    needs_review = True

                # Complex multi-select or autocomplete fields often need review
                if "autocomplete" in (element.get("class") or ""):
                    needs_review = True

                # Fields with certain labels might need special attention
                label_lower = element.get("label", "").lower()
                review_keywords = ["agreement", "certify", "verify", "confirm", "signature", "attestation",
                                   "declare", "affirm", "acknowledge", "compliance"]

                if any(keyword in label_lower for keyword in review_keywords):
                    needs_review = True

                # Add fields requiring interaction
                if needs_review:
                    fields_requiring_interaction.append(element)

            # Only return interaction needed if we found fields requiring it
            if fields_requiring_interaction or has_errors:
                interaction_data = {
                    "section_name": section_data["section_name"],
                    "screenshot_path": section_data["screenshot_path"],
                    "fields": fields_requiring_interaction,
                    "error_messages": error_texts,
                    "has_errors": has_errors,
                    "guidance": "Please review and complete the following fields to continue processing."
                }

                logger.info(
                    f"Human interaction required in section '{section_data['section_name']}' for {len(fields_requiring_interaction)} fields")
                return interaction_data

            return None

        except Exception as e:
            logger.error(f"Error detecting if interaction required: {str(e)}")
            return None

    async def extract_form_state(self) -> Dict[str, Any]:
        """
        Extract the current state of the form.

        This captures all field values to help with decision-making
        and recovery from errors.

        Returns:
            Dictionary mapping field IDs/names to their current values
        """
        try:
            # Capture all form elements with their current values
            form_state = {}

            # Handle text inputs, selects, textareas
            elements = await self.page.query_selector_all(
                "input:not([type='file']):not([type='hidden']), select, textarea")

            for element in elements:
                element_id = await element.get_attribute("id") or ""
                element_name = await element.get_attribute("name") or ""

                if not element_id and not element_name:
                    continue

                field_key = element_id or element_name

                # Get element type
                tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
                element_type = await element.get_attribute("type") or tag_name

                # Get current value based on type
                if element_type == "checkbox" or element_type == "radio":
                    value = await element.evaluate("el => el.checked")

                    # For radio buttons, only include checked ones
                    if element_type == "radio" and not value:
                        continue
                else:
                    value = await element.evaluate("el => el.value")

                form_state[field_key] = value

            return form_state

        except Exception as e:
            logger.error(f"Error extracting form state: {str(e)}")
            return {}