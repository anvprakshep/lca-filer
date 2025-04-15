# utils/file_utils.py
import os
import csv
import json
import time
import pandas as pd
import re
from typing import Dict, Any, List, Optional, Union

from utils.logger import get_logger

logger = get_logger(__name__)


class FileUtils:
    """Utilities for file operations."""

    @staticmethod
    def load_applications_from_csv(file_path: str) -> List[Dict[str, Any]]:
        """
        Load LCA application data from a CSV file.

        Args:
            file_path: Path to CSV file

        Returns:
            List of application data dictionaries
        """
        try:
            if not os.path.exists(file_path):
                logger.error(f"CSV file not found: {file_path}")
                return []

            # Check if this is a regular CSV or a special multi-worksite format
            is_multi_worksite = FileUtils._check_if_multi_worksite_format(file_path)

            if is_multi_worksite:
                return FileUtils._load_multi_worksite_applications(file_path)
            else:
                # Load CSV into DataFrame for standard format
                df = pd.read_csv(file_path)

                # Convert DataFrame to list of dictionaries
                applications = []

                for _, row in df.iterrows():
                    # Handle each row
                    app_data = FileUtils._process_csv_row(row)
                    if app_data:
                        applications.append(app_data)

                logger.info(f"Loaded {len(applications)} applications from {file_path}")
                return applications

        except Exception as e:
            logger.error(f"Error loading applications from CSV: {str(e)}")
            return []

    @staticmethod
    def _check_if_multi_worksite_format(file_path: str) -> bool:
        """
        Check if CSV is in multi-worksite format.

        Args:
            file_path: Path to CSV file

        Returns:
            True if multi-worksite format, False otherwise
        """
        try:
            # Read the header row
            with open(file_path, 'r') as f:
                reader = csv.reader(f)
                headers = next(reader)

            # Check for multi-worksite columns
            worksite_pattern = re.compile(r'Worksite_\d+_')
            for header in headers:
                if worksite_pattern.match(header):
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking CSV format: {str(e)}")
            return False

    @staticmethod
    def _load_multi_worksite_applications(file_path: str) -> List[Dict[str, Any]]:
        """
        Load applications from CSV with multiple worksite format.

        Args:
            file_path: Path to CSV file

        Returns:
            List of application data dictionaries
        """
        try:
            # Load CSV into DataFrame
            df = pd.read_csv(file_path)

            # Convert DataFrame to list of dictionaries
            applications = []

            for _, row in df.iterrows():
                app_data = FileUtils._process_multi_worksite_row(row)
                if app_data:
                    applications.append(app_data)

            logger.info(f"Loaded {len(applications)} multi-worksite applications from {file_path}")
            return applications

        except Exception as e:
            logger.error(f"Error loading multi-worksite applications: {str(e)}")
            return []

    @staticmethod
    def _process_csv_row(row: pd.Series) -> Optional[Dict[str, Any]]:
        """
        Process a CSV row into an application data dictionary.

        Args:
            row: Pandas Series representing a CSV row

        Returns:
            Application data dictionary or None if invalid
        """
        try:
            # Generate a unique application ID
            app_id = str(row.get("Application_ID", f"app_{int(time.time())}_{id(row)}"))

            # Create basic structure
            app_data = {
                "id": app_id,
                "employer": {},
                "job": {},
                "wages": {},
                "worksite": {},  # Primary worksite
                "additional_worksites": [],  # For multiple worksites
                "foreign_worker": {}
            }

            # Map employer fields
            employer_field_mapping = {
                "Employer_Name": "name",
                "Employer_FEIN": "fein",
                "NAICS_Code": "naics",
                "Employer_Address": "address",
                "Employer_City": "city",
                "Employer_State": "state",
                "Employer_Zip": "zip",
                "Employer_Phone": "phone",
                "Employer_Email": "email"
            }

            for csv_field, app_field in employer_field_mapping.items():
                if csv_field in row.index and not pd.isna(row[csv_field]):
                    app_data["employer"][app_field] = row[csv_field]

            # Map job fields
            job_field_mapping = {
                "Job_Title": "title",
                "SOC_Code": "soc_code",
                "Job_Duties": "duties",
                "Job_Requirements": "requirements",
                "Education_Level": "education_level",
                "Experience_Required": "experience_required"
            }

            for csv_field, app_field in job_field_mapping.items():
                if csv_field in row.index and not pd.isna(row[csv_field]):
                    app_data["job"][app_field] = row[csv_field]

            # Map wage fields
            wage_field_mapping = {
                "Wage_Rate": "rate",
                "Wage_Rate_Type": "rate_type",
                "Prevailing_Wage": "prevailing_wage",
                "PW_Source": "pw_source",
                "PW_Year": "pw_year"
            }

            for csv_field, app_field in wage_field_mapping.items():
                if csv_field in row.index and not pd.isna(row[csv_field]):
                    app_data["wages"][app_field] = row[csv_field]

            # Map primary worksite fields
            worksite_field_mapping = {
                "Worksite_Address": "address",
                "Worksite_Address2": "address2",
                "Worksite_City": "city",
                "Worksite_State": "state",
                "Worksite_Zip": "zip",
                "Worksite_County": "county"
            }

            for csv_field, app_field in worksite_field_mapping.items():
                if csv_field in row.index and not pd.isna(row[csv_field]):
                    app_data["worksite"][app_field] = row[csv_field]

            # Check for additional worksite columns in standard format
            additional_worksite_pattern = re.compile(r'Additional_Worksite_(\d+)_(.+)')
            additional_worksites = {}

            for col in row.index:
                match = additional_worksite_pattern.match(col)
                if match and not pd.isna(row[col]):
                    worksite_num = int(match.group(1))
                    field_name = match.group(2).lower()

                    if worksite_num not in additional_worksites:
                        additional_worksites[worksite_num] = {}

                    additional_worksites[worksite_num][field_name] = row[col]

            # Add any additional worksites found
            for _, worksite in sorted(additional_worksites.items()):
                if worksite:  # Only add if there's data
                    app_data["additional_worksites"].append(worksite)

            # Map foreign worker fields
            worker_field_mapping = {
                "Worker_Name": "name",
                "Birth_Country": "birth_country",
                "Citizenship": "citizenship",
                "Education": "education"
            }

            for csv_field, app_field in worker_field_mapping.items():
                if csv_field in row.index and not pd.isna(row[csv_field]):
                    app_data["foreign_worker"][app_field] = row[csv_field]

            # Add attorney information if available
            if "Attorney_Name" in row.index and not pd.isna(row["Attorney_Name"]):
                app_data["attorney"] = {
                    "name": row["Attorney_Name"]
                }

                # Add other attorney fields if available
                attorney_field_mapping = {
                    "Attorney_Firm": "firm",
                    "Attorney_Bar_Number": "bar_number",
                    "Attorney_Address": "address",
                    "Attorney_City": "city",
                    "Attorney_State": "state",
                    "Attorney_Zip": "zip",
                    "Attorney_Phone": "phone",
                    "Attorney_Email": "email"
                }

                for csv_field, app_field in attorney_field_mapping.items():
                    if csv_field in row.index and not pd.isna(row[csv_field]):
                        app_data["attorney"][app_field] = row[csv_field]

            # Set multiple_worksites flag
            if app_data["additional_worksites"]:
                app_data["multiple_worksites"] = True
            else:
                app_data["multiple_worksites"] = False

            return app_data

        except Exception as e:
            logger.error(f"Error processing CSV row: {str(e)}")
            return None

    @staticmethod
    def _process_multi_worksite_row(row: pd.Series) -> Optional[Dict[str, Any]]:
        """
        Process a CSV row with specialized multi-worksite format.

        Args:
            row: Pandas Series representing a CSV row

        Returns:
            Application data dictionary or None if invalid
        """
        try:
            # First process the standard fields
            app_data = FileUtils._process_csv_row(row)
            if not app_data:
                return None

            # Now process specialized worksite columns
            worksite_pattern = re.compile(r'Worksite_(\d+)_(.+)')
            worksites = {}

            # Find all worksite columns
            for col in row.index:
                match = worksite_pattern.match(col)
                if match and not pd.isna(row[col]):
                    worksite_num = int(match.group(1))
                    field_name = match.group(2).lower()

                    if worksite_num not in worksites:
                        worksites[worksite_num] = {}

                    worksites[worksite_num][field_name] = row[col]

            # Primary worksite is worksite_1
            if 1 in worksites:
                app_data["worksite"] = worksites[1]
                del worksites[1]

            # Add remaining worksites as additional
            app_data["additional_worksites"] = []
            for _, worksite in sorted(worksites.items()):
                if worksite:  # Only add if there's data
                    app_data["additional_worksites"].append(worksite)

            # Update multiple_worksites flag
            if app_data["additional_worksites"]:
                app_data["multiple_worksites"] = True
            else:
                app_data["multiple_worksites"] = False

            return app_data

        except Exception as e:
            logger.error(f"Error processing multi-worksite row: {str(e)}")
            return None

    @staticmethod
    def create_sample_csv(output_path: str, include_multiple_worksites: bool = True) -> bool:
        """
        Create a sample CSV file with H-1B application data for testing.

        Args:
            output_path: Path to save the sample CSV
            include_multiple_worksites: Whether to include multiple worksite examples

        Returns:
            True if successful, False otherwise
        """
        try:
            # Base sample data
            sample_data = {
                "Application_ID": [1001, 1002, 1003],
                "Employer_Name": ["Tech Solutions Inc.", "Data Systems LLC", "Global Innovators Corp"],
                "Employer_FEIN": ["123456789", "987654321", "456789123"],
                "NAICS_Code": ["541512", "541511", "541513"],
                "Employer_Address": ["123 Main St", "456 Tech Blvd", "789 Innovation Way"],
                "Employer_City": ["San Francisco", "Austin", "Boston"],
                "Employer_State": ["CA", "TX", "MA"],
                "Employer_Zip": ["94105", "78701", "02110"],
                "Employer_Phone": ["4155551234", "5125554321", "6175559876"],
                "Employer_Email": ["hr@techsolutions.com", "hr@datasystems.com", "hr@globalinnovators.com"],

                "Job_Title": ["Software Engineer", "Data Scientist", "DevOps Engineer"],
                "SOC_Code": ["15-1132", "15-2051", "15-1133"],
                "Job_Duties": [
                    "Design and develop software applications...",
                    "Analyze large datasets to identify patterns...",
                    "Implement CI/CD pipelines and manage cloud infrastructure..."
                ],
                "Job_Requirements": [
                    "Bachelor's degree in Computer Science or related field...",
                    "Master's degree in Statistics, Computer Science or related field...",
                    "Bachelor's degree in Computer Science with 3+ years experience..."
                ],
                "Education_Level": ["Bachelor's", "Master's", "Bachelor's"],
                "Experience_Required": ["2 years", "3 years", "3 years"],

                "Wage_Rate": [120000, 130000, 125000],
                "Wage_Rate_Type": ["year", "year", "year"],
                "Prevailing_Wage": [110000, 120000, 115000],
                "PW_Source": ["OES", "OES", "OES"],
                "PW_Year": [2023, 2023, 2023],

                "Worksite_Address": ["456 Market St", "789 Congress Ave", "101 Federal St"],
                "Worksite_Address2": ["Suite 400", "Floor 5", ""],
                "Worksite_City": ["San Francisco", "Austin", "Boston"],
                "Worksite_State": ["CA", "TX", "MA"],
                "Worksite_Zip": ["94105", "78701", "02110"],
                "Worksite_County": ["San Francisco", "Travis", "Suffolk"],

                "Worker_Name": ["John Smith", "Priya Patel", "Wei Chen"],
                "Birth_Country": ["India", "India", "China"],
                "Citizenship": ["India", "India", "China"],
                "Education": ["Master's Degree", "PhD", "Master's Degree"],

                "Attorney_Name": ["Jane Lawyer", "Robert Attorney", "Lisa Counsel"],
                "Attorney_Firm": ["Immigration Law Group", "Legal Advisors LLC", "Global Immigration Partners"],
                "Attorney_Bar_Number": ["123456", "789012", "345678"],
                "Attorney_Address": ["789 Legal Ave", "456 Law St", "123 Counsel Blvd"],
                "Attorney_City": ["New York", "Chicago", "Los Angeles"],
                "Attorney_State": ["NY", "IL", "CA"],
                "Attorney_Zip": ["10001", "60601", "90001"],
                "Attorney_Phone": ["2125551234", "3125554321", "2135559876"],
                "Attorney_Email": ["jane@lawgroup.com", "robert@legaladvisors.com", "lisa@gip.com"]
            }

            # Add multiple worksite fields if requested
            if include_multiple_worksites:
                # Additional worksite for first application
                sample_data["Additional_Worksite_1_Address"] = ["123 Second St", "", ""]
                sample_data["Additional_Worksite_1_City"] = ["San Jose", "", ""]
                sample_data["Additional_Worksite_1_State"] = ["CA", "", ""]
                sample_data["Additional_Worksite_1_Zip"] = ["95113", "", ""]
                sample_data["Additional_Worksite_1_County"] = ["Santa Clara", "", ""]

                # Second additional worksite for first application
                sample_data["Additional_Worksite_2_Address"] = ["789 Third St", "", ""]
                sample_data["Additional_Worksite_2_City"] = ["Palo Alto", "", ""]
                sample_data["Additional_Worksite_2_State"] = ["CA", "", ""]
                sample_data["Additional_Worksite_2_Zip"] = ["94301", "", ""]
                sample_data["Additional_Worksite_2_County"] = ["Santa Clara", "", ""]

                # Additional worksite for second application
                sample_data["Additional_Worksite_1_Address"][1] = "555 Second Blvd"
                sample_data["Additional_Worksite_1_City"][1] = "Dallas"
                sample_data["Additional_Worksite_1_State"][1] = "TX"
                sample_data["Additional_Worksite_1_Zip"][1] = "75201"
                sample_data["Additional_Worksite_1_County"][1] = "Dallas"

            # Create DataFrame
            df = pd.DataFrame(sample_data)

            # Save to CSV
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
            df.to_csv(output_path, index=False)

            logger.info(f"Created sample CSV at {output_path}")
            return True

        except Exception as e:
            logger.error(f"Error creating sample CSV: {str(e)}")
            return False

    @staticmethod
    def load_json(file_path: str) -> Optional[Dict[str, Any]]:
        """
        Load JSON data from a file.

        Args:
            file_path: Path to JSON file

        Returns:
            Loaded JSON data or None if failed
        """
        try:
            if not os.path.exists(file_path):
                logger.error(f"JSON file not found: {file_path}")
                return None

            with open(file_path, "r") as f:
                data = json.load(f)

            return data

        except Exception as e:
            logger.error(f"Error loading JSON file: {str(e)}")
            return None

    @staticmethod
    def save_json(data: Dict[str, Any], file_path: str) -> bool:
        """
        Save data to a JSON file.

        Args:
            data: Data to save
            file_path: Path to save the file

        Returns:
            True if successful, False otherwise
        """
        try:
            # Create directory if it doesn't exist
            directory = os.path.dirname(file_path)
            if directory:
                os.makedirs(directory, exist_ok=True)

            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)

            logger.info(f"Data saved to {file_path}")
            return True

        except Exception as e:
            logger.error(f"Error saving JSON file: {str(e)}")
            return False