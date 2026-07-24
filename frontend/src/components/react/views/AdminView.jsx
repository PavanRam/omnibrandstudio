import { useEffect, useMemo, useState } from 'react';
import {
  Building2,
  Users,
  Upload,
  RefreshCw,
  LockKeyhole,
  Database,
  Star,
  Trash2,
  ShieldCheck,
  FileText,
  Layers,
  UserPlus,
  CheckCircle2,
  AlertTriangle,
  LayoutDashboard,
  BookOpen,
  Award,
  UploadCloud,
  KeyRound,
} from 'lucide-react';
import { Page } from '../Page.jsx';
import { Button } from '../ui/Button.jsx';
import { Badge } from '../ui/Badge.jsx';
import { cn } from '@/lib/cn.js';
import { useAuth } from '../hooks/useAuth.js';
import {
  activateGoldenSet,
  createUser,
  deleteGoldenExample,
  listBrandGuides,
  listCustomerSegments,
  listGoldenExamples,
  listGoldenSets,
  listUsers,
  openGoldenSet,
  promoteGoldenExample,
  uploadBrandGuide,
  uploadCustomerSegments,
} from '@/lib/api.js';

const DEFAULT_ORG_ID =
  import.meta.env.PUBLIC_DEFAULT_ORG_ID || '00000000-0000-0000-0000-000000000001';
const DEFAULT_BRAND_ID =
  import.meta.env.PUBLIC_DEFAULT_BRAND_ID || '00000000-0000-0000-0000-000000000002';

const inputCls =
  'h-10 w-full rounded-xl border border-border bg-surface px-3 text-sm text-fg ' +
  'placeholder:text-faint transition-colors hover:border-border-strong focus:border-brand focus:outline-none';

const ROLE_TONE = { admin: 'brand', editor: 'success', viewer: 'neutral' };
const USER_STATUS_TONE = { active: 'success', pending: 'warning', deactivated: 'danger' };

function Labeled({ label, hint, children }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold text-fg">
        {label}
        {hint && <span className="ml-2 font-normal text-faint">{hint}</span>}
      </span>
      {children}
    </label>
  );
}

function StatusBanner({ error, status }) {
  if (!error && !status) return null;
  return (
    <div
      className={cn(
        'mb-4 flex items-start gap-2 rounded-xl border px-3 py-2.5 text-sm',
        error
          ? 'border-danger/30 bg-danger/5 text-danger'
          : 'border-success/30 bg-success/5 text-success',
      )}
    >
      {error ? (
        <AlertTriangle size={15} aria-hidden="true" className="mt-0.5 shrink-0" />
      ) : (
        <CheckCircle2 size={15} aria-hidden="true" className="mt-0.5 shrink-0" />
      )}
      <span className="break-words">{error || status}</span>
    </div>
  );
}

function FileDrop({ file, onFile, hint }) {
  return (
    <label className="group flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed border-border-strong bg-surface-2 px-4 py-6 text-center transition-colors hover:border-brand hover:bg-brand-soft/40">
      <UploadCloud size={22} aria-hidden="true" className="text-faint group-hover:text-brand" />
      <span className="text-sm font-medium text-fg">
        {file ? file.name : 'Click to choose a file'}
      </span>
      {hint && <span className="text-xs text-faint">{hint}</span>}
      <input
        type="file"
        className="sr-only"
        onChange={(e) => onFile(e.target.files?.[0] || null)}
      />
    </label>
  );
}

function StatCard({ icon: Icon, label, value, accent = 'text-brand' }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-border bg-surface p-4 card-shadow">
      <span className={cn('grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-surface-2', accent)}>
        <Icon size={18} aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <p className="truncate text-xs font-medium text-muted">{label}</p>
        <p className="text-xl font-semibold tracking-tight text-fg">{value}</p>
      </div>
    </div>
  );
}

const TABS = [
  { key: 'overview', label: 'Overview', icon: LayoutDashboard },
  { key: 'users', label: 'Users', icon: Users },
  { key: 'knowledge', label: 'Knowledge', icon: BookOpen },
  { key: 'golden', label: 'Golden Dataset', icon: Award },
];

