import { useEffect, useId, useState } from 'react';
import { LockKeyhole, ShieldCheck, Eye, EyeOff } from 'lucide-react';
import { AdminView } from './AdminView.jsx';
import { Button } from '../ui/Button.jsx';
import { readSession, writeSession, removeSession } from '@/lib/storage.js';
import { cn } from '@/lib/cn.js';

const SESSION_KEY = 'obs-admin';
// Demo gate only — PUBLIC_ vars ship to the client and are NOT secure.
const PASSWORD = import.meta.env.PUBLIC_ADMIN_PASSWORD || 'firefly';

export function AdminGate() {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [value, setValue] = useState('');
  const [show, setShow] = useState(false);
  const [error, setError] = useState(false);
  const pwId = useId();

  useEffect(() => {
    setAuthed(readSession(SESSION_KEY) === 'granted');
    setReady(true);
  }, []);

  const submit = (e) => {
    e.preventDefault();
    if (value === PASSWORD) {
      writeSession(SESSION_KEY, 'granted');
      setAuthed(true);
      setError(false);
      setValue('');
    } else {
      setError(true);
    }
  };

  const lock = () => {
    removeSession(SESSION_KEY);
    setAuthed(false);
  };

  if (!ready) return null;
  if (authed) return <AdminView onLock={lock} />;

  return (
    <div className="grid min-h-[calc(100dvh-4rem)] place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="relative overflow-hidden rounded-3xl border border-border bg-surface p-7 card-shadow">
          <div className="brand-glow pointer-events-none absolute inset-0 opacity-40" aria-hidden="true" />
          <div className="relative text-center">
            <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl brand-gradient text-white">
              <LockKeyhole size={26} aria-hidden="true" />
            </span>
            <h1 className="mt-4 text-xl font-semibold text-fg">Admin access</h1>
            <p className="mt-1.5 text-sm text-muted">
              This area is restricted. Enter the admin password to continue.
            </p>
          </div>

          <form className="relative mt-6" onSubmit={submit} noValidate>
            <label htmlFor={pwId} className="mb-1.5 block text-sm font-medium text-fg">
              Password
            </label>
            <div className="relative">
              <input
                id={pwId}
                type={show ? 'text' : 'password'}
                value={value}
                autoFocus
                autoComplete="off"
                onChange={(e) => {
                  setValue(e.target.value);
                  setError(false);
                }}
                aria-invalid={error}
                aria-describedby={error ? `${pwId}-err` : undefined}
                className={cn(
                  'h-11 w-full rounded-xl border bg-surface-2 pl-3 pr-10 text-sm text-fg transition-colors',
                  error ? 'border-danger' : 'border-border focus:border-brand',
                )}
              />
              <button
                type="button"
                onClick={() => setShow((v) => !v)}
                aria-label={show ? 'Hide password' : 'Show password'}
                className="absolute right-2 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-lg text-faint hover:text-fg"
              >
                {show ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
              </button>
            </div>

            {error && (
              <p id={`${pwId}-err`} role="alert" className="mt-2 text-sm text-danger">
                Incorrect password. Please try again.
              </p>
            )}

            <Button type="submit" variant="primary" size="lg" className="mt-5 w-full">
              <ShieldCheck size={17} aria-hidden="true" /> Unlock admin panel
            </Button>
          </form>
        </div>

        <p className="mt-4 text-center text-xs text-faint">
          Demo password: <code className="rounded bg-surface-2 px-1.5 py-0.5 text-muted">{PASSWORD}</code>
          {' '}· client-side gate, not real security.
        </p>
      </div>
    </div>
  );
}
