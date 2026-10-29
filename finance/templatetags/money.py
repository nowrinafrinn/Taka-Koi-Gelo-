from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template

register = template.Library()


def group_south_asian(digits):
    """'1234567' -> '12,34,567' (last three digits, then pairs)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ','.join(pairs + [tail])


@register.filter
def taka(value):
    """Format a Decimal as Bangladeshi taka: 123456.5 -> '৳1,23,456.50'.

    Display only. Never feed the result back into a calculation.
    """
    try:
        amount = Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = '-' if amount < 0 else ''
    whole, fraction = f'{abs(amount):.2f}'.split('.')
    return f'{sign}৳{group_south_asian(whole)}.{fraction}'