export function AdminView({ onLock }) {
  const { user } = useAuth();
  const [tab, setTab] = useState('overview');

  const [brandId, setBrandId] = useState(DEFAULT_BRAND_ID);
  const [locale, setLocale] = useState('en-US');
  const [version, setVersion] = useState('v1');

  const [file, setFile] = useState(null);
  const [guides, setGuides] = useState([]);
  const [segments, setSegments] = useState([]);
  const [segmentFile, setSegmentFile] = useState(null);
  const [loadingGuides, setLoadingGuides] = useState(false);
  const [loadingSegments, setLoadingSegments] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadingSegments, setUploadingSegments] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');

  const [managedUsers, setManagedUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [newUserName, setNewUserName] = useState('');
  const [newUserEmail, setNewUserEmail] = useState('');
  const [newUserRole, setNewUserRole] = useState('viewer');
  const [newUserPassword, setNewUserPassword] = useState('');
  const [userStatus, setUserStatus] = useState('');
  const [userError, setUserError] = useState('');
  const [userCreating, setUserCreating] = useState(false);

  const isAdmin = Boolean(user?.roles?.includes('admin'));

  const canUpload = useMemo(
    () => Boolean(brandId.trim() && locale.trim() && version.trim() && file),
    [brandId, locale, version, file],
  );
  const canUploadSegments = useMemo(
    () => Boolean(brandId.trim() && locale.trim() && version.trim() && segmentFile),
    [brandId, locale, version, segmentFile],
  );
  const canCreateUser = useMemo(
    () => Boolean(newUserName.trim() && newUserEmail.trim() && newUserRole.trim()),
    [newUserName, newUserEmail, newUserRole],
  );

  const refreshUsers = async ({ showStatus = true } = {}) => {
    setUsersLoading(true);
    setUserError('');
    try {
      const payload = await listUsers();
      setManagedUsers(payload.items || []);
      if (showStatus) {
        setUserStatus(`Loaded ${payload.count || 0} user account(s) in this tenant.`);
      }
      return payload.count || 0;
    } catch (err) {
      setUserError(err instanceof Error ? err.message : 'Failed to load users');
      return 0;
    } finally {
      setUsersLoading(false);
    }
  };

  const submitUser = async (event) => {
    event.preventDefault();
    if (!canCreateUser) return;

    setUserCreating(true);
    setUserError('');
    setUserStatus('');
    try {
      const payload = await createUser({
        name: newUserName.trim(),
        email: newUserEmail.trim(),
        role: newUserRole.trim(),
        password: newUserPassword.trim() || null,
      });
      const passwordNotice = payload.temporary_password
        ? ` Temporary password: ${payload.temporary_password}`
        : '';
      const totalUsers = await refreshUsers({ showStatus: false });
      setUserStatus(
        `Created ${payload.user?.email || newUserEmail.trim()}.${passwordNotice} Total users: ${totalUsers}.`,
      );
      setNewUserName('');
      setNewUserEmail('');
      setNewUserRole('viewer');
      setNewUserPassword('');
    } catch (err) {
      setUserError(err instanceof Error ? err.message : 'Failed to create user');
    } finally {
      setUserCreating(false);
    }
  };

  const refreshGuides = async () => {
    setLoadingGuides(true);
    setError('');
    setStatus('');
    try {
      const payload = await listBrandGuides(brandId.trim());
      setGuides(payload.items || []);
      setStatus(`Loaded ${payload.count || 0} guide record(s).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load brand guides');
    } finally {
      setLoadingGuides(false);
    }
  };

  const submitGuide = async (event) => {
    event.preventDefault();
    if (!canUpload) return;

    setUploading(true);
    setError('');
    setStatus('');
    try {
      const result = await uploadBrandGuide({
        brandId: brandId.trim(),
        locale: locale.trim(),
        version: version.trim(),
        file,
      });
      setStatus(`Indexed ${result.chunk_count || 0} chunk(s) from ${result.filename || file.name}.`);
      await refreshGuides();
      setFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const refreshSegments = async () => {
    setLoadingSegments(true);
    setError('');
    setStatus('');
    try {
      const payload = await listCustomerSegments(brandId.trim(), locale.trim(), version.trim());
      setSegments(payload.items || []);
      setStatus(`Loaded ${payload.count || 0} segment record(s).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load segments');
    } finally {
      setLoadingSegments(false);
    }
  };

  const submitSegments = async (event) => {
    event.preventDefault();
    if (!canUploadSegments) return;

    setUploadingSegments(true);
    setError('');
    setStatus('');
    try {
      const result = await uploadCustomerSegments({
        brandId: brandId.trim(),
        locale: locale.trim(),
        version: version.trim(),
        file: segmentFile,
      });
      setStatus(
        `Indexed ${result.records_indexed || 0} segment record(s) and ${result.chunks_indexed || 0} chunks.`,
      );
      await refreshSegments();
      setSegmentFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Segment upload failed');
    } finally {
      setUploadingSegments(false);
    }
  };

  // Populate KPI counts once when an admin opens the console.
  useEffect(() => {
    if (!isAdmin) return;
    refreshUsers({ showStatus: false });
    refreshGuides();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  if (!isAdmin) {
    return (
      <Page wide eyebrow="Restricted" title="Admin Console">
        <div className="relative overflow-hidden rounded-3xl border border-border bg-surface px-6 py-16 text-center card-shadow">
          <div className="brand-glow pointer-events-none absolute inset-0 opacity-30" aria-hidden="true" />
          <div className="relative mx-auto max-w-sm">
            <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-danger/10 text-danger">
              <LockKeyhole size={26} aria-hidden="true" />
            </span>
            <h2 className="mt-4 text-lg font-semibold text-fg">Admin access required</h2>
            <p className="mt-1.5 text-sm text-muted">
              You don't have permission to view this console. Ask a tenant admin to grant you the{' '}
              <span className="font-medium text-fg">admin</span> role.
            </p>
          </div>
        </div>
      </Page>
    );
  }

  return (
    <Page
      wide
      eyebrow="Control plane"
      title="Admin Console"
      description="Manage tenant users, brand knowledge, and evaluation datasets."
      actions={
        <div className="flex items-center gap-2">
          <Badge tone="brand">
            <ShieldCheck size={12} aria-hidden="true" /> {user?.email || 'admin'}
          </Badge>
          {onLock ? (
            <Button variant="outline" size="sm" onClick={onLock}>
              <LockKeyhole size={15} aria-hidden="true" /> Lock
            </Button>
          ) : null}
        </div>
      }
    >
      {/* Tab navigation */}
      <div className="flex flex-wrap items-center gap-1 rounded-2xl border border-border bg-surface p-1">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cn(
                'inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-medium transition-colors',
                active ? 'bg-brand text-brand-fg shadow-sm' : 'text-muted hover:bg-surface-2 hover:text-fg',
              )}
            >
              <Icon size={15} aria-hidden="true" />
              {t.label}
            </button>
          );
        })}
      </div>

      <div className="mt-5">
        {tab === 'overview' && (
          <OverviewPanel
            orgId={DEFAULT_ORG_ID}
            brandId={DEFAULT_BRAND_ID}
            users={managedUsers}
            guides={guides}
            segments={segments}
            onGoto={setTab}
          />
        )}

        {tab === 'users' && (
          <UsersPanel
            users={managedUsers}
            loading={usersLoading}
            error={userError}
            status={userStatus}
            onRefresh={refreshUsers}
            form={{
              name: newUserName,
              setName: setNewUserName,
              email: newUserEmail,
              setEmail: setNewUserEmail,
              role: newUserRole,
              setRole: setNewUserRole,
              password: newUserPassword,
              setPassword: setNewUserPassword,
            }}
            canCreate={canCreateUser}
            creating={userCreating}
            onSubmit={submitUser}
          />
        )}

        {(tab === 'knowledge' || tab === 'golden') && (
          <ContextBar
            brandId={brandId}
            setBrandId={setBrandId}
            locale={locale}
            setLocale={setLocale}
            version={version}
            setVersion={setVersion}
          />
        )}

        {tab === 'knowledge' && (
          <>
            <StatusBanner error={error} status={status} />
            <KnowledgePanel
              guides={guides}
              segments={segments}
              file={file}
              setFile={setFile}
              segmentFile={segmentFile}
              setSegmentFile={setSegmentFile}
              canUpload={canUpload}
              canUploadSegments={canUploadSegments}
              uploading={uploading}
              uploadingSegments={uploadingSegments}
              loadingGuides={loadingGuides}
              loadingSegments={loadingSegments}
              onSubmitGuide={submitGuide}
              onRefreshGuides={refreshGuides}
              onSubmitSegments={submitSegments}
              onRefreshSegments={refreshSegments}
            />
          </>
        )}

        {tab === 'golden' && <GoldenDatasetPanel brandId={brandId} locale={locale} version={version} />}
      </div>
    </Page>
  );
}

