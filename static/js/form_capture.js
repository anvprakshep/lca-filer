/**
 * Form Field Capture UI
 * Helps with dynamic form field handling and display
 */

document.addEventListener('DOMContentLoaded', function() {
    // Check if we're on a human interaction page
    const interactionForm = document.getElementById('interaction-form');
    if (interactionForm) {
        setupInteractionForm(interactionForm);
    }

    // Handle form field preview
    const fieldPreviewButtons = document.querySelectorAll('.field-preview-button');
    fieldPreviewButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            const fieldId = this.getAttribute('data-field-id');
            showFieldPreview(fieldId);
        });
    });

    // Handle dynamic field tooltips
    const fieldInfoIcons = document.querySelectorAll('.field-info-icon');
    fieldInfoIcons.forEach(icon => {
        icon.addEventListener('mouseenter', function() {
            const fieldId = this.getAttribute('data-field-id');
            loadFieldInfo(fieldId, this);
        });
    });
});

/**
 * Set up the interaction form with validation and UI enhancements
 */
function setupInteractionForm(form) {
    // Add form validation
    form.addEventListener('submit', function(e) {
        const requiredFields = form.querySelectorAll('[required]');
        let hasErrors = false;

        requiredFields.forEach(field => {
            if (!field.value.trim()) {
                // Show error for empty required field
                const fieldContainer = field.closest('.form-group');
                const errorMsg = fieldContainer.querySelector('.field-error') ||
                                createElement('div', { class: 'field-error' }, 'This field is required');

                if (!fieldContainer.querySelector('.field-error')) {
                    fieldContainer.appendChild(errorMsg);
                }

                field.classList.add('error');
                hasErrors = true;
            } else {
                // Clear error
                const fieldContainer = field.closest('.form-group');
                const errorMsg = fieldContainer.querySelector('.field-error');
                if (errorMsg) {
                    errorMsg.remove();
                }
                field.classList.remove('error');
            }
        });

        if (hasErrors) {
            e.preventDefault();
            // Show message at top of form
            const formError = document.querySelector('.form-error-message') ||
                             createElement('div', { class: 'form-error-message' },
                                          'Please correct the errors below before submitting');

            if (!document.querySelector('.form-error-message')) {
                form.prepend(formError);
            }

            // Scroll to first error
            const firstError = form.querySelector('.field-error');
            if (firstError) {
                firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }
    });

    // Add character counters for text fields
    const textareas = form.querySelectorAll('textarea');
    textareas.forEach(textarea => {
        const counter = createElement('div', { class: 'char-counter' },
                                     `${textarea.value.length} characters`);
        textarea.parentNode.appendChild(counter);

        textarea.addEventListener('input', function() {
            counter.textContent = `${this.value.length} characters`;
        });
    });

    // Enhance select fields with search if they have many options
    const selects = form.querySelectorAll('select');
    selects.forEach(select => {
        if (select.options.length > 10) {
            // Add a search field before the select
            const searchContainer = createElement('div', { class: 'select-search-container' });
            const searchInput = createElement('input', {
                type: 'text',
                class: 'select-search',
                placeholder: 'Search options...'
            });

            searchContainer.appendChild(searchInput);
            select.parentNode.insertBefore(searchContainer, select);

            // Add search functionality
            searchInput.addEventListener('input', function() {
                const search = this.value.toLowerCase();

                for (let i = 0; i < select.options.length; i++) {
                    const option = select.options[i];
                    const text = option.textContent.toLowerCase();

                    if (text.includes(search) || !search) {
                        option.style.display = '';
                    } else {
                        option.style.display = 'none';
                    }
                }
            });
        }
    });
}

/**
 * Show a preview of the field as seen in the FLAG portal
 */
function showFieldPreview(fieldId) {
    // Fetch field data with options
    fetch(`/api/form-elements/${fieldId}`)
        .then(response => response.json())
        .then(data => {
            // Create modal for preview
            const modal = createElement('div', { class: 'field-preview-modal' });

            // Create modal content
            const modalContent = createElement('div', { class: 'field-preview-content' });

            // Add close button
            const closeButton = createElement('button', { class: 'close-button' }, 'Close');
            closeButton.addEventListener('click', function() {
                document.body.removeChild(modal);
            });

            // Add field info
            const fieldInfo = createElement('div', { class: 'field-info' });

            // Add field label
            const fieldLabel = createElement('h3', {}, data.label || data.id);
            fieldInfo.appendChild(fieldLabel);

            // Add screenshot if available
            if (data.screenshot_url) {
                const screenshot = createElement('img', {
                    src: data.screenshot_url,
                    alt: `Screenshot of ${data.label || data.id} field`
                });
                fieldInfo.appendChild(screenshot);
            }

            // Add field type and other metadata
            const fieldType = createElement('p', {}, `Field type: ${data.type}`);
            fieldInfo.appendChild(fieldType);

            if (data.required) {
                const requiredTag = createElement('span', { class: 'required-tag' }, 'Required');
                fieldInfo.appendChild(requiredTag);
            }

            // Add options if available
            if (data.options && data.options.length > 0) {
                const optionsTitle = createElement('h4', {}, 'Available Options:');
                fieldInfo.appendChild(optionsTitle);

                const optionsList = createElement('ul', { class: 'options-list' });
                data.options.forEach(option => {
                    const optionItem = createElement('li', {}, option.label || option.value);
                    if (option.selected || option.checked) {
                        optionItem.classList.add('default-selected');
                    }
                    optionsList.appendChild(optionItem);
                });
                fieldInfo.appendChild(optionsList);
            }

            // Add all content to modal
            modalContent.appendChild(closeButton);
            modalContent.appendChild(fieldInfo);
            modal.appendChild(modalContent);

            // Add to document and show
            document.body.appendChild(modal);

            // Add backdrop click to close
            modal.addEventListener('click', function(e) {
                if (e.target === modal) {
                    document.body.removeChild(modal);
                }
            });
        })
        .catch(error => {
            console.error('Error fetching field info:', error);
        });
}

/**
 * Load field info tooltip
 */
function loadFieldInfo(fieldId, element) {
    // Check if tooltip already exists
    const existingTooltip = element.querySelector('.field-tooltip');
    if (existingTooltip) {
        return;
    }

    // Fetch field info
    fetch(`/api/form-elements/${fieldId}`)
        .then(response => response.json())
        .then(data => {
            // Create tooltip
            const tooltip = createElement('div', { class: 'field-tooltip' });

            // Add field info
            let tooltipContent = data.label || data.id;

            if (data.options && data.options.length > 0) {
                tooltipContent += ` (${data.options.length} options available)`;
            }

            if (data.required) {
                tooltipContent += ' [Required]';
            }

            tooltip.textContent = tooltipContent;

            // Add to element
            element.appendChild(tooltip);

            // Remove after mouse leave
            element.addEventListener('mouseleave', function() {
                if (tooltip.parentNode) {
                    tooltip.parentNode.removeChild(tooltip);
                }
            });
        })
        .catch(error => {
            console.error('Error loading field info:', error);
        });
}

/**
 * Helper function to create DOM elements
 */
function createElement(tag, attributes = {}, textContent = '') {
    const element = document.createElement(tag);

    // Set attributes
    for (const [key, value] of Object.entries(attributes)) {
        element.setAttribute(key, value);
    }

    // Set text content if provided
    if (textContent) {
        element.textContent = textContent;
    }

    return element;
}

/**
 * Capture real-time form field from FLAG portal
 * This function gets called when a new field is encountered during automation
 */
function handleNewFieldCapture(fieldData) {
    // This could be implemented with WebSockets for real-time updates
    console.log('New field captured:', fieldData);

    // Update field registry
    const fieldRegistry = window.fieldRegistry || {};
    fieldRegistry[fieldData.id] = fieldData;
    window.fieldRegistry = fieldRegistry;

    // Dispatch event for UI components to react
    const event = new CustomEvent('fieldCaptured', { detail: fieldData });
    document.dispatchEvent(event);
}

/**
 * Display automated field mapping
 * Shows how a field has been mapped between the FLAG portal and application data
 */
function showFieldMapping(fieldId, mappedValue, confidence) {
    // Create or update mapping visualization
    const mappingContainer = document.getElementById('field-mappings-container') ||
                            createElement('div', { id: 'field-mappings-container' });

    if (!document.getElementById('field-mappings-container')) {
        document.body.appendChild(mappingContainer);
    }

    // Create mapping item
    const mappingItem = createElement('div', {
        class: `mapping-item ${confidence < 0.7 ? 'low-confidence' : 'high-confidence'}`,
        'data-field-id': fieldId
    });

    // Add field info
    const fieldInfo = createElement('div', { class: 'mapping-field-info' }, fieldId);
    mappingItem.appendChild(fieldInfo);

    // Add mapped value
    const valueInfo = createElement('div', { class: 'mapping-value-info' },
                                  typeof mappedValue === 'string' ? mappedValue : JSON.stringify(mappedValue));
    mappingItem.appendChild(valueInfo);

    // Add confidence indicator
    const confidenceIndicator = createElement('div', { class: 'confidence-indicator' },
                                            `${Math.round(confidence * 100)}%`);
    mappingItem.appendChild(confidenceIndicator);

    // Add to container
    mappingContainer.appendChild(mappingItem);

    // Show container
    mappingContainer.style.display = 'block';
}