import { useEffect, useRef, type ReactNode } from 'react';

interface Props { title: string; busy?: boolean; onClose: () => void; children: ReactNode; }

export function Dialog({ title, busy = false, onClose, children }: Props) {
  const ref = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  const busyRef = useRef(busy);
  closeRef.current = onClose;
  busyRef.current = busy;
  useEffect(() => { ref.current?.focus(); }, [title]);
  useEffect(() => {
    const previous = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    ref.current?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopPropagation();
        if (!busyRef.current) closeRef.current();
      }
      // Theater navigation keys must never reach the underlying episode switcher.
      if (event.key.startsWith('Arrow')) event.stopPropagation();
      if (event.key !== 'Tab') return;
      const focusable = Array.from(ref.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), a[href], input:not(:disabled), [tabindex="0"]') ?? []);
      const first = focusable[0], last = focusable.at(-1);
      if (!first) { event.preventDefault(); ref.current?.focus(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === ref.current)) {
        event.preventDefault(); first.focus();
      }
    };
    const root = ref.current;
    root?.addEventListener('keydown', keydown);
    return () => {
      root?.removeEventListener('keydown', keydown);
      document.body.style.overflow = overflow;
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  return <div className="sheet-mask unlock-mask" onClick={() => { if (!busy) onClose(); }}>
    <section ref={ref} tabIndex={-1} className="unlock-sheet" role="dialog" aria-modal="true"
      aria-label={title} aria-busy={busy} onClick={event => event.stopPropagation()}>
      <header><h2>{title}</h2><button aria-label="Close" disabled={busy} onClick={onClose}>×</button></header>
      {children}
    </section>
  </div>;
}
