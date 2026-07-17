create extension if not exists pgcrypto with schema extensions;

create or replace function public.radar_ingest_authorized()
returns boolean
language sql
stable
set search_path = ''
as $$
    select encode(
        extensions.digest(
            coalesce(current_setting('request.headers', true)::jsonb ->> 'x-radar-ingest-key', ''),
            'sha256'
        ),
        'hex'
    ) = 'e2101a90478e9559be0112c8bbcf6dc3224fc57d09f3e66908d0d1de2d96fc61'
$$;

revoke all on function public.radar_ingest_authorized() from public, authenticated;
grant execute on function public.radar_ingest_authorized() to anon, service_role;

grant select, insert, update, delete on table public.radar_runs to anon;
grant select, insert, update, delete on table public.radar_theme_snapshots to anon;
grant select, insert, update, delete on table public.radar_symbol_snapshots to anon;

create policy radar_runs_ingest_select
    on public.radar_runs for select to anon
    using (public.radar_ingest_authorized());
create policy radar_runs_ingest_insert
    on public.radar_runs for insert to anon
    with check (public.radar_ingest_authorized());
create policy radar_runs_ingest_update
    on public.radar_runs for update to anon
    using (public.radar_ingest_authorized())
    with check (public.radar_ingest_authorized());
create policy radar_runs_ingest_delete
    on public.radar_runs for delete to anon
    using (public.radar_ingest_authorized());

create policy radar_theme_snapshots_ingest_select
    on public.radar_theme_snapshots for select to anon
    using (public.radar_ingest_authorized());
create policy radar_theme_snapshots_ingest_insert
    on public.radar_theme_snapshots for insert to anon
    with check (public.radar_ingest_authorized());
create policy radar_theme_snapshots_ingest_update
    on public.radar_theme_snapshots for update to anon
    using (public.radar_ingest_authorized())
    with check (public.radar_ingest_authorized());
create policy radar_theme_snapshots_ingest_delete
    on public.radar_theme_snapshots for delete to anon
    using (public.radar_ingest_authorized());

create policy radar_symbol_snapshots_ingest_select
    on public.radar_symbol_snapshots for select to anon
    using (public.radar_ingest_authorized());
create policy radar_symbol_snapshots_ingest_insert
    on public.radar_symbol_snapshots for insert to anon
    with check (public.radar_ingest_authorized());
create policy radar_symbol_snapshots_ingest_update
    on public.radar_symbol_snapshots for update to anon
    using (public.radar_ingest_authorized())
    with check (public.radar_ingest_authorized());
create policy radar_symbol_snapshots_ingest_delete
    on public.radar_symbol_snapshots for delete to anon
    using (public.radar_ingest_authorized());
