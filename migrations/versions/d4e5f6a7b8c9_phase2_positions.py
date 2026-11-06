"""phase2: positions (Organization Structure)

Additive only — creates the single `positions` table and changes nothing else.

Columns mirror `app/models/position.py` exactly:
  * `department` is a DISPLAY GROUPING (no departments table exists). NULL means
    the Executive Board; other values are validated against
    `app/organizational_structure.DEPARTMENTS` in the application layer.
  * `sort_order` orders positions inside their section for display only.
  * `permission_level` from the ERD is deliberately NOT created: T19 freezes it
    and no logic may read it, so the column has no purpose here.
  * `UNIQUE (organization_id, title)` makes seeding idempotent.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-31

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('positions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=128), nullable=False),
    sa.Column('department', sa.String(length=64), nullable=True),
    sa.Column('duties', sa.Text(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'title', name='uq_position_org_title'),
    )
    with op.batch_alter_table('positions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_positions_organization_id'), ['organization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_positions_department'), ['department'], unique=False)


def downgrade():
    with op.batch_alter_table('positions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_positions_department'))
        batch_op.drop_index(batch_op.f('ix_positions_organization_id'))

    op.drop_table('positions')