/* ---------------------------------------------------------------- Overview */

function OverviewPanel({ orgId, brandId, users, guides, segments, onGoto }) {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icon={Users} label="Tenant users" value={users.length} accent="text-brand" />
        <StatCard icon={FileText} label="Brand guides" value={guides.length} accent="text-success" />
        <StatCard icon={Layers} label="Segment records" value={segments.length} accent="text-warning" />
        <StatCard icon={ShieldCheck} label="Role" value="Admin" accent="text-fg" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-2xl border border-border bg-surface p-5 card-shadow">
          <div className="flex items-center gap-2">
            <Building2 size={18} aria-hidden="true" className="text-brand" />
            <h2 className="text-base font-semibold text-fg">Tenant identity</h2>
          </div>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted">Organization</dt>
              <dd className="font-mono text-xs text-fg">{orgId}</dd>
            </div>
            <div className="flex items-center justify-between gap-3 border-t border-border pt-3">
              <dt className="text-muted">Default brand</dt>
              <dd className="font-mono text-xs text-fg">{brandId}</dd>
            </div>
          </dl>
        </section>

        <section className="rounded-2xl border border-border bg-surface p-5 card-shadow">
          <h2 className="text-base font-semibold text-fg">Quick actions</h2>
          <div className="mt-4 grid gap-2">
            <QuickAction icon={UserPlus} label="Provision a user" onClick={() => onGoto('users')} />
            <QuickAction icon={Upload} label="Upload a brand guide" onClick={() => onGoto('knowledge')} />
            <QuickAction icon={Award} label="Manage golden dataset" onClick={() => onGoto('golden')} />
          </div>
        </section>
      </div>
    </div>
  );
}

