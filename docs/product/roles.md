# Roles and access

| Capability | employee | recruiter | manager | hr_admin |
|---|---|---|---|---|
| Chat with the bot | own | own | own | own |
| See own onboarding run | yes | yes | yes | yes |
| See other employees' runs | no | own pipeline | own department | all |
| See the employee directory | no | own pipeline | own department | all |
| See the risk digest | no | own pipeline | own department | all |
| Send a manual message | no | own pipeline | no | all |
| Resolve an escalation | no | own pipeline | own department | all |
| Read `audience: hr_only` documents | no | no | no | yes |
| Add or correct a directory row | no | no | no | yes |
| Upload and edit knowledge documents | no | no | no | yes |
| Edit scenarios and prompts | no | no | no | via review only |
| Read metrics | no | own pipeline | own department | all |

## Rules

1. Audience is enforced twice: in the retrieval SQL filter and in the admin API query.
2. A recruiter's token carries `recruiter_id`; a mismatch answers `404`, never `403`.
   A manager's token carries the department name as its subject, so the same SQL predicate becomes
   `employees.department = :subject`. A department head sees the digest and the numbers, not the
   conversation text and not the ability to write to the base.
3. The bot runs with a service identity that has read access to `audience: all` and
   `dept:*` chunks for the employee's department, and no access to `hr_only`.
4. Every escalation resolution writes `question_resolved` with the actor and queues the reply
   through the outbox; the cabinet never calls MAX directly.
5. Removing an employee from the directory sets `status='left'`, closes the run, deletes the
   question rows, and redacts personal fields in the audit log. The audit skeleton survives. The
   call is HR-only and idempotent. Restoring the row clears `left_at` but cannot restore what the
   purge deleted: links and transcripts stay gone, and the person starts over.
6. A directory write names its actor and never starts, stops or restarts a run. The scenario and its
   timer own that, so an HRIS sync cannot hijack an onboarding in flight.
7. Age-based retention is a scheduled pass, not a manual chore: questions and personal audit
   fields older than `DATA_RETENTION_DAYS` are purged. See the retention runbook.
