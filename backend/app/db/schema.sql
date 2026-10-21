-- Re-sense: Supabase Postgres schema
-- Run this once against your Supabase project before starting the backend.

create table if not exists papers (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid references auth.users(id) on delete cascade,  -- owner (Supabase Auth)
    filename        text not null,
    file_hash       text not null,               -- sha256 of the raw file, used for dedup per owner
    uploaded_at     timestamptz not null default now(),
    raw_text        text,                        -- extracted plain text (null until parsed)
    structure_json  jsonb,                        -- detected sections/headings/captions
    status          text not null default 'uploaded'
                    check (status in ('uploaded', 'parsing', 'ready', 'parse_failed', 'empty_text'))
);

create table if not exists summaries (
    id              uuid primary key default gen_random_uuid(),
    paper_id        uuid not null references papers(id) on delete cascade,
    tone            text not null check (tone in ('academic', 'technical', 'research_insight', 'figure_table_analysis', 'critical_review')),
    content         text not null,
    generated_at    timestamptz not null default now(),
    unique (paper_id, tone)                       -- one cached summary per tone per paper
);

create table if not exists analysis (
    id              uuid primary key default gen_random_uuid(),
    paper_id        uuid not null references papers(id) on delete cascade,
    chart_data_json jsonb not null,
    generated_at    timestamptz not null default now(),
    unique (paper_id)
);

create table if not exists chat_messages (
    id              uuid primary key default gen_random_uuid(),
    paper_id        uuid not null references papers(id) on delete cascade,
    role            text not null check (role in ('user', 'assistant')),
    content         text not null,
    created_at      timestamptz not null default now()
);

create unique index if not exists papers_user_file_hash_key on papers(user_id, file_hash);
create index if not exists idx_papers_user_uploaded on papers(user_id, uploaded_at desc);
create index if not exists idx_summaries_paper_id on summaries(paper_id);
create index if not exists idx_analysis_paper_id on analysis(paper_id);
create index if not exists idx_chat_messages_paper_id on chat_messages(paper_id);

create table if not exists figures (
    id              uuid primary key default gen_random_uuid(),
    paper_id        uuid not null references papers(id) on delete cascade,
    page_number     int not null,
    storage_path    text not null,
    image_type      text check (image_type in ('chart', 'diagram', 'table', 'code', 'photo', 'other')),
    caption         text,
    width           int not null,
    height          int not null,
    created_at      timestamptz not null default now()
);

create index if not exists idx_figures_paper_id on figures(paper_id);

create table if not exists integrity_reports (
    id              uuid primary key default gen_random_uuid(),
    paper_id        uuid not null references papers(id) on delete cascade,
    report_json     jsonb not null,               -- cached /integrity/references response
    generated_at    timestamptz not null default now(),
    unique (paper_id)
);
