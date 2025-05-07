"""
Progress Tracker for LCA Filing Automation System.

This module provides real-time progress tracking for LCA filings, allowing
both the automation system and the web interface to monitor and update
filing progress with granular step information.
"""

import time
import json
import threading
import asyncio
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime

from utils.logger import get_logger

logger = get_logger(__name__)


class FilingStep:
    """Represents a single step in the filing process."""

    def __init__(self, step_id: str, name: str, description: str, order: int,
                 estimated_time: int = 10, parent_id: Optional[str] = None):
        """
        Initialize filing step.

        Args:
            step_id: Unique identifier for the step
            name: Human-readable name
            description: Detailed description
            order: Ordering value for display
            estimated_time: Estimated completion time in seconds
            parent_id: ID of parent step (for sub-steps)
        """
        self.step_id = step_id
        self.name = name
        self.description = description
        self.order = order
        self.status = "pending"  # pending, in_progress, completed, failed, skipped
        self.start_time = None
        self.end_time = None
        self.duration = None
        self.estimated_time = estimated_time
        self.parent_id = parent_id
        self.progress_pct = 0
        self.message = ""
        self.substeps = []
        self.screenshot_urls = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert step to dictionary."""
        return {
            "step_id": self.step_id,
            "name": self.name,
            "description": self.description,
            "order": self.order,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "estimated_time": self.estimated_time,
            "parent_id": self.parent_id,
            "progress_pct": self.progress_pct,
            "message": self.message,
            "substeps": [substep.to_dict() for substep in self.substeps],
            "screenshot_urls": self.screenshot_urls
        }

    def start(self):
        """Mark step as started."""
        self.status = "in_progress"
        self.start_time = datetime.now().isoformat()
        self.progress_pct = 5

    def complete(self, message: str = ""):
        """Mark step as completed."""
        self.status = "completed"
        self.end_time = datetime.now().isoformat()
        self.progress_pct = 100
        if message:
            self.message = message

        # Calculate duration
        if self.start_time:
            start = datetime.fromisoformat(self.start_time)
            end = datetime.fromisoformat(self.end_time)
            self.duration = (end - start).total_seconds()

    def fail(self, message: str):
        """Mark step as failed."""
        self.status = "failed"
        self.end_time = datetime.now().isoformat()
        self.message = message

        # Calculate duration
        if self.start_time:
            start = datetime.fromisoformat(self.start_time)
            end = datetime.fromisoformat(self.end_time)
            self.duration = (end - start).total_seconds()

    def skip(self, message: str = ""):
        """Mark step as skipped."""
        self.status = "skipped"
        if message:
            self.message = message

    def update_progress(self, progress_pct: int, message: str = ""):
        """Update progress percentage."""
        self.progress_pct = min(progress_pct, 99)  # Never 100% until complete
        if message:
            self.message = message

    def add_screenshot(self, url: str):
        """Add screenshot URL to step."""
        self.screenshot_urls.append(url)

    def add_substep(self, substep: 'FilingStep'):
        """Add a substep to this step."""
        substep.parent_id = self.step_id
        self.substeps.append(substep)


class ProgressTracker:
    """
    Tracks filing progress across multiple steps.

    This class manages the tracking and updating of progress for a filing process,
    providing real-time status information and notifications.
    """

    def __init__(self, filing_id: str, total_steps: int = 10):
        """
        Initialize progress tracker.

        Args:
            filing_id: Unique identifier for the filing
            total_steps: Total number of steps expected
        """
        self.filing_id = filing_id
        self.total_steps = total_steps
        self.steps = []
        self.overall_status = "pending"  # pending, in_progress, completed, failed, paused
        self.overall_progress_pct = 0
        self.start_time = None
        self.end_time = None
        self.duration = None
        self.current_step_id = None
        self.update_callbacks = []
        self.lock = threading.Lock()

        # Create default step structure
        self._create_default_steps()

    def _create_default_steps(self):
        """Create default step structure."""
        steps = [
            FilingStep("initialization", "Initialization", "Setting up the filing process", 1, 10),
            FilingStep("navigation", "Portal Navigation", "Navigating to the FLAG portal", 2, 15),
            FilingStep("login", "Authentication", "Logging in to the FLAG portal", 3, 20),
            FilingStep("form_selection", "Form Selection", "Selecting the H-1B LCA form", 4, 10),
            FilingStep("employer_info", "Employer Information", "Filling employer information section", 5, 30),
            FilingStep("job_info", "Job Information", "Filling job information section", 6, 30),
            FilingStep("wage_info", "Wage Information", "Filling wage information section", 7, 30),
            FilingStep("worksite_info", "Worksite Information", "Filling worksite information section", 8, 30),
            FilingStep("attorney_info", "Attorney Information", "Filling attorney information section", 9, 30),
            FilingStep("review", "Review & Submission", "Reviewing and submitting the form", 10, 20),
        ]

        self.steps = steps

    def to_dict(self) -> Dict[str, Any]:
        """Convert tracker to dictionary."""
        return {
            "filing_id": self.filing_id,
            "total_steps": self.total_steps,
            "steps": [step.to_dict() for step in self.steps],
            "overall_status": self.overall_status,
            "overall_progress_pct": self.overall_progress_pct,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "current_step_id": self.current_step_id
        }

    def start_filing(self):
        """Start the filing process."""
        with self.lock:
            self.start_time = datetime.now().isoformat()
            self.overall_status = "in_progress"
            self._update_overall_progress()
            self._notify_update("filing_started")

    def complete_filing(self, message: str = ""):
        """Complete the filing process."""
        with self.lock:
            self.end_time = datetime.now().isoformat()
            self.overall_status = "completed"
            self.overall_progress_pct = 100

            # Calculate duration
            if self.start_time:
                start = datetime.fromisoformat(self.start_time)
                end = datetime.fromisoformat(self.end_time)
                self.duration = (end - start).total_seconds()

            self._notify_update("filing_completed", message)

    def fail_filing(self, message: str):
        """Mark filing as failed."""
        with self.lock:
            self.end_time = datetime.now().isoformat()
            self.overall_status = "failed"

            # Calculate duration
            if self.start_time:
                start = datetime.fromisoformat(self.start_time)
                end = datetime.fromisoformat(self.end_time)
                self.duration = (end - start).total_seconds()

            self._notify_update("filing_failed", message)

    def pause_filing(self, message: str = ""):
        """Pause the filing process."""
        with self.lock:
            self.overall_status = "paused"
            self._notify_update("filing_paused", message)

    def resume_filing(self):
        """Resume the filing process."""
        with self.lock:
            self.overall_status = "in_progress"
            self._notify_update("filing_resumed")

    def get_step(self, step_id: str) -> Optional[FilingStep]:
        """
        Get a step by ID.

        Args:
            step_id: Step ID to find

        Returns:
            Step object or None if not found
        """
        # First check top-level steps
        for step in self.steps:
            if step.step_id == step_id:
                return step

            # Check substeps
            for substep in step.substeps:
                if substep.step_id == step_id:
                    return substep

        return None

    def start_step(self, step_id: str, message: str = ""):
        """
        Start a step.

        Args:
            step_id: Step ID to start
            message: Optional message
        """
        with self.lock:
            step = self.get_step(step_id)
            if not step:
                logger.warning(f"Step {step_id} not found")
                return

            step.start()
            if message:
                step.message = message

            self.current_step_id = step_id
            self._update_overall_progress()
            self._notify_update("step_started", f"Started step: {step.name}")

    def complete_step(self, step_id: str, message: str = ""):
        """
        Complete a step.

        Args:
            step_id: Step ID to complete
            message: Optional message
        """
        with self.lock:
            step = self.get_step(step_id)
            if not step:
                logger.warning(f"Step {step_id} not found")
                return

            step.complete(message)
            self._update_overall_progress()
            self._notify_update("step_completed", f"Completed step: {step.name}")

    def fail_step(self, step_id: str, message: str):
        """
        Mark a step as failed.

        Args:
            step_id: Step ID to fail
            message: Error message
        """
        with self.lock:
            step = self.get_step(step_id)
            if not step:
                logger.warning(f"Step {step_id} not found")
                return

            step.fail(message)
            self._update_overall_progress()
            self._notify_update("step_failed", f"Failed step: {step.name} - {message}")

    def skip_step(self, step_id: str, message: str = ""):
        """
        Mark a step as skipped.

        Args:
            step_id: Step ID to skip
            message: Optional message
        """
        with self.lock:
            step = self.get_step(step_id)
            if not step:
                logger.warning(f"Step {step_id} not found")
                return

            step.skip(message)
            self._update_overall_progress()
            self._notify_update("step_skipped", f"Skipped step: {step.name}")

    def update_step_progress(self, step_id: str, progress_pct: int, message: str = ""):
        """
        Update progress of a step.

        Args:
            step_id: Step ID to update
            progress_pct: Progress percentage (0-100)
            message: Optional message
        """
        with self.lock:
            step = self.get_step(step_id)
            if not step:
                logger.warning(f"Step {step_id} not found")
                return

            step.update_progress(progress_pct, message)
            self._update_overall_progress()
            self._notify_update("step_progress", f"Step {step.name} progress: {progress_pct}%")

    def add_step_screenshot(self, step_id: str, screenshot_url: str):
        """
        Add screenshot to a step.

        Args:
            step_id: Step ID to update
            screenshot_url: URL of the screenshot
        """
        with self.lock:
            step = self.get_step(step_id)
            if not step:
                logger.warning(f"Step {step_id} not found")
                return

            step.add_screenshot(screenshot_url)
            self._notify_update("screenshot_added", f"Added screenshot to step: {step.name}")

    def add_step(self, step: FilingStep):
        """
        Add a new step.

        Args:
            step: Step to add
        """
        with self.lock:
            # Check if this is a top-level step or a substep
            if step.parent_id:
                parent_step = self.get_step(step.parent_id)
                if parent_step:
                    parent_step.add_substep(step)
                else:
                    logger.warning(f"Parent step {step.parent_id} not found")
                    self.steps.append(step)
            else:
                self.steps.append(step)

            self.total_steps = len(self.steps)
            self._update_overall_progress()
            self._notify_update("step_added", f"Added step: {step.name}")

    def register_update_callback(self, callback: Callable[[str, Dict[str, Any], str], None]):
        """
        Register a callback for updates.

        Args:
            callback: Function to call on updates (event_type, tracker_dict, message)
        """
        self.update_callbacks.append(callback)

    def _update_overall_progress(self):
        """Update overall progress based on step statuses."""
        total_steps = len(self.steps)
        if total_steps == 0:
            self.overall_progress_pct = 0
            return

        # Calculate weighted progress
        total_weight = sum(step.estimated_time for step in self.steps)
        if total_weight == 0:
            total_weight = total_steps  # Fallback to equal weights

        weighted_progress = 0
        for step in self.steps:
            if step.status == "completed":
                weighted_progress += step.estimated_time
            elif step.status == "in_progress":
                weighted_progress += (step.progress_pct / 100.0) * step.estimated_time
            # Pending and failed steps don't contribute to progress

        self.overall_progress_pct = int((weighted_progress / total_weight) * 100)

    def _notify_update(self, event_type: str, message: str = ""):
        """
        Notify all registered callbacks of an update.

        Args:
            event_type: Type of event
            message: Optional message
        """
        tracker_dict = self.to_dict()

        for callback in self.update_callbacks:
            try:
                callback(event_type, tracker_dict, message)
            except Exception as e:
                logger.error(f"Error in progress tracker callback: {str(e)}")


# Singleton tracker registry for global access
class ProgressTrackerRegistry:
    """
    Registry of progress trackers.

    This is a singleton class that provides global access to progress trackers
    for all active filings.
    """

    _instance = None

    def __new__(cls):
        """Ensure singleton pattern."""
        if cls._instance is None:
            cls._instance = super(ProgressTrackerRegistry, cls).__new__(cls)
            cls._instance.trackers = {}
            cls._instance.lock = threading.Lock()
        return cls._instance

    def get_tracker(self, filing_id: str) -> Optional[ProgressTracker]:
        """
        Get tracker for a filing ID.

        Args:
            filing_id: Filing ID

        Returns:
            Progress tracker or None if not found
        """
        with self.lock:
            return self.trackers.get(filing_id)

    def create_tracker(self, filing_id: str, total_steps: int = 10) -> ProgressTracker:
        """
        Create a new tracker.

        Args:
            filing_id: Filing ID
            total_steps: Total number of steps

        Returns:
            New progress tracker
        """
        with self.lock:
            if filing_id in self.trackers:
                return self.trackers[filing_id]

            tracker = ProgressTracker(filing_id, total_steps)
            self.trackers[filing_id] = tracker
            return tracker

    def remove_tracker(self, filing_id: str):
        """
        Remove a tracker.

        Args:
            filing_id: Filing ID to remove
        """
        with self.lock:
            if filing_id in self.trackers:
                del self.trackers[filing_id]

    def get_all_trackers(self) -> Dict[str, ProgressTracker]:
        """
        Get all trackers.

        Returns:
            Dictionary of all trackers
        """
        with self.lock:
            return self.trackers.copy()