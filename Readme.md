# H-1B LCA Filing Automation System - Technical Documentation

## Table of Contents

- [System Overview](#system-overview)
- [Architecture](#architecture)
- [Module Descriptions](#module-descriptions)
- [Key Features](#key-features)
- [Installation and Setup](#installation-and-setup)
- [Configuration](#configuration)
- [Usage Guide](#usage-guide)
- [Web Interface](#web-interface)
- [Workflow](#workflow)
- [Technical Implementation Details](#technical-implementation-details)
- [Customization](#customization)
- [Error Handling and Recovery](#error-handling-and-recovery)
- [AI Capabilities](#ai-capabilities)
- [Security Considerations](#security-considerations)
- [Performance Optimization](#performance-optimization)
- [Troubleshooting](#troubleshooting)
- [Future Improvements](#future-improvements)

## System Overview

The H-1B LCA Filing Automation System is a comprehensive solution designed to automate the process of filing Labor Condition Applications (LCAs) on the Department of Labor's FLAG portal. The system combines headless browser automation with AI decision-making capabilities to provide a scalable, reliable solution for high-volume LCA filings.

The system implements a "human-in-the-loop" approach, where automation handles most of the form filling, but human intervention is requested when critical decisions are needed or when form validation issues arise that cannot be resolved automatically.

### Key Features

- **Automated Form Filling**: Navigates and completes the entire LCA form process
- **AI-Powered Decision Making**: Uses AI to make intelligent choices when filling forms
- **Error Detection and Recovery**: Identifies and fixes form errors automatically
- **Human-in-the-Loop Interaction**: Requests human input for critical fields or validation issues
- **Concurrent Processing**: Handles multiple applications simultaneously
- **Web Interface**: Provides user-friendly dashboard and interactive controls
- **Comprehensive Reporting**: Generates detailed dashboards and statistics
- **Headless Operation**: Runs without a visual display for server deployment
- **Two-Factor Authentication Support**: Handles TOTP authentication for FLAG portal

## Architecture

The system follows a modular, component-based architecture with clear separation of concerns. It is organized into the following main components:

### High-Level Components

1. **Configuration Management**: Handles system settings and credentials
2. **Browser Automation**: Controls browser interactions and form navigation
3. **AI Decision Engine**: Makes intelligent form-filling decisions
4. **Error Management**: Detects and resolves errors during filing
5. **Interactive Processing**: Manages human interaction when needed
6. **Reporting System**: Tracks results and generates reports
7. **Web Interface**: Provides Flask-based web interface for interaction and monitoring

### Technology Stack

- **Python 3.8+**: Core programming language
- **Playwright**: Browser automation framework for headless operation
- **OpenAI GPT-4**: AI model for decision making via the OpenAI API
- **Flask**: Web framework for the user interface
- **Pandas/Matplotlib**: Data analysis and visualization for reporting
- **pyotp**: Two-factor authentication support

## Module Descriptions

### Config Module

Located in the `config/` directory, this module handles all configuration aspects:

- **config.py**: Central configuration manager that loads settings from files and environment variables
- **selectors.py**: Contains DOM selectors for FLAG portal elements
- **form_structure.py**: Defines the structure of the LCA form

### Core Module

Located in the `core/` directory, these components handle browser automation:

- **browser_manager.py**: Manages browser instances and contexts
- **navigation.py**: Handles navigation within the FLAG portal
- **form_filler.py**: Fills form fields with appropriate values
- **error_handler.py**: Detects and fixes form errors

### AI Module

Located in the `ai/` directory, these components provide intelligent decision-making:

- **llm_client.py**: Client for interacting with language models
- **data_validator.py**: Validates application data before submission
- **decision_maker.py**: Makes form-filling decisions
- **models.py**: Pydantic models for structured AI responses

### Utils Module

Located in the `utils/` directory, these utilities support the main functionality:

- **logger.py**: Configures logging throughout the system
- **captcha_solver.py**: Solves CAPTCHAs using external services
- **reporting.py**: Generates dashboards and statistics
- **file_utils.py**: Handles file operations for CSV and JSON data
- **form_capture.py**: Dynamically captures form structure from FLAG portal
- **interactive_filer.py**: Manages interactive filing with human input
- **screenshot_manager.py**: Captures and manages screenshots for debugging
- **authenticator.py**: Handles two-factor authentication

### Web Interface Module

Located in the `templates/` and app-related files:

- **app.py**: Flask application that serves the web interface
- **templates/**: HTML templates for the web interface
- **static/**: Static assets (CSS, JavaScript, images)

### Main Components

- **lca_filer.py**: Main class that orchestrates the entire filing process
- **main.py**: Entry point for the command-line interface
- **app.py**: Entry point for the web application

## Key Features

### Automated Form Filling
The system navigates the entire FLAG portal LCA submission process:
- Logs in to FLAG portal (with 2FA support)
- Selects H-1B form type
- Intelligently fills all form sections
- Handles validation errors
- Submits the form and captures confirmation numbers

### AI-Powered Decision Making
The system uses OpenAI GPT-4 to:
- Validate application data before submission
- Make intelligent decisions about form fields
- Resolve validation errors and suggest fixes
- Handle complex conditional logic

### Error Detection and Recovery
Robust error handling includes:
- Automatic detection of validation errors
- AI-powered suggestions for resolving errors
- Session recovery and retry mechanisms
- Detailed logging and screenshots for troubleshooting

### Human-in-the-Loop Interaction
The system identifies situations where human judgment is required:
- Form fields that require special attention
- Error situations that cannot be resolved automatically
- Web interface for human interaction
- Seamless continuation after human input

### Two-Factor Authentication Support
The system supports DOL's two-factor authentication:
- TOTP (Time-based One-Time Password) generation
- Secret key management
- Secure authentication handling

### Batch Processing
Support for processing multiple applications:
- CSV file upload for batch applications
- Configurable concurrent processing
- Dashboard for monitoring progress
- Comprehensive reporting

## Installation and Setup

### System Requirements

- Python 3.8 or higher
- 4GB RAM minimum (8GB recommended)
- Internet connection

### Installation Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/lca-filing-automation.git
   cd lca-filing-automation
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Install Playwright browsers:
   ```bash
   playwright install chromium
   ```

5. Create configuration file:
   ```bash
   cp config-sample.json config.json
   # Edit config.json with your settings
   ```

## Configuration

The system uses a hierarchical configuration system with the following priority (highest to lowest):

1. Command-line arguments
2. Environment variables
3. Configuration file
4. Default values

### Configuration File Format

The configuration file uses JSON format with the following structure:

```json
{
  "openai": {
    "api_key": "your-openai-api-key",
    "model": "gpt-4",
    "temperature": 0.1
  },
  "browser": {
    "headless": true,
    "user_agent": "Mozilla/5.0...",
    "viewport": {
      "width": 1280,
      "height": 800
    },
    "timeout": 60000
  },
  "flag_portal": {
    "url": "https://flag.dol.gov/",
    "credentials": {
      "username": "your-username",
      "password": "your-password"
    }
  },
  "processing": {
    "max_concurrent": 5,
    "max_retries": 3,
    "retry_delay": 5
  },
  "captcha": {
    "service": "2captcha",
    "api_key": "your-captcha-service-key"
  },
  "totp": {
    "enabled": true,
    "secrets": {
      "username@example.com": "TOTP_SECRET_KEY"
    },
    "issuer": "LCA_Automation"
  },
  "output": {
    "results_dir": "data/results",
    "log_dir": "logs"
  }
}
```

### Environment Variables

You can use the following environment variables to override configuration:

- `OPENAI_API_KEY`: OpenAI API key
- `OPENAI_MODEL`: OpenAI model name
- `BROWSER_HEADLESS`: Whether to run browsers in headless mode
- `FLAG_URL`: FLAG portal URL
- `FLAG_USERNAME`: FLAG portal username
- `FLAG_PASSWORD`: FLAG portal password
- `MAX_CONCURRENT`: Maximum concurrent applications to process
- `CAPTCHA_SERVICE`: CAPTCHA service to use
- `CAPTCHA_API_KEY`: CAPTCHA service API key
- `TOTP_ENABLED`: Enable TOTP authentication
- `TOTP_SECRET`: Default TOTP secret
- `RESULTS_DIR`: Directory for storing results
- `LOG_DIR`: Directory for storing logs

## Usage Guide

### Command-Line Interface

#### Basic Usage

To run the automation with a CSV file containing application data:

```bash
python main.py --config=config.json --input=applications.csv
```

#### Creating a Sample CSV

To generate a sample CSV file with test data:

```bash
python main.py --sample --sample-output=sample_applications.csv
```

#### Processing a Subset of Applications

To process only a specific number of applications:

```bash
python main.py --input=applications.csv --batch-size=10
```

### Web Interface

To start the web interface:

```bash
python app.py
```

This will start a Flask server on port 5000 (default). Access the web interface at http://localhost:5000.

### CSV File Format

The input CSV file should contain the following columns:

- `Application_ID`: Unique identifier for the application
- `Employer_Name`, `Employer_FEIN`, etc.: Employer information
- `Job_Title`, `SOC_Code`, etc.: Job information
- `Wage_Rate`, `Wage_Rate_Type`, etc.: Wage information
- `Worksite_Address`, `Worksite_City`, etc.: Worksite information
- `Worker_Name`, `Birth_Country`, etc.: Foreign worker information
- `Attorney_Name`, `Attorney_Firm`, etc.: Attorney information (optional)
- `Additional_Worksite_*`: Additional worksite information (optional)

See the generated sample CSV for a complete example.

## Web Interface

The web interface provides a user-friendly way to interact with the automation system. Key features include:

### Dashboard

- Overview of active and completed filings
- Real-time status updates
- Success/failure statistics

### New Filing Form

- Form to enter application details manually
- Option to set interactive mode
- TOTP configuration for two-factor authentication

### Batch Processing

- CSV file upload for multiple applications
- Batch processing options
- Concurrent processing configuration

### Filing Status

- Detailed status view for each filing
- Progress tracking with section information
- Screenshots captured during the process

### Human Interaction

- Interface for providing input when required
- Form display with validation errors
- Continuation after input submission

## Workflow

The typical workflow for an LCA filing follows these steps:

1. **Initialization**:
   - Load configuration
   - Initialize browser and AI components

2. **Authentication**:
   - Navigate to FLAG portal
   - Handle login with username/password
   - Process two-factor authentication if needed

3. **Form Selection**:
   - Navigate to new LCA form
   - Select H-1B visa type

4. **AI Decision Making**:
   - Generate form-filling decisions for all sections
   - Mark fields requiring human review

5. **Form Filling**:
   - Process each form section sequentially
   - Fill fields based on AI decisions
   - Validate field values and handle errors
   - Request human input when needed

6. **Submission**:
   - Review completed form
   - Submit the form
   - Capture confirmation number

7. **Reporting**:
   - Generate completion report
   - Save results and statistics
   - Update dashboard

## Technical Implementation Details

### Browser Automation

Browser automation is implemented using Playwright, which provides cross-browser support and powerful selectors. The `BrowserManager` class handles browser lifecycle, with key methods:

```python
async def initialize(self) -> bool
async def new_page(self) -> Page
async def find_element(self, page: Page, selector: str, timeout: int = 5000, state: str = "visible") -> Any
async def click_element(self, page: Page, selector: str, timeout: int = 5000, force: bool = False, retry_count: int = 1) -> None
async def fill_element(self, page: Page, selector: str, value: str, timeout: int = 5000, retry_count: int = 1) -> None
```

The system supports both CSS and XPath selectors for maximum flexibility in locating elements.

### AI Decision Making

The AI decision-making process involves:

1. Validating application data using `DataValidator`
2. Making field decisions using `DecisionMaker`
3. Applying decisions to the form using `FormFiller`
4. Detecting and fixing errors using `ErrorHandler`

The decision-making process can be summarized as:

```python
# Validate data
validated_data, validation_notes = await self.data_validator.validate(application_data)

# Generate decisions
lca_decision = await self.decision_maker.make_decisions(validated_data)

# For each section
for section_obj in lca_decision.form_sections:
    section_name = section_obj.section_name
    decisions = section_obj.decisions
    
    # Fill section with decisions
    await form_filler.fill_section(section_def, decisions)
    
    # Check for errors
    errors = await error_handler.detect_errors()
    if errors:
        await error_handler.fix_errors(errors, form_state)
    
    # Save and continue
    await navigation.save_and_continue()
```

### Human Interaction

Human interaction is implemented through the `InteractiveFiler` class:

1. The system detects when interaction is needed using `FormCapture.detect_interaction_required()`
2. It calls an interaction callback with field information
3. The web interface displays the fields requiring input
4. The user provides the necessary input
5. The system applies the input and continues processing

```python
# Check if interaction is needed
interaction_needed = await self.form_capture.detect_interaction_required()
if interaction_needed:
    # Pause filing
    self.filing_paused = True
    self.pending_interaction = interaction_needed
    
    # Clear previous event
    self.interaction_completed.clear()
    
    # Call callback
    self.interaction_callback(filing_id, interaction_needed)
    
    # Wait for response
    await self.interaction_completed.wait()
    
    # Apply interaction results
    interaction_result = self.interaction_results[filing_id]
    await self._apply_interaction_results(page, form_filler, interaction_result)
```

### Two-Factor Authentication

Two-factor authentication is handled by the `TwoFactorAuth` class:

1. The system stores TOTP secrets for FLAG portal users
2. It generates TOTP codes when needed during login
3. It verifies secrets and provides diagnostics for troubleshooting

```python
# Generate TOTP code
totp_code = self.two_factor_auth.generate_totp_code(username)

# Fill TOTP code
await totp_input.fill(totp_code)
```

### Form Capturing

The system can dynamically capture form structure from the FLAG portal using the `FormCapture` class:

1. It analyzes the current form section to identify fields
2. It extracts field attributes including type, label, and options
3. It records the structure for future reference
4. It identifies fields that may require human interaction

## Customization

### Adding New Form Fields

To add support for new form fields:

1. Update the form structure in `config/form_structure.py`
2. Add selectors for the fields in `config/selectors.py`
3. Ensure the CSV import in `utils/file_utils.py` maps the new fields

### Modifying AI Prompts

To customize the AI decision-making:

1. Edit the prompt templates in `ai/llm_client.py`
2. Adjust confidence thresholds in `ai/decision_maker.py`

### Supporting Different LCA Types

To support other LCA types besides H-1B:

1. Add the new form structure in `config/form_structure.py`
2. Update `core/navigation.py` to select the appropriate form type
3. Modify `ai/decision_maker.py` to handle the different form structure

## Error Handling and Recovery

The system implements multiple levels of error handling:

1. **Form Validation Errors**: Detected and fixed automatically using AI suggestions
2. **Navigation Errors**: Retry logic for intermittent issues
3. **System Errors**: Handled with screenshots and detailed logging
4. **CAPTCHA Challenges**: Solved using external services
5. **Session Timeouts**: Automatically detected and handled
6. **Human Intervention**: Requested when automated fixes fail

### Error Recovery Process

When an error is detected during form filling:

1. The system captures the current form state
2. Errors are detected and classified
3. The AI suggests fixes based on error messages and current values
4. Fixes are applied and validated
5. If errors persist, human intervention is requested through the web interface

## AI Capabilities

The system leverages AI for several critical functions:

### Data Validation

Before submission, the AI validates application data for:

- Missing required fields
- Data format issues
- Potential legal or compliance issues
- Inconsistencies in the data

### Form Filling Decisions

The AI makes intelligent decisions about how to fill each form field:

- Maps application data to appropriate form fields
- Handles conditional logic in the form
- Provides confidence scores for each decision
- Flags fields that may require human review

### Error Resolution

When form errors are detected, the AI:

- Analyzes error messages
- Examines current field values
- Suggests corrections with reasoning
- Applies fixes systematically

## Security Considerations

### Credential Management

The system handles sensitive credentials using these security measures:

- Credentials are never logged or included in error reports
- Support for environment variables to avoid storing credentials in files
- Option to prompt for credentials at runtime

### Data Protection

To protect application data:

- All data is processed locally without external transmission (except to the DOL portal)
- Screenshots and logs are sanitized to remove sensitive information
- File outputs use appropriate permissions

### API Key Security

For secure API key management:

- Keys can be provided via environment variables
- Keys are never logged or included in error reports
- Minimal scope access is recommended for all API keys

### Two-Factor Authentication

For secure 2FA management:

- TOTP secrets can be stored in the configuration file or provided per application
- Secrets are never exposed in logs or reports
- The system can generate and verify TOTP codes for testing

## Performance Optimization

### Concurrent Processing

The system optimizes performance through:

- Configurable concurrent processing of applications
- Browser resource management to minimize memory usage
- Efficient DOM interactions using appropriate selectors

### Resource Management

To minimize resource usage:

- Browser instances are shared when possible
- Files are processed in streaming mode when appropriate
- Memory-intensive operations are performed in batches

### Web Interface Optimizations

The web interface includes:

- Asynchronous status updates via AJAX
- Efficient data transfer with JSON
- Progressive loading of status information

## Troubleshooting

### Common Issues

1. **Login Failures**
   - Check credentials in configuration
   - Verify the FLAG portal is accessible
   - Check for CAPTCHA challenges
   - Verify TOTP configuration for 2FA

2. **Form Filling Errors**
   - Review the application data for accuracy
   - Check for changes in the FLAG portal interface
   - Update selectors if the form has changed

3. **AI-Related Issues**
   - Verify API key is valid
   - Check API quota and limits
   - Review AI prompt templates for accuracy

4. **Web Interface Issues**
   - Check Flask server logs
   - Verify browser compatibility
   - Check for JavaScript errors in browser console

### Logging

The system generates detailed logs at these locations:

- Console output for immediate feedback
- `logs/main.log` for overall application logs
- `logs/lca_filer.log` for filing process logs
- `logs/ai_client.log` for AI interaction logs

### Debugging Mode

To enable detailed debugging information:

```bash
python main.py --input=applications.csv --debug
```

For the web interface:

```bash 
python app.py --debug
```

## Future Improvements

Planned enhancements for future versions:

1. **Enhanced Web Interface**:
   - Interactive visualizations for batch processing
   - Advanced filtering and searching capabilities
   - Mobile-responsive design

2. **Notification System**:
   - Email/SMS alerts for completed filings
   - Push notifications for required human input
   - Webhook notifications for status updates

3. **Document Management**:
   - Automated handling of supporting documents
   - OCR for extracting data from uploaded documents
   - Document validation and verification

4. **Enhanced AI Models**:
   - Fine-tuned models specific to LCA processing
   - Feedback loop to learn from successful filings
   - Cached responses for common decisions to reduce API usage

5. **API Integration**:
   - Direct API integration if DOL offers such capabilities
   - Integration with case management systems
   - API endpoints for programmatic access

6. **Workflow Management**:
   - Multi-step approval workflows
   - Review queue for human verification before submission
   - Role-based permissions for different filing steps

7. **Advanced Browser Pool Management**:
   - More robust browser pool for resource optimization
   - Browser health checks and recovery mechanisms
   - Support for distributed browser instances

8. **Mobile Companion App**:
   - Mobile app for monitoring and interaction
   - Push notifications for required inputs
   - Mobile authentication for secure access

9. **Predictive Analytics**:
   - Analyze success rates by variables
   - Predict processing times and potential issues
   - Optimize filing timing based on historical data

---

This documentation covers the technical aspects of the H-1B LCA Filing Automation System. For questions or support, please contact the system administrator or refer to the repository's issue tracker.