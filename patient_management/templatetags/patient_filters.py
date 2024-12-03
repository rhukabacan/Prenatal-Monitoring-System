from django import template

register = template.Library()

@register.filter
def sub(value, arg):
    """Subtract the arg from the value."""
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return ''

@register.filter
def get_item(lst, index):
    """Get item from list by index."""
    try:
        return lst[index]
    except (IndexError, TypeError):
        return None

@register.filter
def get_attr(obj, attr):
    """Get attribute from object."""
    try:
        return getattr(obj, attr)
    except (AttributeError, TypeError):
        return None

@register.filter
def split(value, arg):
    """Split a string by delimiter."""
    return value.split(arg)

@register.filter
def int(value):
    """Convert string to integer."""
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0 