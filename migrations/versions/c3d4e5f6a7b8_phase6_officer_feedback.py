"""phase6: anonymous officer feedback

Additive only — creates three tables. Changes nothing else.

Anonymity contract C1 is enforced at the SCHEMA level: `officer_feedback` has
no respondent column of any kind (no respondent_id, no token, no IP/user-agent
fields). Its only user foreign key is `officer_user_id` — the officer being
evaluated.

The seeded `feedback_questions` rows are DRAFT placeholders that explicitly
state T6 is unresolved; question wording and the rating scale are NOT finalized
by this migration.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-27

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    questions = op.create_table('feedback_questions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('question_text', sa.Text(), nullable=False),
    sa.Column('question_type', sa.String(length=16), nullable=False),
    sa.Column('scale_min', sa.Integer(), nullable=True),
    sa.Column('scale_max', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('display_order', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('feedback_questions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_feedback_questions_is_active'), ['is_active'], unique=False)

    op.create_table('officer_feedback',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('officer_user_id', sa.Integer(), nullable=False),
    sa.Column('activity_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
    # NOTE: no respondent column exists, by design (C1).
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ),
    sa.ForeignKeyConstraint(['officer_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('officer_feedback', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_officer_feedback_officer_user_id'), ['officer_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_officer_feedback_activity_id'), ['activity_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_officer_feedback_submitted_at'), ['submitted_at'], unique=False)

    op.create_table('feedback_answers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('feedback_id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('rating_value', sa.Integer(), nullable=True),
    sa.Column('comment_text', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['feedback_id'], ['officer_feedback.id'], ),
    sa.ForeignKeyConstraint(['question_id'], ['feedback_questions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('feedback_id', 'question_id', name='uq_answer_feedback_question')
    )
    with op.batch_alter_table('feedback_answers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_feedback_answers_feedback_id'), ['feedback_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_feedback_answers_question_id'), ['question_id'], unique=False)

    # DRAFT question structure only — T6 remains unresolved.
    op.bulk_insert(
        questions,
        [
            {
                "id": 1,
                "question_text": "[DRAFT — pending T6 confirmation] Overall effectiveness in the assigned role.",
                "question_type": "rating",
                "scale_min": 1,
                "scale_max": 5,
                "is_active": True,
                "display_order": 1,
            },
            {
                "id": 2,
                "question_text": "[DRAFT — pending T6 confirmation] Additional comments (optional).",
                "question_type": "text",
                "scale_min": None,
                "scale_max": None,
                "is_active": True,
                "display_order": 2,
            },
        ],
    )


def downgrade():
    # Reverse creation order: child answers first, then submissions, then questions.
    with op.batch_alter_table('feedback_answers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_feedback_answers_question_id'))
        batch_op.drop_index(batch_op.f('ix_feedback_answers_feedback_id'))

    op.drop_table('feedback_answers')

    with op.batch_alter_table('officer_feedback', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_officer_feedback_submitted_at'))
        batch_op.drop_index(batch_op.f('ix_officer_feedback_activity_id'))
        batch_op.drop_index(batch_op.f('ix_officer_feedback_officer_user_id'))

    op.drop_table('officer_feedback')

    with op.batch_alter_table('feedback_questions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_feedback_questions_is_active'))

    op.drop_table('feedback_questions')
