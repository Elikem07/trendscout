"""Feed queries (M3.T8, amendment A1).

emerging  : trend_label = emerging (change point <= 21d, momentum > 1.1)
hot_now   : demand >= 70, momentum >= 1.0, competition <= 65
trending  : rising or emerging, ranked by opportunity
saturated : trend_label = saturated
"""

import datetime
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Score

HOT_DEMAND_MIN = 70.0
HOT_MOMENTUM_MIN = 1.0
HOT_COMPETITION_MAX = 65.0

FEEDS = ("emerging", "hot_now", "trending", "saturated")


def feed(
    session: Session,
    name: str,
    day: datetime.date | None = None,
    limit: int = 50,
) -> Sequence[Score]:
    day = day or datetime.date.today()
    q = select(Score).where(Score.date == day)
    if name == "emerging":
        q = q.where(Score.trend_label == "emerging")
    elif name == "hot_now":
        q = q.where(
            Score.demand >= HOT_DEMAND_MIN,
            Score.momentum >= HOT_MOMENTUM_MIN,
            Score.competition <= HOT_COMPETITION_MAX,
        )
    elif name == "trending":
        q = q.where(Score.trend_label.in_(("rising", "emerging")))
    elif name == "saturated":
        q = q.where(Score.trend_label == "saturated")
    else:
        raise ValueError(f"unknown feed: {name!r}")
    return session.scalars(q.order_by(Score.opportunity.desc()).limit(limit)).all()
