(function($) {
    'use strict';
    
    $(document).ready(function() {
        var $category = $('#id_category');
        var $region = $('#id_region');
        var $surveys = $('#id_surveys');
        
        function updateSurveys() {
            var categoryId = $category.val();
            var regionId = $region.val();
            
            if (categoryId || regionId) {
                // Show loading state
                $surveys.prop('disabled', true);
                
                $.get('/admin/surveys/question/get-surveys/', {
                    category_id: categoryId,
                    region_id: regionId
                }, function(data) {
                    // Clear existing options but keep the first empty one
                    $surveys.find('option').not(':first').remove();
                    
                    // Add new options
                    $.each(data, function(index, survey) {
                        $surveys.append(new Option(survey.name, survey.id));
                    });
                    
                    // Re-enable the select
                    $surveys.prop('disabled', false);
                    
                    // If there's a value already selected, make sure it's still selected
                    if ($surveys.data('initial-value')) {
                        $surveys.val($surveys.data('initial-value'));
                    }
                }).fail(function() {
                    console.error('Failed to load surveys');
                    $surveys.prop('disabled', false);
                });
            } else {
                // If no category or region is selected, clear the surveys
                $surveys.find('option').not(':first').remove();
            }
        }
        
        // Store initial value if editing
        if ($surveys.val()) {
            $surveys.data('initial-value', $surveys.val());
        }
        
        // Handle changes to category and region
        $category.on('change', updateSurveys);
        $region.on('change', updateSurveys);
        
        // Initialize on page load if values are already selected
        if ($category.val() || $region.val()) {
            updateSurveys();
        }
    });
})(django.jQuery);
