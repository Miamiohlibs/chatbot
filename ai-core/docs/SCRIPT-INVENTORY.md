# Script inventory

Written 2026-08-21 for the handover. `ai-core/scripts/` holds 120+ files and
it was not obvious which are load-bearing. Every one is classified below by
HOW IT IS ACTUALLY USED, checked against the live crontab, the docs, and the
test runner -- not by guessing from the filename.

**Nothing was deleted for being unreferenced.** A grep for the filename finds
nothing for cron jobs (they are named in crontab), for hand-run CLI tools, or
for pytest files -- so 'unreferenced' would have condemned `switch_corpus.py`,
which promotes a new corpus and was used on 2026-08-18. One file was archived:
`smoke_test_website_evidence.py`, which imports a module that no longer exists
and therefore cannot run.

## Scheduled (cron) -- these run whether anyone is watching

- `scripts/alert_digest.py` — 07:10 weekdays — digest of overnight alerts
- `scripts/backup_db.py` — 03:30 daily — Postgres dump to /opt/chatbot-private-data/backups/
- `scripts/budget_guard.py` — every 15 min — enforces the spend ladder
- `scripts/budget_report.py` — Mon 07:20 + 1st of month — emailed spend report
- `scripts/cost_rollup.py` — 02:00 daily — turns raw token rows into DailyCost
- `scripts/data_health.py` — 06:40 daily — data integrity probes
- `scripts/etl/gate.py` — scheduled
- `scripts/etl_watch.py` — Mon 06:10 — checks the website for content drift
- `scripts/liveness_watchdog.py` — every 5 min — restarts the service if it is down

## Documented procedures -- named in the docs, run by hand

- `scripts/analyze_eval.py`
- `scripts/analyze_eval_results.py`
- `scripts/digest_email.py`
- `scripts/ensure_prisma_client.sh`
- `scripts/etl/classify.py`
- `scripts/etl/cleanup_collections.py`
- `scripts/etl/config.py`
- `scripts/etl/diff_report.py`
- `scripts/etl/discover.py`
- `scripts/etl/extract.py`
- `scripts/etl/libanswers.py`
- `scripts/etl/navigation.py`
- `scripts/etl/run_etl.py`
- `scripts/etl/upsert.py`
- `scripts/eval_budget_gate.py`
- `scripts/eval_classifier_v38.py`
- `scripts/generate_librarian_report.py`
- `scripts/ingest_myguide.py`
- `scripts/operator_wiring/run_eval_wrapper.py`
- `scripts/operator_wiring/wire_gold_to_weaviate.py`
- `scripts/operator_wiring/wire_jekyll_redirects.py`
- `scripts/populate_librarian_subject_mapping.py`
- `scripts/post_deploy_check.sh`
- `scripts/pre_deploy_smoke.py`
- `scripts/preflight.sh`
- `scripts/reconcile_staff_from_csv.py`
- `scripts/run_eval_safely.sh`
- `scripts/run_offline_tests.sh`
- `scripts/seed_library_locations.py`
- `scripts/seed_library_spaces_v2.py`
- `scripts/set_alternate_names.py`
- `scripts/sync_all_library_data.py`
- `scripts/sync_libguides.py`
- `scripts/sync_librarians_from_csv.py`
- `scripts/sync_myguide_subjects.py`
- `scripts/sync_staff_directory.py`
- `scripts/tombstone_by_url_prefix.py`
- `scripts/validate_prompt_urls.py`
- `scripts/verify_prompt_cache.py`
- `scripts/verify_v2_serving.py`

## Tests -- run by pytest, not by name

- `scripts/etl/test_chunker.py`
- `scripts/etl/test_classify.py`
- `scripts/etl/test_diff_report.py`
- `scripts/etl/test_discover.py`
- `scripts/etl/test_extract.py`
- `scripts/etl/test_gate.py`
- `scripts/etl/test_libanswers.py`
- `scripts/etl/test_navigation.py`
- `scripts/etl/test_preview.py`
- `scripts/etl/test_run_etl_extra_docs.py`
- `scripts/etl/test_stale_exclusions.py`
- `scripts/etl/test_upsert.py`
- `scripts/test_cost_rollup.py`
- `scripts/test_data_health.py`
- `scripts/test_digest_email.py`
- `scripts/test_library_spaces.py`
- `scripts/test_liveness_watchdog.py`
- `scripts/test_switch_corpus.py`

