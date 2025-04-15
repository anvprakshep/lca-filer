# core/form_filler.py
import asyncio
from typing import Dict, Any, List, Optional
from playwright.async_api import Page

from utils.logger import get_logger
from utils.screenshot_manager import ScreenshotManager
from core.browser_manager import BrowserManager, ElementNotFoundError
from ai.models import FieldDecision

logger = get_logger(__name__)


class FormFiller:
    """Handles form filling operations with improved error handling and logging."""

    def __init__(self, page: Page, browser_manager: BrowserManager, screenshot_manager: ScreenshotManager):
        """
        Initialize form filler.

        Args:
            page: Playwright page
            browser_manager: Browser manager for element handling
            screenshot_manager: Screenshot manager for capturing form state
        """
        self.page = page
        self.browser_manager = browser_manager
        self.screenshot_manager = screenshot_manager

        # XPath selectors for common field types
        self.field_type_selectors = {
            "text": ".//input[@type='text' or not(@type)]",
            "textarea": ".//textarea",
            "select": ".//select",
            "radio": ".//input[@type='radio']",
            "checkbox": ".//input[@type='checkbox']",
            "autocomplete": ".//input[contains(@class, 'autocomplete') or contains(@role, 'combobox')]"
        }

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
            logger.info(f"Filling field '{field_id}' with value: {value} (type: {field_type})")

            # Get XPath selector for the field
            if field_id.startswith('//'):
                # Already an XPath
                selector = field_id
            else:
                # Convert ID to XPath
                selector = f"//*[@id='{field_id}' or @name='{field_id}']"

            # Handle different field types
            if field_type == "text" or field_type == "textarea":
                await self.browser_manager.fill_element(self.page, selector, str(value))

            elif field_type == "dropdown" or field_type == "select":
                try:
                    # Get the select element
                    select_element = await self.browser_manager.find_element(self.page, selector)

                    # Select option by value
                    await self.page.select_option(selector, value)
                except ElementNotFoundError:
                    logger.warning(f"Select element not found with selector: {selector}")
                    return False

            elif field_type == "radio":
                radio_selector = f"{selector}[@value='{value}']"
                try:
                    await self.browser_manager.click_element(self.page, radio_selector)
                except ElementNotFoundError:
                    # Try to find any radio with the same name and matching value
                    group_selector = f"//input[@type='radio' and (@name='{field_id}' or @name='{field_id.replace('_', '-')}') and @value='{value}']"
                    await self.browser_manager.click_element(self.page, group_selector)

            elif field_type == "checkbox":
                try:
                    checkbox_element = await self.browser_manager.find_element(self.page, selector)

                    # Get current checked state
                    is_checked = await checkbox_element.is_checked()
                    should_check = value in [True, "true", "True", "yes", "Yes", "1"]

                    # Only click if we need to change the state
                    if is_checked != should_check:
                        await checkbox_element.click()
                except ElementNotFoundError:
                    logger.warning(f"Checkbox not found with selector: {selector}")
                    return False

            elif field_type == "autocomplete":
                # Fill the autocomplete field
                await self.browser_manager.fill_element(self.page, selector, str(value))

                # Wait for dropdown to appear
                await asyncio.sleep(0.5)

                # Press arrow down and enter to select the first option
                await self.page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.2)
                await self.page.keyboard.press("Enter")

            elif field_type == "date":
                # Format date as MM/DD/YYYY if it's not already
                from datetime import datetime
                if isinstance(value, datetime):
                    value = value.strftime("%m/%d/%Y")

                await self.browser_manager.fill_element(self.page, selector, str(value))

            elif field_type == "dynamic_table":
                # Handle dynamic tables (like additional worksites)
                return await self._fill_dynamic_table(field_id, value)

            else:
                logger.warning(f"Unsupported field type: {field_type} for {field_id}")
                return False

            # Take screenshot of filled field for verification
            await self.screenshot_manager.take_element_screenshot(
                self.page,
                selector,
                f"field_{field_id}_filled"
            )

            logger.info(f"Successfully filled {field_id} with value: {value}")
            return True

        except ElementNotFoundError as e:
            logger.error(f"Element not found when filling field {field_id}: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, f"field_{field_id}_not_found")
            return False

        except Exception as e:
            logger.error(f"Error filling field {field_id}: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, f"field_{field_id}_error")
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

            # Take screenshot before starting
            await self.screenshot_manager.take_screenshot(self.page, f"table_{table_id}_before")

            # Get the table selector
            table_selector = f"//*[@id='{table_id}' or @name='{table_id}' or contains(@class, '{table_id}')]"

            # For each row, click the add button and fill the fields
            for i, row_data in enumerate(rows_data):
                # Click add row button if not the first row (first row may already exist)
                if i > 0:
                    # Try different add button selectors
                    add_button_selectors = [
                        f"{table_selector}//button[contains(@aria-label, 'Add') or contains(text(), 'Add')]",
                        f"//button[contains(@aria-label, 'Add Row') or contains(text(), 'Add Worksite')]",
                        f"//button[contains(@class, 'add-row') or contains(@class, 'add-worksite')]"
                    ]

                    add_button_clicked = False
                    for selector in add_button_selectors:
                        try:
                            await self.browser_manager.click_element(self.page, selector)
                            add_button_clicked = True
                            break
                        except ElementNotFoundError:
                            continue

                    if not add_button_clicked:
                        logger.warning(f"Could not find add button for row {i + 1}")
                        return False

                    # Wait for row to be added
                    await asyncio.sleep(0.5)

                # Fill the fields for this row
                row_success = await self._fill_table_row(table_id, i, row_data)
                if not row_success:
                    logger.warning(f"Failed to fill row {i + 1} in table {table_id}")

            # Take screenshot after filling
            await self.screenshot_manager.take_screenshot(self.page, f"table_{table_id}_after")

            logger.info(f"Successfully filled dynamic table {table_id}")
            return True

        except Exception as e:
            logger.error(f"Error filling dynamic table {table_id}: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, f"table_{table_id}_error")
            return False

    async def _fill_table_row(self, table_id: str, row_index: int, row_data: Dict[str, Any]) -> bool:
        """
        Fill a single row in a dynamic table.

        Args:
            table_id: ID of the table
            row_index: Index of the row (0-based)
            row_data: Data for the row

        Returns:
            True if successful, False otherwise
        """
        success = True
        table_selector = f"//*[@id='{table_id}' or @name='{table_id}' or contains(@class, '{table_id}')]"

        # Try various patterns for row fields
        for field_name, field_value in row_data.items():
            # Try different selector patterns
            field_selector_patterns = [
                # Pattern 1: Field in specific row using ID
                f"{table_selector}//tr[{row_index + 1}]//*[@id='{table_id}_{row_index}_{field_name}' or @id='{field_name}_{row_index}']",
                # Pattern 2: Field in specific row by attribute containing field name
                f"{table_selector}//tr[{row_index + 1}]//*[contains(@name, '{field_name}') or contains(@id, '{field_name}')]",
                # Pattern 3: Generic row + column pattern
                f"{table_selector}//tr[{row_index + 1}]//td[*[contains(@placeholder, '{field_name}') or contains(@aria-label, '{field_name}')]]//input",
                # Pattern 4: Any input in the row where label contains field name
                f"{table_selector}//tr[{row_index + 1}]//label[contains(text(), '{field_name}')]//following::input[1]"
            ]

            field_found = False
            for selector in field_selector_patterns:
                try:
                    if await self.browser_manager.is_element_visible(self.page, selector, timeout=1000):
                        # Determine field type
                        element = await self.browser_manager.find_element(self.page, selector)
                        tag_name = await element.evaluate("el => el.tagName.toLowerCase()")

                        if tag_name == "select":
                            await self.page.select_option(selector, str(field_value))
                        else:
                            await self.browser_manager.fill_element(self.page, selector, str(field_value))

                        logger.info(f"Filled table {table_id} row {row_index + 1} field {field_name}")
                        field_found = True
                        break
                except Exception as e:
                    logger.debug(f"Error with selector {selector}: {str(e)}")
                    continue

            if not field_found:
                logger.warning(f"Could not find field {field_name} in row {row_index + 1}")
                success = False

        return success

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

        # Take screenshot before filling section
        await self.screenshot_manager.take_screenshot(self.page, f"section_{section['name']}_before")

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
                should_skip = await self._check_conditional_field(conditional)
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

        # Take screenshot after filling section
        await self.screenshot_manager.take_screenshot(self.page, f"section_{section['name']}_after")

        logger.info(f"Section {section['name']} filled: {results['fields_filled']}/{results['fields_total']} fields")
        return results

    async def _check_conditional_field(self, conditional: Dict[str, Any]) -> bool:
        """
        Check if a conditional field should be skipped.

        Args:
            conditional: Dictionary mapping parent fields to expected values

        Returns:
            True if field should be skipped, False otherwise
        """
        for parent_field, expected_value in conditional.items():
            try:
                parent_selector = f"//*[@id='{parent_field}' or @name='{parent_field}']"

                try:
                    # First check if the element exists
                    parent_element = await self.browser_manager.find_element(self.page, parent_selector)
                except ElementNotFoundError:
                    # Parent field not found, skip this conditional field
                    return True

                # Get element type
                tag_name = await parent_element.evaluate("el => el.tagName.toLowerCase()")
                input_type = await parent_element.evaluate("el => el.type || ''")

                if input_type == "radio" or input_type == "checkbox":
                    # For radio/checkbox, check specific option
                    option_selector = f"{parent_selector}[@value='{expected_value}']"
                    try:
                        option_element = await self.browser_manager.find_element(self.page, option_selector)
                        is_checked = await option_element.is_checked()
                        if not is_checked:
                            return True
                    except ElementNotFoundError:
                        # Option not found, skip
                        return True
                else:
                    # For other inputs, get value and compare
                    actual_value = await parent_element.input_value()
                    if actual_value != expected_value:
                        return True

            except Exception as e:
                logger.warning(f"Error checking conditional field with parent {parent_field}: {str(e)}")
                # If there's an error checking condition, skip the field to be safe
                return True

        # All conditions satisfied, don't skip
        return False

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

            # Take screenshot before handling
            await self.screenshot_manager.take_screenshot(self.page, "worksite_section_before")

            # Check if application has multiple worksites
            has_multiple_worksites = application_data.get("multiple_worksites", False)
            additional_worksites = application_data.get("additional_worksites", [])

            # Fill the "multiple worksites" radio button
            multiple_worksites_value = "Yes" if has_multiple_worksites else "No"
            radio_selector = f"//input[@type='radio' and (@id='multiple_worksites' or @name='multiple_worksites') and @value='{multiple_worksites_value}']"

            try:
                await self.browser_manager.click_element(self.page, radio_selector)
                logger.info(f"Selected 'multiple_worksites' option: {multiple_worksites_value}")
            except ElementNotFoundError:
                # Try alternate selectors
                alternate_selectors = [
                    f"//input[@type='radio' and contains(@id, 'multiple') and contains(@id, 'worksite') and @value='{multiple_worksites_value}']",
                    f"//input[@type='radio' and contains(@name, 'multiple') and contains(@name, 'worksite') and @value='{multiple_worksites_value}']",
                    f"//label[contains(text(), 'multiple worksite')]//*[@type='radio' and @value='{multiple_worksites_value}']"
                ]

                for selector in alternate_selectors:
                    try:
                        await self.browser_manager.click_element(self.page, selector)
                        logger.info(
                            f"Selected 'multiple_worksites' option using alternate selector: {multiple_worksites_value}")
                        break
                    except ElementNotFoundError:
                        continue
                else:
                    logger.error("Could not find multiple worksites radio button")
                    await self.screenshot_manager.take_screenshot(self.page, "multiple_worksites_not_found")
                    return False

            # Wait for UI to update after selection
            await asyncio.sleep(1)

            # Fill primary worksite fields
            worksite_data = application_data.get("worksite", {})
            for field_name, field_value in worksite_data.items():
                field_id = f"worksite_{field_name}"
                await self.fill_field(field_id, field_value)

            # If has multiple worksites, fill the additional worksites
            if has_multiple_worksites and additional_worksites:
                logger.info(f"Filling {len(additional_worksites)} additional worksites")
                await self._fill_dynamic_table("additional_worksites", additional_worksites)

            # Take screenshot after handling
            await self.screenshot_manager.take_screenshot(self.page, "worksite_section_after")

            logger.info("Worksite section handled successfully")
            return True

        except Exception as e:
            logger.error(f"Error handling worksite section: {str(e)}")
            await self.screenshot_manager.take_screenshot(self.page, "worksite_section_error")
            return False

    async def get_form_state(self) -> Dict[str, Any]:
        """
        Get the current state of the form.

        Returns:
            Dictionary mapping field IDs to their current values
        """
        form_state = {}

        try:
            logger.info("Getting current form state")

            # Get all input elements
            input_selectors = [
                "//input[not(@type='hidden')]",
                "//select",
                "//textarea"
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

            logger.info(f"Form state retrieved with {len(form_state)} fields")
            return form_state

        except Exception as e:
            logger.error(f"Error getting form state: {str(e)}")
            return {}