"""web accounts: one account per person

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22 14:00:00

Authorization maps the signed-in account to a handoff role through app_user.person_id, so
two accounts must never speak for the same person. Admins have no person (null).
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_app_user_person_id",
        "app_user",
        ["person_id"],
        unique=True,
        postgresql_where="person_id is not null",
    )


def downgrade() -> None:
    op.drop_index("uq_app_user_person_id", table_name="app_user")
