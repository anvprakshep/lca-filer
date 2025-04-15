# lca_filer.py
import asyncio
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import os

from config.config import Config
from core.browser_manager import BrowserManager
from core.navigation import Navigation
from core.form_filler import FormFiller
from core.error_handler import ErrorHandler
from ai.llm_client import LLMClient
from ai.data_validator import DataValidator
from ai.decision_maker import DecisionMaker
from utils.logger import get_logger
from utils.reporting import Reporter
from utils.authenticator import TwoFactorAuth
from config.form_structure import FormStructure

logger = get_logger(__name__)


class LCAFiler:
    """Main class for LCA filing automation."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize LCA filer.

        Args:
            config_path: Path to configuration file
        """
        # Load configuration
        self.config = Config(config_path)

        # Initialize components
        self.browser_manager = BrowserManager(self.config.get("browser"))
        self.llm_client = LLMClient(self.config.get("openai"))
        self.data_validator = DataValidator(self.llm_client)
        self.decision_maker = DecisionMaker(self.llm_client)
        self.reporter = Reporter(self.config.get("output"))

        # Initialize two-factor authentication if enabled
        self.two_factor_auth = None
        if self.config.get("totp", "enabled", default=False):
            totp_config = self.config.get("totp", {})
            self.two_factor_auth = TwoFactorAuth(totp_config)
            logger.info(f"Two-factor authentication initialized with {len(totp_config.get('secrets', {}))} secrets")

        # Results storage
        self.results = []

    async def initialize(self) -> bool:
        """
        Initialize components.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Initialize browser
            await self.browser_manager.initialize()
            logger.info("LCAFiler initialized")
            return True
        except Exception as e:
            logger.error(f"Error initializing LCAFiler: {str(e)}")
            return False

    async def shutdown(self) -> None:
        """Clean up resources."""
        try:
            # Close browser
            await self.browser_manager.close()
            logger.info("LCAFiler shut down")
        except Exception as e:
            logger.error(f"Error shutting down LCAFiler: {str(e)}")

    async def process_batch(self, applications: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process a batch of LCA applications.

        Args:
            applications: List of application data dictionaries

        Returns:
            List of results
        """
        logger.info(f"Starting batch processing of {len(applications)} applications")

        # Initialize results
        self.results = []

        # Get max concurrent settings
        max_concurrent = self.config.get("processing", "max_concurrent", default=5)

        # Create semaphore for concurrent processing
        semaphore = asyncio.Semaphore(max_concurrent)

        # Create tasks
        tasks = []
        for app in applications:
            task = asyncio.create_task(self._process_with_semaphore(semaphore, app))
            tasks.append(task)

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                app_id = applications[i].get("id", f"app_{i}")
                logger.error(f"Application {app_id} failed with error: {str(result)}")
                processed_results.append({
                    "application_id": app_id,
                    "status": "error",
                    "error": str(result),
                    "timestamp": datetime.now().isoformat()
                })
            else:
                processed_results.append(result)

        # Store results
        self.results = processed_results

        # Generate reports
        self._generate_reports()

        logger.info(
            f"Batch processing completed. Success: {sum(1 for r in processed_results if r.get('status') == 'success')}, "
            f"Errors: {sum(1 for r in processed_results if r.get('status') == 'error')}")

        return processed_results

    async def _process_with_semaphore(self, semaphore: asyncio.Semaphore, application_data: Dict[str, Any]) -> Dict[
        str, Any]:
        """
        Process a single application with rate limiting.

        Args:
            semaphore: Asyncio semaphore for rate limiting
            application_data: Application data

        Returns:
            Result dictionary
        """
        async with semaphore:
            try:
                app_id = application_data.get("id", f"app_{int(time.time())}")
                logger.info(f"Processing application {app_id}")
                return await self.file_lca(application_data)
            except Exception as e:
                logger.error(f"Error processing application {app_id}: {str(e)}")
                raise

    async def file_lca(self, application_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        File a single LCA application.

        Args:
            application_data: Application data

        Returns:
            Result dictionary
        """
        app_id = application_data.get("id", f"app_{int(time.time())}")
        print("Filing LCA with ID {}".format(app_id))
        start_time = time.time()
        result = {
            "application_id": app_id,
            "status": "started",
            "timestamp": datetime.now().isoformat(),
            "steps_completed": []
        }

        # Check for TOTP secret in application data and configure it if needed
        await self._configure_totp_from_application(application_data)

        try:
            # Validate application data
            validated_data, validation_notes = await self.data_validator.validate(application_data)
            print("Validating application data")
            print("Validated Data: ", validated_data)
            print("Validated Data: ", validation_notes)
            if not validated_data:
                result["status"] = "validation_failed"
                result["error"] = validation_notes
                return result

            # result["validation_notes"] = validation_notes

            print("Result: {}".format(result))
            # Create a new page
            page = await self.browser_manager.new_page()

            # Initialize page-specific components
            print("Page opened")
            print("self.config", self.config.get('flag_portal'))
            print("Two Factor Authentication", self.two_factor_auth)
            navigation = Navigation(page, self.config.get("flag_portal"), self.two_factor_auth)
            print("Navigation opened")
            form_filler = FormFiller(page)
            print("FormFiller opened")
            error_handler = ErrorHandler(page, self.llm_client)

            # Navigate to FLAG portal
            if not await navigation.goto_flag_portal():
                result["status"] = "navigation_failed"
                result["error"] = "Failed to navigate to FLAG portal"
                return result

            result["steps_completed"].append("navigation")

            # Login with 2FA if needed
            print("Preparing Login")
            credentials = application_data.get("credentials", self.config.get("flag_portal", "credentials", default={}))

            # Check if the username has a TOTP secret configured
            username = credentials.get("username", "")
            if username and self.two_factor_auth and not self.config.has_totp_secret(username):
                logger.warning(f"No TOTP secret found for username: {username}")

                # Check if TOTP secret is provided in application data
                if "totp_secret" in application_data:
                    # Add the secret to the configuration
                    self.config.set_totp_secret(username, application_data["totp_secret"])
                    logger.info(f"Added TOTP secret for {username} from application data")
                else:
                    logger.warning(f"2FA is enabled but no TOTP secret provided for {username}")

            if not await navigation.login(credentials):
                result["status"] = "login_failed"
                result["error"] = "Failed to login to FLAG portal"
                return result

            result["steps_completed"].append("login")

            # Navigate to new LCA form
            if not await navigation.navigate_to_new_lca():
                result["status"] = "navigation_failed"
                result["error"] = "Failed to navigate to new LCA form"
                return result

            result["steps_completed"].append("new_lca_navigation")

            # Select H-1B form type
            if not await navigation.select_form_type("H-1B"):
                result["status"] = "form_selection_failed"
                result["error"] = "Failed to select H-1B form type"
                return result

            result["steps_completed"].append("form_type_selection")

            # Get AI decisions for the entire form
            lca_decision = await self.decision_maker.make_decisions(validated_data)

            # If human review is required, log the reasons
            if lca_decision.requires_human_review:
                result["requires_human_review"] = True
                result["review_reasons"] = lca_decision.review_reasons
                logger.warning(f"Application {app_id} requires human review: {', '.join(lca_decision.review_reasons)}")

            # Process each section of the form
            for section_obj in lca_decision.form_sections:
                section_name = section_obj.section_name
                decisions = section_obj.decisions

                # Find section definition
                section_def = next((s for s in FormStructure.get_h1b_structure()["sections"]
                                    if s["name"] == section_name), None)

                if not section_def:
                    logger.warning(f"Section definition not found for {section_name}")
                    continue

                logger.info(f"Processing section: {section_name} for application {app_id}")

                # Special handling for worksite section with multiple worksites
                if "worksite" in section_name.lower() and validated_data.get("multiple_worksites", False):
                    logger.info("Using special handling for multiple worksites section")
                    await form_filler.handle_worksite_section(validated_data)
                else:
                    # Fill the section normally
                    section_result = await form_filler.fill_section(section_def, decisions)

                # Check for errors
                errors = await error_handler.detect_errors()
                if errors:
                    # Try to fix errors
                    form_state = await form_filler.get_form_state()
                    fixed = await error_handler.fix_errors(errors, form_state)

                    if not fixed:
                        logger.warning(f"Could not fix all errors in section {section_name}")
                        # Continue anyway, might be able to proceed

                # Save and continue to next section
                if not await navigation.save_and_continue():
                    logger.warning(f"Error saving section {section_name}")
                    # Take screenshot for debugging
                    await self.browser_manager.take_screenshot(page, f"save_error_{section_name}")
                    # Try to continue anyway

                result["steps_completed"].append(f"section_{section_name}")

            # Submit the final form
            if not await navigation.submit_final():
                result["status"] = "submission_failed"
                result["error"] = "Failed to submit LCA form"
                return result

            result["steps_completed"].append("submission")

            # Get confirmation number
            confirmation_number = await navigation.get_confirmation_number()
            if confirmation_number:
                result["confirmation_number"] = confirmation_number
                result["status"] = "success"
                logger.info(
                    f"Successfully filed LCA for application {app_id}, confirmation number: {confirmation_number}")
            else:
                result["status"] = "confirmation_failed"
                result["error"] = "Failed to get confirmation number"

        except Exception as e:
            logger.error(f"Error filing LCA for application {app_id}: {str(e)}")
            result["status"] = "error"
            result["error"] = str(e)

        finally:
            # Calculate processing time
            result["processing_time"] = time.time() - start_time
            result["completion_timestamp"] = datetime.now().isoformat()

        return result

    async def _configure_totp_from_application(self, application_data: Dict[str, Any]) -> None:
        """
        Configure TOTP from application data if needed.

        Args:
            application_data: Application data
        """
        # Check for TOTP secret in credentials
        credentials = application_data.get("credentials", {})
        username = credentials.get("username")
        totp_secret = credentials.get("totp_secret")

        if username and totp_secret:
            # Initialize TOTP handler if not already
            if not self.two_factor_auth:
                totp_config = self.config.get("totp")
                # Make sure we have a 'secrets' dictionary even if it's empty
                if "secrets" not in totp_config:
                    totp_config["secrets"] = {}
                self.two_factor_auth = TwoFactorAuth(totp_config)
                logger.info("Two-factor authentication initialized")

            # Add or update the secret
            self.two_factor_auth.totp_secrets[username] = totp_secret
            self.config.set_totp_secret(username, totp_secret)
            logger.info(f"Configured TOTP secret for {username} from application data")

            # Test the secret
            if self.two_factor_auth:
                totp_code = self.two_factor_auth.generate_totp_code(username)
                if totp_code:
                    logger.info(f"Successfully generated TOTP code for {username}: {totp_code}")
                else:
                    logger.warning(f"Failed to generate TOTP code for {username}")

    def _generate_reports(self) -> None:
        """Generate reports from results."""
        try:
            if not self.results:
                logger.warning("No results to generate reports")
                return

            # Save results to JSON
            results_path = self.reporter.save_results(self.results)

            # Generate dashboard
            dashboard_path = self.reporter.generate_dashboard(self.results)

            # Generate statistics
            stats = self.reporter.generate_statistics(self.results)

            logger.info("Reports generated successfully")

        except Exception as e:
            logger.error(f"Error generating reports: {str(e)}")

    def setup_totp(self, username: str, totp_secret: Optional[str] = None) -> Dict[str, Any]:
        """
        Set up TOTP for a user. If no secret is provided, a new one will be generated.

        Args:
            username: Username to set up TOTP for
            totp_secret: Optional TOTP secret to use

        Returns:
            Dictionary with setup information
        """
        # Initialize TOTP handler if not already
        if not self.two_factor_auth:
            totp_config = self.config.get("totp", {})
            if "secrets" not in totp_config:
                totp_config["secrets"] = {}
            self.two_factor_auth = TwoFactorAuth(totp_config)

        # Use provided secret or the one from DOL
        if not totp_secret:
            totp_secret = self.config.get_totp_secret(username)
            if not totp_secret:
                logger.error(f"No TOTP secret provided or found for {username}")
                return {
                    "username": username,
                    "status": "error",
                    "error": "No TOTP secret provided"
                }

        # Add to configuration and TOTP handler
        self.config.set_totp_secret(username, totp_secret)
        self.two_factor_auth.totp_secrets[username] = totp_secret

        # Test the secret
        test_result = self.two_factor_auth.test_secret(totp_secret)

        if test_result.get("valid", False):
            logger.info(f"TOTP setup successful for {username}")
            return {
                "username": username,
                "status": "success",
                "secret": totp_secret,
                "current_code": test_result.get("current_code"),
                "remaining_seconds": test_result.get("remaining_seconds")
            }
        else:
            logger.error(f"TOTP setup failed for {username}: {test_result.get('error')}")
            return {
                "username": username,
                "status": "error",
                "error": test_result.get("error", "Invalid TOTP secret")
            }

    def get_current_totp_code(self, username: str) -> Optional[str]:
        """
        Get the current TOTP code for a username.

        Args:
            username: Username to get code for

        Returns:
            Current TOTP code or None if not available
        """
        if not self.two_factor_auth:
            # Check if we have a TOTP secret for this username
            totp_secret = self.config.get_totp_secret(username)
            if totp_secret:
                # Initialize TOTP handler on demand
                totp_config = self.config.get("totp", {})
                if "secrets" not in totp_config:
                    totp_config["secrets"] = {}
                totp_config["secrets"][username] = totp_secret
                self.two_factor_auth = TwoFactorAuth(totp_config)
                logger.info("Initialized two-factor authentication on demand")
            else:
                logger.error("TOTP is not enabled and no secret is available")
                return None

        return self.two_factor_auth.generate_totp_code(username)