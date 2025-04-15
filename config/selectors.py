from typing import Dict, Any


class Selectors:
    """DOM selectors for FLAG portal elements."""

    @staticmethod
    def get_all() -> Dict[str, str]:
        """
        Get all selectors for FLAG portal elements.

        Returns:
            Dictionary mapping selector names to CSS selectors
        """
        return {
            # Login page
            "username_field": "#user_email",
            "password_field": ".password-toggle__input ",
            "login_button": "button[type='submit']",

            # Main navigation
            "new_lca_button": "a[href*='new-lca']",
            "continue_button": "button:has-text('Continue')",
            "save_button": "button:has-text('Save')",
            "submit_button": "button:has-text('Submit')",

            # Employer Information section
            "employer_name": "#employerName",
            "employer_id": "#employerId",
            "employer_address": "#employerAddress",
            "employer_city": "#employerCity",
            "employer_state": "#employerState",
            "employer_zip": "#employerZip",
            "employer_phone": "#employerPhone",

            # Job Information section
            "job_title": "#jobTitle",
            "soc_code": "#socCode",
            "job_duties": "#jobDuties",

            # Wage Information
            "wage_rate": "#wageRate",
            "wage_type": "#wageType",
            "prevailing_wage": "#prevailingWage",
            "pw_source": "#pwSource",

            # Worksite Information
            "worksite_address": "#worksiteAddress",
            "worksite_city": "#worksiteCity",
            "worksite_state": "#worksiteState",
            "worksite_zip": "#worksiteZip",

            # Declaration section
            "attorney_checkbox": "#attorneyCheckbox",
            "declaration_checkbox": "#declarationCheckbox",

            # Confirmation
            "confirmation_number": "#confirmationNumber",

            # Captcha
            "captcha_image": "img[alt='CAPTCHA']",
            "captcha_input": "#captchaInput",

            # Error messages
            "error_message": ".error-message",

            # Many more selectors for all form fields...
        }

    @staticmethod
    def get(name: str) -> str:
        """
        Get selector by name.

        Args:
            name: Selector name

        Returns:
            CSS selector string

        Raises:
            KeyError: If selector name doesn't exist
        """
        selectors = Selectors.get_all()
        if name not in selectors:
            raise KeyError(f"Selector not found: {name}")
        return selectors[name]

    @staticmethod
    def get_field_selector(field_id: str) -> str:
        """
        Get selector for a form field by ID.

        Args:
            field_id: Field ID

        Returns:
            CSS selector for the field
        """
        return f"#{field_id}"