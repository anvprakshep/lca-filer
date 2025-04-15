import asyncio
import json
import re
from typing import Dict, Any, List, Optional, Union
import openai
from openai import AsyncOpenAI
from tenacity import retry, wait_exponential, stop_after_attempt

from utils.logger import get_logger
from ai.models import ValidationResult, FieldDecision, FormSection, LCADecision

logger = get_logger(__name__)


class LLMClient:
    """Client for interacting with large language models."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize LLM client.

        Args:
            config: LLM configuration
        """
        self.config = config
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "gpt-4")
        self.temperature = config.get("temperature", 0.1)

        # Set up OpenAI client
        self.client = AsyncOpenAI(api_key=self.api_key)


    @retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(3))
    # Update this portion in the validate_application_data method of LLMClient

    async def validate_application_data(self, application_data: Dict[str, Any]) -> ValidationResult:
        """
        Validate application data before submission.

        Args:
            application_data: Raw application data

        Returns:
            ValidationResult object
        """
        logger.info("Validating application data with AI")

        # Prepare the prompt for validation
        prompt = f"""
        You are an expert in H-1B LCA filings on the Department of Labor's FLAG portal.

        Review the following application data for an H-1B LCA filing and check for:
        1. Missing required fields
        2. Data format issues
        3. Potential legal or compliance issues
        4. Inconsistencies in the data

        APPLICATION DATA:
        {json.dumps(application_data, indent=2)}

        IMPORTANT VALIDATION RULES:
        - For wage comparison: The offered wage rate MUST be greater than or equal to the prevailing wage rate
        - Required employer fields: name, fein, address, city, state, zip, phone
        - Required job fields: title, soc_code
        - Required wage fields: rate, rate_type, prevailing_wage
        - Required worksite fields: address, city, state, zip

        Provide your analysis in JSON format with the following fields:
        1. "valid" (boolean): indicating if this application can proceed
        2. "validation_notes" (string): explaining any issues or concerns
        3. "cleaned_data" (object, optional): the application data in the correct format if valid
        4. "issues" (array, optional): list of specific issues found

        Each issue should include:
        - "field": the field with the issue
        - "issue_type": the type of issue (e.g., "missing", "format", "compliance")
        - "description": detailed description of the issue
        - "severity": how severe the issue is ("low", "medium", "high")
        """

        try:
            return ValidationResult(validation_notes='', valid=True, cleaned_data={}, issues=[])
            # Call the OpenAI API using the new client
            response = await self._call_openai_api(prompt)

            # Parse the response
            parsed_response = self._parse_json_from_response(response)

            # Additional manual wage validation to ensure correctness
            wages_data = application_data.get("wages", {})
            if wages_data:
                wage_rate = float(wages_data.get("rate", 0))
                prevailing_wage = float(wages_data.get("prevailing_wage", 0))

                if "valid" in parsed_response and not parsed_response["valid"]:
                    # Check if there's an incorrect wage comparison error
                    wage_issues = [issue for issue in parsed_response.get("issues", [])
                                   if
                                   "wage" in issue.get("field", "").lower() and "less than" in issue.get("description",
                                                                                                         "").lower()]

                    if wage_issues and wage_rate >= prevailing_wage:
                        # Fix the incorrect wage validation
                        logger.info("Correcting erroneous wage comparison validation")

                        # Remove the incorrect wage issue
                        parsed_response["issues"] = [issue for issue in parsed_response.get("issues", [])
                                                     if not (issue in wage_issues)]

                        # If no other issues remain, mark as valid
                        if not parsed_response["issues"]:
                            parsed_response["valid"] = True
                            parsed_response["validation_notes"] = "Validation passed after wage correction"
                        else:
                            parsed_response["validation_notes"] = parsed_response["validation_notes"].replace(
                                "wage rate is less than the prevailing wage",
                                "other issues need to be resolved"
                            )

            # Convert to ValidationResult
            return ValidationResult(
                valid=parsed_response.get("valid", False),
                validation_notes=parsed_response.get("validation_notes", "Validation failed"),
                cleaned_data=parsed_response.get("cleaned_data",
                                                 application_data if parsed_response.get("valid", False) else None),
                issues=parsed_response.get("issues", [])
            )

        except Exception as e:
            logger.error(f"Error in data validation: {str(e)}")
            return ValidationResult(
                valid=False,
                validation_notes=f"Error validating data: {str(e)}",
                issues=[{"field": "general", "issue_type": "system", "description": str(e), "severity": "high"}]
            )

    @retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(3))
    async def get_section_decisions(self, section: Dict[str, Any], application_data: Dict[str, Any]) -> List[
        FieldDecision]:
        """
        Get AI decisions for filling a form section.

        Args:
            section: Form section definition
            application_data: Validated application data

        Returns:
            List of FieldDecision objects
        """
        logger.info(f"Getting AI decisions for section: {section['name']}")

        # Prepare the prompt
        prompt = f"""
        You are an expert in H-1B LCA filings on the Department of Labor's FLAG portal.

        You need to fill out the following section of an LCA form:

        SECTION: {section['name']}

        SECTION DESCRIPTION: {section.get('description', 'No description available')}

        AVAILABLE FIELDS:
        {json.dumps(section['fields'], indent=2)}

        Based on the application data below, determine the appropriate value for each field.

        APPLICATION DATA:
        {json.dumps(application_data, indent=2)}

        For each field, provide:
        1. The field ID
        2. The value to enter
        3. Your reasoning for selecting this value
        4. Your confidence level (0-1)

        Format your response as a JSON object that matches the following schema:
        ```json
        {
        "decisions": [
                {
        "field_id": "field_name",
                    "value": "value to enter",
                    "reasoning": "explanation for this decision",
                    "confidence": 0.95
                },
                ...
            ]
        }
        ```

        Only respond with valid JSON that matches this schema.
        """

        try:
            # Call the OpenAI API
            response = await self._call_openai_api(prompt)

            # Parse the response
            parsed_response = self._parse_json_from_response(response)

            # Convert to FieldDecision objects
            decisions = []
            for decision in parsed_response.get("decisions", []):
                decisions.append(FieldDecision(
                    field_id=decision["field_id"],
                    value=decision["value"],
                    reasoning=decision["reasoning"],
                    confidence=decision["confidence"]
                ))

            return decisions

        except Exception as e:
            logger.error(f"Error getting section decisions: {str(e)}")
            return []

    @retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(3))
    async def get_error_fixes(self, errors: List[Dict[str, Any]], form_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get AI suggestions for fixing form errors.

        Args:
            errors: List of detected errors
            form_state: Current state of the form

        Returns:
            Dictionary mapping field IDs to fix suggestions
        """
        logger.info(f"Getting AI suggestions for fixing {len(errors)} errors")

        # Prepare the prompt
        prompt = f"""
        You are an expert in fixing errors in H-1B LCA applications on the DOL FLAG portal.

        The following errors were detected:
        {json.dumps(errors, indent=2)}

        The current state of the form is:
        {json.dumps(form_state, indent=2)}

        Please suggest corrections for each field to resolve the errors.
        Format your response as a JSON object with field IDs as keys and corrected values as values.
        For each field, also include a "reasoning" explaining why this change will fix the error.

        Example response format:
        ```json
        {{
            "field_id1": {{
                "value": "corrected value",
                "reasoning": "explanation for the correction"
            }},
            "field_id2": {{
                "value": true,
                "reasoning": "explanation for the correction"
            }}
        }}
        ```

        Only respond with valid JSON that matches this format.
        """

        try:
            # Call the OpenAI API
            response = await self._call_openai_api(prompt)

            # Parse the response
            fixes = self._parse_json_from_response(response)

            return fixes

        except Exception as e:
            logger.error(f"Error getting error fixes: {str(e)}")
            return {}

    async def _call_openai_api(self, prompt: str) -> str:
        """
        Call the OpenAI API with the given prompt.

        Args:
            prompt: Text prompt for the API

        Returns:
            API response text
        """
        try:
            # Run in a thread to avoid blocking the event loop
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert in H-1B LCA filings..."},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=2000
            )

            # Extract text from response
            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Error calling OpenAI API: {str(e)}")
            raise

    def _parse_json_from_response(self, response: str) -> Dict[str, Any]:
        """
        Parse JSON from LLM response.

        Args:
            response: LLM response text

        Returns:
            Parsed JSON as a dictionary
        """
        try:
            # First try to parse the response directly
            return json.loads(response)
        except json.JSONDecodeError:
            # If that fails, try to extract JSON from markdown code blocks
            json_match = re.search(r'```(?:json)?\n(.*?)\n```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                return json.loads(json_str)
            else:
                # If that fails too, try to find anything that looks like JSON
                json_match = re.search(r'({.*})', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                    return json.loads(json_str)
                else:
                    raise ValueError("Failed to parse JSON from response")