from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter
def get_help_text(field):
    """Safely get help text from a form field"""
    if hasattr(field, 'help_text'):
        return field.help_text
    return ''