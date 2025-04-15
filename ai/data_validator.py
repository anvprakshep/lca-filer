# ai/data_validator.py
import asyncio
from typing import Dict, Any, List, Tuple, Optional
import json
import re
import time

from utils.logger import get_logger
from ai.llm_client import LLMClient
from ai.models import ValidationResult

logger = get_logger(__name__)


class DataValidator:
    """Validates application data before submission."""

    def __init__(self, llm_client: LLMClient):
        """
        Initialize data validator.

        Args:
            llm_client: LLM client for AI validation
        """
        self.llm_client = llm_client

    async def validate(self, application_data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Validate application data using AI and rule-based checks.

        Args:
            application_data: Raw application data

        Returns:
            Tuple of (validated_data, validation_notes)
        """
        logger.info("Starting data validation")

        # Perform basic validation
        basic_validation_result = self._perform_basic_validation(application_data)

        if not basic_validation_result[0]:
            logger.error(f"Basic validation failed: {basic_validation_result[1]}")
            return None, basic_validation_result[1]

        # Validate multiple worksites structure if present
        if application_data.get("multiple_worksites", False):
            worksite_validation = self._validate_multiple_worksites(application_data)
            if not worksite_validation[0]:
                logger.error(f"Multiple worksites validation failed: {worksite_validation[1]}")
                return None, worksite_validation[1]

        # Perform AI validation
        ai_validation_result = await self.llm_client.validate_application_data(application_data)

        if not ai_validation_result.valid:
            logger.error(f"AI validation failed: {ai_validation_result.validation_notes}")

            # Format issues for logging
            issue_details = ""
            for issue in ai_validation_result.issues:
                issue_details += f"\n- {issue.get('field', 'unknown')}: {issue.get('description', 'No description')} ({issue.get('severity', 'unknown')} severity)"

            validation_notes = f"{ai_validation_result.validation_notes}\n{issue_details}"
            return None, validation_notes

        # Use the cleaned data from AI validation
        validated_data = ai_validation_result.cleaned_data or application_data

        # Perform specific field normalization
        validated_data = self._normalize_fields(validated_data)

        # Normalize multiple worksite data
        if validated_data.get("multiple_worksites", False):
            validated_data = self._normalize_worksite_data(validated_data)

        logger.info("Data validation successful")
        return validated_data, ai_validation_result.validation_notes

    def _perform_basic_validation(self, application_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Perform basic rule-based validation checks.

        Args:
            application_data: Application data to validate

        Returns:
            Tuple of (is_valid, validation_notes)
        """
        # Check required sections
        required_sections = ["employer", "job", "wages", "worksite"]
        missing_sections = [section for section in required_sections if section not in application_data]

        if missing_sections:
            return False, f"Missing required sections: {', '.join(missing_sections)}"

        # Check credentials if needed for submission
        if "credentials" not in application_data:
            return False, "Missing credentials for FLAG portal"

        # Validate wage information
        wage_valid, wage_message = self._validate_wage_information(application_data)
        if not wage_valid:
            return False, wage_message

        # Check credentials if needed for submission
        if "credentials" not in application_data:
            return False, "Missing credentials for FLAG portal"

        # Check primary worksite required fields
        worksite = application_data.get("worksite", {})
        required_worksite_fields = ["address", "city", "state", "zip"]
        missing_worksite_fields = [field for field in required_worksite_fields if field not in worksite]

        if missing_worksite_fields:
            return False, f"Missing required primary worksite fields: {', '.join(missing_worksite_fields)}"

        # Additional validation could be added here

        return True, "Basic validation passed"

    def _validate_wage_information(self, application_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate wage information to ensure compliance with LCA requirements.

        Args:
            application_data: Application data to validate

        Returns:
            Tuple of (is_valid, validation_notes)
        """
        try:
            wages_data = application_data.get("wages", {})
            if not wages_data:
                return False, "Missing wages section"

            # Extract wage rate and prevailing wage
            wage_rate = wages_data.get("rate")
            prevailing_wage = wages_data.get("prevailing_wage")

            # Convert to numeric values for comparison
            try:
                wage_rate = float(wage_rate) if wage_rate else 0
                prevailing_wage = float(prevailing_wage) if prevailing_wage else 0
            except (ValueError, TypeError):
                return False, "Wage rate and prevailing wage must be numeric values"

            # Ensure wage rate is equal to or greater than prevailing wage
            if wage_rate < prevailing_wage:
                return False, f"The offered wage rate (${wage_rate}) is less than the prevailing wage rate (${prevailing_wage}). The employer must pay at least the prevailing wage."

            # Validate wage rate type
            wage_rate_type = wages_data.get("rate_type", "").lower()
            if not wage_rate_type:
                return False, "Missing wage rate type (hourly, weekly, monthly, annual, etc.)"

            valid_rate_types = ["hour", "hourly", "week", "weekly", "biweekly", "bi-weekly", "month", "monthly", "year",
                                "yearly", "annual"]
            if wage_rate_type not in valid_rate_types:
                return False, f"Invalid wage rate type: {wage_rate_type}. Must be one of: {', '.join(valid_rate_types)}"

            return True, "Wage validation passed"

        except Exception as e:
            return False, f"Error validating wage information: {str(e)}"


    def _validate_multiple_worksites(self, application_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate multiple worksites data structure.

        Args:
            application_data: Application data to validate

        Returns:
            Tuple of (is_valid, validation_notes)
        """
        # Check if multiple_worksites flag is set
        if not application_data.get("multiple_worksites", False):
            return True, "No multiple worksites to validate"

        # Check if additional_worksites list exists
        additional_worksites = application_data.get("additional_worksites", [])
        if not additional_worksites:
            return False, "Multiple worksites flag is set but no additional worksites provided"

        # Validate each additional worksite
        required_fields = ["address", "city", "state", "zip"]
        issues = []

        for i, worksite in enumerate(additional_worksites, 1):
            missing_fields = [field for field in required_fields if field not in worksite]
            if missing_fields:
                issues.append(f"Worksite #{i} is missing required fields: {', '.join(missing_fields)}")

        if issues:
            return False, "\n".join(issues)

        return True, "Multiple worksites validation passed"

    def _normalize_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize specific fields to ensure they meet FLAG portal requirements.

        Args:
            data: Data to normalize

        Returns:
            Normalized data
        """
        normalized = data.copy()

        # Example normalizations

        # Ensure phone numbers are formatted correctly
        if "employer" in normalized and "phone" in normalized["employer"]:
            phone = normalized["employer"]["phone"]
            # Remove non-numeric characters
            phone = re.sub(r'\D', '', str(phone))
            # Ensure it's 10 digits
            if len(phone) >= 10:
                phone = phone[-10:]
            normalized["employer"]["phone"] = phone

        # Ensure ZIP codes are formatted correctly
        if "employer" in normalized and "zip" in normalized["employer"]:
            zip_code = normalized["employer"]["zip"]
            # Remove non-alphanumeric characters
            zip_code = re.sub(r'[^0-9\-]', '', str(zip_code))
            # Ensure basic 5-digit format if not already in 5+4 format
            if not re.match(r'^\d{5}(-\d{4})?$', zip_code):
                zip_code = zip_code[:5]
            normalized["employer"]["zip"] = zip_code

        # Normalize primary worksite zip
        if "worksite" in normalized and "zip" in normalized["worksite"]:
            zip_code = normalized["worksite"]["zip"]
            zip_code = re.sub(r'[^0-9\-]', '', str(zip_code))
            if not re.match(r'^\d{5}(-\d{4})?$', zip_code):
                zip_code = zip_code[:5]
            normalized["worksite"]["zip"] = zip_code

        # Ensure wage rate is numeric
        if "wages" in normalized and "rate" in normalized["wages"]:
            wage_rate = normalized["wages"]["rate"]
            if isinstance(wage_rate, str):
                # Remove non-numeric characters except decimal point
                wage_rate = re.sub(r'[^\d.]', '', wage_rate)
                try:
                    wage_rate = float(wage_rate)
                    normalized["wages"]["rate"] = wage_rate
                except ValueError:
                    # If conversion fails, keep original
                    pass

        return normalized

    def _normalize_worksite_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize multiple worksite data.

        Args:
            data: Data to normalize

        Returns:
            Normalized data
        """
        normalized = data.copy()

        # Ensure the multiple_worksites flag is set correctly
        if "additional_worksites" in normalized and normalized.get("additional_worksites"):
            normalized["multiple_worksites"] = True
        else:
            normalized["multiple_worksites"] = False

        # If multiple_worksites is False, remove any additional worksites
        if not normalized["multiple_worksites"]:
            normalized["additional_worksites"] = []
            return normalized

        # Normalize each additional worksite
        if "additional_worksites" in normalized:
            normalized_worksites = []

            for worksite in normalized["additional_worksites"]:
                # Skip empty worksites
                if not worksite:
                    continue

                normalized_worksite = {}

                # Copy all fields
                for field, value in worksite.items():
                    normalized_worksite[field] = value

                # Normalize zip code
                if "zip" in normalized_worksite:
                    zip_code = normalized_worksite["zip"]
                    zip_code = re.sub(r'[^0-9\-]', '', str(zip_code))
                    if not re.match(r'^\d{5}(-\d{4})?$', zip_code):
                        zip_code = zip_code[:5]
                    normalized_worksite["zip"] = zip_code

                # Ensure required fields exist
                required_fields = ["address", "city", "state", "zip"]
                for field in required_fields:
                    if field not in normalized_worksite:
                        # Try to find it with different naming conventions
                        alternative_names = {
                            "address": ["address1", "street", "street_address"],
                            "city": ["town", "municipality"],
                            "state": ["province", "region"],
                            "zip": ["zipcode", "postal_code", "zip_code", "postalcode"]
                        }

                        for alt_name in alternative_names.get(field, []):
                            if alt_name in normalized_worksite:
                                normalized_worksite[field] = normalized_worksite[alt_name]
                                break

                normalized_worksites.append(normalized_worksite)

            normalized["additional_worksites"] = normalized_worksites

        return normalized