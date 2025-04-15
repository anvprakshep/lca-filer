from typing import Dict, Any, List


class FormStructure:
    """LCA form structure definition."""

    @staticmethod
    def get_h1b_structure() -> Dict[str, Any]:
        """
        Get the structure of the H-1B LCA form.

        Returns:
            Dictionary describing the form structure
        """
        return {
            "sections": [
                {
                    "name": "ETA-9035 & ETA-9035E",
                    "description": "Initial LCA form selection",
                    "fields": [
                        {"id": "form_type", "type": "radio",
                         "options": ["H-1B", "H-1B1 Chile", "H-1B1 Singapore", "E-3 Australia"]}
                    ]
                },
                {
                    "name": "Section A: Employment-Based Nonimmigrant Information",
                    "description": "Basic information about the visa type and employment",
                    "fields": [
                        {"id": "visa_type", "type": "dropdown", "required": True},
                        {"id": "job_title", "type": "text", "required": True, "max_length": 60},
                        {"id": "soc_code", "type": "autocomplete", "required": True},
                        {"id": "soc_title", "type": "text", "required": True, "readonly": True},
                        # More fields...
                    ]
                },
                {
                    "name": "Section B: Employer Information",
                    "description": "Information about the employer",
                    "fields": [
                        {"id": "employer_name", "type": "text", "required": True},
                        {"id": "trade_name_dba", "type": "text", "required": False},
                        {"id": "fein", "type": "text", "required": True, "pattern": r"^\d{9}$"},
                        {"id": "naics_code", "type": "text", "required": True},
                        {"id": "address1", "type": "text", "required": True},
                        {"id": "address2", "type": "text", "required": False},
                        {"id": "city", "type": "text", "required": True},
                        {"id": "state", "type": "dropdown", "required": True},
                        {"id": "postal_code", "type": "text", "required": True, "pattern": r"^\d{5}(-\d{4})?$"},
                        {"id": "country", "type": "dropdown", "required": True, "default": "United States"},
                        {"id": "phone", "type": "text", "required": True, "pattern": r"^\d{10}$"},
                        {"id": "extension", "type": "text", "required": False},
                    ]
                },
                {
                    "name": "Section C: Employer Point of Contact Information",
                    "description": "Contact information for the employer",
                    "fields": [
                        {"id": "contact_last_name", "type": "text", "required": True},
                        {"id": "contact_first_name", "type": "text", "required": True},
                        {"id": "contact_middle_name", "type": "text", "required": False},
                        {"id": "contact_job_title", "type": "text", "required": True},
                        {"id": "contact_address1", "type": "text", "required": True},
                        {"id": "contact_address2", "type": "text", "required": False},
                        {"id": "contact_city", "type": "text", "required": True},
                        {"id": "contact_state", "type": "dropdown", "required": True},
                        {"id": "contact_postal_code", "type": "text", "required": True, "pattern": r"^\d{5}(-\d{4})?$"},
                        {"id": "contact_country", "type": "dropdown", "required": True, "default": "United States"},
                        {"id": "contact_phone", "type": "text", "required": True, "pattern": r"^\d{10}$"},
                        {"id": "contact_extension", "type": "text", "required": False},
                        {"id": "contact_email", "type": "text", "required": True, "pattern": r"^[^@]+@[^@]+\.[^@]+$"},
                    ]
                },
                {
                    "name": "Section D: Attorney or Agent Information",
                    "description": "Information about the attorney or agent",
                    "fields": [
                        {"id": "attorney_represented", "type": "radio", "required": True, "options": ["Yes", "No"]},
                        {"id": "attorney_type", "type": "radio", "required": False, "options": ["Attorney", "Agent"],
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_last_name", "type": "text", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_first_name", "type": "text", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_middle_name", "type": "text", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_address1", "type": "text", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_address2", "type": "text", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_city", "type": "text", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_state", "type": "dropdown", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_postal_code", "type": "text", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_country", "type": "dropdown", "required": False,
                         "conditional": {"attorney_represented": "Yes"}, "default": "United States"},
                        {"id": "attorney_phone", "type": "text", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_extension", "type": "text", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_email", "type": "text", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_firm_name", "type": "text", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                        {"id": "attorney_firm_fein", "type": "text", "required": False,
                         "conditional": {"attorney_represented": "Yes"}},
                    ]
                },
                {
                    "name": "Section E: Wage Information",
                    "description": "Wage and prevailing wage information",
                    "fields": [
                        {"id": "wage_rate", "type": "text", "required": True},
                        {"id": "wage_rate_unit", "type": "dropdown", "required": True,
                         "options": ["Hour", "Week", "Bi-Weekly", "Month", "Year"]},
                        {"id": "prevailing_wage", "type": "text", "required": True},
                        {"id": "pw_unit", "type": "dropdown", "required": True,
                         "options": ["Hour", "Week", "Bi-Weekly", "Month", "Year"]},
                        {"id": "pw_source", "type": "dropdown", "required": True,
                         "options": ["OES", "CBA", "DBA", "SCA", "Other"]},
                        {"id": "pw_source_year", "type": "text", "required": True},
                        {"id": "pw_source_other", "type": "text", "required": False,
                         "conditional": {"pw_source": "Other"}},
                    ]
                },
                {
                    "name": "Section F: Worksite Information",
                    "description": "Information about the worksite(s)",
                    "fields": [
                        {"id": "multiple_worksites", "type": "radio", "required": True, "options": ["Yes", "No"]},

                        # Primary worksite fields
                        {"id": "worksite_address1", "type": "text", "required": True},
                        {"id": "worksite_address2", "type": "text", "required": False},
                        {"id": "worksite_city", "type": "text", "required": True},
                        {"id": "worksite_county", "type": "text", "required": True},
                        {"id": "worksite_state", "type": "dropdown", "required": True},
                        {"id": "worksite_postal_code", "type": "text", "required": True,
                         "pattern": r"^\d{5}(-\d{4})?$"},

                        # Multiple worksites section
                        {
                            "id": "additional_worksites",
                            "type": "dynamic_table",
                            "required": False,
                            "conditional": {"multiple_worksites": "Yes"},
                            "rows": "variable",  # Can have multiple rows
                            "columns": [
                                {"id": "additional_worksite_address1", "type": "text", "required": True},
                                {"id": "additional_worksite_address2", "type": "text", "required": False},
                                {"id": "additional_worksite_city", "type": "text", "required": True},
                                {"id": "additional_worksite_county", "type": "text", "required": True},
                                {"id": "additional_worksite_state", "type": "dropdown", "required": True},
                                {"id": "additional_worksite_postal_code", "type": "text", "required": True}
                            ]
                        },
                    ]
                },
                {
                    "name": "Section G: Declarations and Signature",
                    "description": "Declarations and signature",
                    "fields": [
                        {"id": "declaration_subsection_1", "type": "checkbox", "required": True},
                        {"id": "declaration_subsection_2", "type": "checkbox", "required": True},
                        {"id": "declaration_subsection_3", "type": "checkbox", "required": True},
                        {"id": "declaration_subsection_4", "type": "checkbox", "required": True},
                        {"id": "declaration_signature", "type": "text", "required": True},
                        {"id": "declaration_date", "type": "date", "required": True},
                    ]
                },
            ]
        }

    @staticmethod
    def get_section_fields(section_name: str) -> List[Dict[str, Any]]:
        """
        Get fields for a specific form section.

        Args:
            section_name: Section name

        Returns:
            List of field definitions

        Raises:
            ValueError: If section doesn't exist
        """
        structure = FormStructure.get_h1b_structure()

        for section in structure["sections"]:
            if section["name"] == section_name:
                return section["fields"]

        raise ValueError(f"Section not found: {section_name}")

    @staticmethod
    def get_section_names() -> List[str]:
        """
        Get all section names in order.

        Returns:
            List of section names
        """
        structure = FormStructure.get_h1b_structure()
        return [section["name"] for section in structure["sections"]]