from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import ConflictLog, Hall, SeatHold, Showtime


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(Hall.id).limit(1)):
        return
    # 一号厅：过道在 5,6 列，把每行切成 1-4（4 座）与 7-12（6 座）两段；
    # 第 6,7 排标为家庭排。
    h1 = Hall(name="一号厅", rows=8, cols=12, aisle_cols="5,6", family_rows="6,7")
    # 二号厅：过道在 4,5 列，第 5 排为家庭排。
    h2 = Hall(name="二号厅", rows=6, cols=10, aisle_cols="4,5", family_rows="5")
    db.add_all([h1, h2])
    db.flush()
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    s1 = Showtime(hall_id=h1.id, film_title="星际旅人", start_at=now + timedelta(hours=2))
    s2 = Showtime(hall_id=h1.id, film_title="雾都夜曲", start_at=now + timedelta(hours=5))
    s3 = Showtime(hall_id=h2.id, film_title="山海经异", start_at=now + timedelta(hours=3))
    db.add_all([s1, s2, s3])
    db.flush()
    db.add_all(
        [
            SeatHold(showtime_id=s1.id, order_code="SB-1001", row=3, start_col=2, end_col=4, party_size=3),
            SeatHold(showtime_id=s1.id, order_code="SB-1002", row=5, start_col=7, end_col=9, party_size=3),
            # 家庭排第 6 排：右段 7-12 被占 7-11，仅剩 12 号单座；左段 1-4 全空但只有 4 连座。
            SeatHold(
                showtime_id=s1.id, order_code="SB-1004", row=6, start_col=7, end_col=11,
                party_size=5, with_children=True,
            ),
            # 家庭排第 7 排：右段被占 8-12，仅剩 7 号单座；左段仍只有 4 连座。
            # 于是 5 人亲子请求在两个家庭排内都凑不出连续段，而非家庭排（1-5、8 排）仍有空位。
            SeatHold(
                showtime_id=s1.id, order_code="SB-1005", row=7, start_col=8, end_col=12,
                party_size=5, with_children=True,
            ),
            SeatHold(showtime_id=s3.id, order_code="SB-1003", row=2, start_col=1, end_col=2, party_size=2),
        ]
    )
    db.add(ConflictLog(showtime_id=s1.id, party_size=4, reason="与既有持座重叠：第3排 2-4"))
    db.add(
        ConflictLog(
            showtime_id=s1.id,
            party_size=5,
            reason="家庭排内无足够连续空座（人数 5，过道会切断连续段，且带儿童请求不可使用非家庭排）",
        )
    )
    db.commit()
