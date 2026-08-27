-- Which conversation a correction ticket came from.
--
-- A ticket has carried question / botAnswer / expectedAnswer as free text
-- since it was built, typed or pasted by the librarian at /librarian/ticket.
-- That copy is all anyone ever sees: opening a ticket, there is no way back
-- to the turn it describes -- no earlier turns, no citations, no scope, no
-- idea what the patron asked before. And reading a conversation, there is no
-- way to file a ticket from it. One ticket exists in the table, which is
-- what a path nobody can walk looks like.
--
-- Both columns nullable, no back-fill. Tickets can legitimately arrive
-- without a conversation -- a librarian reporting something a patron told
-- them at the desk -- and the single existing row predates this, so
-- inventing a link for it would assert something untrue.
ALTER TABLE "CorrectionTicket" ADD COLUMN IF NOT EXISTS "conversationId" TEXT;
ALTER TABLE "CorrectionTicket" ADD COLUMN IF NOT EXISTS "messageId" TEXT;

-- No FOREIGN KEY. Conversations are prunable and tickets are the durable
-- record of what went wrong; a cascade would delete the evidence, and a
-- RESTRICT would block pruning. A dangling id renders as "conversation no
-- longer held" rather than breaking the page.
CREATE INDEX IF NOT EXISTS "CorrectionTicket_conversationId_idx"
  ON "CorrectionTicket" ("conversationId");
