import { useEffect, useState } from "react";
import { api } from "../api/client";

type Hall = {
  id: number;
  name: string;
  rows: number;
  cols: number;
  aisle_cols: number[];
  family_rows: number[];
};

export default function HallsPage() {
  const [halls, setHalls] = useState<Hall[]>([]);
  // hallId -> 编辑中的家庭排集合
  const [drafts, setDrafts] = useState<Record<number, Set<number>>>({});
  const [saving, setSaving] = useState<number | null>(null);
  const [note, setNote] = useState<Record<number, string>>({});

  useEffect(() => {
    api<Hall[]>("/halls").then(setHalls);
  }, []);

  function draftFor(h: Hall): Set<number> {
    return drafts[h.id] ?? new Set(h.family_rows);
  }

  function toggle(h: Hall, row: number) {
    const next = new Set(draftFor(h));
    if (next.has(row)) next.delete(row);
    else next.add(row);
    setDrafts((d) => ({ ...d, [h.id]: next }));
  }

  async function save(h: Hall) {
    const family = [...draftFor(h)].sort((a, b) => a - b);
    setSaving(h.id);
    setNote((n) => ({ ...n, [h.id]: "" }));
    try {
      const updated = await api<Hall>(`/halls/${h.id}/family-rows`, {
        method: "PUT",
        body: JSON.stringify({ family_rows: family }),
      });
      setHalls((list) => list.map((x) => (x.id === h.id ? updated : x)));
      setDrafts((d) => {
        const { [h.id]: _drop, ...rest } = d;
        return rest;
      });
      setNote((n) => ({ ...n, [h.id]: "已保存" }));
    } catch (e) {
      setNote((n) => ({ ...n, [h.id]: e instanceof Error ? e.message : String(e) }));
    } finally {
      setSaving(null);
    }
  }

  return (
    <>
      <h2>影厅</h2>
      <table className="table">
        <thead>
          <tr>
            <th>名称</th>
            <th>行×列</th>
            <th>过道列</th>
            <th style={{ minWidth: 280 }}>
              家庭排 <span className="hint">（点击排号标记 / 取消，整排作为亲子区）</span>
            </th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {halls.map((h) => {
            const draft = draftFor(h);
            const changed =
              [...draft].sort((a, b) => a - b).join(",") !==
              [...h.family_rows].sort((a, b) => a - b).join(",");
            return (
              <tr key={h.id}>
                <td>{h.name}</td>
                <td className="mono">
                  {h.rows} × {h.cols}
                </td>
                <td className="mono">{h.aisle_cols.join(", ") || "—"}</td>
                <td>
                  <div className="row-chips">
                    {Array.from({ length: h.rows }, (_, i) => i + 1).map((r) => (
                      <button
                        key={r}
                        type="button"
                        className={`chip${draft.has(r) ? " chip-family" : ""}`}
                        onClick={() => toggle(h, r)}
                        title={draft.has(r) ? `取消第 ${r} 排家庭排标记` : `标记第 ${r} 排为家庭排`}
                      >
                        {r}
                      </button>
                    ))}
                  </div>
                </td>
                <td>
                  <button disabled={!changed || saving === h.id} onClick={() => save(h)}>
                    {saving === h.id ? "保存中…" : "保存家庭排"}
                  </button>
                  {note[h.id] && (
                    <span
                      className={note[h.id] === "已保存" ? "ok inline-note" : "err inline-note"}
                    >
                      {note[h.id]}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}
