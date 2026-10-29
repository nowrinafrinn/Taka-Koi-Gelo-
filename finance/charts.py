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


# ---------------------------------------------------------------------------
# Spending pace line chart (dashboard)
# ---------------------------------------------------------------------------
PACE_WIDTH = 720
PACE_HEIGHT = 260
PACE_LEFT = 92
PACE_RIGHT = 16
PACE_TOP = 22
PACE_BOTTOM = 40


def pace_chart(pace):
    """SVG coordinates for running totals by day. Day 0 (start of month) is ৳0."""
    plot_w = PACE_WIDTH - PACE_LEFT - PACE_RIGHT
    plot_h = PACE_HEIGHT - PACE_TOP - PACE_BOTTOM
    baseline = PACE_TOP + plot_h
    candidates = [pace.spent] + pace.previous[-1:] + ([pace.budget_limit] if pace.budget_limit else [])
    top = nice_ceiling(max(candidates))

    def x(day):
        return PACE_LEFT + plot_w * day / pace.days_in_month

    def y(amount):
        return baseline - float(amount / top) * plot_h

    def points(totals):
        days = [(0, 0)] + [(i + 1, v) for i, v in enumerate(totals[:pace.days_in_month])]
        return ' '.join(f'{x(d):.1f},{y(v):.1f}' for d, v in days)

    labels = sorted({1, 10, 20, pace.days_in_month})
    chart = {
        'width': PACE_WIDTH,
        'height': PACE_HEIGHT,
        'left': PACE_LEFT,
        'right_edge': PACE_WIDTH - PACE_RIGHT,
        'axis_x': PACE_LEFT - 10,
        'top': PACE_TOP,
        'baseline': baseline,
        'label_y': baseline + 24,
        'grid': [
            {'y': baseline - plot_h * fraction, 'label': axis_label(top * Decimal(str(fraction)))}
            for fraction in (0, 0.5, 1)
        ],
        'days': [{'x': x(d), 'label': d} for d in labels],
        'current': points(pace.current),
        'previous': points(pace.previous) if any(pace.previous) else '',
        'today_x': x(pace.day),
        'today_y': y(pace.spent),
        'budget': None,
    }
    if pace.budget_limit:
        chart['budget'] = {'x1': x(0), 'y1': y(0), 'x2': x(pace.days_in_month), 'y2': y(pace.budget_limit)}
    return chart


def _column_frame(count, top_value):
    """Shared layout for the year bar charts: group width, baseline and grid."""
    group_width = (WIDTH - LEFT - RIGHT) / count
    grid = [
        {'y': BASELINE - PLOT_HEIGHT * fraction, 'label': axis_label(top_value * Decimal(str(fraction)))}
        for fraction in (0, 0.5, 1)
    ]
    return group_width, grid


def _frame(groups, grid):
    return {
        'width': WIDTH,
        'height': HEIGHT,
        'left': LEFT,
        'axis_x': LEFT - 10,
        'right_edge': WIDTH - RIGHT,
        'baseline': BASELINE,
        'label_y': BASELINE + 26,
        'grid': grid,
        'groups': groups,
    }


def stacked_category_chart(months, by_month, order):
    """One stacked bar per month: each segment is an expense category.

    `months` are MonthStat (Jan..Dec), `by_month` {month: {category: amount}},
    `order` the fixed category order (bottom to top). Segments are separated by
    a 2px gap so touching colours stay distinguishable.
    """
    top_value = nice_ceiling(max([m.expenses for m in months] or [Decimal('0')]))
    group_width, grid = _column_frame(len(months), top_value)
    bar_width = min(group_width * 0.5, 30)
    groups = []
    for index, m in enumerate(months):
        center = LEFT + group_width * (index + 0.5)
        y = BASELINE
        segments = []
        for category in order:
            amount = by_month.get(m.month, {}).get(category)
            if not amount:
                continue
            height = float(amount / top_value) * PLOT_HEIGHT
            label = category.label
            segments.append({
                'category': category.value, 'x': center - bar_width / 2, 'y': y - height,
                'w': bar_width, 'h': max(height - 2, 1),
                'title': f'{m.month:%B %Y}: {label} {taka(amount)}',
            })
            y -= height
        groups.append({
            'center': center, 'label': f'{m.month:%b}', 'segments': segments,
            'is_future': m.is_future,
            'title': f'{m.month:%B %Y}: expenses {taka(m.expenses)}' if not m.is_future else f'{m.month:%B %Y}: not started yet',
        })
    return _frame(groups, grid)


