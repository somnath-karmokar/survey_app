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