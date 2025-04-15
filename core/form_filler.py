# core/form_filler.py
import asyncio
from typing import Dict, Any, List, Optional
from playwright.async_api import Page

from config.selectors import Selectors
from utils.logger import get_logger
from ai.models import FieldDecision

logger = get_logger(__name__)


class FormFiller:
    """Handles form filling operations."""

    def __init__(self, page: Page):
        """
        Initialize form filler.

        Args:
            page: Playwright page
        """
        self.page = page

    async def fill_field(self, field_id: str, value: Any, field_type: str = "text") -> bool:
        """
        Fill a form field with the provided value.

        Args:
            field_id: Field ID or name
            value: Value to fill
            field_type: Type of field (text, dropdown, radio, checkbox, etc.)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get selector for the field
            selector = Selectors.get_field_selector(field_id)

            # Handle different field types
            if field_type == "text" or field_type == "textarea":
                await self.page.fill(selector, str(value))

            elif field_type == "dropdown" or field_type == "select":
                await self.page.select_option(selector, value)

            elif field_type == "radio":
                radio_selector = f"{selector}[value='{value}']"
                await self.page.click(radio_selector)

            elif field_type == "checkbox":
                if value in [True, "true", "True", "yes", "Yes", "1"]:
                    await self.page.check(selector)
                else:
                    await self.page.uncheck(selector)

            elif field_type == "autocomplete":
                await self.page.fill(selector, str(value))
                await self.page.keyboard.press("ArrowDown")
                await self.page.keyboard.press("Enter")

            elif field_type == "date":
                # Format date as MM/DD/YYYY if it's not already
                from datetime import datetime
                if isinstance(value, datetime):
                    value = value.strftime("%m/%d/%Y")
                await self.page.fill(selector, str(value))

            elif field_type == "dynamic_table":
                # Handle dynamic tables (like additional worksites)
                await self._fill_dynamic_table(field_id, value)

            else:
                logger.warning(f"Unsupported field type: {field_type} for {field_id}")
                return False

            logger.info(f"Filled {field_id} with value: {value}")
            return True

        except Exception as e:
            logger.error(f"Error filling field {field_id}: {str(e)}")
            return False

    async def _fill_dynamic_table(self, table_id: str, rows_data: List[Dict[str, Any]]) -> bool:
        """
        Fill a dynamic table with multiple rows.

        Args:
            table_id: ID of the table
            rows_data: List of row data dictionaries

        Returns:
            True if successful, False otherwise
        """
        try:
            if not rows_data:
                logger.info(f"No data to fill for dynamic table {table_id}")
                return True

            logger.info(f"Filling dynamic table {table_id} with {len(rows_data)} rows")

            # Get table container
            table_selector = Selectors.get_field_selector(table_id)

            # For each row, click the add button and fill the fields
            for i, row_data in enumerate(rows_data):
                # Click add row button if not the first row (first row may already exist)
                if i > 0:
                    add_button_selector = f"{table_selector} button[aria-label='Add Row'], {table_selector} button:has-text('Add Worksite')"
                    await self.page.click(add_button_selector)
                    await self.page.wait_for_timeout(500)  # Short wait for row to be added

                # Fill the fields for this row
                for field_name, field_value in row_data.items():
                    # Field ID for this row might follow a pattern like "additional_worksite_{i}_{field_name}"
                    row_field_id = f"{table_id}_{i}_{field_name}"
                    alt_field_id = f"{field_name}_{i}"  # Alternative format that might be used

                    # Try different selector patterns until one works
                    field_selector = None
                    for selector_pattern in [
                        f"#{row_field_id}",
                        f"#{alt_field_id}",
                        f"{table_selector} tr:nth-child({i + 1}) [name*='{field_name}']",
                        f"{table_selector} tr:nth-child({i + 1}) [id*='{field_name}']",
                        f"{table_selector} tr:nth-child({i + 1}) input[placeholder*='{field_name}']",
                    ]:
                        if await self._is_element_visible(selector_pattern, timeout=1000):
                            field_selector = selector_pattern
                            break

                    if field_selector:
                        try:
                            # Determine field type
                            element_type = await self._get_element_type(field_selector)

                            # Fill the field based on its type
                            if element_type == "select":
                                await self.page.select_option(field_selector, str(field_value))
                            else:  # Default to text input
                                await self.page.fill(field_selector, str(field_value))

                            logger.info(f"Filled dynamic table field {field_name} in row {i + 1}")
                        except Exception as e:
                            logger.error(f"Error filling field {field_name} in row {i + 1}: {str(e)}")
                    else:
                        logger.warning(f"Could not find field {field_name} in row {i + 1}")

            return True

        except Exception as e:
            logger.error(f"Error filling dynamic table {table_id}: {str(e)}")
            return False

    async def _get_element_type(self, selector: str) -> str:
        """
        Get the type of an element.

        Args:
            selector: CSS selector

        Returns:
            Element type ("select", "checkbox", "text", etc.)
        """
        try:
            return await self.page.evaluate(f"""() => {{
                const element = document.querySelector("{selector}");
                if (!element) return "unknown";

                if (element.tagName.toLowerCase() === "select") return "select";
                if (element.tagName.toLowerCase() === "textarea") return "textarea";
                if (element.tagName.toLowerCase() === "input") return element.type || "text";

                return element.tagName.toLowerCase();
            }}""")
        except Exception as e:
            logger.debug(f"Error getting element type: {str(e)}")
            return "text"  # Default to text if can't determine type

    async def fill_section(self, section: Dict[str, Any], decisions: List[FieldDecision]) -> Dict[str, Any]:
        """
        Fill out a section of the form using AI decisions.

        Args:
            section: Form section definition
            decisions: AI-generated field decisions

        Returns:
            Dictionary with results (success, errors)
        """
        logger.info(f"Filling section: {section['name']}")

        results = {
            "section": section["name"],
            "fields_total": len(decisions),
            "fields_filled": 0,
            "fields_failed": 0,
            "errors": []
        }

        # Check if this is the worksite section (special handling for multiple worksites)
        is_worksite_section = "worksite" in section["name"].lower()
        additional_worksites_data = None

        # First pass to collect data for special fields like dynamic tables
        if is_worksite_section:
            for decision in decisions:
                if decision.field_id == "additional_worksites" and isinstance(decision.value, list):
                    additional_worksites_data = decision.value
                    break

        # Process each field
        for decision in decisions:
            field_id = decision.field_id
            value = decision.value

            # Skip special fields that will be handled separately
            if field_id == "additional_worksites":
                continue

            # Skip low-confidence decisions (might want human review)
            if decision.confidence < 0.7:
                logger.warning(f"Low confidence for field {field_id} ({decision.confidence}): {decision.reasoning}")
                continue

            # Find field type from section definition
            field_def = next((f for f in section["fields"] if f["id"] == field_id), None)

            if not field_def:
                logger.warning(f"Field definition not found for {field_id}")
                results["errors"].append(f"Field definition not found for {field_id}")
                continue

            field_type = field_def.get("type", "text")

            # Check conditional fields
            conditional = field_def.get("conditional")
            if conditional:
                # Skip this field if its conditional parent doesn't have the expected value
                should_skip = False
                for parent_field, expected_value in conditional.items():
                    parent_selector = Selectors.get_field_selector(parent_field)
                    parent_field_def = next((f for f in section["fields"] if f["id"] == parent_field), None)

                    if not parent_field_def:
                        continue

                    parent_type = parent_field_def.get("type", "text")

                    if parent_type == "radio" or parent_type == "checkbox":
                        try:
                            # For radio buttons, check if the expected value is selected
                            radio_selector = f"{parent_selector}[value='{expected_value}']"
                            is_checked = await self.page.is_checked(radio_selector)
                            if not is_checked:
                                should_skip = True
                                break
                        except:
                            should_skip = True
                            break
                    else:
                        try:
                            # For other inputs, check if the value matches
                            actual_value = await self.page.input_value(parent_selector)
                            if actual_value != expected_value:
                                should_skip = True
                                break
                        except:
                            should_skip = True
                            break

                if should_skip:
                    logger.info(f"Skipping conditional field {field_id}")
                    continue

            # Fill the field
            success = await self.fill_field(field_id, value, field_type)

            if success:
                results["fields_filled"] += 1
            else:
                results["fields_failed"] += 1
                results["errors"].append(f"Failed to fill field {field_id}")

        # Handle additional worksites if available
        if is_worksite_section and additional_worksites_data:
            # Find the additional worksites field definition
            additional_worksites_field = next((f for f in section["fields"] if f["id"] == "additional_worksites"), None)

            if additional_worksites_field:
                success = await self._fill_dynamic_table("additional_worksites", additional_worksites_data)

                if success:
                    results["fields_filled"] += 1
                    logger.info(f"Successfully filled {len(additional_worksites_data)} additional worksites")
                else:
                    results["fields_failed"] += 1
                    results["errors"].append("Failed to fill additional worksites")

        logger.info(f"Section {section['name']} filled: {results['fields_filled']}/{results['fields_total']} fields")
        return results

    async def handle_worksite_section(self, application_data: Dict[str, Any]) -> bool:
        """
        Special handler for the worksite section with multiple worksites.

        Args:
            application_data: Validated application data

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Handling worksite section with special logic for multiple worksites")

            # Check if application has multiple worksites
            has_multiple_worksites = application_data.get("multiple_worksites", False)
            additional_worksites = application_data.get("additional_worksites", [])

            # Fill the "multiple worksites" radio button
            multiple_worksites_value = "Yes" if has_multiple_worksites else "No"
            multiple_worksites_selector = Selectors.get_field_selector("multiple_worksites")
            radio_selector = f"{multiple_worksites_selector}[value='{multiple_worksites_value}']"
            await self.page.click(radio_selector)

            # Fill primary worksite fields
            worksite_data = application_data.get("worksite", {})
            for field_name, field_value in worksite_data.items():
                field_id = f"worksite_{field_name}"
                await self.fill_field(field_id, field_value)

            # If has multiple worksites, fill the additional worksites
            if has_multiple_worksites and additional_worksites:
                await self._fill_dynamic_table("additional_worksites", additional_worksites)

            return True

        except Exception as e:
            logger.error(f"Error handling worksite section: {str(e)}")
            return False

    async def get_form_state(self) -> Dict[str, Any]:
        """
        Get the current state of the form.

        Returns:
            Dictionary mapping field IDs to their current values
        """
        form_state = {}

        try:
            # Get all input elements
            input_selectors = [
                "input:not([type='hidden'])",
                "select",
                "textarea"
            ]

            for selector in input_selectors:
                elements = await self.page.query_selector_all(selector)

                for element in elements:
                    try:
                        field_id = await element.get_attribute("id")
                        if not field_id:
                            field_name = await element.get_attribute("name")
                            if not field_name:
                                continue
                            field_id = field_name

                        tag_name = await element.evaluate("el => el.tagName.toLowerCase()")

                        if tag_name == "input":
                            input_type = await element.get_attribute("type")

                            if input_type in ["checkbox", "radio"]:
                                is_checked = await element.is_checked()
                                if is_checked:
                                    value = await element.get_attribute("value") or True
                                else:
                                    # Skip unchecked radio buttons
                                    if input_type == "radio":
                                        continue
                                    value = False
                            else:
                                value = await element.input_value()

                        elif tag_name == "select":
                            value = await element.input_value()

                        elif tag_name == "textarea":
                            value = await element.input_value()

                        else:
                            continue

                        form_state[field_id] = value

                    except Exception as e:
                        logger.debug(f"Error getting value for element: {str(e)}")
                        continue

            # Also try to get the state of dynamic tables
            try:
                tables = await self.page.query_selector_all("table, div[role='table']")

                for i, table in enumerate(tables):
                    table_id = await table.get_attribute("id") or f"table_{i}"
                    rows = await table.query_selector_all("tr, div[role='row']")

                    if len(rows) > 1:  # Has at least a header and one data row
                        table_data = []

                        # Skip header row
                        for j, row in enumerate(rows[1:], 1):
                            row_data = {}
                            cells = await row.query_selector_all("td, div[role='cell']")

                            for k, cell in enumerate(cells):
                                # Try to find inputs in the cell
                                inputs = await cell.query_selector_all("input, select, textarea")

                                for input_el in inputs:
                                    input_id = await input_el.get_attribute("id") or ""
                                    input_name = await input_el.get_attribute("name") or ""
                                    field_name = input_id or input_name

                                    if field_name:
                                        # Extract base field name without row/column indices
                                        base_field_name = field_name.split('_')[-1]
                                        value = await input_el.input_value()
                                        row_data[base_field_name] = value

                            if row_data:
                                table_data.append(row_data)

                        if table_data:
                            form_state[table_id] = table_data
            except Exception as e:
                logger.debug(f"Error getting dynamic table state: {str(e)}")

            return form_state

        except Exception as e:
            logger.error(f"Error getting form state: {str(e)}")
            return {}

    async def submit_form(self, button_selector: str) -> bool:
        """
        Submit a form by clicking a button.

        Args:
            button_selector: CSS selector for the submit button

        Returns:
            True if submission was successful, False otherwise
        """
        try:
            # Check if button exists
            if not await self._is_element_visible(button_selector):
                logger.error(f"Submit button not found: {button_selector}")
                return False

            # Click the button
            await self.page.click(button_selector)

            # Wait for navigation to complete
            await self.page.wait_for_load_state("networkidle")

            # Check for error messages
            error_selector = Selectors.get("error_message")
            if await self._is_element_visible(error_selector, timeout=2000):
                error_text = await self.page.text_content(error_selector)
                logger.warning(f"Form submission error: {error_text}")
                return False

            return True

        except Exception as e:
            logger.error(f"Error submitting form: {str(e)}")
            return False

    async def _is_element_visible(self, selector: str, timeout: int = 5000) -> bool:
        """Check if an element is visible on the page."""
        try:
            await self.page.wait_for_selector(selector, state="visible", timeout=timeout)
            return True
        except:
            return False