## Not classified -- kept, not deleted

Neither scheduled nor named in the docs. Most are one-off migrations, corpus
builders and QA probes from earlier phases. They are kept because several are
recovery tooling (`export_weaviate_data.py` / `import_exported_weaviate.py`
rebuild the vector store) and deleting recovery tooling on the eve of a
handover is the wrong risk. Date is the last commit that touched the file.

- `scripts/MIGRATION_TEMPLATE.py` — last touched 2026-01-22
- `scripts/add_building_location.py` — last touched 2026-01-07
- `scripts/advanced_filter.py` — last touched 2025-11-16
- `scripts/advanced_killer_questions.py` — last touched 2025-12-19
- `scripts/adversarial_probe.py` — last touched 2026-06-22
- `scripts/analyze_eval_samples.py` — last touched 2026-05-24
- `scripts/analyze_rag_usage.py` — last touched 2025-11-17
- `scripts/apply_building_location_migration.py` — last touched 2026-01-07
- `scripts/archive_conversations.py` — last touched 2026-08-17
- `scripts/audit_referrals.py` — last touched 2026-08-13
- `scripts/auto_label.py` — last touched 2026-05-13
- `scripts/build_exemplars_jsonl.py` — last touched 2026-05-13
- `scripts/build_regression_questions.py` — last touched 2026-01-21
- `scripts/clean_libchat_transcripts.py` — last touched 2026-05-13
- `scripts/clean_transcripts.py` — last touched 2025-11-16
- `scripts/debug_weaviate.py` — last touched 2026-01-30
- `scripts/deduplicate_transcripts.py` — last touched 2025-11-16
- `scripts/etl/__init__.py` — last touched 2026-04-24
- `scripts/etl/backfill_libanswers.py` — last touched 2026-08-08
- `scripts/etl/chunker.py` — last touched 2026-08-08
- `scripts/eval_synth_alone.py` — last touched 2026-05-20
- `scripts/export_conversations_csv.py` — last touched 2026-08-17
- `scripts/export_weaviate_data.py` — last touched 2026-01-30
- `scripts/find_chunks.py` — last touched 2026-06-12
- `scripts/find_label_candidates.py` — last touched 2026-05-13
- `scripts/full_checkup.py` — last touched 2026-06-17
- `scripts/gen_gold_triage.py` — last touched 2026-05-17
- `scripts/generate_comprehensive_examples.py` — last touched 2025-12-22
- `scripts/import_exported_weaviate.py` — last touched 2026-01-30
- `scripts/import_weaviate_jsonl.py` — last touched 2026-01-22
- `scripts/ingest_libguides_policies_oxford.py` — last touched 2026-02-05
- `scripts/inspect_eval_case.py` — last touched 2026-05-15
- `scripts/label_qa.py` — last touched 2026-05-13
- `scripts/pack_labeled_v38.py` — last touched 2026-05-13
- `scripts/process_new_year_data.py` — last touched 2026-07-16
- `scripts/qa_comprehensive.py` — last touched 2026-06-22
- `scripts/qa_contacts_probe.py` — last touched 2026-06-25
- `scripts/qa_hard_knowledge.py` — last touched 2026-06-16
- `scripts/qa_routing_stress.py` — last touched 2026-06-25
- `scripts/qa_soft_knowledge.py` — last touched 2026-06-22
- `scripts/scrape_libguides_policies.py` — last touched 2026-01-12
- `scripts/seed_pattern_c_corrections.py` — last touched 2026-05-21
- `scripts/setup_db.sh` — last touched 2025-11-10
- `scripts/sweep_thresholds.py` — last touched 2026-05-13
- `scripts/switch_corpus.py` — last touched 2026-08-04
- `scripts/sync_all_librarian_subject_mappings.py` — last touched 2026-01-06
- `scripts/upsert_policies_to_weaviate.py` — last touched 2026-01-30
- `scripts/weaviate_smoke_test.py` — last touched 2026-01-22
