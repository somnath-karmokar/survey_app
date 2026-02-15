from django import template
from django.utils import timezone
from datetime import datetime

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter
def sub(value, arg):
    return value - arg

@register.filter
def split(value, arg):
    return value.split(arg)

@register.filter
def timesince(value, now=None):
    if not value:
        return 0
    if now is None:
        now = timezone.now()
    if isinstance(value, (int, float)):
        return int(value)  # If it's already a number, return it as is
    delta = now - value
    return delta.days

@register.filter
def group_by_level(surveys):
    """Group surveys by their level"""
    levels = {}
    if not surveys:
        return []
        
    for survey in surveys:
        try:
            level = survey.get('survey').level
            if level not in levels:
                levels[level] = {'level': level, 'surveys': []}
            levels[level]['surveys'].append(survey)
        except (AttributeError, KeyError):
            continue
            
    return [levels[level] for level in sorted(levels.keys())] if levels else []

@register.filter
def map_dict(iterable, attr_path):
    """Map a list of dictionaries by an attribute path"""
    if not iterable:
        return []
        
    result = []
    for item in iterable:
        try:
            value = item
            for attr in attr_path.split('.'):
                value = value.get(attr) if isinstance(value, dict) else getattr(value, attr, None)
                if value is None:
                    break
            if value is not None:
                result.append(value)
        except (AttributeError, KeyError):
            continue
    return result

@register.filter
def filter_dict(iterable, condition):
    """Filter a list of dictionaries by a condition"""
    if not iterable:
        return []
    return [item for item in iterable if item.get(condition, False)]

@register.filter
def unique(iterable):
    """Return unique items from an iterable"""
    if not iterable:
        return []
    seen = set()
    return [x for x in iterable if x is not None and x not in seen and not seen.add(x)]

@register.filter
def max_(iterable):
    """Get maximum value from an iterable"""
    if not iterable:
        return 0
    try:
        return max(x for x in iterable if x is not None)
    except (ValueError, TypeError):
        return 0