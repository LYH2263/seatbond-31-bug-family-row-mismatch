from app.services.bond_engine import (
    FAMILY_FULL,
    GENERAL_FULL,
    HoldSpan,
    SeatCell,
    find_bond_across_rows,
    parse_int_list,
    search_bond,
)


def _row(row, cols, aisles=()):
    return [SeatCell(row=row, col=c, is_aisle=(c in aisles)) for c in cols]


def _hall(rows=8, cols=12, aisles=()):
    return {r: _row(r, range(1, cols + 1), aisles) for r in range(1, rows + 1)}


def test_parse_int_list():
    assert parse_int_list("") == []
    assert parse_int_list("  ") == []
    assert parse_int_list("2, 4 ,5") == [2, 4, 5]


def test_children_must_land_in_family_row():
    seats = _hall(aisles={5, 6})  # 一号厅：段 1-4 / 7-12
    # 非家庭排有空位，但不允许进入。
    holds = [
        HoldSpan(row=6, start_col=1, end_col=2),
    ]
    result = search_bond(seats, holds, party_size=3, family_rows={6, 7}, with_children=True)
    assert result.block is not None
    assert result.block.row in {6, 7}
    assert result.block == HoldSpan(row=6, start_col=7, end_col=9)
    assert result.reason is None


def test_children_use_next_family_row_when_first_full():
    seats = _hall(aisles={5, 6})
    holds = [
        HoldSpan(row=6, start_col=7, end_col=12),
        HoldSpan(row=6, start_col=1, end_col=4),
    ]
    result = search_bond(seats, holds, party_size=2, family_rows={6, 7}, with_children=True)
    assert result.block == HoldSpan(row=7, start_col=1, end_col=2)


def test_children_fail_when_family_aisle_segments_too_short():
    """过道把家庭排连续段切短：段长只有 4，5 人亲子请求必须失败，
    即使非家庭排有 6 连座也不能跑去凑合。"""
    seats = _hall(aisles={5, 6})
    holds = [
        HoldSpan(row=6, start_col=7, end_col=11),  # 右段只剩 12；左段仅 1-4
        HoldSpan(row=7, start_col=8, end_col=12),  # 右段只剩 7；左段仅 1-4
    ]
    result = search_bond(seats, holds, party_size=5, family_rows={6, 7}, with_children=True)
    assert result.block is None
    assert result.reason == FAMILY_FULL


def test_children_fail_when_no_family_rows_configured():
    seats = _hall()
    result = search_bond(seats, [], party_size=2, family_rows=set(), with_children=True)
    assert result.block is None
    assert result.reason == FAMILY_FULL


def test_ordinary_request_avoids_family_rows():
    seats = _hall(aisles={5, 6})
    # 家庭排第 6 排左段被占，右段空；普通请求应从非家庭排第 1 排起找。
    holds = [HoldSpan(row=1, start_col=7, end_col=12)]
    result = search_bond(seats, holds, party_size=4, family_rows={6, 7}, with_children=False)
    assert result.block == HoldSpan(row=1, start_col=1, end_col=4)
    assert result.block.row not in {6, 7}


def test_ordinary_does_not_spill_into_family_when_general_area_full():
    seats = _hall(rows=4, cols=12, aisles={5, 6})
    holds = []
    # 非家庭排 1,2,4 全部占满；第 3 排是家庭排且整排空着。
    for r in (1, 2, 4):
        holds.append(HoldSpan(row=r, start_col=1, end_col=4))
        holds.append(HoldSpan(row=r, start_col=7, end_col=12))
    result = search_bond(seats, holds, party_size=2, family_rows={3}, with_children=False)
    # 家庭排整排空着，普通请求也不可占用。
    assert result.block is None
    assert result.reason == GENERAL_FULL


def test_preferred_row_must_match_family_filter():
    seats = _hall(aisles={5, 6})
    # 儿童指定家庭排第 6 排：优先生效。
    result = search_bond(
        seats, [], party_size=2, family_rows={6, 7}, with_children=True, preferred_row=7
    )
    assert result.block == HoldSpan(row=7, start_col=1, end_col=2)
    # 儿童指定非家庭排：偏好被忽略，仍在家庭排内搜索。
    result = search_bond(
        seats, [], party_size=2, family_rows={6, 7}, with_children=True, preferred_row=1
    )
    assert result.block is not None
    assert result.block.row in {6, 7}
    # 普通请求指定家庭排：偏好被忽略，仍避开家庭排。
    result = search_bond(
        seats, [], party_size=2, family_rows={6, 7}, with_children=False, preferred_row=6
    )
    assert result.block is not None
    assert result.block.row not in {6, 7}


def test_legacy_find_across_rows_still_works():
    seats = {
        1: _row(1, range(1, 5)),
        2: _row(2, range(1, 9)),
    }
    holds = [HoldSpan(row=1, start_col=1, end_col=4)]
    assert find_bond_across_rows(seats, holds, 4) == HoldSpan(row=2, start_col=1, end_col=4)
