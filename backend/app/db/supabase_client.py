"""
Thin wrapper around the Supabase client so the rest of the app never
constructs its own client or hardcodes table names.
"""
from functools import lru_cache
from supabase import create_client, Client

from app.config import settings

PAPERS_TABLE = "papers"
SUMMARIES_TABLE = "summaries"
ANALYSIS_TABLE = "analysis"
FIGURES_TABLE = "figures"
FIGURES_BUCKET = "paper-figures"
CHAT_MESSAGES_TABLE = "chat_messages"


@lru_cache
def get_supabase() -> Client:
    """Single shared Supabase client for the process lifetime."""
    return create_client(settings.supabase_url, settings.supabase_key)
