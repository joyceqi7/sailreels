import { useEffect, useState, type ReactNode } from 'react';
import { MOCK_API_ENABLED } from '../api/config';
import { initializeSession } from '../minis/session';

/** Mock catalog previews never create or store a simulated login session. */
export function SessionGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>(
    MOCK_API_ENABLED ? 'ready' : 'loading',
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (MOCK_API_ENABLED) return;
    let active = true;
    setStatus('loading');
    initializeSession().then(
      () => { if (active) setStatus('ready'); },
      () => { if (active) setStatus('error'); },
    );
    return () => { active = false; };
  }, [attempt]);

  if (status === 'ready') return children;
  return (
    <main className="app-shell">
      <section className="session-state" aria-live="polite" aria-busy={status === 'loading'}>
        {status === 'loading' ? <p role="status">Signing you in…</p> : (
          <>
            <h1>Unable to sign in</h1>
            <p>Please check your connection and try again.</p>
            <button onClick={() => { setStatus('loading'); setAttempt(value => value + 1); }}>
              Try again
            </button>
          </>
        )}
      </section>
    </main>
  );
}
