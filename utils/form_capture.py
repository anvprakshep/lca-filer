import asyncio
from datetime import datetime
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

    # Enhancing the FormCapture class in utils/form_capture.py

    async def detect_interaction_required(self, expected_selectors=None) -> Optional[Dict[str, Any]]:
        """
        Enhanced version to detect when interaction is required, including when elements are not found.
        Adds special handling for NAICS code fields without removing original functionality.

        Args:
            expected_selectors: Optional list of selectors that should be present

        Returns:
            Dictionary with interaction data if needed, None otherwise
        """
        try:
            # Capture the current form section
            section_data = await self.capture_current_section()

            # Check if we're missing expected elements
            missing_elements = []
            if expected_selectors:
                for selector_info in expected_selectors:
                    selector = selector_info.get("selector")
                    description = selector_info.get("description", selector)

                    try:
                        element = await self.page.wait_for_selector(selector, timeout=3000)
                        if not element:
                            missing_elements.append({
                                "selector": selector,
                                "description": description,
                                "required": True
                            })
                    except Exception:
                        # Element not found
                        missing_elements.append({
                            "selector": selector,
                            "description": description,
                            "required": True
                        })

            # Normal error detection logic (existing code)
            error_messages = await self.page.query_selector_all(
                ".error-message, .validation-error, .field-error, .alert-danger, [role='alert'], " +
                ".error, .invalid-feedback, .text-danger, .error-text, div[class*='error']")
            has_errors = len(error_messages) > 0

            error_texts = []
            for error in error_messages:
                error_text = await error.text_content()
                if error_text and error_text.strip():
                    if error_text.strip() not in error_texts:
                        error_texts.append(error_text.strip())

            # Enhance fields requiring interaction - check specifically for NAICS code field
            fields_requiring_interaction = []

            # First, check if there's a NAICS code field
            naics_field = None
            naics_selectors = [
                "#naics_code",
                "[name='naics_code']",
                "input[id*='naics'][id*='code']",
                "input[name*='naics'][name*='code']"
            ]

            for selector in naics_selectors:
                try:
                    naics_field = await self.page.query_selector(selector)
                    if naics_field:
                        break
                except:
                    continue

            # If we found a NAICS field, add it to fields requiring interaction
            if naics_field:
                # Get field properties
                field_id = await naics_field.get_attribute("id") or "naics_code"
                field_name = await naics_field.get_attribute("name") or "naics_code"
                placeholder = await naics_field.get_attribute("placeholder") or "Enter NAICS Code"

                fields_requiring_interaction.append({
                    "id": field_id,
                    "name": field_name,
                    "type": "autocomplete",
                    "label": "NAICS Code",
                    "placeholder": placeholder,
                    "default_value": await naics_field.input_value() or "",
                    "required": True,
                    "is_autocomplete": True,
                    "description": "Enter a NAICS code or keywords to search. The system will show matching options as you type.",
                    "example_searches": ["541511", "Software", "Engineering", "Computer"],
                    "sample_values": [
                        {"code": "541511", "description": "Custom Computer Programming Services"},
                        {"code": "541512", "description": "Computer Systems Design Services"},
                        {"code": "541330", "description": "Engineering Services"},
                        {"code": "541712", "description": "Research and Development in Physical Sciences"}
                    ],
                    "min_search_chars": 2,
                    "field_errors": []
                })

            # Add missing element fields
            for missing in missing_elements:
                fields_requiring_interaction.append({
                    "id": missing["selector"].replace(".", "_").replace("#", "_").replace("[", "_").replace("]", "_"),
                    "label": f"Select {missing['description']}",
                    "type": "text",  # Default type
                    "required": missing["required"],
                    "field_errors": [],
                    "description": f"The system couldn't automatically find {missing['description']}. Please enter it manually."
                })

            # Process all elements from section data
            for element in section_data["elements"]:
                # Check if this is a field we want to make interactive
                make_interactive = False

                # Always include fields with errors
                if has_errors and element.get("aria_invalid") == True:
                    make_interactive = True

                # Include NAICS fields (already handled above, so skip)
                if 'naics' in element.get("id", "").lower() or 'naics' in element.get("name", "").lower():
                    continue

                # Include any field that's a complex type
                if element.get("type") in ["autocomplete", "combobox"]:
                    make_interactive = True

                # Add the field if needed
                if make_interactive:
                    field_copy = element.copy()
                    if "field_errors" not in field_copy:
                        field_copy["field_errors"] = []
                    fields_requiring_interaction.append(field_copy)

            # Only request interaction if we have fields requiring it or errors
            if fields_requiring_interaction or has_errors or missing_elements:
                # Take screenshot of current state
                screenshot_path = await self.screenshot_manager.take_screenshot(
                    self.page,
                    f"section_{self.current_section.replace(' ', '_').lower()}"
                )

                # Create guidance message
                guidance_message = "Please review and complete the following fields to continue processing."
                if has_errors:
                    guidance_message = "Please correct the following errors to continue processing."
                elif missing_elements:
                    guidance_message = "The automation couldn't find or select some elements. Please make selections to continue."

                interaction_data = {
                    "section_name": section_data["section_name"],
                    "screenshot_path": screenshot_path,
                    "fields": fields_requiring_interaction,
                    "error_messages": error_texts,
                    "has_errors": has_errors,
                    "has_missing_elements": len(missing_elements) > 0,
                    "guidance": guidance_message,
                    "timestamp": datetime.now().isoformat()
                }

                logger.info(f"Human interaction required in section '{section_data['section_name']}'")
                return interaction_data

            return None

        except Exception as e:
            logger.error(f"Error detecting if interaction required: {str(e)}")
            return None

    async def _generate_options_for_selector(self, selector):
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
            if selector.startswith("input[type='radio']"):
                # Try to extract the name attribute from the selector
                name_match = re.search(r"name=['\"]([^'\"]+)['\"]", selector)
                name = name_match.group(1) if name_match else None

                if name:
                    # Find all radio buttons with the same name
                    radio_selector = f"input[type='radio'][name='{name}']"
                else:
                    # Use a more general selector to find all radio buttons
                    radio_selector = "input[type='radio']"

                # Find all radio buttons
                radio_elements = await self.page.query_selector_all(radio_selector)

                # Extract value and label for each radio button
                for radio in radio_elements:
                    value = await radio.get_attribute("value") or ""

                    # Try to find label associated with this radio button
                    radio_id = await radio.get_attribute("id")
                    label_text = ""

                    if radio_id:
                        # Try to find label by for attribute
                        label_element = await self.page.query_selector(f"label[for='{radio_id}']")
                        if label_element:
                            label_text = await label_element.text_content() or ""

                    # If no label found, try to find parent label
                    if not label_text:
                        label_text = await radio.evaluate("""
                            el => {
                                // Check if inside a label
                                let parent = el.parentElement;
                                while (parent && parent.tagName !== 'LABEL' && parent.tagName !== 'BODY') {
                                    parent = parent.parentElement;
                                }
                                return parent && parent.tagName === 'LABEL' ? parent.textContent.trim() : null;
                            }
                        """)

                    # If still no label, use value as label
                    if not label_text:
                        label_text = value

                    # Add to options if not already present
                    if value and not any(opt["value"] == value for opt in options):
                        options.append({
                            "value": value,
                            "label": label_text.strip() or value
                        })

            # For select elements
            elif selector.startswith("select") or (
                    selector.startswith("#") and await self.page.query_selector(f"{selector}[nodeName='SELECT']")):
                select_element = await self.page.query_selector(selector)
                if select_element:
                    # Get options from the select element
                    options_data = await select_element.evaluate("""
                        select => Array.from(select.options).map(option => ({
                            value: option.value,
                            label: option.textContent,
                            selected: option.selected
                        }))
                    """)
                    options = options_data

            # If we couldn't find any options but we have an XPath or complex selector
            # Let's try to extract all possible values from the page context
            if not options and (selector.startswith("//") or selector.startswith("xpath=") or selector.contains("=")):
                # Look for anything that might be a selectable option
                possible_options = await self.page.evaluate("""
                    () => {
                        // Find all elements that look like options
                        const allOptions = Array.from(document.querySelectorAll('input[type="radio"], input[type="checkbox"], option, button, .selectable-item, [role="option"]'));

                        // Extract their values and labels
                        return allOptions.map(el => {
                            let value = el.value || el.getAttribute('data-value') || el.id || el.textContent.trim();
                            let label = el.textContent.trim() || el.getAttribute('aria-label') || el.title || value;

                            // For radio/checkbox, try to find label if not already found
                            if ((el.type === 'radio' || el.type === 'checkbox') && el.id) {
                                const labelEl = document.querySelector(`label[for="${el.id}"]`);
                                if (labelEl) {
                                    label = labelEl.textContent.trim();
                                }
                            }

                            return { value, label };
                        }).filter(opt => opt.value); // Filter out empty values
                    }
                """)

                # Add any options we found
                for opt in possible_options:
                    if not any(existing["value"] == opt["value"] for existing in options):
                        options.append(opt)

            # Still no options? Try to find all visible text that might be options
            if not options:
                # Just grab all text elements that might be options
                text_elements = await self.page.evaluate("""
                    () => {
                        // Find all elements with text that might be options
                        const textElements = Array.from(document.querySelectorAll('p, span, div, label, a, button'))
                            .filter(el => {
                                // Filter to visible elements with text
                                const style = window.getComputedStyle(el);
                                const text = el.textContent.trim();
                                return text && 
                                       style.display !== 'none' && 
                                       style.visibility !== 'hidden' &&
                                       text.length < 50; // Not too long
                            });

                        return textElements.map(el => ({
                            value: el.textContent.trim(),
                            label: el.textContent.trim()
                        }));
                    }
                """)

                # Add text elements as options
                for opt in text_elements:
                    if not any(existing["value"] == opt["value"] for existing in options):
                        options.append(opt)

        except Exception as e:
            logger.warning(f"Error generating options for selector {selector}: {str(e)}")

            # As a fallback if we couldn't extract options, check for common form patterns
            if "H-1B" in selector or "visa" in selector.lower() or "classification" in selector.lower():
                # Fallback for visa classification radio buttons
                options = [
                    {"value": "H-1B", "label": "H-1B"},
                    {"value": "H-1B1 Chile", "label": "H-1B1 Chile"},
                    {"value": "H-1B1 Singapore", "label": "H-1B1 Singapore"},
                    {"value": "E-3 Australian", "label": "E-3 Australian"}
                ]

        # If still no options found, provide generic ones as a last resort
        if not options:
            options = [
                {"value": "option1", "label": "Option 1"},
                {"value": "option2", "label": "Option 2"},
                {"value": "custom", "label": "Custom (specify below)"}
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
                                        label: option.textContent,
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
                                label: element.textContent,
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
                        label: option.textContent,
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

    async def capture_element(self, element: ElementHandle) -> Optional[Dict[str, Any]]:
        """
        Enhanced version of capture_element with support for autocomplete fields.
        Preserves all existing functionality while adding detection for NAICS fields.

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

            # NEW: Enhanced detection for NAICS code fields
            is_naics_field = False
            if (element_id and 'naics' in element_id.lower()) or (element_name and 'naics' in element_name.lower()):
                is_naics_field = True
                element_type = "autocomplete"  # Override type for NAICS fields

            # Find the label with improved methods
            label_text = await self._find_label_for_element(element, element_id, element_name)

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

            # Build the element data with enhanced properties
            element_data = {
                "id": element_id or element_name or f"element_{tag_name}_{await element.evaluate('el => el.textContent')}",
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

            # NEW: Add special properties for NAICS code fields
            if is_naics_field:
                element_data["is_autocomplete"] = True
                element_data[
                    "description"] = "Enter a NAICS code or keywords to search. The system will show matching options as you type."
                element_data["example_searches"] = ["541511", "Software", "Engineering", "Computer"]
                element_data["sample_values"] = [
                    {"code": "541511", "description": "Custom Computer Programming Services"},
                    {"code": "541512", "description": "Computer Systems Design Services"},
                    {"code": "541330", "description": "Engineering Services"},
                    {"code": "541712", "description": "Research and Development in Physical Sciences"}
                ]
                element_data["min_search_chars"] = 2

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

            # Capture validation message if available
            try:
                validation_message = await element.evaluate("el => el.validationMessage || ''")
                if validation_message:
                    element_data["validation_message"] = validation_message
            except Exception as e:
                logger.debug(f"Could not get validation message: {str(e)}")

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