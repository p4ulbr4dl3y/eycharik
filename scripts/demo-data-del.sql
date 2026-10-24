-- Local demo reset: clears runtime data, the demo cohort, and the indexed knowledge.
-- Do not run this against a database you care about.
TRUNCATE messages, jobs, events, questions, audit_log, runs RESTART IDENTITY CASCADE;
DELETE FROM channel_identities WHERE employee_id IN ('1001', '1002', '1003');
DELETE FROM employees WHERE id IN ('1001', '1002', '1003');
TRUNCATE kb_chunks, kb_documents, kb_files, kb_extractions, kb_index_state RESTART IDENTITY CASCADE;
