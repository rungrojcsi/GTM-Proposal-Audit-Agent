/* J03 — หัวคอลัมน์ที่เรียงลำดับได้ แบบเข้าถึงได้ (accessible)

   เดิมเป็น <th onClick> เฉย ๆ: กดด้วยคีย์บอร์ดไม่ได้ และ screen reader ไม่รู้ว่าเรียงอยู่ไหม
   ตอนนี้ใส่ปุ่มจริงข้างใน + aria-sort ตามสถานะ */
export function SortableTh({ label, active, dir, onSort, width }: {
  label: string; active: boolean; dir: "asc" | "desc"; onSort: () => void; width?: string;
}) {
  return (
    <th aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
      style={{ whiteSpace: "nowrap", padding: 0, width }}>
      <button onClick={onSort} title={`เรียงตาม ${label}`}
        style={{
          all: "unset", cursor: "pointer", display: "flex", alignItems: "center", gap: 4,
          width: "100%", padding: "12px 16px", font: "inherit", color: "inherit",
          textTransform: "inherit", letterSpacing: "inherit", boxSizing: "border-box",
        }}>
        {label}
        <span aria-hidden="true" style={{ opacity: active ? 1 : 0.25 }}>
          {active ? (dir === "asc" ? "▲" : "▼") : "▾"}
        </span>
      </button>
    </th>
  );
}
export default SortableTh;
