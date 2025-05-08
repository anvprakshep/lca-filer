# utils/status_tracker.py
import time
from datetime import datetime
from typing import Dict, Any, Optional, Callable
import logging

logger = logging.getLogger(__name__)


class FilingStatusTracker:
    """
    Enhanced tracker for filing status with detailed stage information.
    """

    def __init__(self, filing_id: str, callback_fn=None):
        """
        Initialize status tracker.

        Args:
            filing_id: Filing identifier
            callback_fn: Callback function for status updates
        """
        self.filing_id = filing_id
        self.callback_fn = callback_fn
        self.start_time = time.time()
        self.current_section = None
        self.section_count = 0
        self.total_sections = 10  # Approximate number of sections
        self.completed_sections = []
        self.stages = self._init_stages()
        self.current_stage = None
        self.current_progress = 0

    def _init_stages(self) -> Dict[str, Dict[str, Any]]:
        """Initialize the stage definitions and progress allocations."""
        return {
            "initialization": {
                "name": "Initialization",
                "progress_range": (0, 5),
                "description": "Setting up the filing process"
            },
            "navigation": {
                "name": "Portal Navigation",
                "progress_range": (5, 10),
                "description": "Navigating to the FLAG portal"
            },
            "authentication": {
                "name": "Authentication",
                "progress_range": (10, 15),
                "description": "Authenticating with the FLAG portal"
            },
            "form_selection": {
                "name": "Form Selection",
                "progress_range": (15, 20),
                "description": "Selecting the H-1B LCA form"
            },
            "form_filling": {
                "name": "Form Filling",
                "progress_range": (20, 80),
                "description": "Filling out form sections"
            },
            "review": {
                "name": "Review",
                "progress_range": (80, 90),
                "description": "Reviewing completed form"
            },
            "submission": {
                "name": "Submission",
                "progress_range": (90, 100),
                "description": "Submitting the form to DOL"
            }
        }

    def update_stage(self, stage_id: str, message: str = None, substage: str = None):
        """
        Update the current stage.

        Args:
            stage_id: Stage identifier
            message: Optional status message
            substage: Optional substage identifier
        """
        if stage_id not in self.stages:
            logger.warning(f"Unknown stage ID: {stage_id}")
            return

        self.current_stage = stage_id
        stage_info = self.stages[stage_id]

        # Calculate progress based on stage range
        progress_range = stage_info["progress_range"]

        if stage_id == "form_filling" and self.section_count > 0 and substage:
            # For form filling, calculate based on section progress
            # Extract section number from substage if possible
            section_num = 0
            if "_" in substage:
                try:
                    section_num = int(substage.split("_")[1])
                except (ValueError, IndexError):
                    section_num = len(self.completed_sections)

            # Calculate more precise progress within form_filling range
            section_progress = min(section_num / self.total_sections, 1.0)
            range_size = progress_range[1] - progress_range[0]
            self.current_progress = progress_range[0] + (range_size * section_progress)
        else:
            # For other stages, use the start of the range
            self.current_progress = progress_range[0]

        # Prepare update data
        update_data = {
            "status": "processing",
            "stage": stage_info["name"],
            "stage_id": stage_id,
            "progress": round(self.current_progress),
            "elapsed_time": round(time.time() - self.start_time, 1),
            "timestamp": datetime.now().isoformat()
        }

        if message:
            update_data["message"] = message

        if substage:
            update_data["substage"] = substage

        if self.current_section:
            update_data["current_section"] = self.current_section

        # Send the update
        self._send_update(update_data)

    def start_section(self, section_name: str):
        """
        Mark a form section as started.

        Args:
            section_name: Name of the section
        """
        self.current_section = section_name
        self.section_count += 1

        # Update stage to form_filling if not already
        if self.current_stage != "form_filling":
            self.update_stage("form_filling", f"Starting section: {section_name}")
        else:
            # Just update with the new section info
            self._send_update({
                "status": "processing",
                "stage": self.stages["form_filling"]["name"],
                "stage_id": "form_filling",
                "substage": f"section_{self.section_count}",
                "current_section": section_name,
                "message": f"Starting section: {section_name}",
                "progress": round(self.current_progress),
                "timestamp": datetime.now().isoformat()
            })

    def complete_section(self, section_name: str):
        """
        Mark a form section as completed.

        Args:
            section_name: Name of the section
        """
        if section_name not in self.completed_sections:
            self.completed_sections.append(section_name)

        # Calculate new progress
        section_progress = len(self.completed_sections) / self.total_sections
        range_size = self.stages["form_filling"]["progress_range"][1] - self.stages["form_filling"]["progress_range"][0]
        self.current_progress = self.stages["form_filling"]["progress_range"][0] + (range_size * section_progress)

        # Send update
        self._send_update({
            "status": "processing",
            "stage": self.stages["form_filling"]["name"],
            "stage_id": "form_filling",
            "substage": f"section_{self.section_count}_complete",
            "current_section": section_name,
            "message": f"Completed section: {section_name}",
            "progress": round(self.current_progress),
            "timestamp": datetime.now().isoformat()
        })

    def interaction_required(self, section_name: str, interaction_type: str = "form_input"):
        """
        Mark that user interaction is required.

        Args:
            section_name: Name of the section
            interaction_type: Type of interaction required
        """
        self._send_update({
            "status": "interaction_needed",
            "stage": self.stages["form_filling"]["name"],
            "stage_id": "form_filling",
            "substage": f"section_{self.section_count}_interaction",
            "current_section": section_name,
            "interaction_type": interaction_type,
            "message": f"Human interaction required for section: {section_name}",
            "progress": round(self.current_progress),
            "timestamp": datetime.now().isoformat()
        })

    def interaction_resolved(self, section_name: str):
        """
        Mark that user interaction has been resolved.

        Args:
            section_name: Name of the section
        """
        self._send_update({
            "status": "processing",
            "stage": self.stages["form_filling"]["name"],
            "stage_id": "form_filling",
            "substage": f"section_{self.section_count}_continuing",
            "current_section": section_name,
            "message": f"Continuing after user interaction in section: {section_name}",
            "progress": round(self.current_progress),
            "timestamp": datetime.now().isoformat()
        })

    def error_occurred(self, message: str, section_name: str = None):
        """
        Mark that an error has occurred.

        Args:
            message: Error message
            section_name: Optional section name
        """
        update_data = {
            "status": "error",
            "message": message,
            "timestamp": datetime.now().isoformat()
        }

        if self.current_stage:
            update_data["stage"] = self.stages[self.current_stage]["name"]
            update_data["stage_id"] = self.current_stage

        if section_name or self.current_section:
            update_data["current_section"] = section_name or self.current_section

        self._send_update(update_data)

    def complete_filing(self, status: str, confirmation_number: str = None):
        """
        Mark the filing as completed.

        Args:
            status: Final status (success, error, etc.)
            confirmation_number: Optional confirmation number
        """
        update_data = {
            "status": status,
            "stage": "Complete",
            "stage_id": "complete",
            "progress": 100,
            "elapsed_time": round(time.time() - self.start_time, 1),
            "timestamp": datetime.now().isoformat()
        }

        if status == "success":
            update_data["message"] = "Filing completed successfully"
            if confirmation_number:
                update_data["confirmation_number"] = confirmation_number
                update_data["message"] = f"Filing completed successfully. Confirmation #: {confirmation_number}"
        else:
            update_data["message"] = f"Filing completed with status: {status}"

        self._send_update(update_data)

    def _send_update(self, update_data: Dict[str, Any]):
        """
        Send a status update via callback.

        Args:
            update_data: Update data dictionary
        """
        if self.callback_fn:
            try:
                self.callback_fn(self.filing_id, update_data)
            except Exception as e:
                logger.error(f"Error in status update callback: {str(e)}")

        # Log the update
        status = update_data.get("status", "unknown")
        message = update_data.get("message", "")
        logger.info(f"Filing {self.filing_id} status update: {status} - {message}")