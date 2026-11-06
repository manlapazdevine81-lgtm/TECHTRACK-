"""attendance: last_edited_by / last_edited_at

Additive only — two nullable columns (and one index) on `attendance_records`.
Nothing else is touched; no data is rewritten.

Semantics
    ``recorded_by`` / ``recorded_at`` keep their existing behaviour: they are
    refreshed by every write, so they reflect the latest correction rather than
    the original creator.
    ``last_edited_by`` / ``last_edited_at`` are set ONLY when an existing row is
    corrected. They are NULL on rows that have never been edited, and are
    re-stamped on every correction. No correction history is stored.

    Both columns are nullable with no server default, so existing rows migrate to
    NULL (never edited), which is exactly the intended meaning.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-31

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_edited_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('last_edited_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_attendance_records_last_edited_by'),
            ['last_edited_by'],
            unique=False,
        )
        batch_op.create_foreign_key(
            'fk_attendance_records_last_edited_by_users',
            'users',
            ['last_edited_by'],
            ['id'],
        )


def downgrade():
    # Reverse in the opposite order: drop the FK and index before the columns.
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_attendance_records_last_edited_by_users', type_='foreignkey'
        )
        batch_op.drop_index(batch_op.f('ix_attendance_records_last_edited_by'))
        batch_op.drop_column('last_edited_at')
        batch_op.drop_column('last_edited_by')
