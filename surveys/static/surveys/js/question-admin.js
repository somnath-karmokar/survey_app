document.addEventListener('DOMContentLoaded', function() {
    // Get the country and category select elements
    const countrySelect = document.getElementById('id_country');
    const categorySelect = document.getElementById('id_category');
    const surveysSelect = document.querySelector('#surveys_to');
    
    if (countrySelect && categorySelect && surveysSelect) {
        // Function to update surveys based on selected country and category
        function updateSurveys() {
            const countryId = countrySelect.value;
            const categoryId = categorySelect.value;
            
            // Build the URL with query parameters
            let url = '/admin/surveys/question/get-surveys/';
            const params = new URLSearchParams();
            
            if (countryId) params.append('country_id', countryId);
            if (categoryId) params.append('category_id', categoryId);
            
            if (params.toString()) {
                url += '?' + params.toString();
            }
            
            // Make the AJAX request
            fetch(url, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(response => response.json())
            .then(data => {
                // Clear existing options
                surveysSelect.innerHTML = '';
                
                // Add new options
                data.forEach(survey => {
                    const option = document.createElement('option');
                    option.value = survey.id;
                    option.textContent = survey.name;
                    surveysSelect.appendChild(option);
                });
            })
            .catch(error => {
                console.error('Error fetching surveys:', error);
            });
        }
        
        // Add event listeners
        countrySelect.addEventListener('change', updateSurveys);
        categorySelect.addEventListener('change', updateSurveys);
        
        // Initial update
        updateSurveys();
    }
});
