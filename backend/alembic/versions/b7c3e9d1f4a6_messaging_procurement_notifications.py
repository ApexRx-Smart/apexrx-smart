"""in-platform messaging, procurement requests and quotations, notifications

* conversation / message / conversation_read: one conversation per pharmacy
  and supplier pair (both organizations, not individual users, own it).
  Messages are never edited or deleted, so the history stays complete.
* procurement_request / procurement_request_item: a pharmacy asks one
  supplier for prices on several medicines. An item is either a catalogue
  product or a free-text description (name, strength, form, pack size), so a
  pharmacy can ask for medicines the supplier does not list, or that are not
  in the central catalogue, without adding anything to the catalogue.
* quotation / quotation_item: the supplier's answers, numbered revisions per
  request. A submitted quotation is never changed: a revision is a new row and
  the previous one becomes "superseded".
* notification / notification_read: events for an organization; read state
  per user.
* purchase_order: procurement_request_id and quotation_id (each unique, so
  one request can never produce two orders). purchase_order_item: product_id
  becomes optional and item_description is added, so a quoted medicine that
  is not in the catalogue can still be ordered. Existing rows are unchanged.

Revision ID: b7c3e9d1f4a6
Revises: f3a9c1d7b2e5
Create Date: 2026-11-15 09:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b7c3e9d1f4a6"
down_revision: Union[str, Sequence[str], None] = "f3a9c1d7b2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REQUEST_STATUSES = "'submitted', 'viewed', 'quoted', 'negotiation', 'accepted', 'rejected', 'cancelled', 'converted'"
QUOTATION_STATUSES = "'draft', 'submitted', 'revision_requested', 'accepted', 'rejected', 'superseded'"
NOTIFICATION_KINDS = (
    "'request_submitted', 'request_cancelled', 'request_declined', 'quotation_submitted', "
    "'revision_requested', 'quotation_accepted', 'quotation_rejected', 'order_created', 'message'"
)


def upgrade() -> None:
    op.execute(
        f"""
        -- ------------------------------------------------------------------
        -- Conversations and messages
        -- ------------------------------------------------------------------
        CREATE TABLE conversation (
            conversation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            pharmacy_organization_id BIGINT NOT NULL,
            supplier_organization_id BIGINT NOT NULL,
            pharmacy_org_type VARCHAR(20) NOT NULL DEFAULT 'pharmacy' CHECK (pharmacy_org_type = 'pharmacy'),
            supplier_org_type VARCHAR(20) NOT NULL DEFAULT 'supplier' CHECK (supplier_org_type = 'supplier'),
            created_by BIGINT REFERENCES app_user(user_id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_message_at TIMESTAMPTZ,
            FOREIGN KEY (pharmacy_organization_id, pharmacy_org_type)
                REFERENCES organization(organization_id, type),
            FOREIGN KEY (supplier_organization_id, supplier_org_type)
                REFERENCES organization(organization_id, type),
            CONSTRAINT uq_conversation_pair UNIQUE (pharmacy_organization_id, supplier_organization_id)
        );
        CREATE INDEX idx_conversation_supplier ON conversation (supplier_organization_id, last_message_at DESC);

        CREATE TABLE message (
            message_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            conversation_id BIGINT NOT NULL REFERENCES conversation(conversation_id),
            sender_organization_id BIGINT NOT NULL REFERENCES organization(organization_id),
            sender_user_id BIGINT REFERENCES app_user(user_id) ON DELETE SET NULL,
            body TEXT NOT NULL CHECK (char_length(btrim(body)) BETWEEN 1 AND 4000),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_message_conversation ON message (conversation_id, message_id);

        -- The sender must be one of the two organizations; messages are permanent.
        CREATE FUNCTION message_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'messages cannot be edited or deleted';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM conversation c
                WHERE c.conversation_id = NEW.conversation_id
                  AND NEW.sender_organization_id IN (c.pharmacy_organization_id, c.supplier_organization_id)
            ) THEN
                RAISE EXCEPTION 'the sender organization is not part of this conversation';
            END IF;
            UPDATE conversation SET last_message_at = NEW.created_at
            WHERE conversation_id = NEW.conversation_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_message_guard
            BEFORE INSERT OR UPDATE OR DELETE ON message
            FOR EACH ROW EXECUTE FUNCTION message_guard();

        CREATE TABLE conversation_read (
            conversation_id BIGINT NOT NULL REFERENCES conversation(conversation_id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
            last_read_message_id BIGINT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (conversation_id, user_id)
        );

        -- ------------------------------------------------------------------
        -- Procurement requests (pharmacy to one supplier)
        -- ------------------------------------------------------------------
        CREATE TABLE procurement_request (
            procurement_request_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            pharmacy_organization_id BIGINT NOT NULL,
            supplier_organization_id BIGINT NOT NULL,
            pharmacy_org_type VARCHAR(20) NOT NULL DEFAULT 'pharmacy' CHECK (pharmacy_org_type = 'pharmacy'),
            supplier_org_type VARCHAR(20) NOT NULL DEFAULT 'supplier' CHECK (supplier_org_type = 'supplier'),
            pharmacy_location_id BIGINT NOT NULL,
            conversation_id BIGINT NOT NULL REFERENCES conversation(conversation_id),
            status VARCHAR(20) NOT NULL DEFAULT 'submitted' CHECK (status IN ({REQUEST_STATUSES})),
            currency CHAR(3) NOT NULL DEFAULT 'RWF',
            notes TEXT,
            needed_by DATE,
            status_reason TEXT,
            created_by BIGINT REFERENCES app_user(user_id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            viewed_at TIMESTAMPTZ,
            FOREIGN KEY (pharmacy_organization_id, pharmacy_org_type)
                REFERENCES organization(organization_id, type),
            FOREIGN KEY (supplier_organization_id, supplier_org_type)
                REFERENCES organization(organization_id, type),
            FOREIGN KEY (pharmacy_location_id, pharmacy_organization_id)
                REFERENCES location(location_id, organization_id)
        );
        CREATE INDEX idx_procurement_request_pharmacy ON procurement_request (pharmacy_organization_id, created_at DESC);
        CREATE INDEX idx_procurement_request_supplier ON procurement_request (supplier_organization_id, status, created_at DESC);

        CREATE TABLE procurement_request_item (
            procurement_request_item_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            procurement_request_id BIGINT NOT NULL
                REFERENCES procurement_request(procurement_request_id) ON DELETE CASCADE,
            line_no INTEGER NOT NULL CHECK (line_no > 0),
            product_id BIGINT REFERENCES product(product_id),
            medicine_name VARCHAR(255) NOT NULL CHECK (btrim(medicine_name) <> ''),
            strength VARCHAR(100),
            dosage_form VARCHAR(100),
            pack_size VARCHAR(100),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            notes TEXT,
            UNIQUE (procurement_request_id, line_no),
            UNIQUE (procurement_request_id, product_id)
        );

        -- ------------------------------------------------------------------
        -- Quotations (supplier answers, numbered revisions)
        -- ------------------------------------------------------------------
        CREATE TABLE quotation (
            quotation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            procurement_request_id BIGINT NOT NULL
                REFERENCES procurement_request(procurement_request_id) ON DELETE CASCADE,
            revision INTEGER NOT NULL CHECK (revision > 0),
            status VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (status IN ({QUOTATION_STATUSES})),
            currency CHAR(3) NOT NULL DEFAULT 'RWF',
            note TEXT,
            estimated_days INTEGER CHECK (estimated_days BETWEEN 0 AND 365),
            created_by BIGINT REFERENCES app_user(user_id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            submitted_by BIGINT REFERENCES app_user(user_id) ON DELETE SET NULL,
            submitted_at TIMESTAMPTZ,
            responded_by BIGINT REFERENCES app_user(user_id) ON DELETE SET NULL,
            responded_at TIMESTAMPTZ,
            response_note TEXT,
            CHECK (status = 'draft' OR submitted_at IS NOT NULL),
            UNIQUE (procurement_request_id, revision)
        );
        -- At most one quotation being written or waiting for an answer, and at
        -- most one accepted, per request.
        CREATE UNIQUE INDEX uq_quotation_open ON quotation (procurement_request_id)
            WHERE status IN ('draft', 'submitted');
        CREATE UNIQUE INDEX uq_quotation_accepted ON quotation (procurement_request_id)
            WHERE status = 'accepted';

        CREATE TABLE quotation_item (
            quotation_item_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            quotation_id BIGINT NOT NULL REFERENCES quotation(quotation_id) ON DELETE CASCADE,
            procurement_request_item_id BIGINT NOT NULL
                REFERENCES procurement_request_item(procurement_request_item_id),
            available BOOLEAN NOT NULL,
            quantity INTEGER CHECK (quantity > 0),
            unit_price NUMERIC(14, 2) CHECK (unit_price >= 0),
            note TEXT,
            CHECK (available = (quantity IS NOT NULL AND unit_price IS NOT NULL)),
            CHECK (available OR (quantity IS NULL AND unit_price IS NULL)),
            UNIQUE (quotation_id, procurement_request_item_id)
        );

        -- Only drafts may have their lines changed: a sent quotation is history.
        CREATE FUNCTION quotation_item_guard() RETURNS trigger AS $$
        DECLARE
            parent_status VARCHAR(20);
        BEGIN
            SELECT status INTO parent_status FROM quotation
            WHERE quotation_id = COALESCE(NEW.quotation_id, OLD.quotation_id);
            IF parent_status IS NOT NULL AND parent_status <> 'draft' THEN
                RAISE EXCEPTION 'quotation lines cannot change once the quotation is sent';
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_quotation_item_guard
            BEFORE INSERT OR UPDATE OR DELETE ON quotation_item
            FOR EACH ROW EXECUTE FUNCTION quotation_item_guard();

        -- ------------------------------------------------------------------
        -- Orders created from an accepted quotation
        -- ------------------------------------------------------------------
        ALTER TABLE purchase_order
            ADD COLUMN procurement_request_id BIGINT UNIQUE
                REFERENCES procurement_request(procurement_request_id),
            ADD COLUMN quotation_id BIGINT UNIQUE REFERENCES quotation(quotation_id),
            ADD CONSTRAINT purchase_order_quotation_check
                CHECK ((procurement_request_id IS NULL) = (quotation_id IS NULL));

        ALTER TABLE purchase_order_item
            ALTER COLUMN product_id DROP NOT NULL,
            ADD COLUMN item_description VARCHAR(255),
            ADD CONSTRAINT purchase_order_item_description_check
                CHECK (product_id IS NOT NULL OR btrim(coalesce(item_description, '')) <> '');

        -- ------------------------------------------------------------------
        -- Notifications
        -- ------------------------------------------------------------------
        CREATE TABLE notification (
            notification_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id BIGINT NOT NULL REFERENCES organization(organization_id) ON DELETE CASCADE,
            kind VARCHAR(30) NOT NULL CHECK (kind IN ({NOTIFICATION_KINDS})),
            from_organization_id BIGINT REFERENCES organization(organization_id) ON DELETE SET NULL,
            conversation_id BIGINT REFERENCES conversation(conversation_id) ON DELETE CASCADE,
            procurement_request_id BIGINT
                REFERENCES procurement_request(procurement_request_id) ON DELETE CASCADE,
            quotation_id BIGINT REFERENCES quotation(quotation_id) ON DELETE CASCADE,
            purchase_order_id BIGINT REFERENCES purchase_order(purchase_order_id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_notification_org ON notification (organization_id, notification_id DESC);

        CREATE TABLE notification_read (
            notification_id BIGINT NOT NULL REFERENCES notification(notification_id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
            read_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (notification_id, user_id)
        );
        CREATE INDEX idx_notification_read_user ON notification_read (user_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS notification_read;
        DROP TABLE IF EXISTS notification;
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM purchase_order_item WHERE product_id IS NULL) THEN
                RAISE EXCEPTION 'orders contain medicines outside the catalogue; downgrade would lose them';
            END IF;
        END $$;
        ALTER TABLE purchase_order_item
            DROP CONSTRAINT IF EXISTS purchase_order_item_description_check,
            DROP COLUMN IF EXISTS item_description,
            ALTER COLUMN product_id SET NOT NULL;
        ALTER TABLE purchase_order
            DROP CONSTRAINT IF EXISTS purchase_order_quotation_check,
            DROP COLUMN IF EXISTS quotation_id,
            DROP COLUMN IF EXISTS procurement_request_id;
        DROP TABLE IF EXISTS quotation_item;
        DROP FUNCTION IF EXISTS quotation_item_guard();
        DROP TABLE IF EXISTS quotation;
        DROP TABLE IF EXISTS procurement_request_item;
        DROP TABLE IF EXISTS procurement_request;
        DROP TABLE IF EXISTS conversation_read;
        DROP TABLE IF EXISTS message;
        DROP FUNCTION IF EXISTS message_guard();
        DROP TABLE IF EXISTS conversation;
        """
    )
