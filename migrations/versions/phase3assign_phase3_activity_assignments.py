"""phase3: activity_assignments

Revision ID: phase3assign
Revises: 625c94493a3d
Create Date: 2026-10-23 20:18:05.817687

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'phase3assign'
down_revision = '625c94493a3d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('activity_assignments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('activity_id', sa.Integer(), nullable=False),
    sa.Column('officer_user_id', sa.Integer(), nullable=False),
    sa.Column('responsibility', sa.Text(), nullable=False),
    sa.Column('assigned_by', sa.Integer(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ),
    sa.ForeignKeyConstraint(['assigned_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['officer_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('activity_id', 'officer_user_id', 'responsibility', name='uq_assignment_activity_officer_responsibility')
    )
    with op.batch_alter_table('activity_assignments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_activity_assignments_activity_id'), ['activity_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_assignments_officer_user_id'), ['officer_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_assignments_status'), ['status'], unique=False)


def downgrade():
    # Additive-only migration: the table was created here, so removing it
    # restores the previous schema exactly. No other table is touched.
    with op.batch_alter_table('activity_assignments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_activity_assignments_status'))
        batch_op.drop_index(batch_op.f('ix_activity_assignments_officer_user_id'))
        batch_op.drop_index(batch_op.f('ix_activity_assignments_activity_id'))

    op.drop_table('activity_assignments')
