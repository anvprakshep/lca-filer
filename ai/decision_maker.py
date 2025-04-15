# ai/decision_maker.py
import asyncio
from typing import Dict, Any, List, Optional
import json
import re

from utils.logger import get_logger
from ai.llm_client import LLMClient
from ai.models import FieldDecision, FormSection, LCADecision
from config.form_structure import FormStructure

logger = get_logger(__name__)


class DecisionMaker:
    """Makes AI-driven decisions for form filling."""

    def __init__(self, llm_client: LLMClient):
        """
        Initialize decision maker.

        Args:
            llm_client: LLM client for AI decisions
        """
        self.llm_client = llm_client
        self.form_structure = FormStructure.get_h1b_structure()

    async def make_decisions(self, application_data: Dict[str, Any]) -> LCADecision:
        """
        Make decisions for the entire LCA form.

        Args:
            application_data: Validated application data

        Returns:
            LCADecision object with all form decisions
        """
        logger.info("Making AI decisions for LCA form")

        form_sections = []
        review_reasons = []

        # Process each section
        for section in self.form_structure["sections"]:
            section_name = section["name"]
            logger.info(f"Processing decisions for section: {section_name}")

            # Special handling for worksite section if multiple worksites
            if "worksite" in section_name.lower() and application_data.get("multiple_worksites", False):
                decisions = await self._handle_multiple_worksites_decisions(section, application_data)
            else:
                # For other sections, first try to map application data directly
                mapped_values = self.map_application_to_form_fields(section, application_data)

                # For any fields that couldn't be directly mapped, use AI to make decisions
                decisions = await self._get_remaining_field_decisions(section, mapped_values, application_data)

            # Check for low confidence decisions
            low_confidence_decisions = [d for d in decisions if d.confidence < 0.7]
            if low_confidence_decisions:
                for decision in low_confidence_decisions:
                    reason = f"Low confidence ({decision.confidence:.2f}) for field {decision.field_id} in section {section_name}"
                    review_reasons.append(reason)
                    logger.warning(reason)

            # Add section to form sections
            form_sections.append(FormSection(
                section_name=section_name,
                decisions=decisions
            ))

        # Determine if human review is required
        requires_human_review = len(review_reasons) > 0

        # Create LCA decision
        lca_decision = LCADecision(
            form_sections=form_sections,
            requires_human_review=requires_human_review,
            review_reasons=review_reasons
        )

        if requires_human_review:
            logger.warning(f"LCA requires human review for {len(review_reasons)} reasons")
        else:
            logger.info("LCA decisions complete, no human review required")

        return lca_decision

    async def _get_remaining_field_decisions(self,
                                             section: Dict[str, Any],
                                             mapped_values: Dict[str, Any],
                                             application_data: Dict[str, Any]) -> List[FieldDecision]:
        """
        Get AI decisions for fields that couldn't be directly mapped.

        Args:
            section: Form section definition
            mapped_values: Values already mapped from application data
            application_data: Complete application data

        Returns:
            List of FieldDecision objects for all fields
        """
        # Get all field IDs in this section
        section_field_ids = [field["id"] for field in section["fields"]]

        # Determine which fields need AI decisions
        fields_needing_decisions = [field_id for field_id in section_field_ids
                                    if field_id not in mapped_values]

        # If all fields have been mapped, no need for AI
        if not fields_needing_decisions:
            # Convert mapped values to FieldDecision objects
            decisions = []
            for field_id, value in mapped_values.items():
                decisions.append(FieldDecision(
                    field_id=field_id,
                    value=value,
                    reasoning="Directly mapped from application data",
                    confidence=1.0
                ))
            return decisions

        # Otherwise, get AI decisions for all fields
        # (We ask for all to ensure consistency, but will override with mapped values after)
        ai_decisions = await self.llm_client.get_section_decisions(section, application_data)

        # Replace AI decisions with our direct mappings where available
        final_decisions = []
        for decision in ai_decisions:
            field_id = decision.field_id
            if field_id in mapped_values:
                # Use our mapped value instead of AI decision
                final_decisions.append(FieldDecision(
                    field_id=field_id,
                    value=mapped_values[field_id],
                    reasoning="Directly mapped from application data",
                    confidence=1.0
                ))
            else:
                # Keep the AI decision
                final_decisions.append(decision)

        # Check if we're missing any fields that should have decisions
        covered_field_ids = {d.field_id for d in final_decisions}
        for field_id in section_field_ids:
            if field_id not in covered_field_ids:
                # This could happen if the AI didn't provide a decision for this field
                # and it wasn't in our mapped values

                # Find the field definition
                field_def = next((f for f in section["fields"] if f["id"] == field_id), None)
                if field_def:
                    # Check if it's a conditional field
                    if field_def.get("conditional"):
                        # Skip conditional fields - they may not need decisions yet
                        continue

                    # Otherwise, add a placeholder decision
                    default_value = ""
                    if field_def.get("type") == "checkbox":
                        default_value = False
                    elif field_def.get("type") == "radio":
                        options = field_def.get("options", [])
                        default_value = options[0] if options else ""

                    final_decisions.append(FieldDecision(
                        field_id=field_id,
                        value=default_value,
                        reasoning="Default value assigned (field not mapped or decided by AI)",
                        confidence=0.5  # Low confidence to flag for review
                    ))

        return final_decisions

    async def _handle_multiple_worksites_decisions(self, section: Dict[str, Any], application_data: Dict[str, Any]) -> \
    List[FieldDecision]:
        """
        Handle decision making for a section with multiple worksites.

        Args:
            section: Form section definition
            application_data: Validated application data

        Returns:
            List of FieldDecision objects
        """
        logger.info("Making decisions for multiple worksites section")

        # First map what we can directly
        mapped_values = self.map_application_to_form_fields(section, application_data)

        # Get standard decisions for the section
        decisions = await self._get_remaining_field_decisions(section, mapped_values, application_data)

        # Find or create the multiple_worksites decision
        multiple_worksites_decision = next(
            (d for d in decisions if d.field_id == "multiple_worksites"),
            None
        )

        if not multiple_worksites_decision:
            # Add a decision for the multiple_worksites radio button
            decisions.append(FieldDecision(
                field_id="multiple_worksites",
                value="Yes",
                reasoning="Application data indicates multiple worksites",
                confidence=1.0
            ))
        elif multiple_worksites_decision.value != "Yes":
            # Update the decision to "Yes"
            multiple_worksites_decision.value = "Yes"
            multiple_worksites_decision.reasoning = "Updated based on application data with multiple worksites"
            multiple_worksites_decision.confidence = 1.0

        # Check if additional_worksites decision exists
        additional_worksites_decision = next(
            (d for d in decisions if d.field_id == "additional_worksites"),
            None
        )

        if not additional_worksites_decision:
            # Create a decision for the additional_worksites field
            additional_worksites = application_data.get("additional_worksites", [])

            # Format the additional worksites for the form
            formatted_worksites = await self.get_additional_worksite_decisions(application_data)

            decisions.append(FieldDecision(
                field_id="additional_worksites",
                value=formatted_worksites,
                reasoning="Using additional worksites from application data",
                confidence=1.0
            ))

        return decisions

    async def get_decisions_for_section(self, section_name: str, application_data: Dict[str, Any]) -> List[
        FieldDecision]:
        """
        Get decisions for a specific form section.

        Args:
            section_name: Name of the section
            application_data: Validated application data

        Returns:
            List of FieldDecision objects
        """
        # Find the section definition
        section = next((s for s in self.form_structure["sections"] if s["name"] == section_name), None)

        if not section:
            logger.error(f"Section not found: {section_name}")
            return []

        # Special handling for worksite section if multiple worksites
        if "worksite" in section_name.lower() and application_data.get("multiple_worksites", False):
            return await self._handle_multiple_worksites_decisions(section, application_data)
        else:
            # First map what we can directly
            mapped_values = self.map_application_to_form_fields(section, application_data)

            # Then get AI decisions for the rest
            return await self._get_remaining_field_decisions(section, mapped_values, application_data)

    async def get_additional_worksite_decisions(self, application_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Format additional worksite data for form filling.

        Args:
            application_data: Validated application data

        Returns:
            List of formatted worksite data for dynamic table
        """
        additional_worksites = application_data.get("additional_worksites", [])

        if not additional_worksites:
            return []

        formatted_worksites = []

        for worksite in additional_worksites:
            formatted_worksite = {
                "address": worksite.get("address", ""),
                "address2": worksite.get("address2", ""),
                "city": worksite.get("city", ""),
                "county": worksite.get("county", ""),
                "state": worksite.get("state", ""),
                "postal_code": worksite.get("zip", "")
            }

            formatted_worksites.append(formatted_worksite)

        return formatted_worksites

    def map_application_to_form_fields(self, section: Dict[str, Any], application_data: Dict[str, Any]) -> Dict[
        str, Any]:
        """
        Map application data to form fields for a section.

        Args:
            section: Form section definition
            application_data: Validated application data

        Returns:
            Dictionary mapping field IDs to values
        """
        field_values = {}
        section_name = section["name"].lower()

        # Map fields based on section type
        if "employer" in section_name:
            # Employer section
            employer_data = application_data.get("employer", {})
            field_mapping = {
                "employer_name": "name",
                "employer_id": "fein",
                "employer_address": "address",
                "employer_city": "city",
                "employer_state": "state",
                "employer_zip": "zip",
                "employer_phone": "phone",
                "employer_email": "email"
            }

            for form_field, app_field in field_mapping.items():
                if app_field in employer_data:
                    field_values[form_field] = employer_data[app_field]

        elif "job" in section_name:
            # Job information section
            job_data = application_data.get("job", {})
            field_mapping = {
                "job_title": "title",
                "soc_code": "soc_code",
                "job_duties": "duties"
            }

            for form_field, app_field in field_mapping.items():
                if app_field in job_data:
                    field_values[form_field] = job_data[app_field]

        elif "wage" in section_name:
            # Wage information section
            wage_data = application_data.get("wages", {})
            field_mapping = {
                "wage_rate": "rate",
                "wage_rate_unit": "rate_type",
                "prevailing_wage": "prevailing_wage",
                "pw_source": "pw_source",
                "pw_source_year": "pw_year"
            }

            for form_field, app_field in field_mapping.items():
                if app_field in wage_data:
                    field_values[form_field] = wage_data[app_field]

            # Map wage type from text to form value
            if "rate_type" in wage_data:
                rate_type = wage_data["rate_type"].lower()
                if rate_type == "year" or rate_type == "yearly" or rate_type == "annual":
                    field_values["wage_rate_unit"] = "Year"
                elif rate_type == "month" or rate_type == "monthly":
                    field_values["wage_rate_unit"] = "Month"
                elif rate_type == "biweekly" or rate_type == "bi-weekly":
                    field_values["wage_rate_unit"] = "Bi-Weekly"
                elif rate_type == "week" or rate_type == "weekly":
                    field_values["wage_rate_unit"] = "Week"
                elif rate_type == "hour" or rate_type == "hourly":
                    field_values["wage_rate_unit"] = "Hour"

        elif "worksite" in section_name:
            # Worksite information section
            worksite_data = application_data.get("worksite", {})
            field_mapping = {
                "worksite_address1": "address",
                "worksite_address2": "address2",
                "worksite_city": "city",
                "worksite_state": "state",
                "worksite_postal_code": "zip",
                "worksite_county": "county"
            }

            for form_field, app_field in field_mapping.items():
                if app_field in worksite_data:
                    field_values[form_field] = worksite_data[app_field]

            # Handle multiple worksites
            if application_data.get("multiple_worksites", False):
                field_values["multiple_worksites"] = "Yes"

                # Format additional worksites for the dynamic table
                additional_worksites = application_data.get("additional_worksites", [])
                if additional_worksites:
                    # This will be filled asynchronously by get_additional_worksite_decisions
                    # We just note that it exists here
                    field_values["has_additional_worksites"] = True
            else:
                field_values["multiple_worksites"] = "No"

        elif "attorney" in section_name:
            # Attorney information section
            attorney_data = application_data.get("attorney", {})

            # Check if attorney is represented
            if attorney_data:
                field_values["attorney_represented"] = "Yes"

                field_mapping = {
                    "attorney_last_name": "last_name",
                    "attorney_first_name": "first_name",
                    "attorney_address1": "address",
                    "attorney_city": "city",
                    "attorney_state": "state",
                    "attorney_postal_code": "zip",
                    "attorney_phone": "phone",
                    "attorney_email": "email",
                    "attorney_firm_name": "firm"
                }

                for form_field, app_field in field_mapping.items():
                    if app_field in attorney_data:
                        field_values[form_field] = attorney_data[app_field]

                # If name is stored as a single field, try to split it
                if "name" in attorney_data and ("last_name" not in attorney_data or "first_name" not in attorney_data):
                    full_name = attorney_data["name"]
                    name_parts = full_name.split()

                    if len(name_parts) >= 2:
                        field_values["attorney_first_name"] = name_parts[0]
                        field_values["attorney_last_name"] = " ".join(name_parts[1:])
            else:
                field_values["attorney_represented"] = "No"

        # Declaration section - handle attestations
        elif "declaration" in section_name or "signature" in section_name:
            # Most checkboxes need to be checked
            for field in section["fields"]:
                if field.get("type") == "checkbox":
                    field_values[field["id"]] = True

            # Signature field should be filled with employer name or attorney name
            signature_fields = ["declaration_signature", "signature", "attestation_signature"]
            for sig_field in signature_fields:
                if sig_field in [f["id"] for f in section["fields"]]:
                    # Try to use employer name or attorney name as signature
                    if "employer" in application_data and "name" in application_data["employer"]:
                        field_values[sig_field] = application_data["employer"]["name"]
                    elif "attorney" in application_data and "name" in application_data["attorney"]:
                        field_values[sig_field] = application_data["attorney"]["name"]
                    break

        return field_values

    def get_field_suggestions(self, field_def: Dict[str, Any], application_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get suggestions for a specific field based on application data.

        Args:
            field_def: Field definition
            application_data: Application data

        Returns:
            Dictionary with suggested value and confidence
        """
        field_id = field_def["id"]
        field_type = field_def.get("type", "text")

        # Exact pattern matches for common fields
        field_patterns = {
            r"employer_name|company_name": lambda data: data.get("employer", {}).get("name"),
            r"employer.*?address|company.*?address": lambda data: data.get("employer", {}).get("address"),
            r"employer.*?city|company.*?city": lambda data: data.get("employer", {}).get("city"),
            r"employer.*?state|company.*?state": lambda data: data.get("employer", {}).get("state"),
            r"employer.*?zip|company.*?zip|employer.*?postal": lambda data: data.get("employer", {}).get("zip"),
            r"employer.*?phone|company.*?phone": lambda data: data.get("employer", {}).get("phone"),
            r"employer.*?email|company.*?email": lambda data: data.get("employer", {}).get("email"),
            r"job_title|position_title": lambda data: data.get("job", {}).get("title"),
            r"soc_code": lambda data: data.get("job", {}).get("soc_code"),
            r"job_duties|duties": lambda data: data.get("job", {}).get("duties"),
            r"wage_rate|salary": lambda data: data.get("wages", {}).get("rate"),
            r"prevailing_wage|pw_rate": lambda data: data.get("wages", {}).get("prevailing_wage"),
            r"worksite.*?address": lambda data: data.get("worksite", {}).get("address"),
            r"worksite.*?city": lambda data: data.get("worksite", {}).get("city"),
            r"worksite.*?state": lambda data: data.get("worksite", {}).get("state"),
            r"worksite.*?zip|worksite.*?postal": lambda data: data.get("worksite", {}).get("zip"),
            r"attorney.*?name": lambda data: data.get("attorney", {}).get("name"),
            r"attorney.*?firm": lambda data: data.get("attorney", {}).get("firm"),
            r"foreign_worker|beneficiary|worker": lambda data: data.get("foreign_worker", {}).get("name")
        }

        # Check for pattern matches
        for pattern, getter in field_patterns.items():
            if re.search(pattern, field_id, re.IGNORECASE):
                value = getter(application_data)
                if value is not None:
                    return {
                        "value": value,
                        "confidence": 0.9,
                        "source": "pattern_match"
                    }

        # Default fallbacks based on field type
        if field_type == "checkbox":
            return {
                "value": False,
                "confidence": 0.5,
                "source": "default"
            }
        elif field_type == "radio":
            options = field_def.get("options", [])
            if options:
                return {
                    "value": options[0],
                    "confidence": 0.5,
                    "source": "default"
                }

        # No suggestion found
        return {
            "value": "",
            "confidence": 0.0,
            "source": "none"
        }