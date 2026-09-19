import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";

type Show = { id: number; film_title: string; hall_name?: string };
type Cell = {
  row: number;
  col: number;
  is_aisle: boolean;
  is_family_row: boolean;
  occupied: boolean;
  heat: number;
};
type MapOut = {
  showtime_id: number;
  hall_name: string;
  rows: number;
  cols: number;
  family_rows: number[];
  cells: Cell[];
};

export default function SeatMapPage() {
  const [shows, setShows] = useState<Show[]>([]);
  const [sid, setSid] = useState<number | "">("");
  const [map, setMap] = useState<MapOut | null>(null);

  useEffect(() => {
    api<Show[]>("/showtimes").then((s) => {
      setShows(s);
      if (s[0]) setSid(s[0].id);
    });
  }, []);

  useEffect(() => {
    if (sid === "") return;
    api<MapOut>(`/seatmap/${sid}`).then(setMap);
  }, [sid]);

  const familyRows = useMemo(() => new Set(map?.family_rows ?? []), [map]);
  const gridStyle = useMemo(
    () =>
      map
        ? {
            // 首列留给排号，再加座位列。
            gridTemplateColumns: `22px repeat(${map.cols}, 28px)`,
          }
        : undefined,
    [map]
  );

  // rows 从银幕往后排；排号列固定金色显示家庭排。
  const rowNumbers = map ? Array.from({ length: map.rows }, (_, i) => i + 1) : [];

  return (
    <>
      <div className="toolbar">
        <label>
          场次{" "}
          <select value={sid} onChange={(e) => setSid(Number(e.target.value))}>
            {shows.map((s) => (
              <option key={s.id} value={s.id}>
                {s.film_title} · {s.hall_name}
              </option>
            ))}
          </select>
        </label>
        {map && (
          <span className="mono">
            {map.hall_name} · {map.rows}×{map.cols} · 热力座图
          </span>
        )}
        <span className="legend">
          <span className="legend-swatch family" /> 家庭排（亲子区）
          <span className="legend-swatch aisle-s" /> 过道
          <span className="legend-swatch occupied-s" /> 已锁
        </span>
      </div>
      <div className="screen">银 幕</div>
      {map && (
        <div className="seat-grid" style={gridStyle}>
          {rowNumbers.map((r) => [
            <div
              key={`rowlabel-${r}`}
              className={`row-label${familyRows.has(r) ? " row-label-family" : ""}`}
              title={familyRows.has(r) ? `第 ${r} 排 · 家庭排` : `第 ${r} 排`}
            >
              {r}
            </div>,
            ...map.cells
              .filter((c) => c.row === r)
              .map((c) => (
                <div
                  key={`${c.row}-${c.col}`}
                  className={[
                    "seat",
                    c.is_aisle ? "aisle" : c.occupied ? "occ" : "free",
                    c.is_family_row && !c.is_aisle ? "family-row" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  title={`R${c.row}C${c.col}${c.is_family_row ? " · 家庭排" : ""}`}
                  style={
                    !c.is_aisle && c.heat
                      ? {
                          boxShadow: [
                            `inset 0 0 0 1px rgba(255,180,80,${Math.min(0.9, c.heat / 10)})`,
                            c.is_family_row
                              ? "inset 0 0 0 1.5px rgba(232,196,106,.9), 0 0 10px rgba(232,196,106,.35)"
                              : "",
                          ]
                            .filter(Boolean)
                            .join(", "),
                        }
                      : undefined
                  }
                >
                  {c.is_aisle ? "" : c.col}
                </div>
              )),
          ])}
        </div>
      )}
    </>
  );
}
