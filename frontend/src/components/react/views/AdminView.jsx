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
  X,
  Plus,
  Eye,
} from 'lucide-react';
import { Page } from '../Page.jsx';
import { Modal } from '../ui/Modal.jsx';
import { Button } from '../ui/Button.jsx';
import { Badge } from '../ui/Badge.jsx';
import { cn } from '@/lib/cn.js';
import { useAuth } from '../hooks/useAuth.js';
import {
  activateGoldenSet,
  createBrand,
  createUser,
  deleteGoldenExample,
  getBrandConfig,
  listBrandGuides,
  listBrands,
  listCustomerSegments,
  listGoldenExamples,
  listGoldenSets,
  listUsers,
  openGoldenSet,
  promoteGoldenExample,
  updateBrandConfig,
  updateUser,
  updateUserBrands,
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
  { key: 'brand', label: 'Brand Profile', icon: Building2 },
  { key: 'knowledge', label: 'Knowledge', icon: BookOpen },
  { key: 'golden', label: 'Golden Dataset', icon: Award },
];

export function AdminView({ onLock }) {
  const { user } = useAuth();
  const [tab, setTab] = useState('overview');

  const [brandId, setBrandId] = useState(DEFAULT_BRAND_ID);
  const [locale, setLocale] = useState('en-US');
  const [version, setVersion] = useState('v1');

  // Multi-brand support (2026-07-27) — the org's full brand list, for the
  // Brand Profile/Knowledge/Golden Dataset context selector and the "Add
  // brand" flow, replacing what used to be a free-text brand-ID field.
  const [orgBrands, setOrgBrands] = useState([]);
  const [brandsLoading, setBrandsLoading] = useState(false);
  const [newBrandName, setNewBrandName] = useState('');
  const [creatingBrand, setCreatingBrand] = useState(false);
  const [brandError, setBrandError] = useState('');

  const refreshBrands = async () => {
    setBrandsLoading(true);
    try {
      const res = await listBrands();
      const list = res.brands || [];
      setOrgBrands(list);
      // Default the selector to the first known brand once the list loads,
      // instead of leaving it pointed at the env-var fallback forever.
      setBrandId((prev) => (list.some((b) => b.id === prev) ? prev : list[0]?.id || prev));
    } catch (err) {
      setBrandError(err instanceof Error ? err.message : 'Failed to load brands');
    } finally {
      setBrandsLoading(false);
    }
  };

  useEffect(() => {
    refreshBrands();
  }, []);

  const submitNewBrand = async () => {
    const name = newBrandName.trim();
    if (!name) return;
    setCreatingBrand(true);
    setBrandError('');
    try {
      const created = await createBrand(name);
      setNewBrandName('');
      await refreshBrands();
      setBrandId(created.id);
    } catch (err) {
      setBrandError(err instanceof Error ? err.message : 'Failed to create brand');
    } finally {
      setCreatingBrand(false);
    }
  };

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
  const [newUserBrandIds, setNewUserBrandIds] = useState(new Set());
  const [newUserStatus, setNewUserStatus] = useState('active');
  const [userStatus, setUserStatus] = useState('');
  const [userError, setUserError] = useState('');
  const [userCreating, setUserCreating] = useState(false);
  const [editingBrandsUserId, setEditingBrandsUserId] = useState('');
  const [activeBrandLocales, setActiveBrandLocales] = useState(['en-US']);

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
    () => Boolean(newUserEmail.trim() && newUserRole.trim()),
    [newUserEmail, newUserRole],
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
      if (editingBrandsUserId) {
        // Edit mode
        const payload = {
          roles: [newUserRole],
          brand_ids: Array.from(newUserBrandIds),
          status: newUserStatus,
        };
        if (newUserPassword.trim()) {
          payload.password = newUserPassword.trim();
        }
        await updateUser(editingBrandsUserId, payload);
        await refreshUsers({ showStatus: false });
        cancelEditingUser();
        setUserStatus('User details updated successfully.');
      } else {
        // Create mode
        const payload = await createUser({
          name: newUserName.trim(),
          email: newUserEmail.trim(),
          role: newUserRole.trim(),
          password: newUserPassword.trim() || null,
          brandIds: newUserBrandIds.size > 0 ? Array.from(newUserBrandIds) : null,
        });
        const passwordNotice = payload.temporary_password
          ? ` Temporary password: ${payload.temporary_password}`
          : '';
        const totalUsers = await refreshUsers({ showStatus: false });
        setUserStatus(
          `Created ${payload.user?.email || newUserEmail.trim()}.${passwordNotice} Total users: ${totalUsers}.`,
        );
        cancelEditingUser();
      }
    } catch (err) {
      setUserError(err instanceof Error ? err.message : 'Failed to save user');
    } finally {
      setUserCreating(false);
    }
  };

  const toggleNewUserBrand = (id) => {
    setNewUserBrandIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const startEditingUser = (managedUser) => {
    setEditingBrandsUserId(managedUser.user_id);
    setNewUserEmail(managedUser.email);
    setNewUserRole(managedUser.roles?.[0] || 'viewer');
    setNewUserStatus(managedUser.status || 'active');
    setNewUserBrandIds(new Set(managedUser.brand_ids || []));
    setNewUserPassword('');
  };

  const cancelEditingUser = () => {
    setEditingBrandsUserId('');
    setNewUserEmail('');
    setNewUserRole('viewer');
    setNewUserStatus('active');
    setNewUserBrandIds(new Set());
    setNewUserPassword('');
    setNewUserName('');
  };

  useEffect(() => {
    if (!brandId) return;
    getBrandConfig(brandId)
      .then((res) => {
        const locs = res.locales && res.locales.length ? res.locales : (res.available_locales || ['en-US']);
        setActiveBrandLocales(locs);
        if (locs.length > 0 && !locs.includes(locale)) {
          setLocale(locs[0]);
        }
      })
      .catch((err) => {
        console.error('Failed to load brand locales for context bar', err);
      });
  }, [brandId]);

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

  // Auto-refresh brand guides and customer segments when context or tab changes (2026-07-27)
  useEffect(() => {
    if (!isAdmin) return;
    if (tab === 'knowledge' || tab === 'brand') {
      refreshGuides();
      refreshSegments();
    }
  }, [tab, brandId, locale, version, isAdmin]);

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
              brandIds: newUserBrandIds,
              toggleBrand: toggleNewUserBrand,
            }}
            canCreate={canCreateUser}
            creating={userCreating}
            onSubmit={submitUser}
            orgBrands={orgBrands}
            editingBrandsUserId={editingBrandsUserId}
            onStartEditingBrands={startEditingUser}
            onCancelEditingBrands={cancelEditingUser}
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
            brands={orgBrands}
            brandsLoading={brandsLoading}
            activeBrandLocales={activeBrandLocales}
          />
        )}

        {tab === 'brand' && (
          <>
            <BrandPillRow
              brands={orgBrands}
              brandId={brandId}
              setBrandId={setBrandId}
              newBrandName={newBrandName}
              setNewBrandName={setNewBrandName}
              onCreateBrand={submitNewBrand}
              creatingBrand={creatingBrand}
              brandError={brandError}
            />
            <BrandProfilePanel
              brandId={brandId}
              locale={locale}
              setLocale={setLocale}
              version={version}
              setVersion={setVersion}
              guides={guides}
              file={file}
              setFile={setFile}
              canUpload={canUpload}
              uploading={uploading}
              loadingGuides={loadingGuides}
              onSubmitGuide={submitGuide}
              onRefreshGuides={refreshGuides}
              onSaved={refreshBrands}
            />
          </>
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

function UsersPanel({
  users,
  loading,
  error,
  status,
  onRefresh,
  form,
  canCreate,
  creating,
  onSubmit,
  orgBrands,
  editingBrandsUserId,
  onStartEditingBrands,
  onCancelEditingBrands,
}) {
  const brandName = (id) => orgBrands.find((b) => b.id === id)?.name || id;

  return (
    <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
      {/* Create / Edit user form */}
      <section className="rounded-2xl border border-border bg-surface p-5 card-shadow">
        <div className="mb-4 flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-xl brand-gradient text-white">
            <UserPlus size={18} aria-hidden="true" />
          </span>
          <div>
            <h2 className="text-base font-semibold text-fg">
              {editingBrandsUserId ? 'Edit user' : 'Add a user'}
            </h2>
            <p className="text-xs text-muted">
              {editingBrandsUserId ? 'Update account details and brand associations.' : 'Provision an account in this tenant.'}
            </p>
          </div>
        </div>

        <StatusBanner error={error} status={status} />

        <form className="space-y-3" onSubmit={onSubmit} autoComplete="off">
          {!editingBrandsUserId && (
            <Labeled label="Full name">
              <input
                className={inputCls}
                value={form.name}
                onChange={(e) => form.setName(e.target.value)}
                placeholder="Jane Doe"
                autoComplete="off"
              />
            </Labeled>
          )}
          <Labeled label="Email">
            <input
              className={inputCls}
              type="email"
              value={form.email}
              onChange={(e) => form.setEmail(e.target.value)}
              placeholder="jane@company.com"
              autoComplete="off"
              disabled={Boolean(editingBrandsUserId)}
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
                <option value="reviewer">Reviewer</option>
                <option value="admin">Admin</option>
              </select>
            </Labeled>
            
            {editingBrandsUserId ? (
              <Labeled label="Status">
                <select
                  className={inputCls}
                  value={form.status}
                  onChange={(e) => form.setStatus(e.target.value)}
                >
                  <option value="active">Active</option>
                  <option value="deactivated">Deactivated</option>
                  <option value="pending">Pending</option>
                </select>
              </Labeled>
            ) : (
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
            )}
          </div>

          {editingBrandsUserId && (
            <Labeled label="Password" hint="optional">
              <input
                className={inputCls}
                type="password"
                minLength={8}
                value={form.password}
                onChange={(e) => form.setPassword(e.target.value)}
                placeholder="Leave blank to keep current password"
                autoComplete="new-password"
              />
            </Labeled>
          )}

          <Labeled label="Brands" hint="none selected = inherit your own brands">
            <div className="flex flex-wrap gap-1.5">
              {orgBrands.map((b) => (
                <button
                  key={b.id}
                  type="button"
                  onClick={() => form.toggleBrand(b.id)}
                  className={cn(
                    'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                    form.brandIds.has(b.id)
                      ? 'border-brand bg-brand text-brand-fg'
                      : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg',
                  )}
                >
                  {b.name}
                </button>
              ))}
            </div>
          </Labeled>
          
          <p className="flex items-start gap-1.5 text-xs text-faint">
            <KeyRound size={13} aria-hidden="true" className="mt-0.5 shrink-0" />
            {editingBrandsUserId 
              ? 'Update the password field only if you want to set a new password for this user.'
              : 'Leave the password blank to auto-generate a temporary one, shown after creation.'}
          </p>

          <div className="flex gap-2">
            <Button type="submit" variant="primary" size="md" className="flex-1" disabled={!canCreate || creating}>
              {creating ? 'Saving…' : (editingBrandsUserId ? 'Save changes' : 'Add user')}
            </Button>
            {editingBrandsUserId && (
              <Button type="button" variant="secondary" size="md" onClick={onCancelEditingBrands}>
                Cancel
              </Button>
            )}
          </div>
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
            {users.map((u) => {
              const isSelected = editingBrandsUserId === u.user_id;
              return (
                <li 
                  key={u.user_id} 
                  className={cn(
                    "px-5 py-3 cursor-pointer hover:bg-surface-2 transition-colors",
                    isSelected && "bg-brand-soft/20 border-l-4 border-l-brand"
                  )}
                  onClick={() => onStartEditingBrands(u)}
                >
                  <div className="flex items-center gap-3">
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
                        {(u.brand_ids || []).length === 0 ? (
                          <span className="text-[11px] text-faint">org-wide</span>
                        ) : (
                          (u.brand_ids || []).map((id) => (
                            <span key={id} className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-muted">
                              {brandName(id)}
                            </span>
                          ))
                        )}
                      </div>
                    </div>
                    <Badge tone={USER_STATUS_TONE[u.status] || 'neutral'}>{u.status}</Badge>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

/* --------------------------------------------------------------- Context bar */

function ContextBar({
  brandId,
  setBrandId,
  locale,
  setLocale,
  version,
  setVersion,
  brands,
  brandsLoading,
  activeBrandLocales = ['en-US'],
}) {
  return (
    <div className="mb-4 rounded-2xl border border-border bg-surface-2/60 p-3">
      <div className="mb-2 flex items-center gap-1.5 px-1 text-xs font-semibold uppercase tracking-wide text-faint">
        <Building2 size={12} aria-hidden="true" /> Working context
      </div>
      <div className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr]">
        <select
          className={inputCls}
          value={brandId}
          onChange={(e) => setBrandId(e.target.value)}
          aria-label="Brand"
        >
          {brands.length === 0 ? (
            <option value="">{brandsLoading ? 'Loading brands…' : 'No brands yet'}</option>
          ) : (
            brands.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))
          )}
        </select>
        
        <select
          className={inputCls}
          value={locale}
          onChange={(e) => setLocale(e.target.value)}
          aria-label="Locale"
        >
          {activeBrandLocales.map((loc) => (
            <option key={loc} value={loc}>
              {loc}
            </option>
          ))}
        </select>

        <input className={inputCls} value={version} onChange={(e) => setVersion(e.target.value)} aria-label="Version" placeholder="Version" />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------- Brand Profile */

// Admin-editable brand entitlement + truthfulness profile (next_tasks.md
// items 14/22/42, 2026-07-27) — this is the actual UI surface for what
// pipeline/agents/intake.py reads from brands.config to enforce channel/
// locale entitlement and check brief-vs-brand plausibility, and what the
// chat's channel/locale pickers (item 23/23a) narrow down to. Real form
// fields only — no raw JSON entry, per explicit direction.
// Brand switcher pills, one per org brand, plus "Add brand" as one of the
// pills (2026-07-27 layout revamp — replaces the free-text/dropdown brand
// field for this tab specifically with the pill-row style shown in the
// user's mockup). Controls the SAME top-level `brandId` state the
// Knowledge/Golden Dataset tabs' ContextBar also controls, so switching
// brands here is reflected there too, and vice versa.
function BrandPillRow({
  brands,
  brandId,
  setBrandId,
  newBrandName,
  setNewBrandName,
  onCreateBrand,
  creatingBrand,
  brandError,
}) {
  const [addingBrand, setAddingBrand] = useState(false);
  // Project-defined tone tokens only (see global.css's `@theme`) — raw
  // Tailwind palette classes like bg-blue-500 aren't guaranteed to exist here.
  const swatchColors = ['bg-brand', 'bg-success', 'bg-warning', 'bg-danger', 'bg-muted'];

  const confirmAdd = async () => {
    await onCreateBrand();
    setAddingBrand(false);
  };

  return (
    <div className="mb-5">
      <div className="flex flex-wrap items-center gap-2">
        {brands.map((b, idx) => (
          <button
            key={b.id}
            type="button"
            onClick={() => setBrandId(b.id)}
            className={cn(
              'flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-medium transition-colors',
              b.id === brandId
                ? 'border-brand bg-brand-soft text-fg'
                : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg',
            )}
          >
            <span className={cn('h-5 w-5 shrink-0 rounded-md', swatchColors[idx % swatchColors.length])} />
            {b.name}
            {b.source_locale && <span className="text-xs text-faint">{b.source_locale}</span>}
          </button>
        ))}

        {addingBrand ? (
          <div className="flex items-center gap-1.5 rounded-full border border-border bg-surface px-2 py-1">
            <input
              autoFocus
              className="h-7 w-36 border-none bg-transparent text-sm text-fg outline-none placeholder:text-faint"
              value={newBrandName}
              onChange={(e) => setNewBrandName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  confirmAdd();
                }
                if (e.key === 'Escape') setAddingBrand(false);
              }}
              placeholder="Brand name"
            />
            <Button variant="secondary" size="sm" onClick={confirmAdd} disabled={creatingBrand || !newBrandName.trim()}>
              {creatingBrand ? '…' : 'Add'}
            </Button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setAddingBrand(true)}
            className="flex items-center gap-1.5 rounded-full border border-dashed border-border-strong px-3 py-2 text-sm font-medium text-muted transition-colors hover:border-brand hover:text-brand"
          >
            <Plus size={15} aria-hidden="true" /> Add brand
          </button>
        )}
      </div>
      {brandError ? <p className="mt-1.5 text-xs text-danger">{brandError}</p> : null}
    </div>
  );
}

function BrandProfilePanel({
  brandId,
  locale,
  setLocale,
  version,
  setVersion,
  guides,
  file,
  setFile,
  canUpload,
  uploading,
  loadingGuides,
  onSubmitGuide,
  onRefreshGuides,
  onSaved,
}) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [name, setName] = useState('');
  const [industry, setIndustry] = useState('');
  const [keyClaims, setKeyClaims] = useState([]);
  const [claimDraft, setClaimDraft] = useState('');
  const [availableChannels, setAvailableChannels] = useState([]);
  const [availableLocales, setAvailableLocales] = useState([]);
  const [selectedChannels, setSelectedChannels] = useState(new Set());
  const [selectedLocales, setSelectedLocales] = useState(new Set());

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    getBrandConfig(brandId)
      .then((res) => {
        if (cancelled) return;
        setName(res.brand_name || '');
        setIndustry(res.industry || '');
        setKeyClaims(res.key_claims || []);
        setAvailableChannels(res.available_channels || []);
        setAvailableLocales(res.available_locales || []);
        // null/unset from the API means "no allow-list configured yet" —
        // default the checkboxes to everything selected (i.e. today's
        // effective behavior: allow all), not an empty, confusing set.
        setSelectedChannels(new Set(res.channels && res.channels.length ? res.channels : res.available_channels || []));
        setSelectedLocales(new Set(res.locales && res.locales.length ? res.locales : res.available_locales || []));
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load brand profile');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  const toggleChannel = (channel) => {
    setSelectedChannels((prev) => {
      const next = new Set(prev);
      if (next.has(channel)) next.delete(channel);
      else next.add(channel);
      return next;
    });
  };

  const toggleLocale = (locale) => {
    setSelectedLocales((prev) => {
      const next = new Set(prev);
      if (next.has(locale)) next.delete(locale);
      else next.add(locale);
      return next;
    });
  };

  const addClaim = () => {
    const trimmed = claimDraft.trim();
    if (!trimmed) return;
    setKeyClaims((prev) => [...prev, trimmed]);
    setClaimDraft('');
  };

  const removeClaim = (idx) => {
    setKeyClaims((prev) => prev.filter((_, i) => i !== idx));
  };

  const save = async () => {
    setSaving(true);
    setError('');
    setStatus('');
    try {
      // Selecting every available option is treated the same as "no
      // restriction configured" (empty allow-list) so a brand that starts
      // fully-open and stays fully-open doesn't silently start narrowing
      // itself the moment new channels/locales are added to the platform.
      const channelsPayload =
        selectedChannels.size === availableChannels.length ? [] : Array.from(selectedChannels);
      const localesPayload =
        selectedLocales.size === availableLocales.length ? [] : Array.from(selectedLocales);
      await updateBrandConfig(brandId, {
        name,
        industry,
        keyClaims,
        channels: channelsPayload,
        locales: localesPayload,
      });
      setStatus('Brand profile saved.');
      if (onSaved) await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save brand profile');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <StatusBanner error={error} status={status} />
      {loading ? (
        <p className="text-sm text-muted">Loading brand profile…</p>
      ) : (
        <>
          <div>
            <p className="text-base font-semibold text-fg">Brand profile</p>
            <p className="text-xs text-faint">
              Used by intake to reject briefs that don't plausibly match this brand, before any
              generation cost is spent. Leave blank to skip this check entirely.
            </p>
          </div>

          <div className="grid gap-8 lg:grid-cols-2 lg:items-start">
            {/* Column 1 — Identity & Guidelines */}
            <div className="space-y-5">
              {/* Brand details */}
              <div className="rounded-2xl border border-border bg-surface p-4 card-shadow">
                <p className="mb-3 text-sm font-semibold text-fg">Brand details</p>
                <div className="space-y-4">
                  <Labeled label="Brand name">
                    <input
                      className={inputCls}
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="Brand name"
                    />
                  </Labeled>
                  <Labeled label="Industry" hint="e.g. telecom, artisanal bakery">
                    <input
                      className={inputCls}
                      value={industry}
                      onChange={(e) => setIndustry(e.target.value)}
                      placeholder="Industry"
                    />
                  </Labeled>
                  <Labeled label="Key claims / offerings" hint="what this brand actually says about itself">
                    <div className="flex flex-wrap gap-1.5">
                      {keyClaims.map((claim, idx) => (
                        <span
                          key={`${claim}-${idx}`}
                          className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-1 text-xs text-muted"
                        >
                          {claim}
                          <button
                            type="button"
                            onClick={() => removeClaim(idx)}
                            aria-label={`Remove ${claim}`}
                            className="text-faint hover:text-danger"
                          >
                            <X size={12} aria-hidden="true" />
                          </button>
                        </span>
                      ))}
                    </div>
                    <div className="mt-2 flex gap-2">
                      <input
                        className={inputCls}
                        value={claimDraft}
                        onChange={(e) => setClaimDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            addClaim();
                          }
                        }}
                        placeholder="Add a claim and press Enter"
                      />
                      <Button variant="secondary" size="sm" onClick={addClaim} disabled={!claimDraft.trim()}>
                        <Plus size={14} aria-hidden="true" /> Add
                      </Button>
                    </div>
                  </Labeled>
                </div>
                <Button variant="primary" className="mt-5 w-full" onClick={save} disabled={saving || !name.trim()}>
                  {saving ? 'Saving…' : 'Save brand profile'}
                </Button>
              </div>

              {/* Guideline upload */}
              <div className="rounded-2xl border border-border bg-surface p-4 card-shadow">
                <p className="mb-1 text-sm font-semibold text-fg">Guideline</p>
                <p className="mb-3 text-xs text-faint">
                  Uploaded here, this brand's guideline — changes appear in the Knowledge tab too,
                  since it's the same data.
                </p>

                <div className="mb-4 grid grid-cols-2 gap-2">
                  <input
                    className={cn(inputCls, 'text-xs')}
                    value={locale}
                    onChange={(e) => setLocale(e.target.value)}
                    placeholder="Locale"
                    aria-label="Guideline locale"
                  />
                  <input
                    className={cn(inputCls, 'text-xs')}
                    value={version}
                    onChange={(e) => setVersion(e.target.value)}
                    placeholder="Version"
                    aria-label="Guideline version"
                  />
                </div>
                <FileDrop file={file} onFile={setFile} hint="PDF, DOCX, or TXT" />
                <div className="mt-2 flex items-center gap-2">
                  <Button variant="secondary" size="sm" onClick={onSubmitGuide} disabled={!canUpload || uploading}>
                    <Upload size={14} aria-hidden="true" />
                    {uploading ? 'Uploading…' : 'Upload guideline'}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={onRefreshGuides} disabled={loadingGuides}>
                    <RefreshCw size={13} aria-hidden="true" className={loadingGuides ? 'animate-spin' : ''} />
                  </Button>
                </div>
                {guides.length > 0 && (
                  <ul className="mt-3 space-y-1.5">
                    {guides.map((g) => (
                      <li
                        key={g.id || `${g.locale}-${g.version}`}
                        className="flex items-center justify-between gap-2 rounded-lg border border-border bg-surface-2 px-2.5 py-1.5 text-xs"
                      >
                        <span className="flex items-center gap-1.5 text-fg">
                          <FileText size={13} aria-hidden="true" className="text-faint" />
                          {g.filename || `${g.locale} · ${g.version}`}
                        </span>
                        <span className="text-faint">{g.locale}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            {/* Column 2 — Entitlements & Golden Dataset */}
            <div className="space-y-5">
              <div className="rounded-2xl border border-border bg-surface p-4 card-shadow">
                <p className="mb-1 text-sm font-semibold text-fg">Entitled channels</p>
                <p className="mb-3 text-xs text-faint">Only these channels are offered for this brand.</p>
                <div className="flex flex-wrap gap-1.5">
                  {availableChannels.map((channel) => (
                    <button
                      key={channel}
                      type="button"
                      onClick={() => toggleChannel(channel)}
                      className={cn(
                        'rounded-full border px-2.5 py-1 text-xs font-medium capitalize transition-colors',
                        selectedChannels.has(channel)
                          ? 'border-brand bg-brand text-brand-fg'
                          : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg',
                      )}
                    >
                      {channel}
                    </button>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl border border-border bg-surface p-4 card-shadow">
                <p className="mb-1 text-sm font-semibold text-fg">Entitled locales</p>
                <p className="mb-3 text-xs text-faint">en-US is always entitled as the source locale.</p>
                <div className="flex flex-wrap gap-1.5">
                  {availableLocales.map((loc) => (
                    <button
                      key={loc}
                      type="button"
                      onClick={() => toggleLocale(loc)}
                      className={cn(
                        'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                        selectedLocales.has(loc)
                          ? 'border-brand bg-brand text-brand-fg'
                          : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg',
                      )}
                    >
                      {loc}
                    </button>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl border border-border bg-surface p-4 card-shadow">
                <p className="mb-1 text-sm font-semibold text-fg">Golden Dataset</p>
                <p className="mb-3 text-xs text-faint">
                  Managed here, this brand's golden dataset — changes appear in the Golden Dataset
                  tab too, since it's the same data.
                </p>
                <GoldenDatasetPanel brandId={brandId} locale={locale} version={version} hideExamples={true} />
              </div>
            </div>
          </div>
        </>
      )}
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

function GoldenDatasetPanel({ brandId, locale, version, hideExamples = false }) {
  const [sets, setSets] = useState([]);
  const [examples, setExamples] = useState([]);
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  
  // Modal state variables
  const [viewingExample, setViewingExample] = useState(null);
  const [previewingSet, setPreviewingSet] = useState(null);
  const [previewExamples, setPreviewExamples] = useState([]);
  const [loadingPreview, setLoadingPreview] = useState(false);
  
  // Lazy loading examples
  const [visibleCount, setVisibleCount] = useState(3);

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

  const handlePreviewSet = async (set) => {
    setPreviewingSet(set);
    setLoadingPreview(true);
    try {
      const res = await listGoldenExamples(brandId.trim(), { setId: set.id });
      setPreviewExamples(res.items || []);
    } catch (err) {
      console.error("Failed to load set examples for preview", err);
    } finally {
      setLoadingPreview(false);
    }
  };

  useEffect(() => {
    refresh();
    setVisibleCount(3);
  }, [brandId, locale, version]);

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

      <div className={cn("grid gap-4", hideExamples ? "grid-cols-1" : "lg:grid-cols-2")}>
        <div className="rounded-xl border border-border bg-surface-2 p-3.5">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Dataset sets</h3>
          {sets.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border bg-surface px-3 py-6 text-center text-sm text-muted">
              No dataset sets yet.
            </p>
          ) : (
            <div className="max-h-[350px] overflow-y-auto pr-1">
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
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <Badge tone={set.status === 'active' ? 'success' : 'neutral'}>{set.status}</Badge>
                        <span className="text-xs text-faint">{set.source}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button variant="ghost" size="sm" onClick={() => handlePreviewSet(set)} title="Preview set examples">
                        Preview
                      </Button>
                      {set.status !== 'active' ? (
                        <Button variant="secondary" size="sm" onClick={() => activate(set.id)}>
                          Activate
                        </Button>
                      ) : (
                        <CheckCircle2 size={16} aria-hidden="true" className="shrink-0 text-success" />
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {!hideExamples && (
          <div className="rounded-xl border border-border bg-surface-2 p-3.5">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Examples</h3>
            {examples.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border bg-surface px-3 py-6 text-center text-sm text-muted">
                No examples yet.
              </p>
            ) : (
              <div className="space-y-3">
                <div className="max-h-[350px] overflow-y-auto pr-1">
                  <ul className="space-y-2">
                    {examples.slice(0, visibleCount).map((example) => (
                      <li
                        key={example.id}
                        className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface px-3 py-2.5"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-fg">
                            {example.description || 'On-brand copy example'}
                          </p>
                          <div className="mt-1 flex items-center gap-1.5">
                            <Badge tone={example.status === 'golden' ? 'brand' : 'neutral'}>
                              {example.status}
                            </Badge>
                            <span className="truncate text-xs text-muted">
                              {example.channel || 'any'} · {example.locale}
                            </span>
                          </div>
                        </div>
                        <div className="flex shrink-0 gap-1">
                          <Button variant="ghost" size="sm" onClick={() => setViewingExample(example)} title="View content details">
                            <Eye size={14} aria-hidden="true" />
                          </Button>
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
                </div>
                
                {examples.length > visibleCount && (
                  <button
                    type="button"
                    onClick={() => setVisibleCount((prev) => prev + 3)}
                    className="w-full text-center py-1.5 text-xs font-semibold text-brand hover:text-brand-hover hover:underline transition-colors bg-surface border border-border rounded-lg"
                  >
                    Load more ({examples.length - visibleCount} remaining)
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Set Preview Modal */}
      <Modal
        open={Boolean(previewingSet)}
        onClose={() => setPreviewingSet(null)}
        title={`Preview Set: ${previewingSet?.locale} · ${previewingSet?.guide_version || 'no version'}`}
        description={`Showing examples in this ${previewingSet?.status} set.`}
        size="lg"
      >
        {loadingPreview ? (
          <p className="text-sm text-muted">Loading set examples…</p>
        ) : previewExamples.length === 0 ? (
          <p className="text-sm text-muted">No examples in this set.</p>
        ) : (
          <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
            {previewExamples.map((ex) => (
              <div key={ex.id} className="rounded-xl border border-border bg-surface-2 p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <Badge tone={ex.status === 'golden' ? 'brand' : 'neutral'}>
                      {ex.status}
                    </Badge>
                    <span className="text-xs font-semibold text-fg">
                      {ex.channel || 'any'} · {ex.locale}
                    </span>
                  </div>
                  {ex.expected_brand_score !== undefined && (
                    <span className="text-xs font-medium text-brand">
                      Brand Score: {ex.expected_brand_score}/100
                    </span>
                  )}
                </div>
                {ex.description && (
                  <p className="text-xs font-medium text-fg">{ex.description}</p>
                )}
                <div className="rounded-lg bg-surface p-2.5 border border-border">
                  <p className="text-xs whitespace-pre-wrap font-mono text-muted">{ex.expected_content}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </Modal>

      {/* View Single Example Details Modal */}
      <Modal
        open={Boolean(viewingExample)}
        onClose={() => setViewingExample(null)}
        title={`Example Details (${viewingExample?.channel || 'any'} · ${viewingExample?.locale})`}
        size="md"
      >
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Badge tone={viewingExample?.status === 'golden' ? 'brand' : 'neutral'}>
                {viewingExample?.status}
              </Badge>
              <span className="text-xs text-muted">Source: {viewingExample?.source}</span>
            </div>
            {viewingExample?.expected_brand_score !== undefined && (
              <span className="text-xs font-medium text-brand">
                Target Score: {viewingExample?.expected_brand_score}/100
              </span>
            )}
          </div>

          {viewingExample?.description && (
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-wide text-faint">Description</span>
              <p className="mt-1 text-sm text-fg">{viewingExample.description}</p>
            </div>
          )}

          <div>
            <span className="text-[11px] font-semibold uppercase tracking-wide text-faint">Expected Copy Content</span>
            <div className="mt-1 rounded-xl border border-border bg-surface-2 p-3.5 max-h-[30vh] overflow-y-auto">
              <p className="text-sm whitespace-pre-wrap font-mono text-muted">{viewingExample?.expected_content}</p>
            </div>
          </div>

          {viewingExample?.known_hallucination_traps && (
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-wide text-faint">Known Hallucination Traps</span>
              <p className="mt-1 text-xs text-muted">
                {typeof viewingExample.known_hallucination_traps === 'string'
                  ? viewingExample.known_hallucination_traps
                  : JSON.stringify(viewingExample.known_hallucination_traps)}
              </p>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-3 border-t border-border">
            {viewingExample?.status !== 'golden' && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => {
                  promote(viewingExample.id);
                  setViewingExample(null);
                }}
              >
                Promote to golden
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={() => setViewingExample(null)}>
              Close
            </Button>
          </div>
        </div>
      </Modal>
    </section>
  );
}
