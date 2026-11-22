-- AutoClips SaaS: isolated, private Postgres schema. Apply only to a reviewed staging database.
-- No table in this schema is exposed to anon/authenticated in the Supabase Data API.
create schema if not exists autoclips_saas;
revoke all on schema autoclips_saas from public, anon, authenticated;
create extension if not exists pgcrypto;

create table if not exists autoclips_saas.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null check (length(name) between 2 and 120),
  created_at timestamptz not null default now()
);
create table if not exists autoclips_saas.memberships (
  org_id uuid not null references autoclips_saas.organizations(id) on delete cascade,
  user_id uuid not null,
  role text not null check (role in ('owner','admin','editor','viewer')),
  joined_at timestamptz not null default now(),
  primary key (org_id,user_id)
);
create index if not exists memberships_by_user on autoclips_saas.memberships(user_id);

create table if not exists autoclips_saas.wallets (
  org_id uuid primary key references autoclips_saas.organizations(id) on delete cascade,
  available integer not null default 0 check (available >= 0),
  reserved integer not null default 0 check (reserved >= 0),
  total_purchased integer not null default 0 check (total_purchased >= 0),
  updated_at timestamptz not null default now()
);
create table if not exists autoclips_saas.channels (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references autoclips_saas.organizations(id) on delete cascade,
  youtube_channel_id text not null check (length(youtube_channel_id) between 12 and 64),
  title text not null,
  token_ciphertext text not null,
  scopes text not null,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (org_id, youtube_channel_id),
  unique (id, org_id)
);
create table if not exists autoclips_saas.oauth_states (
  state_hash text primary key,
  org_id uuid not null references autoclips_saas.organizations(id) on delete cascade,
  user_id uuid not null,
  code_verifier text not null,
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists oauth_states_expiry on autoclips_saas.oauth_states(expires_at);
create table if not exists autoclips_saas.sources (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references autoclips_saas.organizations(id) on delete cascade,
  youtube_source_id text,
  local_fingerprint text,
  authorized_basis text not null check (length(authorized_basis) between 3 and 300),
  created_at timestamptz not null default now(),
  unique (id, org_id)
);
create unique index if not exists sources_youtube_unique on autoclips_saas.sources(org_id, youtube_source_id) where youtube_source_id is not null;


create table if not exists autoclips_saas.source_videos (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references autoclips_saas.organizations(id) on delete cascade,
  source_id uuid not null,
  youtube_video_id text not null check (length(youtube_video_id) between 8 and 24),
  title text not null default '',
  published_at timestamptz,
  state text not null default 'awaiting_original' check (state in ('awaiting_original','ready_for_editing')),
  discovered_at timestamptz not null default now(),
  constraint source_videos_source_tenant foreign key (source_id,org_id) references autoclips_saas.sources(id,org_id),
  unique (org_id,source_id,youtube_video_id)
);
create index if not exists source_videos_org on autoclips_saas.source_videos(org_id,source_id,discovered_at desc);

create table if not exists autoclips_saas.jobs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references autoclips_saas.organizations(id) on delete cascade,
  channel_id uuid not null,
  source_id uuid,
  client_key text not null check (length(client_key) between 8 and 180),
  object_key text not null unique,
  expected_sha256 text not null check (expected_sha256 ~ '^[0-9a-f]{64}$'),
  expected_bytes bigint not null check (expected_bytes between 1024 and 1073741824),
  verified_bytes bigint,
  title text not null check (length(title) between 1 and 100),
  description text not null default '',
  visibility text not null default 'private' check (visibility in ('private')),
  rights_confirmed boolean not null default false,
  approved_by uuid,
  status text not null default 'awaiting_media'
    check (status in ('awaiting_media','ready','queued','uploading','published','needs_reconciliation','cancelled')),
  credit_state text not null default 'none'
    check (credit_state in ('none','reserved','captured','released')),
  youtube_video_id text,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  last_error text,
  locked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint job_channel_tenant foreign key (channel_id,org_id) references autoclips_saas.channels(id,org_id),
  constraint job_source_tenant foreign key (source_id,org_id) references autoclips_saas.sources(id,org_id),
  unique (org_id,client_key),
  unique (org_id,youtube_video_id),
  check (status <> 'published' or (youtube_video_id is not null and credit_state='captured')),
  check (status not in ('queued','uploading') or (rights_confirmed and credit_state='reserved'))
);
create index if not exists jobs_queue on autoclips_saas.jobs(created_at) where status='queued';
create index if not exists jobs_tenant_status on autoclips_saas.jobs(org_id,status);

create table if not exists autoclips_saas.credit_events (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references autoclips_saas.organizations(id) on delete cascade,
  job_id uuid references autoclips_saas.jobs(id),
  kind text not null check (kind in ('purchase','reserve','capture','release','adjustment')),
  amount integer not null,
  external_key text,
  created_at timestamptz not null default now(),
  check ((job_id is not null) or (external_key is not null))
);
create unique index if not exists credit_event_per_job_kind on autoclips_saas.credit_events(job_id,kind) where job_id is not null;
create unique index if not exists credit_event_external on autoclips_saas.credit_events(external_key) where external_key is not null;

create table if not exists autoclips_saas.stripe_checkouts (
  session_id text primary key,
  org_id uuid not null references autoclips_saas.organizations(id) on delete cascade,
  user_id uuid not null,
  credits integer not null check (credits between 100 and 100000),
  amount_cents integer not null check (amount_cents >= 1500),
  paid_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists stripe_checkouts_org on autoclips_saas.stripe_checkouts(org_id);

-- Defense in depth: only the trusted API's DB role reads these tables.
do $$
declare tbl text;
begin
  foreach tbl in array array[
    'organizations','memberships','wallets','channels','oauth_states',
    'sources','source_videos','jobs','credit_events','stripe_checkouts'
  ] loop
    execute format('alter table autoclips_saas.%I enable row level security',tbl);
    execute format('revoke all on autoclips_saas.%I from public, anon, authenticated',tbl);
  end loop;
end $$;
-- Backend uses a trusted owner/service DB role. It must authorize each request by Supabase user ID
-- and membership before touching tenant data. Never expose this schema or DATABASE_URL in the browser.
