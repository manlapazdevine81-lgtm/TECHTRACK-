"""users: must_change_password (first-login password change)

Additive only — one non-nullable BOOLEAN column on `users`. No existing column,
index, constraint, or row is modified or deleted.

`server_default=false` backfills every existing account with FALSE, so all
current users keep their normal access. Newly provisioned accounts are created
with TRUE by the application and must choose a new password before they can use
any protected route.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-02

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'must_change_password',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('must_change_password')
