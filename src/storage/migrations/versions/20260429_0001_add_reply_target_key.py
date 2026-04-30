"""add reply target idempotency key"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260429_0001"
down_revision = None
branch_labels = None
depends_on = None


ACTIVE_ATTEMPT_WHERE = "reply_target_key IS NOT NULL AND status IN ('pending', 'posted')"


def upgrade():
    op.add_column("post_attempts", sa.Column("reply_target_key", sa.String(length=128), nullable=True))
    op.create_index("ix_post_attempts_reply_target_key", "post_attempts", ["reply_target_key"])
    _backfill_reply_target_keys()
    op.create_index(
        "uq_post_attempts_active_reply_target",
        "post_attempts",
        ["reply_target_key"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_ATTEMPT_WHERE),
        sqlite_where=sa.text(ACTIVE_ATTEMPT_WHERE),
    )


def downgrade():
    op.drop_index("uq_post_attempts_active_reply_target", table_name="post_attempts")
    op.drop_index("ix_post_attempts_reply_target_key", table_name="post_attempts")
    op.drop_column("post_attempts", "reply_target_key")


def _backfill_reply_target_keys():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                """
                UPDATE post_attempts AS pa
                SET reply_target_key = COALESCE(
                    'reddit:comment:' || tc.platform_comment_id,
                    'reddit:thread:' || t.platform_thread_id
                )
                FROM drafts AS d
                JOIN decisions AS de ON de.id = d.decision_id
                JOIN classifications AS c ON c.id = de.classification_id
                JOIN threads AS t ON t.id = c.thread_id
                LEFT JOIN thread_comments AS tc ON tc.id = c.target_comment_id
                WHERE pa.draft_id = d.id
                  AND pa.status = 'posted'
                  AND pa.reply_target_key IS NULL
                """
            )
        )
        return

    bind.execute(
        sa.text(
            """
            UPDATE post_attempts
            SET reply_target_key = (
                SELECT COALESCE(
                    'reddit:comment:' || thread_comments.platform_comment_id,
                    'reddit:thread:' || threads.platform_thread_id
                )
                FROM drafts
                JOIN decisions ON decisions.id = drafts.decision_id
                JOIN classifications ON classifications.id = decisions.classification_id
                JOIN threads ON threads.id = classifications.thread_id
                LEFT JOIN thread_comments ON thread_comments.id = classifications.target_comment_id
                WHERE drafts.id = post_attempts.draft_id
            )
            WHERE status = 'posted'
              AND reply_target_key IS NULL
            """
        )
    )