def budget_chart(months):
    """Budget (grey) next to spent per month. Spending within the limit is
    green; the part above the limit is red. No budget: spent bar only."""
    values = [m.expenses for m in months] + [m.budget_limit for m in months if m.budget_limit]
    top_value = nice_ceiling(max(values or [Decimal('0')]))
    group_width, grid = _column_frame(len(months), top_value)
    bar_width = min(group_width * 0.3, 18)

    def height_for(amount):
        return float(amount / top_value) * PLOT_HEIGHT

    groups = []
    for index, m in enumerate(months):
        center = LEFT + group_width * (index + 0.5)
        group = {'center': center, 'label': f'{m.month:%b}', 'is_future': m.is_future,
                 'budget': None, 'within': None, 'over': None, 'no_budget': m.budget_limit is None}
        if not m.is_future:
            spent_x = center + 1 if m.budget_limit is not None else center - bar_width / 2
            if m.budget_limit is not None:
                budget_h = height_for(m.budget_limit)
                group['budget'] = {'x': center - bar_width - 1, 'y': BASELINE - budget_h, 'w': bar_width, 'h': budget_h,
                                   'title': f'{m.month:%B %Y} budget: {taka(m.budget_limit)}'}
                within = min(m.expenses, m.budget_limit)
                over = max(m.expenses - m.budget_limit, Decimal('0'))
            else:
                within, over = m.expenses, Decimal('0')
            within_h, over_h = height_for(within), height_for(over)
            spent_title = f'{m.month:%B %Y}: spent {taka(m.expenses)}'
            if m.budget_limit is None:
                spent_title += ', no budget set'
            elif over:
                spent_title += f', over budget by {taka(over)}'
            group['within'] = {'x': spent_x, 'y': BASELINE - within_h, 'w': bar_width, 'h': within_h, 'title': spent_title}
            if over:
                group['over'] = {'x': spent_x, 'y': BASELINE - within_h - over_h, 'w': bar_width,
                                 'h': max(over_h - 2, 1), 'title': spent_title}
        groups.append(group)
    return _frame(groups, grid)


def daily_chart(daily):
    """One bar per day of the month. The biggest day is highlighted; days that
    haven't happened yet get no bar."""
    days = daily.days
    top_value = nice_ceiling(max([d.amount for d in days] or [Decimal('0')]))
    group_width, grid = _column_frame(len(days), top_value)
    bar_width = group_width * 0.62
    biggest = daily.biggest
    last = len(days)
    labelled = {1, 5, 10, 15, 20, 25, last}
    groups = []
    for index, d in enumerate(days):
        center = LEFT + group_width * (index + 0.5)
        height = float(d.amount / top_value) * PLOT_HEIGHT if d.amount else 0
        if d.is_future:
            title = f'{d.date.day} {d.date:%B}: hasn’t happened yet'
        elif d.amount:
            title = f'{d.date.day} {d.date:%B}: {taka(d.amount)} spent'
        else:
            title = f'{d.date.day} {d.date:%B}: no expenses'
        groups.append({
            'date': d.date, 'center': center, 'label': d.date.day if d.date.day in labelled else '',
            'x': center - bar_width / 2, 'y': BASELINE - height, 'w': bar_width, 'h': height,
            'is_biggest': biggest is not None and d.date == biggest.date,
            'is_future': d.is_future, 'title': title,
            'hit': {'x': center - group_width / 2, 'w': group_width},
        })
    return _frame(groups, grid)
