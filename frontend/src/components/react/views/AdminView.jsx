import { useMemo, useState } from 'react';
import { Building2, Users, Upload, RefreshCw, LockKeyhole } from 'lucide-react';
import { Page, SectionHeading } from '../Page.jsx';
import { Button } from '../ui/Button.jsx';
import { Badge } from '../ui/Badge.jsx';
import {
  listBrandGuides,
  listCustomerSegments,
  uploadBrandGuide,
  uploadCustomerSegments,
} from '@/lib/api.js';

const DEFAULT_ORG_ID =
  import.meta.env.PUBLIC_DEFAULT_ORG_ID || '00000000-0000-0000-0000-000000000001';
const DEFAULT_BRAND_ID =
  import.meta.env.PUBLIC_DEFAULT_BRAND_ID || '00000000-0000-0000-0000-000000000002';

const DEMO_USERS = [
  { id: 'api_key', role: 'api_key', scope: 'brand-scoped' },
  { id: 'ops-admin', role: 'admin', scope: 'org-scoped' },
  { id: 'brand-editor', role: 'editor', scope: 'brand-scoped' },
];

export function AdminView({ onLock }) {
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

  const canUpload = useMemo(
    () => Boolean(brandId.trim() && locale.trim() && version.trim() && file),
    [brandId, locale, version, file],
  );
  const canUploadSegments = useMemo(
    () => Boolean(brandId.trim() && locale.trim() && version.trim() && segmentFile),
    [brandId, locale, version, segmentFile],
  );

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

  return (
    <Page
      wide
      eyebrow="Restricted"
      title="Admin Control Plane"
      description="Manage org/brand context and ingest brand intelligence for chat-first orchestration."
      actions={
        <>
          <Badge tone="brand">
            <Building2 size={12} aria-hidden="true" /> Org {DEFAULT_ORG_ID.slice(0, 8)}…
          </Badge>
          <Button variant="outline" size="sm" onClick={onLock}>
            <LockKeyhole size={15} aria-hidden="true" /> Lock
          </Button>
        </>
      }
    >
      {error ? (
        <div className="mb-4 rounded-xl border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      ) : null}
      {status ? (
        <div className="mb-4 rounded-xl border border-success/40 bg-success/10 px-3 py-2 text-sm text-success">
          {status}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
        <section className="rounded-2xl border border-border bg-surface p-4 card-shadow">
          <SectionHeading
            title="Org / Brand Management"
            description="Reference identities used by the conversation and campaign APIs."
          />
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-muted">Org ID</dt>
              <dd className="font-medium text-fg">{DEFAULT_ORG_ID}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted">Default Brand ID</dt>
              <dd className="font-medium text-fg">{DEFAULT_BRAND_ID}</dd>
            </div>
          </dl>

          <SectionHeading title="User Context" description="Current scoped identities." />
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full min-w-[24rem] text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-3 py-2">User</th>
                  <th className="px-3 py-2">Role</th>
                  <th className="px-3 py-2">Scope</th>
                </tr>
              </thead>
              <tbody>
                {DEMO_USERS.map((user) => (
                  <tr key={user.id} className="border-b border-border last:border-0">
                    <td className="px-3 py-2 text-fg">{user.id}</td>
                    <td className="px-3 py-2 text-muted">{user.role}</td>
                    <td className="px-3 py-2 text-muted">{user.scope}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-2xl border border-border bg-surface p-4 card-shadow">
          <SectionHeading
            title="RAG Ingestion"
            description="Upload brand guidelines and inspect indexed guide versions."
            action={
              <Button variant="ghost" size="sm" onClick={refreshGuides} disabled={loadingGuides}>
                <RefreshCw size={14} aria-hidden="true" /> {loadingGuides ? 'Loading…' : 'Refresh'}
              </Button>
            }
          />

          <form className="space-y-3" onSubmit={submitGuide}>
            <label className="block text-sm text-muted">
              <span>Brand ID</span>
              <input
                className="mt-1 h-10 w-full rounded-xl border border-border bg-surface-2 px-3 text-sm text-fg"
                value={brandId}
                onChange={(e) => setBrandId(e.target.value)}
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-sm text-muted">
                <span>Locale</span>
                <input
                  className="mt-1 h-10 w-full rounded-xl border border-border bg-surface-2 px-3 text-sm text-fg"
                  value={locale}
                  onChange={(e) => setLocale(e.target.value)}
                />
              </label>
              <label className="block text-sm text-muted">
                <span>Version</span>
                <input
                  className="mt-1 h-10 w-full rounded-xl border border-border bg-surface-2 px-3 text-sm text-fg"
                  value={version}
                  onChange={(e) => setVersion(e.target.value)}
                />
              </label>
            </div>
            <label className="block text-sm text-muted">
              <span>Brand guide file</span>
              <input
                className="mt-1 block w-full text-sm text-muted"
                type="file"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            </label>
            <Button type="submit" variant="primary" disabled={!canUpload || uploading}>
              <Upload size={15} aria-hidden="true" /> {uploading ? 'Uploading…' : 'Upload guide'}
            </Button>
          </form>

          <div className="mt-4 rounded-xl border border-border bg-surface-2 p-3">
            <h3 className="text-sm font-medium text-fg">Indexed guides</h3>
            {guides.length === 0 ? (
              <p className="mt-1 text-sm text-muted">No guide records loaded yet.</p>
            ) : (
              <ul className="mt-2 space-y-2 text-sm">
                {guides.map((guide) => (
                  <li key={guide.id} className="rounded-lg border border-border bg-surface px-2.5 py-2">
                    <p className="font-medium text-fg">{guide.source_filename}</p>
                    <p className="text-muted">
                      {guide.locale} · {guide.version} · {guide.chunk_count} chunks
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>

      <section className="mt-4 rounded-2xl border border-border bg-surface p-4 card-shadow">
        <SectionHeading
          title="Segment Ingestion"
          description="Upload audience-segment datasets and inspect indexed segment records for the selected brand/locale/version."
          action={
            <Button variant="ghost" size="sm" onClick={refreshSegments} disabled={loadingSegments}>
              <RefreshCw size={14} aria-hidden="true" /> {loadingSegments ? 'Loading…' : 'Refresh'}
            </Button>
          }
        />

        <form className="space-y-3" onSubmit={submitSegments}>
          <label className="block text-sm text-muted">
            <span>Segment file (.csv, .json, .txt, .md)</span>
            <input
              className="mt-1 block w-full text-sm text-muted"
              type="file"
              onChange={(e) => setSegmentFile(e.target.files?.[0] || null)}
            />
          </label>
          <Button type="submit" variant="primary" disabled={!canUploadSegments || uploadingSegments}>
            <Users size={15} aria-hidden="true" /> {uploadingSegments ? 'Uploading…' : 'Upload segments'}
          </Button>
        </form>

        <div className="mt-4 rounded-xl border border-border bg-surface-2 p-3">
          <h3 className="text-sm font-medium text-fg">Indexed segments</h3>
          {segments.length === 0 ? (
            <p className="mt-1 text-sm text-muted">No segment records loaded yet.</p>
          ) : (
            <ul className="mt-2 space-y-2 text-sm">
              {segments.map((segment) => (
                <li key={segment.id} className="rounded-lg border border-border bg-surface px-2.5 py-2">
                  <p className="font-medium text-fg">{segment.metadata?.segment || segment.metadata?.name || segment.id}</p>
                  <p className="text-muted">{segment.text?.slice(0, 180)}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </Page>
  );
}
