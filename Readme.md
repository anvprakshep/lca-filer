# H-1B LCA Filing Automation System - Technical Documentation

## Table of Contents

- [System Overview](#system-overview)
- [Architecture](#architecture)
- [Module Descriptions](#module-descriptions)
- [Installation and Setup](#installation-and-setup)
- [Configuration](#configuration)
- [Usage Guide](#usage-guide)
- [Customization](#customization)
- [Error Handling and Recovery](#error-handling-and-recovery)
- [AI Capabilities](#ai-capabilities)
- [Security Considerations](#security-considerations)
- [Performance Optimization](#performance-optimization)
- [Troubleshooting](#troubleshooting)
- [Future Improvements](#future-improvements)

## System Overview

The H-1B LCA Filing Automation System is a comprehensive solution designed to automate the process of filing Labor Condition Applications (LCAs) on the Department of Labor's FLAG portal. The system combines headless browser automation with AI decision-making capabilities to provide a scalable, reliable solution for high-volume LCA filings.

### Key Features

- **Automated Form Filling**: Navigates and completes the entire LCA form process
- **AI-Powered Decision Making**: Uses AI to make intelligent choices when filling forms
- **Error Detection and Recovery**: Identifies and fixes form errors automatically
- **Concurrent Processing**: Handles multiple applications simultaneously
- **Comprehensive Reporting**: Generates detailed dashboards and statistics
- **Headless Operation**: Runs without a visual display for server deployment

## Architecture

The system follows a modular, component-based architecture with clear separation of concerns. It is organized into the following main components:

### High-Level Components

1. **Configuration Management**: Handles system settings and credentials
2. **Browser Automation**: Controls browser interactions and form navigation
3. **AI Decision Engine**: Makes intelligent form-filling decisions
4. **Error Management**: Detects and resolves errors during filing
5. **Reporting System**: Tracks results and generates reports

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

### Main Components

- **lca_filer.py**: Main class that orchestrates the entire filing process
- **main.py**: Entry point for the application with command-line interface

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
- `RESULTS_DIR`: Directory for storing results
- `LOG_DIR`: Directory for storing logs

## Usage Guide

### Basic Usage

To run the automation with a CSV file containing application data:

```bash
python main.py --config=config.json --input=applications.csv
```

### Creating a Sample CSV

To generate a sample CSV file with test data:

```bash
python main.py --sample --sample-output=sample_applications.csv
```

### Processing a Subset of Applications

To process only a specific number of applications:

```bash
python main.py --input=applications.csv --batch-size=10
```

### CSV File Format

The input CSV file should contain the following columns:

- `Application_ID`: Unique identifier for the application
- `Employer_Name`, `Employer_FEIN`, etc.: Employer information
- `Job_Title`, `SOC_Code`, etc.: Job information
- `Wage_Rate`, `Wage_Rate_Type`, etc.: Wage information
- `Worksite_Address`, `Worksite_City`, etc.: Worksite information
- `Worker_Name`, `Birth_Country`, etc.: Foreign worker information
- `Attorney_Name`, `Attorney_Firm`, etc.: Attorney information (optional)

See the generated sample CSV for a complete example.

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

### Error Recovery Process

When an error is detected during form filling:

1. The system captures the current form state
2. Errors are detected and classified
3. The AI suggests fixes based on error messages and current values
4. Fixes are applied and validated
5. If errors persist, they are logged for human review

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

## Troubleshooting

### Common Issues

1. **Login Failures**
   - Check credentials in configuration
   - Verify the FLAG portal is accessible
   - Check for CAPTCHA challenges

2. **Form Filling Errors**
   - Review the application data for accuracy
   - Check for changes in the FLAG portal interface
   - Update selectors if the form has changed

3. **AI-Related Issues**
   - Verify API key is valid
   - Check API quota and limits
   - Review AI prompt templates for accuracy

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

## Future Improvements

Planned enhancements for future versions:

1. **Web Interface**: Add a web-based dashboard for monitoring and control
2. **Notification System**: Email/SMS alerts for completed filings
3. **Document Management**: Automated handling of supporting documents
4. **Enhanced AI Models**: Fine-tuned models specific to LCA processing
5. **API Integration**: Direct API integration if DOL offers such capabilities
6. **Workflow Management**: Support for approval workflows with human review steps

---

This documentation covers the technical aspects of the H-1B LCA Filing Automation System. For questions or support, please contact the system administrator or refer to the repository's issue tracker.