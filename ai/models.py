from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class FieldDecision(BaseModel):
    """Model for field-filling decisions."""
    field_id: str = Field(..., description="The DOM selector ID for the field")
    value: str = Field(..., description="The value to enter in the field")
    reasoning: str = Field(..., description="Explanation for why this value was chosen")
    confidence: float = Field(..., description="Confidence score between 0-1")

class FormSection(BaseModel):
    """Model for form section decisions."""
    section_name: str = Field(..., description="Name of the LCA form section")
    decisions: List[FieldDecision] = Field(..., description="List of field decisions for this section")

class LCADecision(BaseModel):
    """Model for overall LCA decisions."""
    form_sections: List[FormSection] = Field(..., description="All form section decisions")
    requires_human_review: bool = Field(..., description="Whether this LCA requires human review")
    review_reasons: List[str] = Field(..., description="Reasons for human review if required")

class ErrorFix(BaseModel):
    """Model for error fix suggestions."""
    field_id: str = Field(..., description="The field ID to fix")
    value: Any = Field(..., description="The value to use")
    reasoning: str = Field(..., description="Reasoning for the fix")

class ValidationResult(BaseModel):
    """Model for data validation results."""
    valid: bool = Field(..., description="Whether the data is valid")
    validation_notes: str = Field(..., description="Notes about validation")
    cleaned_data: Optional[Dict[str, Any]] = Field(None, description="Cleaned data if valid")
    issues: List[Dict[str, Any]] = Field(default_factory=list, description="List of issues found")