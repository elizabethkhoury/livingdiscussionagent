"""add account health snapshots and halt records"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260430_0002"
down_revision = "20260429_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_health_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("link_karma", sa.Integer(), nullable=False),
        sa.Column("comment_karma", sa.Integer(), nullable=False),
        sa.Column("total_karma", sa.Integer(), nullable=False),
        sa.Column("link_karma_delta", sa.Integer(), nullable=True),
        sa.Column("comment_karma_delta", sa.Integer(), nullable=True),
        sa.Column("total_karma_delta", sa.Integer(), nullable=True),
        sa.Column("tracked_post_score_total", sa.Integer(), nullable=False),
        sa.Column("tracked_post_score_delta", sa.Integer(), nullable=True),
        sa.Column("source_payload_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", "snapshot_date", name="uq_account_health_snapshot_user_date"),
    )
    op.create_index("ix_account_health_snapshots_snapshot_date", "account_health_snapshots", ["snapshot_date"])
    op.create_index("ix_account_health_snapshots_username", "account_health_snapshots", ["username"])
    op.create_index("ix_account_health_snapshots_username_date", "account_health_snapshots", ["username", "snapshot_date"])

    op.create_table(
        "agent_halts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("triggered_by_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("thresholds_json", sa.JSON(), nullable=False),
        sa.Column("observed_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["triggered_by_snapshot_id"], ["account_health_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_halts_created_at", "agent_halts", ["created_at"])
    op.create_index("ix_agent_halts_reason_code", "agent_halts", ["reason_code"])
    op.create_index("ix_agent_halts_resolved_at", "agent_halts", ["resolved_at"])
    op.create_index("ix_agent_halts_triggered_by_snapshot_id", "agent_halts", ["triggered_by_snapshot_id"])


def downgrade():
    op.drop_index("ix_agent_halts_triggered_by_snapshot_id", table_name="agent_halts")
    op.drop_index("ix_agent_halts_resolved_at", table_name="agent_halts")
    op.drop_index("ix_agent_halts_reason_code", table_name="agent_halts")
    op.drop_index("ix_agent_halts_created_at", table_name="agent_halts")
    op.drop_table("agent_halts")
    op.drop_index("ix_account_health_snapshots_username_date", table_name="account_health_snapshots")
    op.drop_index("ix_account_health_snapshots_username", table_name="account_health_snapshots")
    op.drop_index("ix_account_health_snapshots_snapshot_date", table_name="account_health_snapshots")
    op.drop_table("account_health_snapshots")
