-- Where a chat session came from. NULL for ordinary traffic; "staff" when
-- the visitor arrived through /staff-test.
--
-- Nullable with no default on purpose: every existing row predates the
-- staff link, and back-filling them with anything -- "web" included --
-- would assert something about traffic nobody measured.
ALTER TABLE "Conversation" ADD COLUMN IF NOT EXISTS "origin" TEXT;
CREATE INDEX IF NOT EXISTS "Conversation_origin_idx" ON "Conversation" ("origin");
