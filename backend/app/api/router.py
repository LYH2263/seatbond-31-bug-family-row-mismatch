from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import ConflictLog, Hall, SeatHold, Showtime
from app.schemas.schemas import (
    ConflictOut,
    HallFamilyUpdate,
    HallOut,
    HoldOut,
    HoldRequest,
    SeatMapCell,
    SeatMapOut,
    ShowtimeOut,
)
from app.services.bond_engine import (
    FAMILY_FULL,
    HoldSpan,
    SeatCell,
    conflicts_with,
    parse_int_list,
    search_bond,
)

api_router = APIRouter()


def _aisles(hall: Hall) -> list[int]:
    return parse_int_list(hall.aisle_cols)


def _family_rows(hall: Hall) -> list[int]:
    return parse_int_list(hall.family_rows)


def _hall_out(h: Hall) -> HallOut:
    return HallOut(
        id=h.id,
        name=h.name,
        rows=h.rows,
        cols=h.cols,
        aisle_cols=_aisles(h),
        family_rows=_family_rows(h),
    )


def _build_seats_by_row(hall: Hall, aisles: set[int]) -> dict[int, list[SeatCell]]:
    seats_by_row: dict[int, list[SeatCell]] = {}
    for r in range(1, hall.rows + 1):
        seats_by_row[r] = [
            SeatCell(row=r, col=c, is_aisle=c in aisles) for c in range(1, hall.cols + 1)
        ]
    return seats_by_row


@api_router.get("/health")
def health():
    return {"status": "ok"}


@api_router.get("/halls", response_model=list[HallOut])
def list_halls(db: Session = Depends(get_db)):
    return [_hall_out(h) for h in db.scalars(select(Hall).order_by(Hall.id)).all()]


@api_router.put("/halls/{hall_id}/family-rows", response_model=HallOut)
def update_family_rows(hall_id: int, body: HallFamilyUpdate, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "影厅不存在")
    invalid = [r for r in body.family_rows if r < 1 or r > hall.rows]
    if invalid:
        raise HTTPException(422, f"家庭排编号超出范围（1-{hall.rows}）：{invalid}")
    # 去重并排序，统一逗号分隔存储。
    hall.family_rows = ",".join(str(r) for r in sorted(set(body.family_rows)))
    db.commit()
    db.refresh(hall)
    return _hall_out(hall)


@api_router.get("/showtimes", response_model=list[ShowtimeOut])
def list_showtimes(db: Session = Depends(get_db)):
    rows = db.scalars(select(Showtime).order_by(Showtime.start_at)).all()
    out = []
    for s in rows:
        hall = db.get(Hall, s.hall_id)
        out.append(
            ShowtimeOut(
                id=s.id,
                hall_id=s.hall_id,
                film_title=s.film_title,
                start_at=s.start_at,
                hall_name=hall.name if hall else None,
            )
        )
    return out


@api_router.get("/seatmap/{showtime_id}", response_model=SeatMapOut)
def seatmap(showtime_id: int, db: Session = Depends(get_db)):
    st = db.get(Showtime, showtime_id)
    if not st:
        raise HTTPException(404, "场次不存在")
    hall = db.get(Hall, st.hall_id)
    assert hall
    aisles = set(_aisles(hall))
    family = set(_family_rows(hall))
    holds = db.scalars(select(SeatHold).where(SeatHold.showtime_id == showtime_id)).all()
    occupied: set[tuple[int, int]] = set()
    for h in holds:
        for c in range(h.start_col, h.end_col + 1):
            occupied.add((h.row, c))
    cells: list[SeatMapCell] = []
    total = hall.rows * hall.cols
    for r in range(1, hall.rows + 1):
        for c in range(1, hall.cols + 1):
            occ = (r, c) in occupied
            cells.append(
                SeatMapCell(
                    row=r,
                    col=c,
                    is_aisle=c in aisles,
                    is_family_row=r in family,
                    occupied=occ,
                    heat=1.0 if occ else (0.15 if c in aisles else 0.0),
                )
            )
    return SeatMapOut(
        showtime_id=showtime_id,
        hall_name=hall.name,
        rows=hall.rows,
        cols=hall.cols,
        family_rows=sorted(family),
        cells=cells,
    )


@api_router.get("/holds", response_model=list[HoldOut])
def list_holds(db: Session = Depends(get_db)):
    return db.scalars(select(SeatHold).order_by(SeatHold.id.desc())).all()


@api_router.get("/conflicts", response_model=list[ConflictOut])
def list_conflicts(db: Session = Depends(get_db)):
    return db.scalars(select(ConflictLog).order_by(ConflictLog.id.desc())).all()


@api_router.post("/holds", response_model=HoldOut)
def create_hold(body: HoldRequest, db: Session = Depends(get_db)):
    st = db.get(Showtime, body.showtime_id)
    if not st:
        raise HTTPException(404, "场次不存在")
    hall = db.get(Hall, st.hall_id)
    assert hall
    aisles = set(_aisles(hall))
    family_rows = set(_family_rows(hall))
    existing = db.scalars(select(SeatHold).where(SeatHold.showtime_id == body.showtime_id)).all()
    holds = [HoldSpan(row=h.row, start_col=h.start_col, end_col=h.end_col) for h in existing]
    seats_by_row = _build_seats_by_row(hall, aisles)

    # Preferred rows outside the family filter are rejected for clarity: a
    # children request must stay in a family row, and an ordinary request must
    # not be guided into the parent-child area.
    if body.preferred_row is not None:
        in_family = body.preferred_row in family_rows
        if body.with_children and not in_family:
            raise HTTPException(422, "带儿童请求只能选择家庭排")
        if not body.with_children and in_family:
            raise HTTPException(422, "普通请求默认避开家庭排")

    result = search_bond(
        seats_by_row,
        holds,
        body.party_size,
        family_rows,
        body.with_children,
        preferred_row=body.preferred_row,
    )
    block = result.block
    if block is None:
        # 同一条原因同时写入冲突日志和 409 响应，保证锁座页提示与冲突页一致。
        if result.reason == FAMILY_FULL:
            message = (
                f"家庭排内无足够连续空座（人数 {body.party_size}，过道会切断连续段，"
                "且带儿童请求不可使用非家庭排）"
            )
        else:
            message = (
                f"非家庭排无足够连续空座（人数 {body.party_size}，普通请求默认避开家庭排）"
            )
        db.add(
            ConflictLog(
                showtime_id=body.showtime_id,
                party_size=body.party_size,
                reason=message,
            )
        )
        db.commit()
        raise HTTPException(409, message)

    hits = conflicts_with(holds, block)
    if hits:
        message = f"与既有持座冲突：第{hits[0].row}排 {hits[0].start_col}-{hits[0].end_col}"
        db.add(
            ConflictLog(
                showtime_id=body.showtime_id,
                party_size=body.party_size,
                reason=message,
            )
        )
        db.commit()
        raise HTTPException(409, message)

    code = f"SB-{int(datetime.utcnow().timestamp()) % 100000:05d}"
    hold = SeatHold(
        showtime_id=body.showtime_id,
        order_code=code,
        row=block.row,
        start_col=block.start_col,
        end_col=block.end_col,
        party_size=body.party_size,
        with_children=body.with_children,
    )
    db.add(hold)
    db.commit()
    db.refresh(hold)
    return hold
