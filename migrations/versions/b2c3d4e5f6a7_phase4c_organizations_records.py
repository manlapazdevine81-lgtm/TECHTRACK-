"""phase4c: organizations and organizational_records

Additive only — creates the two Phase 4C tables and changes nothing else.

Columns mirror the ORM models exactly:
  * ``app/models/organization.py`` — ``logo_url`` is intentionally absent (T17
    branding unconfirmed); ``adviser_id`` is a nullable FK to ``users.id``.
  * ``app/models/organizational_record.py`` — ``organization_id`` is required,
    ``file_url`` is nullable and unused (T14), and ``record_date`` is NOT NULL
    for fresh installations (application validation already requires it).

Revision ID: b2c3d4e5f6a7
Revises: phase3assign
Create Date: 2026-10-25

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'phase3assign'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('organizations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('academic_year', sa.String(length=32), nullable=True),
    sa.Column('adviser_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['adviser_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_organizations_adviser_id'), ['adviser_id'], unique=False)

    op.create_table('organizational_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('record_type', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('file_url', sa.String(length=512), nullable=True),
    sa.Column('record_date', sa.Date(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('organizational_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_organizational_records_organization_id'), ['organization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_organizational_records_record_type'), ['record_type'], unique=False)


def downgrade():
    # Reverse creation order: the child table (and its indexes) first, then the
    # parent. No other table is touched.
    with op.batch_alter_table('organizational_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_organizational_records_record_type'))
        batch_op.drop_index(batch_op.f('ix_organizational_records_organization_id'))

    op.drop_table('organizational_records')

    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_organizations_adviser_id'))

    op.drop_table('organizations')
