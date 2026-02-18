"""Create market_composite_v2_snapshots table.

Revision ID: 20260217_02
Revises: 20260217_01
Create Date: 2026-02-17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260217_02"
down_revision = "20260217_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("market_composite_v2_snapshots"):
        return

    op.create_table(
        "market_composite_v2_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crypto_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("regime_score", sa.Float(), nullable=False),
        sa.Column("flow_score", sa.Float(), nullable=False),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("regime_weight", sa.Float(), nullable=False),
        sa.Column("flow_weight", sa.Float(), nullable=False),
        sa.Column("sentiment_weight", sa.Float(), nullable=False),
        sa.Column("risk_weight", sa.Float(), nullable=False),
        sa.Column("composite_score", sa.Float(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["crypto_id"], ["cryptocurrencies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "crypto_id",
            "snapshot_date",
            "horizon_days",
            name="uq_market_composite_v2_crypto_date_horizon",
        ),
    )
    op.create_index(
        "ix_market_composite_v2_snapshots_id",
        "market_composite_v2_snapshots",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_market_composite_v2_snapshots_crypto_id",
        "market_composite_v2_snapshots",
        ["crypto_id"],
        unique=False,
    )
    op.create_index(
        "ix_market_composite_v2_snapshots_snapshot_date",
        "market_composite_v2_snapshots",
        ["snapshot_date"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("market_composite_v2_snapshots"):
        return

    op.drop_index("ix_market_composite_v2_snapshots_snapshot_date", table_name="market_composite_v2_snapshots")
    op.drop_index("ix_market_composite_v2_snapshots_crypto_id", table_name="market_composite_v2_snapshots")
    op.drop_index("ix_market_composite_v2_snapshots_id", table_name="market_composite_v2_snapshots")
    op.drop_table("market_composite_v2_snapshots")
