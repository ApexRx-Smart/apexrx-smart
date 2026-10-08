-- ============================================================
-- ApexRx Smart
-- Initial Database Schema
-- PostgreSQL
-- ============================================================


-- ============================================================
-- 1. USER
-- ============================================================

CREATE TABLE app_user (
    user_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         VARCHAR(150) NOT NULL,
    email        VARCHAR(255) NOT NULL UNIQUE,
    phone        VARCHAR(30)
);


-- ============================================================
-- 2. ORGANIZATION
-- ============================================================

CREATE TABLE organization (
    organization_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name              VARCHAR(255) NOT NULL,
    type              VARCHAR(50) NOT NULL
);


-- ============================================================
-- 3. MEMBERSHIP
-- ============================================================

CREATE TABLE membership (
    membership_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id           BIGINT NOT NULL,
    organization_id   BIGINT NOT NULL,
    role              VARCHAR(50) NOT NULL,

    CONSTRAINT fk_membership_user
        FOREIGN KEY (user_id)
        REFERENCES app_user(user_id),

    CONSTRAINT fk_membership_organization
        FOREIGN KEY (organization_id)
        REFERENCES organization(organization_id),

    CONSTRAINT uq_membership
        UNIQUE (user_id, organization_id)
);


-- ============================================================
-- 4. LOCATION
-- ============================================================

CREATE TABLE location (
    location_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id   BIGINT NOT NULL,
    name              VARCHAR(255) NOT NULL,
    address           TEXT,
    city              VARCHAR(100),
    latitude          NUMERIC(9,6),
    longitude         NUMERIC(9,6),

    CONSTRAINT fk_location_organization
        FOREIGN KEY (organization_id)
        REFERENCES organization(organization_id)
);


-- ============================================================
-- 5. DRUG
-- ============================================================

CREATE TABLE drug (
    drug_id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                VARCHAR(255) NOT NULL,
    therapeutic_class   VARCHAR(255)
);


-- ============================================================
-- 6. PRODUCT
-- ============================================================

CREATE TABLE product (
    product_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    drug_id         BIGINT NOT NULL,
    product_name    VARCHAR(255) NOT NULL,
    brand           VARCHAR(255),
    strength        VARCHAR(100),
    dosage_form     VARCHAR(100),
    pack_size       VARCHAR(100),
    barcode         VARCHAR(100),
    manufacturer    VARCHAR(255),

    CONSTRAINT fk_product_drug
        FOREIGN KEY (drug_id)
        REFERENCES drug(drug_id)
);


-- ============================================================
-- 7. BATCH
-- ============================================================

CREATE TABLE batch (
    batch_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id      BIGINT NOT NULL,
    batch_number    VARCHAR(100) NOT NULL,
    expiry_date     DATE NOT NULL,

    CONSTRAINT fk_batch_product
        FOREIGN KEY (product_id)
        REFERENCES product(product_id),

    CONSTRAINT uq_batch_product
        UNIQUE (product_id, batch_number)
);


-- ============================================================
-- 8. STOCK
-- ============================================================

CREATE TABLE stock (
    stock_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id    BIGINT NOT NULL,
    batch_id       BIGINT NOT NULL,
    quantity       INTEGER NOT NULL DEFAULT 0,
    availability   VARCHAR(50),
    last_updated   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_stock_location
        FOREIGN KEY (location_id)
        REFERENCES location(location_id),

    CONSTRAINT fk_stock_batch
        FOREIGN KEY (batch_id)
        REFERENCES batch(batch_id),

    CONSTRAINT uq_stock_location_batch
        UNIQUE (location_id, batch_id),

    CONSTRAINT chk_stock_quantity
        CHECK (quantity >= 0)
);
