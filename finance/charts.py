"""Geometry for the server-drawn SVG bar chart on the stats page.

Money stays Decimal in services.py. Here it is only converted to pixel
positions, which is the one place floats are fine: they are coordinates,
never shown or summed as money.
"""

from decimal import Decimal

from .templatetags.money import group_south_asian, taka

WIDTH = 720
HEIGHT = 300
LEFT = 92          # room for the ৳ axis labels
RIGHT = 8
TOP = 18
BOTTOM = 62        # room for month labels and verdict dots
PLOT_HEIGHT = HEIGHT - TOP - BOTTOM
BASELINE = TOP + PLOT_HEIGHT


def nice_ceiling(value):
    """Round up to 1, 2, 2.5 or 5 x 10^n so axis labels are tidy."""
    if value <= 0:
        return Decimal('1000')
    exponent = len(str(int(value))) - 1
    magnitude = Decimal(10) ** exponent
    for step in (Decimal('1'), Decimal('2'), Decimal('2.5'), Decimal('5')):
        if value <= step * magnitude:
            return step * magnitude
    return Decimal('10') * magnitude


def axis_label(amount):
    return f'৳{group_south_asian(str(int(amount)))}'


def bar_chart(months):
    """Return everything the template needs to draw the chart for `months`."""
    top_value = nice_ceiling(max([m.income for m in months] + [m.expenses for m in months]))
    group_width = (WIDTH - LEFT - RIGHT) / len(months)
    bar_width = group_width * 0.32
    gap = group_width * 0.06

    def height_for(amount):
        return float(amount / top_value) * PLOT_HEIGHT

    grid = [
        {'y': BASELINE - PLOT_HEIGHT * fraction, 'label': axis_label(top_value * Decimal(str(fraction)))}
        for fraction in (0, 0.5, 1)
    ]

    groups = []
    for index, m in enumerate(months):
        center = LEFT + group_width * (index + 0.5)
        income_h = height_for(m.income)
        expense_h = height_for(m.expenses)
        show_year = index == 0 or m.month.month == 1
        verdict_text = {
            'surplus': f'surplus {taka(m.net)}',
            'deficit': f'deficit {taka(m.shortfall)}',
            'even': 'income and expenses were equal',
            'no_income': 'no income recorded',
            'empty': 'nothing recorded',
            'future': 'not started yet',
        }[m.verdict]
        if m.verdict == 'future':
            title = f'{m.month:%B %Y}: not started yet'
        else:
            title = f'{m.month:%B %Y}: income {taka(m.income)}, expenses {taka(m.expenses)}, {verdict_text}'
        if m.over_budget:
            title += f', over the {taka(m.budget_limit)} budget'
        groups.append({
            'center': center,
            'label': f'{m.month:%b}',
            'year': f'{m.month:%Y}' if show_year else '',
            'income': {'x': center - gap / 2 - bar_width, 'y': BASELINE - income_h, 'w': bar_width, 'h': income_h},
            'expense': {'x': center + gap / 2, 'y': BASELINE - expense_h, 'w': bar_width, 'h': expense_h},
            'hit': {'x': center - group_width / 2, 'w': group_width},
            'marker_x': center + gap / 2 + bar_width / 2,
            'marker_y': BASELINE - expense_h - 10,
            'verdict': m.verdict,
            'over_budget': m.over_budget,
            'is_current': m.is_current,
            'is_future': m.verdict == 'future',
            'title': title,
        })

    return {
        'width': WIDTH,
        'height': HEIGHT,
        'left': LEFT,
        'axis_x': LEFT - 10,
        'right_edge': WIDTH - RIGHT,
        'baseline': BASELINE,
        'dot_y': BASELINE + 14,
        'label_y': BASELINE + 38,
        'year_y': BASELINE + 56,
        'grid': grid,
        'groups': groups,
    }
