import { useState } from 'react';
import { Sparkles } from 'lucide-react';
import { useAuth } from './hooks/useAuth.js';
import { LoginModal } from './LoginModal.jsx';

export function HomeLoginLauncher({
  label = 'Log in',
  className = '',
  showIcon = false,
  openWhenUnauthenticated = true,
}) {
  const { user, login } = useAuth();
  const [open, setOpen] = useState(false);

  const handleClick = () => {
    if (user) {
      window.location.assign('/app');
      return;
    }

    if (openWhenUnauthenticated) {
      setOpen(true);
      return;
    }

    window.location.assign('/app');
  };

  const handleLogin = async ({ email, password }) => {
    await login({ email, password });
    setOpen(false);
    window.location.assign('/app');
  };

  return (
    <>
      <button type="button" onClick={handleClick} className={className}>
        {showIcon ? <Sparkles size={16} aria-hidden="true" /> : null}
        {label}
      </button>
      <LoginModal open={open} onClose={() => setOpen(false)} onLogin={handleLogin} />
    </>
  );
}
