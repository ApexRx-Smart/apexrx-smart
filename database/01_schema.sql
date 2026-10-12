-- =====================================================================
-- ApexRx Smart : schéma PostgreSQL v1 (prototype du 15 octobre 2026)
-- Cible : PostgreSQL 16+ (testé en 16) avec PostGIS.
-- Base de l'ER de l'équipe (drug, product, batch, organization,
-- location, stock, app_user, membership), corrigée et complétée.
--
-- Lancer sur une base dédiée :  CREATE DATABASE apexrx;
-- L'API doit se connecter avec le rôle apexrx_api (pas le propriétaire,
-- pas un superutilisateur), sinon la sécurité par ligne (RLS) est ignorée.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- recherche tolérante aux fautes
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- utilisé seulement par le seed de démo

-- ---------------------------------------------------------------------
-- 1. Types
-- ---------------------------------------------------------------------
CREATE TYPE platform_role       AS ENUM ('patient', 'doctor', 'member', 'admin');
CREATE TYPE membership_role     AS ENUM ('owner', 'staff');
CREATE TYPE org_type            AS ENUM ('pharmacy', 'supplier');
CREATE TYPE verification_status AS ENUM ('pending', 'verified', 'rejected', 'suspended');
CREATE TYPE conversation_kind   AS ENUM ('pharmacy_supplier', 'pharmacy_pharmacy');
CREATE TYPE message_kind        AS ENUM ('text', 'quote', 'attachment', 'system');
CREATE TYPE quote_status        AS ENUM ('proposed', 'accepted', 'declined', 'countered', 'expired', 'withdrawn');
CREATE TYPE order_status        AS ENUM ('requested', 'confirmed', 'rejected', 'fulfilled', 'cancelled');
CREATE TYPE payment_method      AS ENUM ('mtn_momo', 'airtel_money', 'card');

-- ---------------------------------------------------------------------
-- 2. Identité : utilisateurs, organisations, appartenance, vérification
-- ---------------------------------------------------------------------
CREATE TABLE app_user (
    user_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name              text        NOT NULL,
    email             text        NOT NULL,
    phone             text,
    password_hash     text        NOT NULL,
    platform_role     platform_role NOT NULL DEFAULT 'member',
    language          text        NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'fr', 'rw')),
    is_active         boolean     NOT NULL DEFAULT true,
    email_verified_at timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX app_user_email_key ON app_user (lower(email));

