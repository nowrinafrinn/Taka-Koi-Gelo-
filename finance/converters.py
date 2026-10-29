import datetime


class IsoDateConverter:
    """URL part 'YYYY-MM-DD' <-> datetime.date.

    Only this exact form matches, so each day has one URL. A well-formed but
    impossible date (2026-02-30) raises ValueError, which Django turns into a 404.
    """

    regex = r'\d{4}-\d{2}-\d{2}'

    def to_python(self, value):
        return datetime.date.fromisoformat(value)

    def to_url(self, value):
        return value.isoformat() if hasattr(value, 'isoformat') else str(value)
