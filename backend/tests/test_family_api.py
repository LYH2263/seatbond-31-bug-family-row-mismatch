from app.models.models import Hall, SeatHold, Showtime


def _make_hall_show(db, *, rows=8, cols=12, aisle_cols="5,6", family_rows="6,7"):
    hall = Hall(name=f"厅-{aisle_cols}-{family_rows}", rows=rows, cols=cols,
                aisle_cols=aisle_cols, family_rows=family_rows)
    db.add(hall)
    db.flush()
    show = Showtime(hall_id=hall.id, film_title="测试片", start_at=__import__("datetime").datetime.utcnow())
    db.add(show)
    db.commit()
    return hall, show


def test_seed_scenario_children_fails_but_ordinary_succeeds(client, db):
    """种子场景：家庭排已满（过道切短后无 5 连座），儿童请求失败；
    非家庭排仍有空位，普通请求（避开家庭排）成功。"""
    hall, show = _make_hall_show(db)
    db.add_all([
        SeatHold(showtime_id=show.id, order_code="F-1", row=6, start_col=7, end_col=11,
                 party_size=5, with_children=True),
        SeatHold(showtime_id=show.id, order_code="F-2", row=7, start_col=8, end_col=12,
                 party_size=5, with_children=True),
    ])
    db.commit()

    # 儿童 5 人：家庭排内左段只有 4 连座，右段只剩单座 → 409，原因指向家庭排。
    r = client.post("/api/holds", json={"showtime_id": show.id, "party_size": 5, "with_children": True})
    assert r.status_code == 409
    assert "家庭排" in r.json()["detail"]

    # 普通 5 人：避开家庭排，在非家庭排右段 7-11 成功。
    r = client.post("/api/holds", json={"showtime_id": show.id, "party_size": 5})
    assert r.status_code == 200, r.text
    hold = r.json()
    assert hold["with_children"] is False
    assert hold["row"] not in {6, 7}
    assert hold["start_col"] == 7 and hold["end_col"] == 11


def test_children_success_lands_in_family_row(client, db):
    hall, show = _make_hall_show(db)
    r = client.post("/api/holds", json={"showtime_id": show.id, "party_size": 3, "with_children": True})
    assert r.status_code == 200, r.text
    hold = r.json()
    assert hold["row"] in {6, 7}
    assert hold["with_children"] is True


def test_conflict_log_records_family_reason(client, db):
    hall, show = _make_hall_show(db)
    db.add_all([
        SeatHold(showtime_id=show.id, order_code="F-1", row=6, start_col=7, end_col=11, party_size=5),
        SeatHold(showtime_id=show.id, order_code="F-2", row=7, start_col=8, end_col=12, party_size=5),
    ])
    db.commit()
    client.post("/api/holds", json={"showtime_id": show.id, "party_size": 5, "with_children": True})
    conflicts = client.get("/api/conflicts").json()
    assert any("家庭排" in c["reason"] for c in conflicts)


def test_preferred_row_family_mismatch_rejected(client, db):
    hall, show = _make_hall_show(db)
    # 儿童请求指定非家庭排 → 422
    r = client.post("/api/holds", json={
        "showtime_id": show.id, "party_size": 2, "with_children": True, "preferred_row": 1,
    })
    assert r.status_code == 422
    # 普通请求指定家庭排 → 422
    r = client.post("/api/holds", json={
        "showtime_id": show.id, "party_size": 2, "preferred_row": 6,
    })
    assert r.status_code == 422


def test_family_rows_read_write_api(client, db):
    hall, _ = _make_hall_show(db, family_rows="")
    # 读：初始为空
    halls = client.get("/api/halls").json()
    target = next(h for h in halls if h["id"] == hall.id)
    assert target["family_rows"] == []

    # 写
    r = client.put(f"/api/halls/{hall.id}/family-rows", json={"family_rows": [2, 4, 2]})
    assert r.status_code == 200, r.text
    assert r.json()["family_rows"] == [2, 4]  # 去重排序

    # 再读已持久化
    halls = client.get("/api/halls").json()
    target = next(h for h in halls if h["id"] == hall.id)
    assert target["family_rows"] == [2, 4]

    # 清空
    r = client.put(f"/api/halls/{hall.id}/family-rows", json={"family_rows": []})
    assert r.json()["family_rows"] == []

    # 超范围 → 422
    r = client.put(f"/api/halls/{hall.id}/family-rows", json={"family_rows": [99]})
    assert r.status_code == 422

    # 不存在影厅 → 404
    r = client.put("/api/halls/9999/family-rows", json={"family_rows": []})
    assert r.status_code == 404


def test_seatmap_marks_family_rows(client, db):
    hall, show = _make_hall_show(db, family_rows="6,7")
    db.add(SeatHold(showtime_id=show.id, order_code="F-1", row=6, start_col=1, end_col=2, party_size=2))
    db.commit()
    r = client.get(f"/api/seatmap/{show.id}")
    assert r.status_code == 200
    data = r.json()
    assert data["family_rows"] == [6, 7]
    family_cells = [c for c in data["cells"] if c["is_family_row"]]
    assert {c["row"] for c in family_cells} == {6, 7}
    assert all(c["row"] in {6, 7} for c in family_cells)
    # 非家庭排单元格不带标记
    assert all(not c["is_family_row"] for c in data["cells"] if c["row"] not in {6, 7})
    # 过道标记仍在
    aisle = next(c for c in data["cells"] if c["col"] == 5)
    assert aisle["is_aisle"] is True


def test_ordinary_prefers_non_family_even_if_family_emptier(client, db):
    hall, show = _make_hall_show(db)
    # 非家庭排第 1 排占掉部分，仍应落在非家庭排而不是家庭排
    r = client.post("/api/holds", json={"showtime_id": show.id, "party_size": 4})
    assert r.status_code == 200
    assert r.json()["row"] == 1
    assert r.json()["row"] not in {6, 7}
