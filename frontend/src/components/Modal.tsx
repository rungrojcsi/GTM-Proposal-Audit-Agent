/* J02 — เปลือก modal ที่เข้าถึงได้ (accessible)

   เดิมแต่ละ modal เขียน .overlay/.modal เองและไม่มี: role="dialog", ปิดด้วย Escape,
   กักโฟกัสไว้ในกล่อง (focus trap), คืนโฟกัสให้ปุ่มเดิมเมื่อปิด */
import { useEffect, useRef } from "react";

export default function Modal({ title, width = 520, onClose, closeOnBackdrop = true, children }: {
  title: string; width?: number; onClose?: () => void; closeOnBackdrop?: boolean;
  children: React.ReactNode;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);

  /* J03 — onClose ต้องอยู่ใน ref ไม่ใช่ dependency ของ useEffect
     ทุก call site ส่ง arrow function inline (`onClose={() => ...}`) ซึ่งเปลี่ยน identity
     ทุกครั้งที่ parent re-render. ถ้าใส่ใน dep array -> พิมพ์ 1 ตัวอักษรในช่อง input
     -> setState -> re-render -> onClose ใหม่ -> effect cleanup+rerun -> โฟกัสเด้งไป
     focusables()[0] (ปุ่มตัวแรกในกล่อง) ทุกครั้ง = พิมพ์ได้ทีละตัวเดียว
     (Boss เจอจริงที่ modal "ยืนยันก่อนประเมิน" ช่อง Client/Project name)
     effect นี้ต้องรันครั้งเดียวตอน mount เท่านั้น */
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    returnTo.current = document.activeElement as HTMLElement | null;
    const focusables = () => Array.from(
      boxRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
      ) ?? [],
    );
    focusables()[0]?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onCloseRef.current?.(); return; }
      if (e.key !== "Tab") return;
      const f = focusables();
      if (f.length === 0) return;
      const first = f[0], last = f[f.length - 1];
      // focus trap: Tab ที่ตัวท้ายวนกลับตัวแรก และ Shift+Tab ที่ตัวแรกวนไปตัวท้าย
      if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); returnTo.current?.focus?.(); };
  }, []);

  return (
    <div className="overlay" onClick={() => closeOnBackdrop && onClose?.()}>
      <div ref={boxRef} className="modal" style={{ width }} role="dialog" aria-modal="true"
        aria-label={title} onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}
