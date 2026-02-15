from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Template filter to access dictionary values by key, including keys with hyphens.
    Usage: {{ my_dict|get_item:"my-key" }}
    """
    return dictionary.get(key, '')
