"""verify: assessment provenance and integrity

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13 09:00:00

- exercise.generator_id: which generator proposed the draft.
- attempt.assessor_id / assessment_error: which assessor judged it, or why it failed.
- aggregate_result exists exactly when assessment_status = 'succeeded', so a provider
  failure can never carry a learner result.
- The attempt trigger now also freezes a completed assessment; only a pending or failed
  attempt may be (re)assessed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ORIGINAL_FN = """
    create or replace function sb_forbid_answer_change() returns trigger as $$
    begin
      if new.answer is distinct from old.answer or new.exercise_id is distinct from old.exercise_id
         or new.successor_id is distinct from old.successor_id then
        raise exception 'attempt answers are immutable' using errcode = 'P0001';
      end if;
      return new;
    end; $$ language plpgsql;
"""


def upgrade() -> None:
    op.add_column("exercise", sa.Column("generator_id", sa.Text(), nullable=True))
    op.add_column("attempt", sa.Column("assessor_id", sa.Text(), nullable=True))
    op.add_column("attempt", sa.Column("assessment_error", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_attempt_result_only_when_succeeded",
        "attempt",
        "(assessment_status = 'succeeded') = (aggregate_result is not null)",
    )
    op.execute("""
        create or replace function sb_forbid_answer_change() returns trigger as $$
        begin
          if new.answer is distinct from old.answer or new.exercise_id is distinct from old.exercise_id
             or new.successor_id is distinct from old.successor_id then
            raise exception 'attempt answers are immutable' using errcode = 'P0001';
          end if;
          if old.assessment_status = 'succeeded' then
            raise exception 'completed attempt assessments are immutable' using errcode = 'P0001';
          end if;
          return new;
        end; $$ language plpgsql;
    """)


def downgrade() -> None:
    op.execute(ORIGINAL_FN)
    op.drop_constraint("ck_attempt_result_only_when_succeeded", "attempt", type_="check")
    op.drop_column("attempt", "assessment_error")
    op.drop_column("attempt", "assessor_id")
    op.drop_column("exercise", "generator_id")
