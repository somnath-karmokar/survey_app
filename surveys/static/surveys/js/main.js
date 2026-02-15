// Main JavaScript for Survey App
document.addEventListener('DOMContentLoaded', function() {
    // Enable Bootstrap tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Add active class to current nav item
    const currentLocation = location.href;
    const menuItems = document.querySelectorAll('.nav-link');
    const menuLength = menuItems.length;
    
    for (let i = 0; i < menuLength; i++) {
        if (menuItems[i].href === currentLocation) {
            menuItems[i].classList.add('active');
            menuItems[i].setAttribute('aria-current', 'page');
        }
    }

    // Auto-hide alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });

    // Handle survey form validation
    const surveyForm = document.getElementById('survey-form');
    if (surveyForm) {
        surveyForm.addEventListener('submit', function(e) {
            const requiredFields = surveyForm.querySelectorAll('[required]');
            let isValid = true;
            
            requiredFields.forEach(field => {
                if (!field.value.trim()) {
                    isValid = false;
                    field.classList.add('is-invalid');
                } else {
                    field.classList.remove('is-invalid');
                }
            });
            
            if (!isValid) {
                e.preventDefault();
                // Scroll to first invalid field
                const firstInvalid = surveyForm.querySelector('.is-invalid');
                if (firstInvalid) {
                    firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
        });
    }

    // Handle character counters for textareas
    const textareas = document.querySelectorAll('textarea[maxlength]');
    textareas.forEach(textarea => {
        const maxLength = textarea.getAttribute('maxlength');
        const counter = document.createElement('small');
        counter.className = 'form-text text-muted text-end d-block';
        counter.textContent = `0/${maxLength} characters`;
        
        textarea.parentNode.insertBefore(counter, textarea.nextSibling);
        
        textarea.addEventListener('input', function() {
            const currentLength = this.value.length;
            counter.textContent = `${currentLength}/${maxLength} characters`;
            
            if (currentLength > maxLength * 0.8) {
                counter.classList.add('text-warning');
            } else {
                counter.classList.remove('text-warning');
            }
        });
    });

    // Handle rating inputs
    const ratingInputs = document.querySelectorAll('.rating-input');
    ratingInputs.forEach(input => {
        input.addEventListener('change', function() {
            const value = this.value;
            const container = this.closest('.rating-container');
            const stars = container.querySelectorAll('.rating-star');
            
            stars.forEach((star, index) => {
                if (index < value) {
                    star.classList.add('text-warning');
                    star.classList.remove('text-muted');
                } else {
                    star.classList.remove('text-warning');
                    star.classList.add('text-muted');
                }
            });
        });
    });
});

// Utility function to show loading state
function setLoadingState(button, isLoading) {
    const originalText = button.innerHTML;
    
    if (isLoading) {
        button.disabled = true;
        button.innerHTML = `
            <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
            <span class="visually-hidden">Loading...</span>
            ${button.getAttribute('data-loading-text') || 'Processing...'}
        `;
    } else {
        button.disabled = false;
        button.innerHTML = originalText;
    }
}

// Handle form submissions with loading state
document.addEventListener('submit', function(e) {
    const form = e.target;
    const submitButton = form.querySelector('button[type="submit"]');
    
    if (submitButton) {
        setLoadingState(submitButton, true);
        
        // Re-enable the button if the form is invalid
        if (!form.checkValidity()) {
            setLoadingState(submitButton, false);
        }
    }
});
