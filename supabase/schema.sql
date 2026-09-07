-- MEDQ PHASE 1 DATABASE
-- Paste this entire file into Supabase -> SQL Editor -> New query -> Run.

create extension if not exists pgcrypto;

-- 1) USER PROFILES
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  role text not null default 'student' check (role in ('admin','student')),
  created_at timestamptz not null default now()
);

-- 2) BOOK LIBRARY METADATA
create table if not exists public.books (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  subject text,
  exam_tags text[] not null default array[]::text[],
  file_key text,
  file_size_bytes bigint,
  page_count integer,
  status text not null default 'uploaded'
    check (status in ('uploaded','processing','ready','failed')),
  uploaded_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now()
);

-- 3) QUESTION BANK
create table if not exists public.questions (
  id uuid primary key default gen_random_uuid(),
  book_id uuid references public.books(id) on delete cascade,
  subject text,
  chapter text,
  topic text,
  difficulty text check (difficulty in ('easy','medium','hard')),
  stem text not null,
  option_a text,
  option_b text,
  option_c text,
  option_d text,
  option_e text,
  correct_option text,
  explanation text,
  source_page integer,
  created_at timestamptz not null default now()
);

-- 4) PERSONAL ATTEMPTS
create table if not exists public.attempts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  question_id uuid not null references public.questions(id) on delete cascade,
  selected_option text,
  is_correct boolean not null,
  attempted_at timestamptz not null default now()
);

-- 5) PERSONAL BOOKMARKS
create table if not exists public.bookmarks (
  user_id uuid not null references public.profiles(id) on delete cascade,
  question_id uuid not null references public.questions(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, question_id)
);

-- Automatically create a profile whenever a Supabase Auth user is created.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  insert into public.profiles (id, display_name, role)
  values (
    new.id,
    coalesce(new.raw_user_meta_data ->> 'display_name', split_part(new.email, '@', 1)),
    'student'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute procedure public.handle_new_user();

-- ROW LEVEL SECURITY
alter table public.profiles enable row level security;
alter table public.books enable row level security;
alter table public.questions enable row level security;
alter table public.attempts enable row level security;
alter table public.bookmarks enable row level security;

-- Profiles: each user sees/updates only their own profile.
drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
on public.profiles for select
to authenticated
using ((select auth.uid()) = id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
on public.profiles for update
to authenticated
using ((select auth.uid()) = id)
with check ((select auth.uid()) = id);

-- Books: both users can read library metadata.
drop policy if exists "books_read_authenticated" on public.books;
create policy "books_read_authenticated"
on public.books for select
to authenticated
using (true);

-- Questions: both users can read questions.
drop policy if exists "questions_read_authenticated" on public.questions;
create policy "questions_read_authenticated"
on public.questions for select
to authenticated
using (true);

-- Attempts: user only sees/inserts their own attempts.
drop policy if exists "attempts_select_own" on public.attempts;
create policy "attempts_select_own"
on public.attempts for select
to authenticated
using ((select auth.uid()) = user_id);

drop policy if exists "attempts_insert_own" on public.attempts;
create policy "attempts_insert_own"
on public.attempts for insert
to authenticated
with check ((select auth.uid()) = user_id);

-- Bookmarks: user only sees/manages own bookmarks.
drop policy if exists "bookmarks_select_own" on public.bookmarks;
create policy "bookmarks_select_own"
on public.bookmarks for select
to authenticated
using ((select auth.uid()) = user_id);

drop policy if exists "bookmarks_insert_own" on public.bookmarks;
create policy "bookmarks_insert_own"
on public.bookmarks for insert
to authenticated
with check ((select auth.uid()) = user_id);

drop policy if exists "bookmarks_delete_own" on public.bookmarks;
create policy "bookmarks_delete_own"
on public.bookmarks for delete
to authenticated
using ((select auth.uid()) = user_id);

-- Authenticated Data API grants. RLS still controls row access.
grant select, update on public.profiles to authenticated;
grant select on public.books to authenticated;
grant select on public.questions to authenticated;
grant select, insert on public.attempts to authenticated;
grant select, insert, delete on public.bookmarks to authenticated;
