from django import template

register = template.Library()

@register.filter
def abbreviate_name(name):
    """
    Convert a full name to abbreviated format like 'S. Karmokar'
    Takes first letter of first word followed by dot and space, then the rest
    """
    if not name:
        return name
    
    words = name.split()
    if len(words) == 0:
        return name
    elif len(words) == 1:
        return name
    else:
        # Take first letter of first word, add dot, then join remaining words
        first_initial = words[0][0].upper() if words[0] else ''
        remaining_name = ' '.join(words[1:])
        return f"{first_initial}. {remaining_name}"
