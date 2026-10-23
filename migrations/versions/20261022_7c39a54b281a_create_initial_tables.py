"""create initial tables

Revision ID: 7c39a54b281a
Revises:
Create Date: 2026-10-22 10:54:09.650177
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c39a54b281a"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_destinations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=2), nullable=False),
        sa.Column(
            "climate",
            sa.Enum(
                "hot", "mild", "cold", name="climate", native_enum=False, create_constraint=True, length=32
            ),
            nullable=False,
        ),
        sa.Column(
            "pace",
            sa.Enum(
                "relaxed",
                "balanced",
                "intense",
                name="pace",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("pace_note", sa.Text(), nullable=False),
        sa.Column("fixed_cost", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("nightly_cost", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("cost_source", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "trips",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("organizer_id", sa.String(length=36), nullable=True),
        sa.Column("admin_token_hash", sa.String(length=64), nullable=False),
        sa.Column("date_window_start", sa.Date(), nullable=False),
        sa.Column("date_window_end", sa.Date(), nullable=False),
        sa.Column("nights", sa.Integer(), nullable=False),
        sa.Column("alpha", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "collecting",
                "planned",
                "agreed",
                name="trip_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("alpha >= 0 AND alpha <= 1", name="alpha_range"),
        sa.CheckConstraint("date_window_end > date_window_start", name="window_order"),
        sa.CheckConstraint("nights >= 1", name="nights_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("admin_token_hash"),
    )
    op.create_table(
        "members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=60), nullable=False),
        sa.Column("invite_token_hash", sa.String(length=64), nullable=False),
        sa.Column("is_organizer", sa.Boolean(), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invite_token_hash"),
        sa.UniqueConstraint("trip_id", "position"),
    )
    op.create_index(op.f("ix_members_trip_id"), "members", ["trip_id"], unique=False)
    op.create_table(
        "plan_rounds",
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("alpha", sa.Float(), nullable=False),
        sa.Column("alternatives_evaluated", sa.Integer(), nullable=False),
        sa.Column("excluded_destinations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("blocking_limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("trip_id", "round"),
    )
    op.create_table(
        "trip_destinations",
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("destination_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["catalog_destinations.id"],
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("trip_id", "destination_id"),
    )
    op.create_table(
        "constraints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("member_id", sa.String(length=36), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("hard", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("soft", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "confirmed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_id", "version"),
    )
    op.create_index(op.f("ix_constraints_member_id"), "constraints", ["member_id"], unique=False)
    op.create_table(
        "plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("destination_id", sa.String(length=64), nullable=False),
        sa.Column("variant_label", sa.String(length=60), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("est_cost_per_person", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("alpha", sa.Float(), nullable=False),
        sa.Column("alternatives_evaluated", sa.Integer(), nullable=False),
        sa.Column("violated_limits", sa.Integer(), nullable=False),
        sa.Column("per_member_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("explanation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["catalog_destinations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["trip_id", "round"], ["plan_rounds.trip_id", "plan_rounds.round"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trip_id", "round", "position"),
    )
    op.create_table(
        "reactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("member_id", sa.String(length=36), nullable=False),
        sa.Column(
            "verdict",
            sa.Enum(
                "accepted",
                "accepted_with_reservation",
                "rejected",
                name="verdict",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("reacted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "member_id"),
    )
    op.create_index(op.f("ix_reactions_plan_id"), "reactions", ["plan_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reactions_plan_id"), table_name="reactions")
    op.drop_table("reactions")
    op.drop_table("plans")
    op.drop_index(op.f("ix_constraints_member_id"), table_name="constraints")
    op.drop_table("constraints")
    op.drop_table("trip_destinations")
    op.drop_table("plan_rounds")
    op.drop_index(op.f("ix_members_trip_id"), table_name="members")
    op.drop_table("members")
    op.drop_table("trips")
    op.drop_table("catalog_destinations")
