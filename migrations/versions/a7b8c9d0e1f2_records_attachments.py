"""organizational_records: attachment metadata (T14 approved)

Additive only — two nullable columns on `organizational_records`. No existing
column, index, constraint, or row is touched.

  * `attachment_name` VARCHAR(255) — the ORIGINAL (sanitised) filename, shown to
    staff. NULL means "no attachment".
  * `attachment_size` INTEGER     — size in bytes, shown alongside the filename.

The stored file itself is referenced by the EXISTING `file_url` column, which
holds an opaque UUID key (never a filesystem path). Physical files live under
`instance/uploads/records/`, outside `static/`, and are served only through the
authorized download route.

Existing rows get NULL in both columns, which is exactly "no attachment", so the
migration preserves all current records unchanged.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-02

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('organizational_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('attachment_name', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('attachment_size', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('organizational_records', schema=None) as batch_op:
        batch_op.drop_column('attachment_size')
        batch_op.drop_column('attachment_name')
