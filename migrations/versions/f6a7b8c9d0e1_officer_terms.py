"""officer_terms — organizational position assignments

Additive only: creates the single `officer_terms` table. No existing table,
column, index, or row is touched.

Columns mirror `app/models/officer_term.py` and docs/ERD.md `officer_terms`:
  * `user_id`      -> users.id     (system account, unchanged)
  * `position_id`  -> positions.id (organizational position)
  * `start_date` / `end_date`      (end_date NULL while the term is open)
  * `status`                       ('active' | 'ended'; nothing is deleted)

`UNIQUE (user_id, position_id, start_date)` prevents recording the same
assignment twice on the same day while still allowing a user to hold several
positions and a position to be held by several users.

This table is organizational metadata only: no authorization code reads it, and
`positions.permission_level` remains frozen (T19).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-02

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('officer_terms',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('position_id', sa.Integer(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['position_id'], ['positions.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'position_id', 'start_date', name='uq_term_user_position_start'),
    )
    with op.batch_alter_table('officer_terms', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_officer_terms_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_officer_terms_position_id'), ['position_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_officer_terms_status'), ['status'], unique=False)


def downgrade():
    with op.batch_alter_table('officer_terms', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_officer_terms_status'))
        batch_op.drop_index(batch_op.f('ix_officer_terms_position_id'))
        batch_op.drop_index(batch_op.f('ix_officer_terms_user_id'))

    op.drop_table('officer_terms')
