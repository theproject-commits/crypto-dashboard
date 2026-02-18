"""Change price_history market columns to decimal.

Revision ID: 20260217_01
Revises:
Create Date: 2026-02-17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260217_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("price_history"):
        return

    with op.batch_alter_table("price_history") as batch_op:
        batch_op.alter_column(
            "market_cap_usd",
            existing_type=sa.BigInteger(),
            type_=sa.Numeric(30, 10),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "total_volume_usd",
            existing_type=sa.BigInteger(),
            type_=sa.Numeric(30, 10),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("price_history"):
        return

    with op.batch_alter_table("price_history") as batch_op:
        batch_op.alter_column(
            "market_cap_usd",
            existing_type=sa.Numeric(30, 10),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "total_volume_usd",
            existing_type=sa.Numeric(30, 10),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
