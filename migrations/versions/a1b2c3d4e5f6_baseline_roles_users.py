"""phase0 baseline: roles and users

The original database was bootstrapped with ``db.create_all()``, so these two
tables never had an Alembic revision. This baseline makes the chain buildable
from an empty database: every later revision references ``users.id``.

Columns mirror ``app/models/user.py`` exactly:
  * ``roles.name`` is unique.
  * ``users.email`` and ``users.student_id`` are unique (student_id nullable).
  * ``users`` has ``created_at`` but NO ``updated_at`` — the model has none, and
    the revision must not invent a server default the model does not declare.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-10-25

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('roles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('display_name', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )

    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('student_id', sa.String(length=64), nullable=True),
    sa.Column('role_id', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('student_id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)


def downgrade():
    # Reverse creation order: users first (it owns the FK to roles).
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    op.drop_table('roles')
