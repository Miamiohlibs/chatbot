-- A person's verdict on where a conversation came from, overriding the
-- rules. Separate from `origin`, which records a fact rather than a
-- judgement; keeping them apart is what lets the dashboard say which is
-- which.
ALTER TABLE "Conversation" ADD COLUMN IF NOT EXISTS "sourceOverride" TEXT;
ALTER TABLE "Conversation" ADD COLUMN IF NOT EXISTS "sourceOverrideBy" TEXT;
ALTER TABLE "Conversation" ADD COLUMN IF NOT EXISTS "sourceOverrideAt" TIMESTAMP(3);
CREATE INDEX IF NOT EXISTS "Conversation_sourceOverride_idx"
    ON "Conversation" ("sourceOverride");
