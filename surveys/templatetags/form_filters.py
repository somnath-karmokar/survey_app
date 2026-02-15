from django import template
from django.forms.widgets import RadioSelect, CheckboxSelectMultiple

register = template.Library()

@register.filter(name='clean_widget_attrs')
def clean_widget_attrs(field):
    """Remove form-check-input class from widget's attrs if it's a RadioSelect or CheckboxSelectMultiple"""
    if hasattr(field, 'field') and hasattr(field.field, 'widget'):
        if isinstance(field.field.widget, (RadioSelect, CheckboxSelectMultiple)):
            if 'class' in field.field.widget.attrs and 'form-check-input' in field.field.widget.attrs['class']:
                # Remove form-check-input class from widget's attrs
                field.field.widget.attrs['class'] = field.field.widget.attrs['class'].replace('form-check-input', '').strip()
    return field
