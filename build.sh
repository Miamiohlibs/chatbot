#!/usr/bin/env bash
set -euo pipefail

# The Python client generates from ai-core/schema.prisma, which is a COPY of
# the canonical prisma/schema.prisma with the datasource url inlined. They
# drift the moment somebody edits the canonical one and forgets this step --
# which happened on 2026-08-21: the migration added Conversation.origin to
# the database, the canonical schema had it, and the generated client did
# not. Every visitor carrying the staff cookie then failed to connect at
# all, because their conversation could not be created.
#
# Syncing here means the deploy cannot produce that mismatch again.
echo "Syncing Prisma schemas..."
./local-auto-start.sh --sync-prisma

#backend
echo "Building backend..."
cd ai-core
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
prisma generate


echo "Building frontend..."
#frontend
cd ../client
npm ci
npm run build



# restart app
sudo /bin/systemctl restart chatbot.service
echo "chatbot.service restarted."
