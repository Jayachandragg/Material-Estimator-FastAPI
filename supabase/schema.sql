-- Material Estimator — database schema
-- Run once in Supabase: Dashboard → SQL Editor → New query → paste → Run.
-- Then run seed_products.sql to load the product catalogue.

-- ───────────────────────── profiles ─────────────────────────
create table if not exists public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  email       text not null,
  full_name   text not null default '',
  company     text not null default '',
  role        text not null default 'user' check (role in ('user','admin')),
  created_at  timestamptz not null default now()
);

-- Create a profile automatically when someone signs up.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, full_name, company)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'full_name', ''),
    coalesce(new.raw_user_meta_data->>'company', '')
  );
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Admin check used by the security policies (security definer avoids policy recursion).
create or replace function public.is_admin()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.profiles where id = auth.uid() and role = 'admin');
$$;

alter table public.profiles enable row level security;

drop policy if exists "profiles: read own or admin" on public.profiles;
create policy "profiles: read own or admin" on public.profiles
  for select using (id = auth.uid() or public.is_admin());

drop policy if exists "profiles: update own" on public.profiles;
create policy "profiles: update own" on public.profiles
  for update using (id = auth.uid()) with check (id = auth.uid());

-- Users may edit their name/company but never their own role.
revoke update on public.profiles from authenticated;
grant update (full_name, company) on public.profiles to authenticated;

-- Only admins can change roles, and never their own (prevents locking out the last admin by mistake).
create or replace function public.set_user_role(target uuid, new_role text)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'Only admins can change roles'; end if;
  if target = auth.uid() then raise exception 'You cannot change your own role'; end if;
  if new_role not in ('user','admin') then raise exception 'Invalid role'; end if;
  update public.profiles set role = new_role where id = target;
end $$;
revoke execute on function public.set_user_role(uuid, text) from public, anon;
grant execute on function public.set_user_role(uuid, text) to authenticated;

-- ───────────────────────── estimates ─────────────────────────
create table if not exists public.estimates (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name           text not null default 'Untitled project',
  snapshot       jsonb not null,          -- inputs: { state, project } exactly as the estimator produces it
  results        jsonb not null default '{}'::jsonb, -- calculated material list at save time (compute()/lineInfo())
  catalogue      jsonb not null default '[]'::jsonb, -- product catalogue used, so later product edits never change this estimate
  engine_version text not null default 'calculator_v8',
  area           numeric,
  product_count  integer not null default 0,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index if not exists estimates_user_updated on public.estimates (user_id, updated_at desc);

create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$ begin new.updated_at = now(); return new; end $$;
drop trigger if exists estimates_touch on public.estimates;
create trigger estimates_touch before update on public.estimates
  for each row execute function public.touch_updated_at();

alter table public.estimates enable row level security;

drop policy if exists "estimates: owner read" on public.estimates;
create policy "estimates: owner read" on public.estimates
  for select using (user_id = auth.uid() or public.is_admin());
drop policy if exists "estimates: owner insert" on public.estimates;
create policy "estimates: owner insert" on public.estimates
  for insert with check (user_id = auth.uid());
drop policy if exists "estimates: owner update" on public.estimates;
create policy "estimates: owner update" on public.estimates
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists "estimates: owner delete" on public.estimates;
create policy "estimates: owner delete" on public.estimates
  for delete using (user_id = auth.uid());

-- ───────────────────────── products ─────────────────────────
-- Seeded with the verified values from calculator_v8.html (seed_products.sql).
-- Product ids are referenced by the calculation steps, so admins can edit
-- names, unit descriptions and coverage rates, but cannot add/remove products.
create table if not exists public.products (
  id          text primary key,
  sort_order  integer not null default 0,
  name        text not null,
  unit        text not null,
  unit_desc   text not null default '',
  rates       jsonb not null default '[]'::jsonb,
  updated_at  timestamptz not null default now(),
  updated_by  uuid references auth.users(id)
);
drop trigger if exists products_touch on public.products;
create trigger products_touch before update on public.products
  for each row execute function public.touch_updated_at();

alter table public.products enable row level security;

-- Everyone (including guests who are not signed in) can read the catalogue; it is not secret.
drop policy if exists "products: signed-in read" on public.products;
drop policy if exists "products: public read" on public.products;
create policy "products: public read" on public.products
  for select to anon, authenticated using (true);
drop policy if exists "products: admin update" on public.products;
create policy "products: admin update" on public.products
  for update to authenticated using (public.is_admin()) with check (public.is_admin());

-- ───────────────────────── first admin ─────────────────────────
-- After you sign up in the app, make yourself admin (replace the email):
-- update public.profiles set role = 'admin' where email = 'you@example.com';
