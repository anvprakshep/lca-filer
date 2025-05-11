import os
import json
import asyncio
from typing import Dict, Any, Optional, List

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, time
import secrets
import threading

# Import LCA filer components
from lca_filer import LCAFiler
from config.config import Config
from utils.authenticator import TwoFactorAuth
from utils.file_utils import FileUtils
from utils.logger import get_logger, log_exception
from utils.interactive_filer import InteractiveFiler

# Set up logging
logger = get_logger(__name__)

# Initialize Flask app
template_dir = os.path.abspath('templates')
static_dir = os.path.abspath('static')
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(16))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Limit file uploads to 16MB
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# Global LCA filer instance (will be initialized in before_first_request)
lca_filer = None
interactive_filer: InteractiveFiler | None = None

# Async event loop for running async code with Flask
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Store active filing processes
active_filings = {}

# Load configuration
config_path = os.environ.get('CONFIG_PATH', 'config.json')
config = Config(config_path)


# Status update manager for real-time updates
class StatusUpdateManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.status_updates = {}

    def update_status(self, filing_id: str, status_update: Dict[str, Any]) -> None:
        """
        Update the status of a filing.

        Args:
            filing_id: Filing ID
            status_update: Status update dictionary
        """
        with self.lock:
            # Create entry if it doesn't exist
            if filing_id not in self.status_updates:
                self.status_updates[filing_id] = []

            # Add timestamp if not present
            if "timestamp" not in status_update:
                status_update["timestamp"] = datetime.now().isoformat()

            # Add the update to the list
            self.status_updates[filing_id].append(status_update)

            # Update active filing status if it exists
            if filing_id in active_filings:
                active_filings[filing_id]["status"] = status_update.get("status", active_filings[filing_id]["status"])

                # Create status history if needed
                if "status_history" not in active_filings[filing_id]:
                    active_filings[filing_id]["status_history"] = []

                # Add update to status history
                active_filings[filing_id]["status_history"].append(status_update)

                # Update current section if present
                if "current_section" in status_update:
                    active_filings[filing_id]["current_section"] = status_update["current_section"]

    def get_updates(self, filing_id: str, since: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get status updates for a filing.

        Args:
            filing_id: Filing ID
            since: Optional timestamp to filter updates

        Returns:
            List of status updates
        """
        with self.lock:
            if filing_id not in self.status_updates:
                return []

            if since:
                # Return only updates since the given timestamp
                return [update for update in self.status_updates[filing_id]
                        if update.get("timestamp", "") > since]
            else:
                # Return all updates
                return self.status_updates[filing_id]


# Create status update manager
status_update_manager = StatusUpdateManager()

# Interaction manager
class InteractionManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.interaction_queue = {}
        self.interaction_history = {}  # Store history of all interactions

    def register_interaction(self, filing_id, interaction_data):
        with self.lock:
            self.interaction_queue[filing_id] = interaction_data

            # Initialize history for this filing if needed
            if filing_id not in self.interaction_history:
                self.interaction_history[filing_id] = []

            # Update active filings with interaction needed status
            if filing_id in active_filings:
                active_filings[filing_id]["interaction_needed"] = interaction_data
                active_filings[filing_id]["status"] = "interaction_needed"

                # Add status update for interaction needed
                status_update_manager.update_status(filing_id, {
                    "status": "interaction_needed",
                    "step": "interaction_required",
                    "message": f"Human interaction required for section: {interaction_data.get('section_name', 'current section')}",
                    "interaction_data": {
                        "section": interaction_data.get('section_name', ''),
                        "fields": [field.get("id") for field in interaction_data.get("fields", [])],
                        "has_errors": interaction_data.get("has_errors", False)
                    }
                })

    def get_interaction(self, filing_id):
        with self.lock:
            return self.interaction_queue.get(filing_id)

    def resolve_interaction(self, filing_id, interaction_result):
        with self.lock:
            if filing_id in self.interaction_queue:
                # Keep a copy of the interaction for history
                if filing_id in self.interaction_history:
                    # Add to history
                    self.interaction_history[filing_id].append({
                        "interaction": self.interaction_queue[filing_id],
                        "result": interaction_result,
                        "timestamp": datetime.now().isoformat()
                    })

                if filing_id in active_filings:
                    # Initialize interaction history if needed
                    if "interaction_history" not in active_filings[filing_id]:
                        active_filings[filing_id]["interaction_history"] = []

                    # Add to history
                    active_filings[filing_id]["interaction_history"].append({
                        "interaction": self.interaction_queue[filing_id],
                        "result": interaction_result,
                        "timestamp": datetime.now().isoformat()
                    })

                    # Remove active interaction
                    active_filings[filing_id]["interaction_needed"] = None
                    active_filings[filing_id]["status"] = "processing"

                    # Add status update for resuming after interaction
                    status_update_manager.update_status(filing_id, {
                        "status": "processing",
                        "step": "continuing_after_interaction",
                        "message": "Continuing process after human interaction"
                    })

                logger.info(self.interaction_queue)

                # Remove from queue
                self.interaction_queue[filing_id].clear()
                del self.interaction_queue[filing_id]
                return True

        return False

    def get_interaction_history(self, filing_id):
        with self.lock:
            return self.interaction_history.get(filing_id, [])


# Create interaction manager
interaction_manager = InteractionManager()

def enhanced_status_update_callback(filing_id: str, update: Dict[str, Any]) -> None:
    """
    Enhanced status update callback with more detailed stage information.

    Args:
        filing_id: Filing ID to update
        update: Status update dictionary with detailed stage info
    """
    # Add timestamp if not present
    if "timestamp" not in update:
        update["timestamp"] = datetime.now().isoformat()

    # Add more specific information based on the current step
    if "step" in update:
        step = update["step"]
        # Add more details for specific steps
        if step == "navigation":
            update["stage"] = "Connecting to FLAG portal"
            update["progress"] = 10
        elif step == "login":
            update["stage"] = "Authenticating with FLAG portal"
            update["progress"] = 20
        elif step == "form_type_selection":
            update["stage"] = "Selecting H-1B form type"
            update["progress"] = 25
        elif step == "naics_code_handling":
            update["stage"] = "Processing NAICS code field"
            update["progress"] = 30
            if "current_section" not in update:
                update["current_section"] = "Employer Information"
        elif "section" in step:
            # Extract section name if available
            section_name = update.get("current_section", "form section")
            update["stage"] = f"Processing {section_name}"
            # Calculate approx progress - sections are typically 30-80% of process
            section_num = 0
            if "_" in step:
                try:
                    section_num = int(step.split("_")[1])
                except ValueError:
                    pass
            progress = 30 + min(50, section_num * 10)
            update["progress"] = progress
        elif step == "submission":
            update["stage"] = "Submitting form to DOL"
            update["progress"] = 90
        elif step == "complete":
            update["stage"] = "Filing completed"
            update["progress"] = 100

    # Call the original status update manager
    status_update_manager.update_status(filing_id, update)

    # Log detailed update
    detail_str = f"{update.get('status', 'unknown')} - {update.get('stage', '')} - {update.get('message', '')}"
    logger.info(f"Filing {filing_id} status update: {detail_str}")


def prepare_human_interaction_template_data(interaction_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare data for the human interaction template with improved field rendering and NAICS handling.

    Args:
        interaction_data: Raw interaction data from the filing process

    Returns:
        Enhanced template data dictionary
    """
    # Prepare data for template
    template_data = {
        'interaction': {
            'section_name': interaction_data.get('section_name', 'Current Form Section'),
            'guidance': interaction_data.get('guidance', 'Please complete the following fields'),
            'screenshot_path': interaction_data.get('screenshot_path', ''),
            'error_messages': interaction_data.get('error_messages', []),
            'has_errors': interaction_data.get('has_errors', False),
            'has_missing_elements': interaction_data.get('has_missing_elements', False),
            'fields': []
        }
    }

    # Add special note for missing elements
    if interaction_data.get('has_missing_elements', False):
        template_data['interaction']['missing_elements_note'] = (
            "The automation couldn't find some expected elements. "
            "Please make selections based on what you see in the screenshot."
        )

    # Pass through the fetch_results_function for NAICS fields if available
    if 'fetch_results_function' in interaction_data:
        template_data['interaction']['fetch_results_function'] = interaction_data['fetch_results_function']

    # Group fields by type for better organization
    grouped_fields = {
        'text': [],
        'select': [],
        'checkbox': [],
        'radio': [],
        'complex': [],
        'other': []
    }

    # Process each field to enhance rendering in the template
    for field in interaction_data.get('fields', []):
        # Basic field data
        field_type = field.get('type', 'text')

        # Create a field object with all needed rendering information
        field_obj = {
            'id': field.get('id', ''),
            'name': field.get('name', ''),
            'label': field.get('label', field.get('id', 'Field')),
            'type': field_type,
            'default_value': field.get('default_value', ''),
            'required': field.get('required', False),
            'description': field.get('description', ''),
            'field_errors': field.get('field_errors', []),
            'validation_message': field.get('validation_message', ''),
            'note': field.get('note', ''),
            'placeholder': field.get('placeholder', ''),
            'pattern': field.get('pattern', ''),
            'min': field.get('min', ''),
            'max': field.get('max', ''),
            'step': field.get('step', ''),
            'accept': field.get('accept', ''),  # For file inputs
            'maxlength': field.get('maxlength', ''),
            'disabled': field.get('disabled', False),
            'read_only': field.get('read_only', False)
        }

        # Add special attributes for autocomplete/NAICS fields
        if field_type == 'autocomplete' or field.get('is_autocomplete', False):
            field_obj['is_autocomplete'] = True
            field_obj['dynamic_search'] = field.get('dynamic_search', False)
            field_obj['example_searches'] = field.get('example_searches', [])
            field_obj['min_search_chars'] = field.get('min_search_chars', 2)
            field_obj['sample_values'] = field.get('sample_values', [])

        # Handle options for select, radio, etc.
        if 'options' in field:
            field_obj['options'] = []
            for option in field['options']:
                field_obj['options'].append({
                    'value': option.get('value', ''),
                    'label': option.get('label', option.get('value', '')),
                    'selected': option.get('selected', False) or option.get('checked', False),
                    'disabled': option.get('disabled', False),
                    'group': option.get('group', None)
                })

        # Add to appropriate group
        if field_type in ['text', 'password', 'email', 'number', 'tel', 'url', 'date', 'textarea']:
            grouped_fields['text'].append(field_obj)
        elif field_type in ['select']:
            grouped_fields['select'].append(field_obj)
        elif field_type == 'checkbox':
            grouped_fields['checkbox'].append(field_obj)
        elif field_type == 'radio':
            grouped_fields['radio'].append(field_obj)
        elif field_type in ['file', 'autocomplete', 'combobox'] or field.get('is_autocomplete', False):
            grouped_fields['complex'].append(field_obj)
        else:
            grouped_fields['other'].append(field_obj)

    # Add all fields to the template data
    template_data['interaction']['grouped_fields'] = grouped_fields

    # Also include flat list for backward compatibility
    all_fields = []
    for group in grouped_fields.values():
        all_fields.extend(group)
    template_data['interaction']['fields'] = all_fields

    return template_data

# Interaction callback for the interactive filer
def handle_interaction(filing_id, interaction_data):
    """Handle required interaction from the filing process"""
    interaction_manager.register_interaction(filing_id, interaction_data)


# Callback to handle status updates from the interactive filer
def handle_status_update(filing_id, status_update):
    """Handle status update from the filing process"""
    status_update_manager.update_status(filing_id, status_update)
    logger.info(
        f"Status update for filing {filing_id}: {status_update.get('status')} - {status_update.get('message', '')}")


# User login status check
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page', 'warning')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)

    return decorated_function


# Initialize LCA filer
@app.before_first_request
def initialize_lca_filer():
    global lca_filer, interactive_filer
    try:
        # Initialize LCA filer in the async event loop
        future = asyncio.run_coroutine_threadsafe(async_initialize_lca_filer(), loop)
        lca_filer, interactive_filer = future.result()
        logger.info("LCA filer initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize LCA filer: {str(e)}")
        # Will be initialized on demand later


async def async_initialize_lca_filer():
    try:
        # Create a new LCA filer
        filer = LCAFiler()

        # Explicitly initialize browser and other components with retry logic
        logger.info("Initializing LCA filer components")
        for attempt in range(3):  # Try up to 3 times
            try:
                if await filer.initialize():
                    logger.info("LCA filer initialization successful")
                    break
                else:
                    logger.error(f"Failed to initialize LCA filer on attempt {attempt+1}")
                    if attempt < 2:  # Don't wait after the last attempt
                        await asyncio.sleep(2)  # Wait before retry
            except Exception as e:
                logger.error(f"Error during initialization attempt {attempt+1}: {str(e)}")
                if attempt < 2:
                    await asyncio.sleep(2)  # Wait before retry
        else:
            # If we get here, all attempts failed
            logger.error("All initialization attempts failed")
            return None, None

        # Create interactive filer with proper callback
        interactive = InteractiveFiler(filer, handle_interaction)

        # Set status update callback
        interactive.set_status_update_callback(handle_status_update)

        return filer, interactive
    except Exception as e:
        logger.error(f"Error in async initialization: {str(e)}")
        return None, None


# Shutdown handler
@app.teardown_appcontext
def shutdown_lca_filer(exception=None):
    global lca_filer, interactive_filer
    try:
        # Check if interactive filer has active filings
        if interactive_filer and interactive_filer.has_active_filings():
            logger.info("Not shutting down LCA filer - active filings in progress")
            return

        # Only shut down if no filings are active
        active_filings_exist = any(filing.get("active", False) for filing in active_filings.values())

        if not active_filings_exist and lca_filer:
            # Clean up in the async event loop
            future = asyncio.run_coroutine_threadsafe(lca_filer.shutdown(), loop)
            future.result()
            logger.info("LCA filer shut down")
    except Exception as e:
        logger.error(f"Error in shutdown handler: {str(e)}")


# Routes
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Here you would check credentials against your database
        # For now, we'll use hardcoded values for demonstration
        if username == 'admin' and password == 'password':
            session['user_id'] = username
            flash('Logged in successfully', 'success')
            next_page = request.args.get('next', url_for('dashboard'))
            return redirect(next_page)
        else:
            flash('Invalid credentials', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    # Get list of active and completed filings
    completed_filings = []

    # Load results if available
    results_dir = config.get('output', 'results_dir', default='data/results')
    if os.path.exists(results_dir):
        for gen_dir in os.listdir(results_dir):
            results_path = os.path.join(results_dir, gen_dir, 'lca_results.json')
            if os.path.exists(results_path):
                try:
                    with open(results_path, 'r') as f:
                        results = json.load(f)
                        for result in results:
                            completed_filings.append({
                                'id': result.get('application_id', 'Unknown'),
                                'status': result.get('status', 'Unknown'),
                                'timestamp': result.get('timestamp', 'Unknown'),
                                'generation_id': result.get('generation_id', 'Unknown'),
                                'confirmation_number': result.get('confirmation_number', 'N/A')
                            })
                except Exception as e:
                    logger.error(f"Error loading results from {results_path}: {str(e)}")

    return render_template('dashboard.html',
                           active_filings=active_filings.values(),
                           completed_filings=completed_filings)


@app.route('/new-filing', methods=['GET', 'POST'])
@login_required
def new_filing():
    if request.method == 'POST':
        try:
            # Create a new filing from form data
            filing_data = {
                "id": f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "credentials": {
                    "username": request.form.get('flag_username'),
                    "password": request.form.get('flag_password'),
                    "totp_secret": request.form.get('totp_secret', '')
                },
                "employer": {
                    "name": request.form.get('employer_name'),
                    "fein": request.form.get('employer_fein'),
                    "naics": request.form.get('naics_code'),
                    "address": request.form.get('employer_address'),
                    "city": request.form.get('employer_city'),
                    "state": request.form.get('employer_state'),
                    "zip": request.form.get('employer_zip'),
                    "phone": request.form.get('employer_phone'),
                    "email": request.form.get('employer_email')
                },
                "job": {
                    "title": request.form.get('job_title'),
                    "soc_code": request.form.get('soc_code'),
                    "duties": request.form.get('job_duties'),
                    "requirements": request.form.get('job_requirements')
                },
                "wages": {
                    "rate": request.form.get('wage_rate'),
                    "rate_type": request.form.get('wage_rate_type'),
                    "prevailing_wage": request.form.get('prevailing_wage'),
                    "pw_source": request.form.get('pw_source')
                },
                "worksite": {
                    "address": request.form.get('worksite_address'),
                    "city": request.form.get('worksite_city'),
                    "state": request.form.get('worksite_state'),
                    "zip": request.form.get('worksite_zip'),
                    "county": request.form.get('worksite_county')
                },
                "foreign_worker": {
                    "name": request.form.get('worker_name'),
                    "birth_country": request.form.get('birth_country'),
                    "citizenship": request.form.get('citizenship'),
                    "education": request.form.get('education')
                }
            }

            # Check for attorney information
            if request.form.get('has_attorney') == 'yes':
                filing_data["attorney"] = {
                    "name": request.form.get('attorney_name'),
                    "firm": request.form.get('attorney_firm'),
                    "address": request.form.get('attorney_address'),
                    "city": request.form.get('attorney_city'),
                    "state": request.form.get('attorney_state'),
                    "zip": request.form.get('attorney_zip'),
                    "phone": request.form.get('attorney_phone'),
                    "email": request.form.get('attorney_email')
                }

            # Check for multiple worksites
            if request.form.get('has_multiple_worksites') == 'yes':
                filing_data["multiple_worksites"] = True
                filing_data["additional_worksites"] = []

                # Process additional worksite fields
                # This is a simplified version - in a real app, you'd use JavaScript to add dynamic fields
                for i in range(1, 4):  # Support up to 3 additional worksites
                    worksite_prefix = f'additional_worksite_{i}'
                    if request.form.get(f'{worksite_prefix}_address'):
                        worksite = {
                            "address": request.form.get(f'{worksite_prefix}_address'),
                            "city": request.form.get(f'{worksite_prefix}_city'),
                            "state": request.form.get(f'{worksite_prefix}_state'),
                            "zip": request.form.get(f'{worksite_prefix}_zip'),
                            "county": request.form.get(f'{worksite_prefix}_county')
                        }
                        filing_data["additional_worksites"].append(worksite)

            # Process options
            filing_data["capture_elements"] = 'capture_elements' in request.form
            filing_data["interactive_mode"] = 'interactive_mode' in request.form

            # Store filing in active filings
            active_filings[filing_data["id"]] = {
                "id": filing_data["id"],
                "status": "pending",
                "timestamp": datetime.now().isoformat(),
                "data": filing_data
            }

            # Redirect to the form review page
            return redirect(url_for('review_filing', filing_id=filing_data["id"]))

        except Exception as e:
            logger.error(f"Error creating new filing: {str(e)}")
            flash(f"Error creating filing: {str(e)}", 'danger')

    # GET request - show the form
    return render_template('new_filing.html')


@app.route('/review-filing/<filing_id>', methods=['GET', 'POST'])
@login_required
def review_filing(filing_id):
    if filing_id not in active_filings:
        flash('Filing not found', 'danger')
        return redirect(url_for('dashboard'))

    filing = active_filings[filing_id]

    if request.method == 'POST':
        # Start the filing process in the background
        try:
            global lca_filer, interactive_filer

            # Initialize filer if needed
            if not lca_filer or not interactive_filer:
                future = asyncio.run_coroutine_threadsafe(async_initialize_lca_filer(), loop)
                lca_filer, interactive_filer = future.result()
                if not lca_filer or not interactive_filer:
                    raise Exception("Failed to initialize LCA filer")

            # ADD THIS SECTION: Configure TOTP from application data
            credentials = filing["data"].get("credentials", {})
            username = credentials.get("username")
            totp_secret = credentials.get("totp_secret")

            if username and totp_secret:
                # Enable TOTP if not already
                if not lca_filer.config.get("totp", "enabled", default=False):
                    lca_filer.config.set(True, "totp", "enabled")
                    logger.info("Enabled TOTP authentication")

                # Initialize two-factor auth if needed
                if not lca_filer.two_factor_auth:
                    totp_config = lca_filer.config.get("totp")
                    if "secrets" not in totp_config:
                        totp_config["secrets"] = {}
                    lca_filer.two_factor_auth = TwoFactorAuth(totp_config)
                    logger.info("Two-factor authentication initialized")

                # Set the secret
                lca_filer.two_factor_auth.totp_secrets[username] = totp_secret
                lca_filer.config.set_totp_secret(username, totp_secret)
                logger.info(f"Configured TOTP secret for {username} from application data")

                # Test the secret
                if lca_filer.two_factor_auth:
                    test_code = lca_filer.two_factor_auth.generate_totp_code(username)
                    logger.info(f"Current TOTP code for testing: {test_code}")
            # END ADDED SECTION

            # Configure status update callback
            interactive_filer.set_status_update_callback(handle_status_update)

            # Mark as processing
            filing["status"] = "processing"

            # Add initial status update
            status_update_manager.update_status(filing_id, {
                "status": "processing",
                "step": "starting",
                "message": "Starting filing process"
            })

            # Start the filing process in a separate thread
            from threading import Thread

            def process_filing(filer, filing_data):
                try:
                    # Set a flag to indicate this filing is active
                    filing_data["active"] = True

                    # Run the async filing in the event loop
                    filing_result = asyncio.run_coroutine_threadsafe(
                        filer.start_interactive_filing(filing_data["data"]), loop).result()

                    # Update filing status with result
                    filing_data["status"] = filing_result.get("status", "error")
                    filing_data["result"] = filing_result
                    filing_data["completed_at"] = datetime.now().isoformat()

                    # Mark as no longer active
                    filing_data["active"] = False

                    # Add final status update
                    status_update_manager.update_status(filing_id, {
                        "status": filing_result.get("status", "error"),
                        "step": "complete",
                        "message": f"Filing completed with status: {filing_result.get('status', 'error')}",
                        "confirmation_number": filing_result.get("confirmation_number", "")
                    })

                    logger.info(f"Filing {filing_data['id']} completed with status: {filing_data['status']}")
                except Exception as e:
                    logger.error(f"Error processing filing {filing_data['id']}: {str(e)}")
                    filing_data["status"] = "error"
                    filing_data["error"] = str(e)
                    filing_data["completed_at"] = datetime.now().isoformat()
                    filing_data["active"] = False  # Mark as no longer active

                    # Add error status update
                    status_update_manager.update_status(filing_id, {
                        "status": "error",
                        "step": "error",
                        "message": f"Error during filing: {str(e)}",
                        "error": str(e)
                    })

            # Start background thread with interactive filer
            thread = Thread(target=process_filing, args=(interactive_filer, filing))
            thread.daemon = True
            thread.start()

            flash('Filing process started. You may be asked for input during certain steps.', 'success')
            return redirect(url_for('filing_status', filing_id=filing_id))

        except Exception as e:
            logger.error(f"Error starting filing process: {str(e)}")
            flash(f"Error starting filing: {str(e)}", 'danger')

    return render_template('review_filing.html', filing=filing)


@app.route('/filing-status/<filing_id>')
@login_required
def filing_status(filing_id):
    if filing_id not in active_filings:
        flash('Filing not found', 'danger')
        return redirect(url_for('dashboard'))

    filing = active_filings[filing_id]

    # Check if we need human interaction
    needs_interaction = False
    if filing["status"] == "interaction_needed" and "interaction_needed" in filing:
        needs_interaction = True

    # Get screenshots if available
    screenshots = []
    if "result" in filing and "steps_completed" in filing["result"]:
        # Find screenshots for this filing
        screenshot_dir = f"screenshots/{filing.get('generation_id', 'global')}/{filing_id}"
        if os.path.exists(screenshot_dir):
            for filename in os.listdir(screenshot_dir):
                if filename.endswith(".png"):
                    # Extract description from filename
                    name_parts = filename.split("_")
                    if len(name_parts) >= 2:
                        description = "_".join(name_parts[1:-1])  # Remove index and timestamp
                        description = description.replace("_", " ").title()
                    else:
                        description = filename

                    screenshots.append({
                        "path": f"screenshots/{filing.get('generation_id', 'global')}/{filing_id}/{filename}",
                        "description": description
                    })

    filing["screenshots"] = screenshots

    # Get status updates
    updates = status_update_manager.get_updates(filing_id)

    # Include updates in the template context
    return render_template('filing_status.html',
                           filing=filing,
                           needs_interaction=needs_interaction,
                           status_updates=updates)


@app.route('/api/filing-status/<filing_id>', methods=['GET'])
@login_required
def api_filing_status(filing_id):
    if filing_id not in active_filings:
        return jsonify({"error": "Filing not found"}), 404

    # Get since parameter
    since = request.args.get('since')

    # Get updates
    updates = status_update_manager.get_updates(filing_id, since)

    # Basic filing info
    filing = active_filings[filing_id]

    # Return status
    return jsonify({
        "filing_id": filing_id,
        "status": filing.get("status", "unknown"),
        "updates": updates,
        "current_section": filing.get("current_section", ""),
        "interaction_needed": filing.get("interaction_needed") is not None,
        "last_update": updates[-1] if updates else None
    })


@app.route('/human-interaction/<filing_id>', methods=['GET', 'POST'])
@login_required
def human_interaction(filing_id):
    if filing_id not in active_filings:
        flash('Filing not found', 'danger')
        return redirect(url_for('dashboard'))

    filing = active_filings[filing_id]

    # Get interaction data from the manager
    interaction_data = interaction_manager.get_interaction(filing_id)

    if not interaction_data:
        flash('No interaction required for this filing', 'warning')
        return redirect(url_for('filing_status', filing_id=filing_id))

    if request.method == 'POST':
        # Process the human input
        try:
            # Extract field values from form
            interaction_result = {}

            # Debug logging to help troubleshoot
            logger.debug(f"Form data for filing {filing_id}: {request.form}")
            print(f"Form data for filing {filing_id}: {request.form}")
            # Process all fields from the form, including special fields
            for key, value in request.form.items():
                # Store all form data, including the special fields for NAICS selection
                interaction_result[key] = value
                logger.debug(f"Processing form field: {key} = {value}")
                print(f"Processing form field: {key} = {value}")

            # Log the complete interaction result
            logger.info(f"Interaction result for filing {filing_id}: {interaction_result}")

            print("interaction_result", interaction_result)
            print("interaction_filer", interactive_filer)
            # Pass the results back to the interactive filer
            if interactive_filer:
                interactive_filer.set_interaction_result(filing_id, interaction_result)

            # Mark interaction as resolved
            interaction_manager.resolve_interaction(filing_id, interaction_result)

            # Resume the filing process
            flash('Your input has been submitted and the filing process will continue.', 'success')
            return redirect(url_for('filing_status', filing_id=filing_id))

        except Exception as e:
            logger.error(f"Error processing human interaction: {str(e)}")
            flash(f"Error submitting input: {str(e)}", 'danger')

    # Use the enhanced template data preparation
    template_data = prepare_human_interaction_template_data(interaction_data)
    template_data['filing'] = filing

    return render_template('human_interaction.html', **template_data)


@app.route('/upload-csv', methods=['GET', 'POST'])
@login_required
def upload_csv():
    if request.method == 'POST':
        if 'csv_file' not in request.files:
            flash('No file part', 'danger')
            return redirect(request.url)

        file = request.files['csv_file']

        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)

        if file and '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() == 'csv':
            try:
                # Save the file temporarily
                temp_path = f"temp_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                file.save(temp_path)

                # Load applications from CSV
                applications = FileUtils.load_applications_from_csv(temp_path)

                # Remove temp file
                os.remove(temp_path)

                if not applications:
                    flash('No valid applications found in CSV', 'warning')
                    return redirect(request.url)

                # Store applications for batch processing
                session['batch_applications'] = applications
                flash(f'Successfully loaded {len(applications)} applications from CSV', 'success')
                return redirect(url_for('batch_processing'))

            except Exception as e:
                logger.error(f"Error processing CSV upload: {str(e)}")
                flash(f"Error processing CSV: {str(e)}", 'danger')
                return redirect(request.url)
        else:
            flash('Invalid file type. Please upload a CSV file.', 'danger')
            return redirect(request.url)

    return render_template('upload_csv.html')


@app.route('/batch-processing', methods=['GET', 'POST'])
@login_required
def batch_processing():
    if 'batch_applications' not in session:
        flash('No batch applications loaded', 'warning')
        return redirect(url_for('upload_csv'))

    applications = session['batch_applications']

    if request.method == 'POST':
        try:
            global lca_filer, interactive_filer

            # Initialize filer if needed
            if not lca_filer or not interactive_filer:
                future = asyncio.run_coroutine_threadsafe(async_initialize_lca_filer(), loop)
                lca_filer, interactive_filer = future.result()
                if not lca_filer or not interactive_filer:
                    raise Exception("Failed to initialize LCA filer")

            # Set status update callback
            interactive_filer.set_status_update_callback(handle_status_update)

            # Configure batch processing options
            max_concurrent = int(request.form.get('max_concurrent', 5))

            # Get processing mode for each application
            apps_to_process = []
            for i, app in enumerate(applications):
                app_mode = request.form.get(f"app_processing_mode_{i}", "interactive")
                if app_mode != "skip":
                    apps_to_process.append({
                        "app": app,
                        "mode": app_mode
                    })

            # Start batch processing in a separate thread
            from threading import Thread

            def process_batch(filer, apps, max_concurrent):
                try:
                    batch_filings = []

                    # Register each application as an active filing
                    for app_info in apps:
                        app = app_info["app"]
                        mode = app_info["mode"]

                        # Create filing entry
                        filing_id = app.get("id", f"app_{int(time.time())}_{id(app)}")
                        filing = {
                            "id": filing_id,
                            "status": "pending",
                            "timestamp": datetime.now().isoformat(),
                            "data": app
                        }

                        # Add processing mode
                        app["interactive_mode"] = (mode == "interactive")

                        # Add to active filings
                        active_filings[filing_id] = filing
                        batch_filings.append(filing)

                        # Add initial status update
                        status_update_manager.update_status(filing_id, {
                            "status": "pending",
                            "step": "batch_queued",
                            "message": "Queued for batch processing"
                        })

                    # Process filings with concurrent limit
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
                        futures = []

                        for filing in batch_filings:
                            # Update status to queued
                            status_update_manager.update_status(filing["id"], {
                                "status": "queued",
                                "step": "batch_processing",
                                "message": f"Queued for processing in batch"
                            })

                            future = executor.submit(
                                asyncio.run_coroutine_threadsafe,
                                interactive_filer.start_interactive_filing(filing["data"]),
                                loop
                            )
                            futures.append((future, filing))

                        # Process results as they complete
                        for future, filing in futures:
                            try:
                                filing_result = future.result().result()

                                # Update filing status
                                filing["status"] = filing_result.get("status", "error")
                                filing["result"] = filing_result
                                filing["completed_at"] = datetime.now().isoformat()

                                # Add final status update
                                status_update_manager.update_status(filing["id"], {
                                    "status": filing_result.get("status", "error"),
                                    "step": "batch_complete",
                                    "message": f"Batch processing completed with status: {filing_result.get('status', 'error')}",
                                    "confirmation_number": filing_result.get("confirmation_number", "")
                                })

                                logger.info(f"Batch filing {filing['id']} completed with status: {filing['status']}")
                            except Exception as e:
                                logger.error(f"Error in batch filing {filing['id']}: {str(e)}")
                                filing["status"] = "error"
                                filing["error"] = str(e)
                                filing["completed_at"] = datetime.now().isoformat()

                                # Add error status update
                                status_update_manager.update_status(filing["id"], {
                                    "status": "error",
                                    "step": "batch_error",
                                    "message": f"Error during batch processing: {str(e)}",
                                    "error": str(e)
                                })

                    logger.info(f"Batch processing completed for {len(batch_filings)} applications")
                except Exception as e:
                    logger.error(f"Error in batch processing: {str(e)}")

            # Start background thread
            thread = Thread(target=process_batch, args=(interactive_filer, apps_to_process, max_concurrent))
            thread.daemon = True
            thread.start()

            flash(f'Batch processing started for {len(apps_to_process)} applications. Check results in the dashboard.',
                  'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            logger.error(f"Error starting batch processing: {str(e)}")
            flash(f"Error starting batch processing: {str(e)}", 'danger')

    return render_template('batch_processing.html', applications=applications)


@app.route('/api/form-elements/<field_id>', methods=['GET'])
@login_required
def get_form_element_options(field_id):
    """API endpoint to get options for a specific form field."""
    try:
        from config.form_structure import FormStructure

        # Search for the field in all sections
        field_info = None
        for section in FormStructure.get_h1b_structure()["sections"]:
            for field in section["fields"]:
                if field["id"] == field_id:
                    field_info = {
                        "id": field["id"],
                        "type": field.get("type", "text"),
                        "options": field.get("options", []),
                        "required": field.get("required", False),
                        "section": section["name"]
                    }
                    break
            if field_info:
                break

        if not field_info:
            return jsonify({"error": "Field not found"}), 404

        # Check if we have dynamically captured options for this field
        if interactive_filer and interactive_filer.form_capture:
            for section_name, section_data in interactive_filer.form_capture.captured_elements.items():
                for element in section_data.get("elements", []):
                    if element.get("id") == field_id or element.get("name") == field_id:
                        # Merge with static field info
                        field_info.update({
                            "type": element.get("type", field_info.get("type")),
                            "options": element.get("options", field_info.get("options")),
                            "required": element.get("required", field_info.get("required")),
                            "label": element.get("label"),
                            "placeholder": element.get("placeholder"),
                            "default_value": element.get("default_value"),
                            "dynamically_captured": True
                        })
                        if "screenshot_path" in element:
                            field_info["screenshot_url"] = url_for('static', filename=element["screenshot_path"])
                        break

        return jsonify(field_info)

    except Exception as e:
        logger.error(f"Error getting field options for {field_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/field-registry', methods=['GET'])
@login_required
def get_field_registry():
    """API endpoint to get the complete field registry."""
    try:
        # Start with an empty registry
        field_registry = {}

        # Add fields from static form structure
        from config.form_structure import FormStructure
        for section in FormStructure.get_h1b_structure()["sections"]:
            for field in section["fields"]:
                field_id = field.get("id")
                if field_id:
                    field_registry[field_id] = {
                        "id": field_id,
                        "type": field.get("type", "text"),
                        "options": field.get("options", []),
                        "required": field.get("required", False),
                        "section": section["name"],
                        "source": "Static form structure",
                        "last_updated": "N/A"
                    }

        # Add dynamically captured fields if available
        if interactive_filer and interactive_filer.form_capture:
            for section_name, section_data in interactive_filer.form_capture.captured_elements.items():
                for element in section_data.get("elements", []):
                    field_id = element.get("id")
                    if field_id:
                        # New field or update existing
                        field_registry[field_id] = {
                            "id": field_id,
                            "type": element.get("type", "unknown"),
                            "label": element.get("label", field_id),
                            "options": element.get("options", []),
                            "required": element.get("required", False),
                            "placeholder": element.get("placeholder", ""),
                            "default_value": element.get("default_value", ""),
                            "section": section_name,
                            "source": "Dynamic capture",
                            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }

                        # Add screenshot path if available
                        if "screenshot_path" in element:
                            field_registry[field_id]["screenshot_url"] = url_for('static',
                                                                                 filename=element["screenshot_path"])

        return jsonify(field_registry)

    except Exception as e:
        logger.error(f"Error getting field registry: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/capture-display')
@login_required
def capture_display():
    """Show captured form elements and comparison with static structure."""
    captured_elements = {}

    if interactive_filer and interactive_filer.form_capture:
        captured_elements = interactive_filer.form_capture.captured_elements

    # Get static form structure
    from config.form_structure import FormStructure
    form_structure = FormStructure.get_h1b_structure()["sections"]

    return render_template('capture_display.html',
                           captured_elements=captured_elements,
                           form_structure=form_structure)


@app.route('/api/totp/test', methods=['POST'])
@login_required
def test_totp_configuration():
    """API endpoint to test TOTP configuration."""
    try:
        data = request.json
        username = data.get('username')
        totp_secret = data.get('totp_secret')

        if not username:
            return jsonify({"error": "Username is required"}), 400

        global lca_filer, interactive_filer

        # Initialize filer if needed
        if not lca_filer or not interactive_filer:
            future = asyncio.run_coroutine_threadsafe(async_initialize_lca_filer(), loop)
            lca_filer, interactive_filer = future.result()
            if not lca_filer or not interactive_filer:
                return jsonify({"error": "Failed to initialize LCA filer"}), 500

        # If a secret was provided, configure it first
        if totp_secret:
            # Configure TOTP
            if not lca_filer.config.get("totp", "enabled", default=False):
                lca_filer.config.set(True, "totp", "enabled")

            # Initialize two-factor auth if needed
            if not lca_filer.two_factor_auth:
                totp_config = lca_filer.config.get("totp", {})
                if "secrets" not in totp_config:
                    totp_config["secrets"] = {}
                lca_filer.two_factor_auth = TwoFactorAuth(totp_config)

            # Set the secret
            lca_filer.two_factor_auth.totp_secrets[username] = totp_secret
            lca_filer.config.set_totp_secret(username, totp_secret)

        # Now test the configuration
        verification_result = lca_filer.verify_totp_configuration(username)

        # If we don't have a working configuration, return error
        if verification_result.get("error"):
            return jsonify(verification_result), 400

        # Return success with current code and remaining time
        return jsonify({
            "success": True,
            "username": username,
            "current_code": verification_result.get("current_code"),
            "remaining_seconds": verification_result.get("remaining_seconds"),
            "message": f"TOTP configured successfully. Current code: {verification_result.get('current_code')}"
        })

    except Exception as e:
        logger.error(f"Error testing TOTP configuration: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/totp/configure', methods=['POST'])
@login_required
def configure_totp():
    """API endpoint to configure TOTP for a username."""
    try:
        data = request.json
        username = data.get('username')
        totp_secret = data.get('totp_secret')

        if not username or not totp_secret:
            return jsonify({"error": "Username and TOTP secret are required"}), 400

        global lca_filer, interactive_filer

        # Initialize filer if needed
        if not lca_filer or not interactive_filer:
            future = asyncio.run_coroutine_threadsafe(async_initialize_lca_filer(), loop)
            lca_filer, interactive_filer = future.result()
            if not lca_filer or not interactive_filer:
                return jsonify({"error": "Failed to initialize LCA filer"}), 500

        # Configure TOTP
        if not lca_filer.config.get("totp", "enabled", default=False):
            lca_filer.config.set(True, "totp", "enabled")

        # Initialize two-factor auth if needed
        if not lca_filer.two_factor_auth:
            totp_config = lca_filer.config.get("totp", {})
            if "secrets" not in totp_config:
                totp_config["secrets"] = {}
            lca_filer.two_factor_auth = TwoFactorAuth(totp_config)

        # Set the secret
        lca_filer.two_factor_auth.totp_secrets[username] = totp_secret
        lca_filer.config.set_totp_secret(username, totp_secret)

        # Save the configuration
        config_file = lca_filer.config.config.get("config_path", "config.json")
        lca_filer.config.save(config_file)

        # Generate a test code
        verification_result = lca_filer.verify_totp_configuration(username)

        # Return result
        return jsonify({
            "success": True,
            "username": username,
            "current_code": verification_result.get("current_code"),
            "remaining_seconds": verification_result.get("remaining_seconds"),
            "message": "TOTP secret saved to configuration"
        })

    except Exception as e:
        logger.error(f"Error configuring TOTP: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/naics-search', methods=['GET'])
@login_required
def api_naics_search():
    """API endpoint for NAICS code search that communicates with the FLAG portal and returns selectors."""
    search_term = request.args.get('term', '')
    filing_id = request.args.get('filing_id', '')

    if not search_term or not filing_id:
        return jsonify({"error": "Missing search term or filing ID"}), 400

    # Check if filing exists
    if filing_id not in active_filings:
        return jsonify({"error": "Filing not found"}), 404

    # Check if this is an interactive filing with pending interaction
    interaction_data = interaction_manager.get_interaction(filing_id)
    if not interaction_data:
        return jsonify({"error": "No pending interaction for this filing"}), 400

    # Check if the interaction has a fetch_results_function
    fetch_results_function = interaction_data.get('fetch_results_function')
    if not fetch_results_function:
        # If no dynamic function is available, generate sample results based on search term
        logger.warning(f"No fetch_results_function available for filing {filing_id}, using fallback")
        results = generate_fallback_naics_results(search_term)
        return jsonify({"results": results, "result_selectors": []})

    try:
        # Create a Future to run the async function in the event loop
        future = asyncio.run_coroutine_threadsafe(
            fetch_results_function(search_term),
            loop
        )

        # Get the results with a timeout
        response = future.result(timeout=10)

        # Log the response structure for debugging
        logger.debug(f"NAICS search response for term '{search_term}': {response}")

        # Enhanced to handle the new response format that includes element selectors
        results = []
        result_selectors = []

        if isinstance(response, dict):
            # New format with results and selectors
            results = response.get("results", [])
            result_selectors = response.get("result_selectors", [])
        else:
            # Old format with just results
            results = response or []

        # If no results found but we have a search term, provide some fallback results
        if not results and search_term:
            results = generate_fallback_naics_results(search_term)

        # Return both results and selectors
        response_data = {
            "results": results,
            "result_selectors": result_selectors
        }

        logger.debug(f"Sending NAICS search response: {response_data}")

        return jsonify(response_data)

    except asyncio.TimeoutError:
        logger.error(f"Timeout fetching NAICS results for term '{search_term}'")
        return jsonify({
            "error": "Timeout while fetching results",
            "results": generate_fallback_naics_results(search_term),
            "result_selectors": []
        })

    except Exception as e:
        logger.error(f"Error fetching NAICS results: {str(e)}")
        return jsonify({
            "error": str(e),
            "results": generate_fallback_naics_results(search_term),
            "result_selectors": []
        })

def generate_fallback_naics_results(search_term):
    """Generate fallback NAICS results if the FLAG portal search fails."""
    search_term_lower = search_term.lower()

    # Common NAICS codes as fallback
    common_naics = []

    # # If search term is numeric, try to match by code
    # if search_term.isdigit():
    #     filtered_results = [
    #         naics for naics in common_naics
    #         if naics["code"].startswith(search_term)
    #     ]
    # else:
    #     # Otherwise match by description
    #     filtered_results = [
    #         naics for naics in common_naics
    #         if search_term_lower in naics["description"].lower()
    #     ]
    #
    # # If still no results, return top 5 most common codes
    # if not filtered_results:
    #     fallback_results = common_naics[:5]
    #     # Add the search term as a custom option
    #     fallback_results.append({
    #         "code": search_term if search_term.isdigit() and len(search_term) == 6 else "999999",
    #         "description": f"Custom: {search_term}",
    #         "text": f"Use custom value: {search_term}"
    #     })
    #     return fallback_results

    return common_naics


if __name__ == '__main__':
    # Start the async event loop in a separate thread
    from threading import Thread

    thread = Thread(target=lambda: loop.run_forever())
    thread.daemon = True
    thread.start()

    # Start Flask development server
    app.run(debug=True)