CREATE TABLE refresh_token (
    token_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     bigint      NOT NULL REFERENCES app_user ON DELETE CASCADE,
    token_hash  text        NOT NULL UNIQUE,
    expires_at  timestamptz NOT NULL,
    revoked_at  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX refresh_token_user_idx ON refresh_token (user_id);

CREATE TABLE organization (
    organization_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                text        NOT NULL,
    type                org_type    NOT NULL,
    -- NPC (National Pharmacy Council) pour une pharmacie, licence pour un fournisseur
    registration_number text        NOT NULL,
    verification_status verification_status NOT NULL DEFAULT 'pending',
    verified_by         bigint      REFERENCES app_user,
    verified_at         timestamptz,
    rejection_reason    text,
    phone               text,
    email               text,
    plan                text        NOT NULL DEFAULT 'essential' CHECK (plan IN ('essential', 'premium')),
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (type, registration_number),
    CHECK (verification_status <> 'verified' OR verified_at IS NOT NULL)
);

CREATE TABLE membership (
    membership_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         bigint NOT NULL REFERENCES app_user ON DELETE CASCADE,
    organization_id bigint NOT NULL REFERENCES organization ON DELETE CASCADE,
    role            membership_role NOT NULL DEFAULT 'staff',
    UNIQUE (user_id, organization_id)
);
CREATE INDEX membership_org_idx ON membership (organization_id);

CREATE TABLE location (
    location_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL REFERENCES organization ON DELETE CASCADE,
    name            text   NOT NULL,
    address         text,
    city            text   NOT NULL DEFAULT 'Kigali',
    district        text,            -- Gasabo, Kicukiro, Nyarugenge
    sector          text,
    latitude        double precision NOT NULL CHECK (latitude  BETWEEN -90  AND 90),
    longitude       double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    geog            geography(Point, 4326) GENERATED ALWAYS AS
                    (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED,
    is_public       boolean NOT NULL DEFAULT true,   -- visible aux patients (pharmacies)
    is_active       boolean NOT NULL DEFAULT true
);
CREATE INDEX location_org_idx  ON location (organization_id);
CREATE INDEX location_geog_idx ON location USING gist (geog);

CREATE TABLE verification_document (
    document_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL REFERENCES organization ON DELETE CASCADE,
    doc_type        text   NOT NULL CHECK (doc_type IN ('business_license', 'pharmacy_license', 'owner_id', 'other')),
    file_path       text   NOT NULL,
    status          verification_status NOT NULL DEFAULT 'pending',
    reviewed_by     bigint REFERENCES app_user,
    reviewed_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 3. Catalogue normalisé : drug -> product -> batch (comme dans votre ER)
-- ---------------------------------------------------------------------
CREATE TABLE drug (
    drug_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name              text NOT NULL UNIQUE,     -- nom générique (DCI)
    therapeutic_class text,
    atc_code          text
);

CREATE TABLE product (
    product_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    drug_id       bigint NOT NULL REFERENCES drug,
    product_name  text   NOT NULL,
    brand         text,
    strength      text,
    dosage_form   text,
    pack_size     text,
    barcode       text,
    manufacturer  text
);
CREATE UNIQUE INDEX product_barcode_key ON product (barcode) WHERE barcode IS NOT NULL;
CREATE INDEX product_drug_idx        ON product (drug_id);
CREATE INDEX product_name_trgm_idx   ON product USING gin (product_name gin_trgm_ops);
CREATE INDEX product_brand_trgm_idx  ON product USING gin (brand gin_trgm_ops);
CREATE INDEX drug_name_trgm_idx      ON drug    USING gin (name gin_trgm_ops);

CREATE TABLE batch (
    batch_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id   bigint NOT NULL REFERENCES product,
    batch_number text   NOT NULL,
    expiry_date  date   NOT NULL,
    UNIQUE (product_id, batch_number),
    UNIQUE (batch_id, product_id)            -- nécessaire à la clé étrangère composite de stock
);

-- ---------------------------------------------------------------------
-- 4. Stock et prix
--    Un seul tableau pour pharmacies ET fournisseurs, distingués par le type
--    de l'organisation propriétaire du lieu :
--      pharmacie  -> prix de détail, visible des patients
--      fournisseur-> prix catalogue, visible des SEULES pharmacies vérifiées
--    CORRECTIONS par rapport à l'ER : prix, quantité minimale de commande et
--    seuil de stock bas ajoutés ; le lot (batch) devient optionnel car un
--    catalogue fournisseur n'est pas toujours suivi par lot.
-- ---------------------------------------------------------------------
CREATE TABLE stock (
    stock_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id         bigint NOT NULL REFERENCES location ON DELETE CASCADE,
    product_id          bigint NOT NULL REFERENCES product,
    batch_id            bigint,
    quantity            integer NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    low_stock_threshold integer NOT NULL DEFAULT 10 CHECK (low_stock_threshold >= 0),
    unit_price          numeric(12,2) CHECK (unit_price >= 0),
    currency            char(3) NOT NULL DEFAULT 'RWF',
    min_order_qty       integer NOT NULL DEFAULT 1 CHECK (min_order_qty >= 1),
    availability        text GENERATED ALWAYS AS (
                            CASE WHEN quantity <= 0 THEN 'out_of_stock'
                                 WHEN quantity <= low_stock_threshold THEN 'low_stock'
                                 ELSE 'in_stock' END) STORED,
    source              text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'csv_import', 'demo')),
    last_updated        timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (batch_id, product_id) REFERENCES batch (batch_id, product_id)
);
CREATE UNIQUE INDEX stock_unique_idx ON stock (location_id, product_id, COALESCE(batch_id, 0));
CREATE INDEX stock_product_idx ON stock (product_id);

CREATE FUNCTION touch_last_updated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.last_updated := now();
    RETURN NEW;
END $$;
CREATE TRIGGER stock_touch BEFORE UPDATE ON stock
    FOR EACH ROW EXECUTE FUNCTION touch_last_updated();

-- Prix négocié par pharmacie, séparé du prix catalogue : les autres pharmacies
-- ne le voient jamais.
CREATE TABLE negotiated_price (
    negotiated_price_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_org_id     bigint NOT NULL REFERENCES organization,
    pharmacy_org_id     bigint NOT NULL REFERENCES organization,
    product_id          bigint NOT NULL REFERENCES product,
    unit_price          numeric(12,2) NOT NULL CHECK (unit_price >= 0),
    min_qty             integer NOT NULL DEFAULT 1 CHECK (min_qty >= 1),
    valid_until         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (supplier_org_id, pharmacy_org_id, product_id)
);

-- ---------------------------------------------------------------------
-- 5. Chat, offres de prix et demandes de prix multi-fournisseurs
-- ---------------------------------------------------------------------
CREATE TABLE conversation (
    conversation_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind             conversation_kind NOT NULL,
    org_a_id         bigint NOT NULL REFERENCES organization,
    org_b_id         bigint NOT NULL REFERENCES organization,
    initiator_org_id bigint NOT NULL REFERENCES organization,
    product_id       bigint REFERENCES product,      -- sujet éventuel de la discussion
    created_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (org_a_id < org_b_id),                     -- une seule conversation par paire
    CHECK (initiator_org_id IN (org_a_id, org_b_id)),
    UNIQUE (org_a_id, org_b_id)
);

-- Règles : jamais fournisseur <-> fournisseur ; organisations vérifiées.
CREATE FUNCTION conversation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    a organization%ROWTYPE;
    b organization%ROWTYPE;
BEGIN
    SELECT * INTO a FROM organization WHERE organization_id = NEW.org_a_id;
    SELECT * INTO b FROM organization WHERE organization_id = NEW.org_b_id;
    IF a.verification_status <> 'verified' OR b.verification_status <> 'verified' THEN
        RAISE EXCEPTION 'Both organizations must be verified to open a conversation';
    END IF;
    IF a.type = 'supplier' AND b.type = 'supplier' THEN
        RAISE EXCEPTION 'Suppliers cannot talk to each other';
    END IF;
    IF NEW.kind = 'pharmacy_supplier' AND a.type = b.type THEN
        RAISE EXCEPTION 'pharmacy_supplier conversation needs one pharmacy and one supplier';
    END IF;
    IF NEW.kind = 'pharmacy_pharmacy' AND (a.type <> 'pharmacy' OR b.type <> 'pharmacy') THEN
        RAISE EXCEPTION 'pharmacy_pharmacy conversation needs two pharmacies';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER conversation_guard_trg BEFORE INSERT ON conversation
    FOR EACH ROW EXECUTE FUNCTION conversation_guard();

-- Chat entre pharmacies : opt-in et blocage.
CREATE TABLE org_block (
    blocker_org_id bigint NOT NULL REFERENCES organization,
    blocked_org_id bigint NOT NULL REFERENCES organization,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (blocker_org_id, blocked_org_id),
    CHECK (blocker_org_id <> blocked_org_id)
);

CREATE TABLE message (
    message_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id bigint NOT NULL REFERENCES conversation ON DELETE CASCADE,
    sender_user_id  bigint REFERENCES app_user,
    sender_org_id   bigint NOT NULL REFERENCES organization,
    kind            message_kind NOT NULL DEFAULT 'text',
    body            text,
    attachment_path text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    read_at         timestamptz
);
CREATE INDEX message_conv_idx ON message (conversation_id, created_at);

-- Offre de prix structurée : le prix convenu dans le chat est enregistré.
CREATE TABLE quote (
    quote_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id    bigint NOT NULL REFERENCES conversation ON DELETE CASCADE,
    message_id         bigint UNIQUE REFERENCES message,
    proposed_by_org_id bigint NOT NULL REFERENCES organization,
    pharmacy_org_id    bigint NOT NULL REFERENCES organization,
    supplier_org_id    bigint NOT NULL REFERENCES organization,
    product_id         bigint NOT NULL REFERENCES product,
    unit_price         numeric(12,2) NOT NULL CHECK (unit_price > 0),
    quantity           integer NOT NULL CHECK (quantity > 0),
    valid_until        timestamptz,
    status             quote_status NOT NULL DEFAULT 'proposed',
    parent_quote_id    bigint REFERENCES quote,       -- contre-offre
    created_at         timestamptz NOT NULL DEFAULT now(),
    responded_at       timestamptz,
    CHECK (proposed_by_org_id IN (pharmacy_org_id, supplier_org_id))
);
CREATE INDEX quote_conv_idx ON quote (conversation_id);

-- Quand une offre est acceptée, le prix négocié est enregistré pour cette
-- pharmacie uniquement. SECURITY DEFINER : le trigger écrit malgré la RLS.
CREATE FUNCTION quote_accepted() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NEW.status = 'accepted' AND OLD.status IS DISTINCT FROM 'accepted' THEN
        NEW.responded_at := now();
        INSERT INTO negotiated_price (supplier_org_id, pharmacy_org_id, product_id, unit_price, min_qty, valid_until)
        VALUES (NEW.supplier_org_id, NEW.pharmacy_org_id, NEW.product_id, NEW.unit_price, NEW.quantity, NEW.valid_until)
        ON CONFLICT (supplier_org_id, pharmacy_org_id, product_id)
        DO UPDATE SET unit_price = EXCLUDED.unit_price, min_qty = EXCLUDED.min_qty,
                      valid_until = EXCLUDED.valid_until, created_at = now();
    ELSIF NEW.status <> OLD.status THEN
        NEW.responded_at := now();
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER quote_accepted_trg BEFORE UPDATE OF status ON quote
    FOR EACH ROW EXECUTE FUNCTION quote_accepted();

-- Demande de prix envoyée à plusieurs fournisseurs : chacun ne voit que la sienne.
CREATE TABLE rfq (
    rfq_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pharmacy_org_id bigint NOT NULL REFERENCES organization,
    product_id      bigint NOT NULL REFERENCES product,
    quantity        integer NOT NULL CHECK (quantity > 0),
    note            text,
    status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled')),
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE rfq_recipient (
    rfq_id          bigint NOT NULL REFERENCES rfq ON DELETE CASCADE,
    supplier_org_id bigint NOT NULL REFERENCES organization,
    conversation_id bigint REFERENCES conversation,
    status          text NOT NULL DEFAULT 'sent' CHECK (status IN ('sent', 'quoted', 'declined')),
    PRIMARY KEY (rfq_id, supplier_org_id)
);

-- ---------------------------------------------------------------------
-- 6. Commandes et livraison (livraison : table prévue, non fonctionnelle)
-- ---------------------------------------------------------------------
CREATE TABLE purchase_order (
    order_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pharmacy_org_id bigint NOT NULL REFERENCES organization,
    supplier_org_id bigint NOT NULL REFERENCES organization,
    quote_id        bigint REFERENCES quote,
    status          order_status NOT NULL DEFAULT 'requested',
    total_amount    numeric(14,2) NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE purchase_order_item (
    order_item_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id      bigint NOT NULL REFERENCES purchase_order ON DELETE CASCADE,
    product_id    bigint NOT NULL REFERENCES product,
    quantity      integer NOT NULL CHECK (quantity > 0),
    unit_price    numeric(12,2) NOT NULL CHECK (unit_price >= 0)
);
CREATE TABLE delivery (
    delivery_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id      bigint NOT NULL REFERENCES purchase_order,
    status        text NOT NULL DEFAULT 'coming_soon',
    scheduled_for timestamptz,
    notes         text
);

-- ---------------------------------------------------------------------
-- 7. Premium : assurance, abonnements, prévisions
--    Aucun identifiant patient ni numéro de carte n'est stocké.
--    Les taux ci-dessous sont à renseigner depuis les données officielles
--    de chaque assureur : le seed de démo n'utilise que des valeurs fictives.
-- ---------------------------------------------------------------------
CREATE TABLE insurer (
    insurer_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text NOT NULL UNIQUE
);
CREATE TABLE insurance_plan (
    plan_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    insurer_id       bigint NOT NULL REFERENCES insurer,
    name             text NOT NULL,
    coverage_pct     numeric(5,2) NOT NULL CHECK (coverage_pct BETWEEN 0 AND 100),
    max_cover_amount numeric(12,2) CHECK (max_cover_amount >= 0),   -- plafond par achat, optionnel
    is_active        boolean NOT NULL DEFAULT true,
    source_note      text,                                          -- d'où vient le taux
    UNIQUE (insurer_id, name)
);
CREATE TABLE insurance_exclusion (
    plan_id bigint NOT NULL REFERENCES insurance_plan ON DELETE CASCADE,
    drug_id bigint NOT NULL REFERENCES drug,
    PRIMARY KEY (plan_id, drug_id)
);

-- À payer par le patient = total - part de l'assureur (0 si médicament exclu).
CREATE FUNCTION insurance_split(p_drug_id bigint, p_unit_price numeric, p_quantity integer, p_plan_id bigint)
RETURNS TABLE (total numeric, insurer_pays numeric, patient_pays numeric, excluded boolean)
LANGUAGE sql STABLE AS $$
    WITH plan AS (SELECT coverage_pct, max_cover_amount FROM insurance_plan WHERE plan_id = p_plan_id AND is_active),
         ex   AS (SELECT EXISTS (SELECT 1 FROM insurance_exclusion WHERE plan_id = p_plan_id AND drug_id = p_drug_id) AS is_excluded),
         calc AS (
             SELECT p_unit_price * p_quantity AS total,
                    CASE WHEN ex.is_excluded THEN 0
                         ELSE LEAST(p_unit_price * p_quantity * plan.coverage_pct / 100,
                                    COALESCE(plan.max_cover_amount, 'Infinity'::numeric)) END AS cover,
                    ex.is_excluded
             FROM plan, ex)
    SELECT round(total, 2), round(cover, 2), round(total - cover, 2), is_excluded FROM calc
$$;

CREATE TABLE subscription (
    subscription_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL REFERENCES organization,
    plan_code       text NOT NULL CHECK (plan_code IN ('essential', 'premium')),
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'past_due', 'cancelled')),
    amount_rwf      numeric(12,2),
    started_at      timestamptz NOT NULL DEFAULT now(),
    ends_at         timestamptz
);
CREATE TABLE payment (
    payment_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subscription_id bigint NOT NULL REFERENCES subscription,
    method          payment_method NOT NULL,
    amount_rwf      numeric(12,2) NOT NULL,
    status          text NOT NULL DEFAULT 'simulated' CHECK (status IN ('simulated', 'pending', 'paid', 'failed')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE forecast (
    forecast_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id    bigint NOT NULL REFERENCES organization,
    product_id         bigint NOT NULL REFERENCES product,
    month              date   NOT NULL CHECK (month = date_trunc('month', month)::date),
    predicted_quantity integer NOT NULL CHECK (predicted_quantity >= 0),
    is_illustrative    boolean NOT NULL DEFAULT true,   -- vrai tant qu'il n'y a pas d'historique réel
    model_version      text NOT NULL DEFAULT 'demo-seasonal-moving-average',
    UNIQUE (organization_id, product_id, month)
);

-- ---------------------------------------------------------------------
-- 8. Alertes patient, audit
-- ---------------------------------------------------------------------
CREATE TABLE stock_alert (
    alert_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id    bigint NOT NULL REFERENCES product,
    user_id       bigint REFERENCES app_user ON DELETE CASCADE,
    contact_phone text,
    district      text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    notified_at   timestamptz,
    CHECK (user_id IS NOT NULL OR contact_phone IS NOT NULL)
);
CREATE TABLE audit_log (
    audit_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         bigint REFERENCES app_user,
    organization_id bigint REFERENCES organization,
    action          text NOT NULL,        -- ex. 'view_supplier_offers', 'approve_verification'
    entity          text,
    entity_id       bigint,
    metadata        jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_org_idx ON audit_log (organization_id, created_at);

-- ---------------------------------------------------------------------
-- 9. Sécurité par ligne (RLS) : défense en profondeur de la règle de
--    confidentialité. L'API ouvre une transaction et fait, par requête :
--      SELECT set_config('app.org_id',   '<id organisation ou vide>', true);
--      SELECT set_config('app.is_admin', 'true|false', true);
-- ---------------------------------------------------------------------
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'apexrx_api') THEN
        CREATE ROLE apexrx_api NOLOGIN;
    END IF;
END $$;

CREATE FUNCTION app_org_id() RETURNS bigint LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.org_id', true), '')::bigint $$;

CREATE FUNCTION app_is_admin() RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT COALESCE(NULLIF(current_setting('app.is_admin', true), '')::boolean, false) $$;

CREATE FUNCTION app_is_verified_pharmacy() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT EXISTS (SELECT 1 FROM organization
                  WHERE organization_id = app_org_id() AND type = 'pharmacy' AND verification_status = 'verified') $$;

CREATE FUNCTION app_owns_location(p_location_id bigint) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT EXISTS (SELECT 1 FROM location WHERE location_id = p_location_id AND organization_id = app_org_id()) $$;

CREATE FUNCTION app_stock_visible(p_location_id bigint) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT EXISTS (
       SELECT 1 FROM location l JOIN organization o ON o.organization_id = l.organization_id
       WHERE l.location_id = p_location_id AND (
              (o.type = 'pharmacy' AND o.verification_status = 'verified')          -- détail : public
           OR  o.organization_id = app_org_id()                                      -- mon propre stock
           OR (o.type = 'supplier' AND o.verification_status = 'verified'
               AND app_is_verified_pharmacy())                                       -- fournisseurs : pharmacies NPC vérifiées
       )) $$;

CREATE FUNCTION app_rfq_is_mine(p_rfq_id bigint) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT EXISTS (SELECT 1 FROM rfq WHERE rfq_id = p_rfq_id AND pharmacy_org_id = app_org_id()) $$;

CREATE FUNCTION app_rfq_sent_to_me(p_rfq_id bigint) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT EXISTS (SELECT 1 FROM rfq_recipient WHERE rfq_id = p_rfq_id AND supplier_org_id = app_org_id()) $$;

CREATE FUNCTION app_in_conversation(p_conversation_id bigint) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT EXISTS (SELECT 1 FROM conversation
                  WHERE conversation_id = p_conversation_id AND app_org_id() IN (org_a_id, org_b_id)) $$;

ALTER TABLE stock            ENABLE ROW LEVEL SECURITY;
ALTER TABLE negotiated_price ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation     ENABLE ROW LEVEL SECURITY;
ALTER TABLE message          ENABLE ROW LEVEL SECURITY;
ALTER TABLE quote            ENABLE ROW LEVEL SECURITY;
ALTER TABLE rfq              ENABLE ROW LEVEL SECURITY;
ALTER TABLE rfq_recipient    ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_order   ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_order_item ENABLE ROW LEVEL SECURITY;

CREATE POLICY stock_read  ON stock FOR SELECT USING (app_is_admin() OR app_stock_visible(location_id));
CREATE POLICY stock_write ON stock FOR ALL
    USING (app_owns_location(location_id)) WITH CHECK (app_owns_location(location_id));

CREATE POLICY np_read  ON negotiated_price FOR SELECT
    USING (app_is_admin() OR app_org_id() IN (supplier_org_id, pharmacy_org_id));
CREATE POLICY np_write ON negotiated_price FOR ALL
    USING (supplier_org_id = app_org_id()) WITH CHECK (supplier_org_id = app_org_id());

CREATE POLICY conv_all ON conversation FOR ALL
    USING (app_org_id() IN (org_a_id, org_b_id))
    WITH CHECK (app_org_id() IN (org_a_id, org_b_id));
CREATE POLICY msg_read  ON message FOR SELECT USING (app_in_conversation(conversation_id));
CREATE POLICY msg_write ON message FOR INSERT
    WITH CHECK (app_in_conversation(conversation_id) AND sender_org_id = app_org_id());
CREATE POLICY msg_read_mark ON message FOR UPDATE USING (app_in_conversation(conversation_id));

CREATE POLICY quote_all ON quote FOR ALL
    USING (app_org_id() IN (pharmacy_org_id, supplier_org_id))
    WITH CHECK (app_org_id() IN (pharmacy_org_id, supplier_org_id));

CREATE POLICY rfq_read  ON rfq FOR SELECT USING (pharmacy_org_id = app_org_id() OR app_rfq_sent_to_me(rfq_id));
CREATE POLICY rfq_write ON rfq FOR ALL USING (pharmacy_org_id = app_org_id()) WITH CHECK (pharmacy_org_id = app_org_id());
CREATE POLICY rfqr_read ON rfq_recipient FOR SELECT USING (supplier_org_id = app_org_id() OR app_rfq_is_mine(rfq_id));
CREATE POLICY rfqr_write ON rfq_recipient FOR ALL USING (app_rfq_is_mine(rfq_id)) WITH CHECK (app_rfq_is_mine(rfq_id));
CREATE POLICY rfqr_answer ON rfq_recipient FOR UPDATE USING (supplier_org_id = app_org_id());

CREATE POLICY po_all ON purchase_order FOR ALL
    USING (app_org_id() IN (pharmacy_org_id, supplier_org_id))
    WITH CHECK (app_org_id() IN (pharmacy_org_id, supplier_org_id));
CREATE POLICY poi_all ON purchase_order_item FOR ALL
    USING (EXISTS (SELECT 1 FROM purchase_order o WHERE o.order_id = purchase_order_item.order_id))
    WITH CHECK (EXISTS (SELECT 1 FROM purchase_order o WHERE o.order_id = purchase_order_item.order_id));

-- ---------------------------------------------------------------------
-- 10. Vues et fonctions de recherche
-- ---------------------------------------------------------------------
-- Disponibilité publique (patients, médecins) : pharmacies vérifiées uniquement,
-- aucune donnée fournisseur, quantité exacte non exposée.
CREATE VIEW v_pharmacy_availability WITH (security_invoker = true) AS
SELECT s.stock_id, o.organization_id AS pharmacy_id, o.name AS pharmacy_name,
       l.location_id, l.address, l.district, l.sector, l.latitude, l.longitude, l.geog,
       d.drug_id, d.name AS generic_name,
       p.product_id, p.product_name, p.brand, p.strength, p.dosage_form, p.pack_size,
       s.unit_price, s.currency, s.availability, s.last_updated
FROM stock s
JOIN location l     ON l.location_id = s.location_id AND l.is_public AND l.is_active
JOIN organization o ON o.organization_id = l.organization_id
                   AND o.type = 'pharmacy' AND o.verification_status = 'verified'
JOIN product p      ON p.product_id = s.product_id
JOIN drug d         ON d.drug_id = p.drug_id;

-- Comparateur d'offres fournisseurs : la RLS limite aux pharmacies vérifiées
-- (et à chaque fournisseur pour ses propres lignes). Le prix négocié de la
-- pharmacie connectée prime sur le prix catalogue.
CREATE VIEW v_supplier_offers WITH (security_invoker = true) AS
SELECT s.stock_id, o.organization_id AS supplier_id, o.name AS supplier_name,
       l.location_id, l.district, l.sector, l.latitude, l.longitude, l.geog,
       d.drug_id, d.name AS generic_name,
       p.product_id, p.product_name, p.brand, p.strength, p.dosage_form, p.pack_size,
       s.unit_price AS catalogue_price,
       np.unit_price AS negotiated_price,
       COALESCE(np.unit_price, s.unit_price) AS effective_price,
       s.currency, s.min_order_qty, s.availability, s.last_updated
FROM stock s
JOIN location l     ON l.location_id = s.location_id AND l.is_active
JOIN organization o ON o.organization_id = l.organization_id
                   AND o.type = 'supplier' AND o.verification_status = 'verified'
JOIN product p      ON p.product_id = s.product_id
JOIN drug d         ON d.drug_id = p.drug_id
LEFT JOIN negotiated_price np
       ON np.supplier_org_id = o.organization_id AND np.pharmacy_org_id = app_org_id()
      AND np.product_id = s.product_id AND (np.valid_until IS NULL OR np.valid_until > now());

-- Recherche patient : tolérante aux fautes, tri par prix ou par distance.
CREATE FUNCTION search_pharmacy_availability(
    p_query text,
    p_lat   double precision DEFAULT NULL,
    p_lng   double precision DEFAULT NULL,
    p_sort  text DEFAULT 'price',          -- 'price' | 'distance'
    p_limit integer DEFAULT 50)
RETURNS TABLE (pharmacy_id bigint, pharmacy_name text, address text, district text,
               latitude double precision, longitude double precision,
               product_id bigint, product_name text, strength text, dosage_form text,
               unit_price numeric, availability text, last_updated timestamptz,
               distance_m double precision)
LANGUAGE sql STABLE AS $$
    SELECT v.pharmacy_id, v.pharmacy_name, v.address, v.district, v.latitude, v.longitude,
           v.product_id, v.product_name, v.strength, v.dosage_form,
           v.unit_price, v.availability, v.last_updated,
           CASE WHEN p_lat IS NULL OR p_lng IS NULL THEN NULL
                ELSE ST_Distance(v.geog, ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326)::geography) END AS distance_m
    FROM v_pharmacy_availability v
    WHERE v.availability <> 'out_of_stock'
      AND (v.product_name ILIKE '%' || p_query || '%'
           OR v.generic_name ILIKE '%' || p_query || '%'
           OR v.brand ILIKE '%' || p_query || '%'
           OR similarity(v.generic_name, p_query) > 0.3
           OR similarity(v.product_name, p_query) > 0.3)
    ORDER BY CASE WHEN p_sort = 'price' THEN v.unit_price END ASC NULLS LAST,
             CASE WHEN p_sort = 'distance' AND p_lat IS NOT NULL
                  THEN ST_Distance(v.geog, ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326)::geography) END ASC NULLS LAST,
             v.unit_price ASC NULLS LAST
    LIMIT p_limit
$$;

-- ---------------------------------------------------------------------
-- 11. Droits du rôle applicatif
-- ---------------------------------------------------------------------
GRANT USAGE ON SCHEMA public TO apexrx_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO apexrx_api;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO apexrx_api;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO apexrx_api;
-- Pour créer le compte de connexion de l'API (choisir un vrai mot de passe) :
--   CREATE ROLE apexrx_api_login LOGIN PASSWORD '...' IN ROLE apexrx_api;