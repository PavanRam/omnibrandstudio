import { useId, useState } from 'react';
import { Sparkles, Mail, Lock } from 'lucide-react';
import { Modal } from './ui/Modal.jsx';
import { Button } from './ui/Button.jsx';
import { cn } from '@/lib/cn.js';

/** Demo sign-in dialog. Any valid-looking input "logs in" the user. */
export function LoginModal({ open, onClose, onLogin }) {
  const emailId = useId();
  const pwId = useId();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!email.includes('@') || password.length < 8) {
      setError('Enter a valid email and a password of at least 8 characters.');
      return;
    }

    setError('');
    setSubmitting(true);
    try {
      await onLogin({ email, password });
      onClose();
      setPassword('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} size="sm">
      <div className="text-center">
        <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl brand-gradient text-white">
          <Sparkles size={22} aria-hidden="true" />
        </span>
        <h2 className="mt-4 text-xl font-semibold text-fg">Welcome back</h2>
        <p className="mt-1 text-sm text-muted">
          Sign in to OmniBrand Studio to save and manage your creations.
        </p>
      </div>

      <form className="mt-6 space-y-4" onSubmit={submit} noValidate>
        <div>
          <label htmlFor={emailId} className="mb-1.5 block text-sm font-medium text-fg">
            Email
          </label>
          <div className="relative">
            <Mail
              size={16}
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
            />
            <input
              id={emailId}
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className={cn(
                'h-11 w-full rounded-xl border border-border bg-surface-2 pl-9 pr-3 text-sm text-fg',
                'transition-colors focus:border-brand focus:bg-surface',
              )}
            />
          </div>
        </div>

        <div>
          <label htmlFor={pwId} className="mb-1.5 block text-sm font-medium text-fg">
            Password
          </label>
          <div className="relative">
            <Lock
              size={16}
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
            />
            <input
              id={pwId}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className={cn(
                'h-11 w-full rounded-xl border border-border bg-surface-2 pl-9 pr-3 text-sm text-fg',
                'transition-colors focus:border-brand focus:bg-surface',
              )}
            />
          </div>
        </div>

        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}

        <Button type="submit" variant="primary" size="lg" className="w-full" disabled={submitting}>
          {submitting ? 'Signing in...' : 'Sign in'}
        </Button>
      </form>
    </Modal>
  );
}
