"""Contiguous seat bonding: aisle columns break runs; holds conflict on overlap.

Family rows partition the auditorium for auto search:
* requests travelling with children may ONLY land inside family rows;
* ordinary requests avoid family rows by default so the parent-child area
  stays available.
Aisle breaking always applies on top of the row filter, so a children request
inside family rows can still fail when aisles cut every contiguous segment
short — that failure is reported as FAMILY_FULL rather than silently falling
back to non-family rows.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeatCell:
    row: int
    col: int
    is_aisle: bool = False


@dataclass(frozen=True)
class HoldSpan:
    row: int
    start_col: int
    end_col: int  # inclusive


# Failure reason codes for search_bond.
FAMILY_FULL = "family_full"  # children request: no long-enough free segment within family rows
GENERAL_FULL = "general_full"  # ordinary request: no long-enough free segment outside family rows


@dataclass(frozen=True)
class BondSearchResult:
    block: HoldSpan | None
    reason: str | None = None  # None when block is found


def parse_int_list(raw: str) -> list[int]:
    """Parse a comma-separated int list ('2,4, 5') tolerating blanks."""
    if not raw or not raw.strip():
        return []
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    return out



def contiguous_runs(row_cells: list[SeatCell]) -> list[tuple[int, int]]:
    """Return inclusive (start_col, end_col) runs of non-aisle seats, broken by aisles."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    prev_col: int | None = None
    for cell in sorted(row_cells, key=lambda c: c.col):
        if cell.is_aisle:
            if start is not None and prev_col is not None:
                runs.append((start, prev_col))
            start = None
            prev_col = None
            continue
        if start is None:
            start = cell.col
        elif prev_col is not None and cell.col != prev_col + 1:
            runs.append((start, prev_col))
            start = cell.col
        prev_col = cell.col
    if start is not None and prev_col is not None:
        runs.append((start, prev_col))
    return runs


def occupied_cols(holds: list[HoldSpan], row: int) -> set[int]:
    cols: set[int] = set()
    for h in holds:
        if h.row != row:
            continue
        for c in range(h.start_col, h.end_col + 1):
            cols.add(c)
    return cols


def find_contiguous_block(
    row_cells: list[SeatCell],
    holds: list[HoldSpan],
    row: int,
    party_size: int,
) -> HoldSpan | None:
    """Find leftmost contiguous empty seats of party_size in a row."""
    if party_size <= 0:
        return None
    taken = occupied_cols(holds, row)
    for start, end in contiguous_runs(row_cells):
        free = [c for c in range(start, end + 1) if c not in taken]
        # free may have holes if holds punched middle — rebuild consecutive segments
        seg_start: int | None = None
        prev: int | None = None
        for col in free:
            if seg_start is None:
                seg_start = col
            elif prev is not None and col != prev + 1:
                if prev - seg_start + 1 >= party_size:
                    return HoldSpan(row=row, start_col=seg_start, end_col=seg_start + party_size - 1)
                seg_start = col
            prev = col
        if seg_start is not None and prev is not None and prev - seg_start + 1 >= party_size:
            return HoldSpan(row=row, start_col=seg_start, end_col=seg_start + party_size - 1)
    return None


def find_bond_across_rows(
    seats_by_row: dict[int, list[SeatCell]],
    holds: list[HoldSpan],
    party_size: int,
) -> HoldSpan | None:
    for row in sorted(seats_by_row.keys()):
        block = find_contiguous_block(seats_by_row[row], holds, row, party_size)
        if block is not None:
            return block
    return None


def search_bond(
    seats_by_row: dict[int, list[SeatCell]],
    holds: list[HoldSpan],
    party_size: int,
    family_rows: set[int],
    with_children: bool,
    preferred_row: int | None = None,
) -> BondSearchResult:
    """Search for a contiguous block under family-row and aisle constraints.

    Children requests are confined to family rows; failure there returns
    FAMILY_FULL even if non-family rows still have seats — aisle cuts are
    evaluated first inside each family row, so a too-short family segment is
    never papered over by spilling into the ordinary area.
    Ordinary requests search only non-family rows and never fall back into
    family rows, returning GENERAL_FULL when the ordinary area is exhausted.
    """
    allowed_rows = {r for r in seats_by_row if (r in family_rows) != with_children}
    if with_children and not family_rows:
        return BondSearchResult(block=None, reason=FAMILY_FULL)
    if not allowed_rows:
        return BondSearchResult(
            block=None, reason=FAMILY_FULL if with_children else GENERAL_FULL
        )

    # A preferred row is honoured only when it passes the family filter.
    if preferred_row is not None and preferred_row in allowed_rows:
        block = find_contiguous_block(
            seats_by_row.get(preferred_row, []), holds, preferred_row, party_size
        )
        if block is not None:
            return BondSearchResult(block=block)

    for row in sorted(allowed_rows):
        block = find_contiguous_block(seats_by_row[row], holds, row, party_size)
        if block is not None:
            return BondSearchResult(block=block)

    return BondSearchResult(
        block=None, reason=FAMILY_FULL if with_children else GENERAL_FULL
    )


def conflicts_with(existing: list[HoldSpan], candidate: HoldSpan) -> list[HoldSpan]:
    hits: list[HoldSpan] = []
    for h in existing:
        if h.row != candidate.row:
            continue
        if h.end_col < candidate.start_col or candidate.end_col < h.start_col:
            continue
        hits.append(h)
    return hits