function QuickAction({ icon: Icon, label, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-3 rounded-xl border border-border bg-surface-2 px-3.5 py-3 text-left text-sm font-medium text-fg transition-colors hover:border-brand hover:bg-brand-soft/40"
    >
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-brand">
        <Icon size={16} aria-hidden="true" />
      </span>
      {label}
    </button>
  );
}

/* ------------------------------------------------------------------- Users */

function initials(nameOrEmail = '') {
  const base = nameOrEmail.includes('@') ? nameOrEmail.split('@')[0] : nameOrEmail;
  const parts = base.replace(/[._-]+/g, ' ').trim().split(/\s+/).slice(0, 2);
  return (parts.map((p) => p[0]).join('') || 'U').toUpperCase();
}

function UsersPanel({ users, loading, error, status, onRefresh, form, canCreate, creating, onSubmit }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)] lg:items-start">
      {/* Create user */}
      <section className="rounded-2xl border border-border bg-surface p-5 card-shadow">
        <div className="mb-4 flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-xl brand-gradient text-white">
            <UserPlus size={18} aria-hidden="true" />
          </span>
          <div>
            <h2 className="text-base font-semibold text-fg">Add a user</h2>
            <p className="text-xs text-muted">Provision an account in this tenant.</p>
          </div>
        </div>

        <StatusBanner error={error} status={status} />

        <form className="space-y-3" onSubmit={onSubmit} autoComplete="off">
          <Labeled label="Full name">
            <input
              className={inputCls}
              value={form.name}
              onChange={(e) => form.setName(e.target.value)}
              placeholder="Jane Doe"
              autoComplete="off"
            />
          </Labeled>
          <Labeled label="Email">
            <input
              className={inputCls}
              type="email"
              value={form.email}
              onChange={(e) => form.setEmail(e.target.value)}
              placeholder="jane@company.com"
              autoComplete="off"
            />
          </Labeled>
          <div className="grid grid-cols-2 gap-3">
            <Labeled label="Role">
              <select
                className={inputCls}
                value={form.role}
                onChange={(e) => form.setRole(e.target.value)}
              >
                <option value="viewer">Viewer</option>
                <option value="editor">Editor</option>
                <option value="admin">Admin</option>
              </select>
            </Labeled>
            <Labeled label="Password" hint="optional">
              <input
                className={inputCls}
                type="password"
                minLength={8}
                value={form.password}
                onChange={(e) => form.setPassword(e.target.value)}
                placeholder="Auto-generated"
                autoComplete="new-password"
              />
            </Labeled>
          </div>
          <p className="flex items-start gap-1.5 text-xs text-faint">
            <KeyRound size={13} aria-hidden="true" className="mt-0.5 shrink-0" />
            Leave the password blank to auto-generate a temporary one, shown after creation.
          </p>
          <Button type="submit" variant="primary" size="md" className="w-full" disabled={!canCreate || creating}>
            {creating ? 'Creating…' : 'Add user'}
          </Button>
        </form>
      </section>

      {/* Users table */}
      <section className="rounded-2xl border border-border bg-surface card-shadow">
        <div className="flex items-center justify-between gap-2 border-b border-border px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-fg">Tenant users</h2>
            <p className="text-xs text-muted">{users.length} account{users.length === 1 ? '' : 's'}</p>
          </div>
          <Button variant="secondary" size="sm" onClick={() => onRefresh()} disabled={loading}>
            <RefreshCw size={14} aria-hidden="true" className={loading ? 'animate-spin' : ''} />
            {loading ? 'Loading…' : 'Refresh'}
          </Button>
        </div>

        {users.length === 0 ? (
          <div className="px-5 py-12 text-center">
            <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-surface-2 text-faint">
              <Users size={22} aria-hidden="true" />
            </span>
            <p className="mt-3 text-sm font-medium text-fg">No users yet</p>
            <p className="mt-1 text-sm text-muted">Add your first teammate with the form.</p>
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {users.map((u) => (
              <li key={u.user_id} className="flex items-center gap-3 px-5 py-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-brand-soft text-xs font-semibold text-brand">
                  {initials(u.email)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-fg">{u.email}</p>
                  <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                    {(u.roles || []).map((r) => (
                      <Badge key={r} tone={ROLE_TONE[r] || 'neutral'}>
                        {r}
                      </Badge>
                    ))}
                  </div>
                </div>
                <Badge tone={USER_STATUS_TONE[u.status] || 'neutral'}>{u.status}</Badge>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/* --------------------------------------------------------------- Context bar */

function ContextBar({ brandId, setBrandId, locale, setLocale, version, setVersion }) {
  return (
    <div className="mb-4 rounded-2xl border border-border bg-surface-2/60 p-3">
      <div className="mb-2 flex items-center gap-1.5 px-1 text-xs font-semibold uppercase tracking-wide text-faint">
        <Building2 size={12} aria-hidden="true" /> Working context
      </div>
      <div className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr]">
        <input
          className={cn(inputCls, 'font-mono text-xs')}
          value={brandId}
          onChange={(e) => setBrandId(e.target.value)}
          placeholder="Brand ID"
          aria-label="Brand ID"
        />
        <input className={inputCls} value={locale} onChange={(e) => setLocale(e.target.value)} aria-label="Locale" placeholder="Locale" />
        <input className={inputCls} value={version} onChange={(e) => setVersion(e.target.value)} aria-label="Version" placeholder="Version" />
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- Knowledge */

function KnowledgePanel({
  guides,
  segments,
  file,
  setFile,
  segmentFile,
  setSegmentFile,
  canUpload,
  canUploadSegments,
  uploading,
  uploadingSegments,
  loadingGuides,
  loadingSegments,
  onSubmitGuide,
  onRefreshGuides,
  onSubmitSegments,
  onRefreshSegments,
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* Brand guides */}
      <section className="rounded-2xl border border-border bg-surface p-5 card-shadow">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText size={18} aria-hidden="true" className="text-brand" />
            <h2 className="text-base font-semibold text-fg">Brand guides</h2>
          </div>
          <Button variant="ghost" size="sm" onClick={onRefreshGuides} disabled={loadingGuides}>
            <RefreshCw size={14} aria-hidden="true" className={loadingGuides ? 'animate-spin' : ''} />
          </Button>
        </div>

        <form className="space-y-3" onSubmit={onSubmitGuide}>
          <FileDrop file={file} onFile={setFile} hint="PDF, DOCX, MD or TXT" />
          <Button type="submit" variant="primary" size="md" className="w-full" disabled={!canUpload || uploading}>
            <Upload size={15} aria-hidden="true" /> {uploading ? 'Uploading…' : 'Upload & index guide'}
          </Button>
        </form>

        <div className="mt-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">
            Indexed guides
          </p>
          {guides.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border bg-surface-2 px-3 py-6 text-center text-sm text-muted">
              No guides indexed yet.
            </p>
          ) : (
            <ul className="space-y-2">
              {guides.map((guide) => (
                <li key={guide.id} className="flex items-center gap-3 rounded-xl border border-border bg-surface-2 px-3 py-2.5">
                  <FileText size={16} aria-hidden="true" className="shrink-0 text-faint" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-fg">{guide.source_filename}</p>
                    <p className="text-xs text-muted">
                      {guide.locale} · {guide.version} · {guide.chunk_count} chunks
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* Segments */}
      <section className="rounded-2xl border border-border bg-surface p-5 card-shadow">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Layers size={18} aria-hidden="true" className="text-brand" />
            <h2 className="text-base font-semibold text-fg">Audience segments</h2>
          </div>
          <Button variant="ghost" size="sm" onClick={onRefreshSegments} disabled={loadingSegments}>
            <RefreshCw size={14} aria-hidden="true" className={loadingSegments ? 'animate-spin' : ''} />
          </Button>
        </div>

        <form className="space-y-3" onSubmit={onSubmitSegments}>
          <FileDrop file={segmentFile} onFile={setSegmentFile} hint="CSV, JSON, TXT or MD" />
          <Button
            type="submit"
            variant="primary"
            size="md"
            className="w-full"
            disabled={!canUploadSegments || uploadingSegments}
          >
            <Users size={15} aria-hidden="true" /> {uploadingSegments ? 'Uploading…' : 'Upload & index segments'}
          </Button>
        </form>

        <div className="mt-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">
            Indexed segments
          </p>
          {segments.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border bg-surface-2 px-3 py-6 text-center text-sm text-muted">
              No segment records loaded yet.
            </p>
          ) : (
            <ul className="space-y-2">
              {segments.map((segment) => (
                <li key={segment.id} className="rounded-xl border border-border bg-surface-2 px-3 py-2.5">
                  <p className="truncate text-sm font-medium text-fg">
                    {segment.metadata?.segment || segment.metadata?.name || segment.id}
                  </p>
                  <p className="mt-0.5 line-clamp-2 text-xs text-muted">{segment.text?.slice(0, 180)}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}

/* ----------------------------------------------------------- Golden dataset */

function GoldenDatasetPanel({ brandId, locale, version }) {
  const [sets, setSets] = useState([]);
  const [examples, setExamples] = useState([]);
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');

  const refresh = async () => {
    setLoading(true);
    setError('');
    setStatus('');
    try {
      const [setsPayload, examplesPayload] = await Promise.all([
        listGoldenSets(brandId.trim()),
        listGoldenExamples(brandId.trim()),
      ]);
      setSets(setsPayload.items || []);
      setExamples(examplesPayload.items || []);
      setStatus(
        `Loaded ${setsPayload.count || 0} dataset set(s) and ${examplesPayload.count || 0} example(s).`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load golden dataset');
    } finally {
      setLoading(false);
    }
  };

  const openSet = async () => {
    setOpening(true);
    setError('');
    setStatus('');
    try {
      const result = await openGoldenSet({
        brandId: brandId.trim(),
        locale: locale.trim(),
        guideVersion: version.trim() || null,
      });
      setStatus(`Opened draft dataset set ${result.set_id?.slice(0, 8)}….`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to open dataset set');
    } finally {
      setOpening(false);
    }
  };

  const runAction = async (fn, message) => {
    setError('');
    setStatus('');
    try {
      await fn();
      setStatus(message);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed');
    }
  };

  const activate = (setId) =>
    runAction(
      () => activateGoldenSet({ brandId: brandId.trim(), setId }),
      `Activated dataset set ${setId.slice(0, 8)}….`,
    );

  const promote = (exampleId) =>
    runAction(
      () => promoteGoldenExample({ brandId: brandId.trim(), exampleId }),
      `Promoted example ${exampleId.slice(0, 8)}… to golden.`,
    );

  const remove = (exampleId) =>
    runAction(
      () => deleteGoldenExample({ brandId: brandId.trim(), exampleId }),
      `Deleted example ${exampleId.slice(0, 8)}….`,
    );

  return (
    <section className="rounded-2xl border border-border bg-surface p-5 card-shadow">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <Award size={18} aria-hidden="true" className="mt-0.5 text-brand" />
          <div>
            <h2 className="text-base font-semibold text-fg">Golden dataset</h2>
            <p className="mt-0.5 max-w-xl text-sm text-muted">
              Versioned evaluation sets that calibrate the judge panel. Activate one set per locale;
              promote strong examples to golden.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={refresh} disabled={loading}>
            <RefreshCw size={14} aria-hidden="true" className={loading ? 'animate-spin' : ''} />
            {loading ? 'Loading…' : 'Refresh'}
          </Button>
          <Button variant="primary" size="sm" onClick={openSet} disabled={opening}>
            <Database size={14} aria-hidden="true" /> {opening ? 'Opening…' : 'New draft set'}
          </Button>
        </div>
      </div>

      <StatusBanner error={error} status={status} />

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface-2 p-3.5">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Dataset sets</h3>
          {sets.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border bg-surface px-3 py-6 text-center text-sm text-muted">
              No dataset sets yet.
            </p>
          ) : (
            <ul className="space-y-2">
              {sets.map((set) => (
                <li
                  key={set.id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface px-3 py-2.5"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-fg">
                      {set.locale} · {set.guide_version || 'no version'}
                    </p>
                    <div className="mt-1 flex items-center gap-1.5">
                      <Badge tone={set.status === 'active' ? 'success' : 'neutral'}>{set.status}</Badge>
                      <span className="text-xs text-faint">{set.source}</span>
                    </div>
                  </div>
                  {set.status !== 'active' ? (
                    <Button variant="secondary" size="sm" onClick={() => activate(set.id)}>
                      Activate
                    </Button>
                  ) : (
                    <CheckCircle2 size={16} aria-hidden="true" className="shrink-0 text-success" />
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded-xl border border-border bg-surface-2 p-3.5">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Examples</h3>
          {examples.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border bg-surface px-3 py-6 text-center text-sm text-muted">
              No examples yet.
            </p>
          ) : (
            <ul className="space-y-2">
              {examples.map((example) => (
                <li
                  key={example.id}
                  className="flex items-start justify-between gap-3 rounded-lg border border-border bg-surface px-3 py-2.5"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <Badge tone={example.status === 'golden' ? 'brand' : 'neutral'}>
                        {example.status}
                      </Badge>
                      <span className="truncate text-xs font-medium text-fg">
                        {example.channel || 'any'} · {example.locale}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-muted">
                      {(example.expected_content || '').slice(0, 140)}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    {example.status !== 'golden' ? (
                      <Button variant="ghost" size="sm" onClick={() => promote(example.id)} title="Promote to golden">
                        <Star size={14} aria-hidden="true" />
                      </Button>
                    ) : null}
                    <Button variant="ghost" size="sm" onClick={() => remove(example.id)} title="Delete example">
                      <Trash2 size={14} aria-hidden="true" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
