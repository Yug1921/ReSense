-- ReSense: user accounts (Supabase Auth). Run once in the Supabase SQL editor.
-- Safe to re-run.

-- Each paper belongs to the account that uploaded it.
alter table papers
    add column if not exists user_id uuid references auth.users(id) on delete cascade;

-- The same file can now be uploaded by different people, so dedup is per account.
alter table papers drop constraint if exists papers_file_hash_key;
create unique index if not exists papers_user_file_hash_key on papers(user_id, file_hash);
create index if not exists idx_papers_user_uploaded on papers(user_id, uploaded_at desc);

-- Papers uploaded before accounts existed have no owner and are hidden.
-- To keep them, sign up in the app first, then run this with your email:
-- update papers set user_id = (select id from auth.users where email = 'you@example.com')
-- where user_id is null;
