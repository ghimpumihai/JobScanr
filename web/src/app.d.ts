import type { Session, User } from '@supabase/supabase-js';

declare global {
  namespace App {
    interface Locals {
      supabase: import('@supabase/supabase-js').SupabaseClient;
      getSession: () => Promise<Session | null>;
      user: User | null;
      session: Session | null;
    }
    interface PageData {
      session: Session | null;
      user: User | null;
    }
  }
}

export {};
