--
-- PostgreSQL database dump
--

\restrict VV2KksmCdSMZYLMvu60OTjNQNJavPI36tN965evDBqH3z0Mc9lZshxHJLtsLhUo

-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: christian
--

-- *not* creating schema, since initdb creates it


ALTER SCHEMA public OWNER TO christian;

--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: christian
--

COMMENT ON SCHEMA public IS '';


--
-- Name: commission_role_type; Type: TYPE; Schema: public; Owner: christian
--

CREATE TYPE public.commission_role_type AS ENUM (
    'PRESIDENT',
    'DELEGUE',
    'MEMBRE',
    'ASSISTANT'
);


ALTER TYPE public.commission_role_type OWNER TO christian;

--
-- Name: paymentstatus; Type: TYPE; Schema: public; Owner: christian
--

CREATE TYPE public.paymentstatus AS ENUM (
    'pending',
    'success',
    'failed',
    'expired',
    'validation'
);


ALTER TYPE public.paymentstatus OWNER TO christian;

--
-- Name: statut_budget; Type: TYPE; Schema: public; Owner: christian
--

CREATE TYPE public.statut_budget AS ENUM (
    'Brouillon',
    'Voté',
    'Clôturé'
);


ALTER TYPE public.statut_budget OWNER TO christian;

--
-- Name: generate_recu_numero(); Type: FUNCTION; Schema: public; Owner: christian
--

CREATE FUNCTION public.generate_recu_numero() RETURNS text
    LANGUAGE plpgsql
    AS $$
        DECLARE
            yr TEXT := to_char(current_date, 'YYYY');
            seq_name TEXT := format('rec_num_seq_%s', yr);
            seq_val BIGINT;
            letter_index INT;
            serie_letter TEXT;
            serie_number INT;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'S' AND c.relname = seq_name AND n.nspname = 'public'
            ) THEN
                EXECUTE format('CREATE SEQUENCE public.%I START 1', seq_name);
            END IF;

            EXECUTE format('SELECT nextval(''public.%I'')', seq_name) INTO seq_val;
            letter_index := ((seq_val - 1) / 9999);
            serie_number := ((seq_val - 1) % 9999) + 1;
            serie_letter := chr(65 + letter_index);

            RETURN format('REC-ONEC-CPK-%s-%s%s', yr, serie_letter, lpad(serie_number::text, 4, '0'));
        END;
        $$;


ALTER FUNCTION public.generate_recu_numero() OWNER TO christian;

--
-- Name: generate_recu_numero(integer); Type: FUNCTION; Schema: public; Owner: christian
--

CREATE FUNCTION public.generate_recu_numero(p_tenant_id integer) RETURNS text
    LANGUAGE plpgsql
    AS $$
        DECLARE
            yr TEXT := to_char(current_date, 'YYYY');
            seq_name TEXT := format('rec_num_seq_%s_%s', p_tenant_id, yr);
            seq_val BIGINT;
            letter_index INT;
            serie_letter TEXT;
            serie_number INT;
            org_slug TEXT;
        BEGIN
            SELECT upper(trim(coalesce(o.slug, 'ORG'))) INTO org_slug
            FROM organisations o
            WHERE o.id = p_tenant_id
            LIMIT 1;

            IF org_slug IS NULL THEN
                org_slug := 'ORG';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'S' AND c.relname = seq_name AND n.nspname = 'public'
            ) THEN
                EXECUTE format('CREATE SEQUENCE public.%I START 1', seq_name);
            END IF;

            EXECUTE format('SELECT nextval(''public.%I'')', seq_name) INTO seq_val;
            letter_index := ((seq_val - 1) / 9999);
            serie_number := ((seq_val - 1) % 9999) + 1;
            serie_letter := chr(65 + letter_index);

            RETURN format(
                'REC-ONEC-%s-%s-%s%s',
                org_slug,
                yr,
                serie_letter,
                lpad(serie_number::text, 4, '0')
            );
        END;
        $$;


ALTER FUNCTION public.generate_recu_numero(p_tenant_id integer) OWNER TO christian;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO christian;

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    user_id uuid,
    action character varying(120) NOT NULL,
    target_table character varying(120),
    target_id character varying(120),
    old_value jsonb,
    new_value jsonb,
    ip_address character varying(64),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    entity_type character varying(50),
    entity_id character varying(100),
    field_name character varying(50),
    organisation_id integer
);


ALTER TABLE public.audit_logs OWNER TO christian;

--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.audit_logs_id_seq OWNER TO christian;

--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: banques; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.banques (
    id integer NOT NULL,
    nom character varying(150) NOT NULL,
    code character varying(50),
    is_active boolean DEFAULT true NOT NULL,
    organisation_id integer NOT NULL
);


ALTER TABLE public.banques OWNER TO christian;

--
-- Name: banques_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.banques_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.banques_id_seq OWNER TO christian;

--
-- Name: banques_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.banques_id_seq OWNED BY public.banques.id;


--
-- Name: budget_audit_logs; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.budget_audit_logs (
    id integer NOT NULL,
    exercice_id integer,
    budget_poste_id integer,
    action character varying(20) NOT NULL,
    field_name character varying(50) NOT NULL,
    old_value numeric(15,2),
    new_value numeric(15,2),
    user_id uuid,
    created_at timestamp with time zone NOT NULL,
    organisation_id integer NOT NULL
);


ALTER TABLE public.budget_audit_logs OWNER TO christian;

--
-- Name: budget_audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.budget_audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.budget_audit_logs_id_seq OWNER TO christian;

--
-- Name: budget_audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.budget_audit_logs_id_seq OWNED BY public.budget_audit_logs.id;


--
-- Name: budget_exercices; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.budget_exercices (
    id integer NOT NULL,
    annee integer NOT NULL,
    statut public.statut_budget DEFAULT 'Brouillon'::public.statut_budget NOT NULL,
    organisation_id integer NOT NULL
);


ALTER TABLE public.budget_exercices OWNER TO christian;

--
-- Name: budget_exercices_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.budget_exercices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.budget_exercices_id_seq OWNER TO christian;

--
-- Name: budget_exercices_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.budget_exercices_id_seq OWNED BY public.budget_exercices.id;


--
-- Name: budget_postes; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.budget_postes (
    id integer NOT NULL,
    exercice_id integer NOT NULL,
    code character varying(20) NOT NULL,
    libelle character varying(255) NOT NULL,
    type character varying(20),
    montant_prevu numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    montant_engage numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    montant_paye numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    parent_code character varying(20),
    active boolean DEFAULT true NOT NULL,
    is_deleted boolean NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by uuid,
    parent_id integer,
    organisation_id integer NOT NULL,
    is_global boolean DEFAULT false NOT NULL
);


ALTER TABLE public.budget_postes OWNER TO christian;

--
-- Name: budget_lignes_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.budget_lignes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.budget_lignes_id_seq OWNER TO christian;

--
-- Name: budget_lignes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.budget_lignes_id_seq OWNED BY public.budget_postes.id;


--
-- Name: caisse_centrale; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.caisse_centrale (
    id integer NOT NULL,
    solde_usd numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    solde_cdf numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    derniere_maj timestamp with time zone DEFAULT now() NOT NULL,
    organisation_id integer NOT NULL
);


ALTER TABLE public.caisse_centrale OWNER TO christian;

--
-- Name: caisse_centrale_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.caisse_centrale_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.caisse_centrale_id_seq OWNER TO christian;

--
-- Name: caisse_centrale_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.caisse_centrale_id_seq OWNED BY public.caisse_centrale.id;


--
-- Name: category_changes_history; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.category_changes_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    expert_id uuid NOT NULL,
    numero_ordre character varying(50) NOT NULL,
    old_category character varying(50),
    new_category character varying(50) NOT NULL,
    changed_by uuid,
    reason text,
    old_data jsonb,
    new_data jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.category_changes_history OWNER TO christian;

--
-- Name: clotures; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.clotures (
    id integer NOT NULL,
    reference_numero character varying(50) NOT NULL,
    date_cloture timestamp with time zone DEFAULT now() NOT NULL,
    caissier_id uuid,
    solde_initial_usd numeric(14,2) NOT NULL,
    solde_initial_cdf numeric(14,2) NOT NULL,
    total_entrees_usd numeric(14,2) NOT NULL,
    total_entrees_cdf numeric(14,2) NOT NULL,
    total_sorties_usd numeric(14,2) NOT NULL,
    total_sorties_cdf numeric(14,2) NOT NULL,
    solde_theorique_usd numeric(14,2) NOT NULL,
    solde_theorique_cdf numeric(14,2) NOT NULL,
    solde_physique_usd numeric(14,2) NOT NULL,
    solde_physique_cdf numeric(14,2) NOT NULL,
    ecart_usd numeric(14,2) NOT NULL,
    ecart_cdf numeric(14,2) NOT NULL,
    billetage_usd jsonb,
    billetage_cdf jsonb,
    observation character varying(500),
    statut character varying(30) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    date_debut timestamp with time zone,
    pdf_path character varying(500),
    taux_change_applique numeric(12,4) NOT NULL,
    organisation_id integer NOT NULL
);


ALTER TABLE public.clotures OWNER TO christian;

--
-- Name: clotures_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.clotures_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.clotures_id_seq OWNER TO christian;

--
-- Name: clotures_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.clotures_id_seq OWNED BY public.clotures.id;


--
-- Name: commission_members; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.commission_members (
    id integer NOT NULL,
    service_id integer NOT NULL,
    user_id uuid,
    full_name character varying(255) NOT NULL,
    role_type public.commission_role_type DEFAULT 'MEMBRE'::public.commission_role_type NOT NULL,
    custom_title character varying(150),
    is_signer boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    email character varying(255),
    matricule character varying(50)
);


ALTER TABLE public.commission_members OWNER TO christian;

--
-- Name: commission_members_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.commission_members_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.commission_members_id_seq OWNER TO christian;

--
-- Name: commission_members_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.commission_members_id_seq OWNED BY public.commission_members.id;


--
-- Name: comptes_bancaires; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.comptes_bancaires (
    id integer NOT NULL,
    banque_id integer,
    intitule character varying(200) NOT NULL,
    numero_compte character varying(120) NOT NULL,
    devise character varying(3) DEFAULT 'USD'::character varying NOT NULL,
    solde_initial numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    solde_actuel numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    organisation_id integer NOT NULL,
    account_type character varying(10) DEFAULT 'BANK'::character varying NOT NULL,
    CONSTRAINT ck_comptes_bancaires_account_type CHECK (((account_type)::text = ANY (ARRAY[('BANK'::character varying)::text, ('CASH'::character varying)::text]))),
    CONSTRAINT ck_comptes_bancaires_bank_ref CHECK (((((account_type)::text = 'BANK'::text) AND (banque_id IS NOT NULL)) OR (((account_type)::text = 'CASH'::text) AND (banque_id IS NULL))))
);


ALTER TABLE public.comptes_bancaires OWNER TO christian;

--
-- Name: comptes_bancaires_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.comptes_bancaires_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.comptes_bancaires_id_seq OWNER TO christian;

--
-- Name: comptes_bancaires_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.comptes_bancaires_id_seq OWNED BY public.comptes_bancaires.id;


--
-- Name: denominations; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.denominations (
    id integer NOT NULL,
    devise character varying(10) NOT NULL,
    valeur numeric(14,2) NOT NULL,
    label character varying(100) NOT NULL,
    est_actif boolean NOT NULL,
    ordre integer NOT NULL
);


ALTER TABLE public.denominations OWNER TO christian;

--
-- Name: denominations_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.denominations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.denominations_id_seq OWNER TO christian;

--
-- Name: denominations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.denominations_id_seq OWNED BY public.denominations.id;


--
-- Name: document_sequences; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.document_sequences (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    doc_type character varying(10) NOT NULL,
    year integer NOT NULL,
    counter integer DEFAULT 1 NOT NULL,
    updated_at timestamp with time zone DEFAULT now(),
    tenant_id integer NOT NULL
);


ALTER TABLE public.document_sequences OWNER TO christian;

--
-- Name: dossiers_requisition; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.dossiers_requisition (
    id uuid NOT NULL,
    reference character varying(60) NOT NULL,
    description text,
    status character varying(30) NOT NULL,
    commentaires_examen text,
    created_by uuid,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.dossiers_requisition OWNER TO christian;

--
-- Name: encaissements; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.encaissements (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    numero_recu character varying(50),
    type_client character varying(50) NOT NULL,
    expert_comptable_id uuid,
    client_nom character varying(300),
    description text,
    montant numeric(15,2) DEFAULT 0 NOT NULL,
    montant_total numeric(15,2) DEFAULT 0 NOT NULL,
    montant_paye numeric(15,2) DEFAULT 0 NOT NULL,
    statut_paiement character varying(20) DEFAULT 'non_paye'::character varying NOT NULL,
    mode_paiement character varying(30) DEFAULT 'cash'::character varying NOT NULL,
    reference character varying(100),
    date_encaissement timestamp with time zone DEFAULT now() NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    budget_poste_id integer,
    montant_percu numeric(15,2) NOT NULL,
    devise_perception character varying(10) NOT NULL,
    taux_change_applique numeric(12,4) NOT NULL,
    is_deleted boolean NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by uuid,
    service_id integer,
    budget_poste_code character varying(20),
    budget_poste_libelle character varying(255),
    libelle character varying(255) NOT NULL,
    canal character varying(10) DEFAULT 'CAISSE'::character varying NOT NULL,
    compte_bancaire_id integer,
    piece_jointe character varying(250),
    organisation_id integer NOT NULL,
    is_reconciled boolean NOT NULL,
    reconciled_at timestamp with time zone,
    reconciled_by_id uuid,
    bank_statement_ref character varying(100),
    est_proforma boolean DEFAULT false NOT NULL,
    numero_proforma character varying(50),
    date_paiement timestamp with time zone,
    source_proforma_id uuid,
    CONSTRAINT ck_encaissements_canal CHECK (((canal)::text = ANY (ARRAY[('CAISSE'::character varying)::text, ('BANQUE'::character varying)::text]))),
    CONSTRAINT ck_encaissements_client_ref CHECK (((((type_client)::text = 'expert_comptable'::text) AND (expert_comptable_id IS NOT NULL)) OR (((type_client)::text <> 'expert_comptable'::text) AND (client_nom IS NOT NULL) AND (length(TRIM(BOTH FROM client_nom)) > 0)))),
    CONSTRAINT ck_encaissements_compte_bancaire CHECK (((((canal)::text = 'BANQUE'::text) AND (compte_bancaire_id IS NOT NULL)) OR ((canal)::text = 'CAISSE'::text))),
    CONSTRAINT ck_encaissements_mode_paiement CHECK (((mode_paiement)::text = ANY (ARRAY[('cash'::character varying)::text, ('mobile_money'::character varying)::text, ('virement'::character varying)::text, ('card'::character varying)::text]))),
    CONSTRAINT ck_encaissements_montant_nonneg CHECK ((montant >= (0)::numeric)),
    CONSTRAINT ck_encaissements_montant_paye_nonneg CHECK ((montant_paye >= (0)::numeric)),
    CONSTRAINT ck_encaissements_montant_total_nonneg CHECK ((montant_total >= (0)::numeric)),
    CONSTRAINT ck_encaissements_statut_paiement CHECK (((statut_paiement)::text = ANY (ARRAY[('non_paye'::character varying)::text, ('partiel'::character varying)::text, ('complet'::character varying)::text, ('avance'::character varying)::text]))),
    CONSTRAINT ck_encaissements_type_client CHECK (((type_client)::text = ANY (ARRAY[('expert_comptable'::character varying)::text, ('client_externe'::character varying)::text, ('banque_institution'::character varying)::text, ('partenaire'::character varying)::text, ('organisation'::character varying)::text, ('autre'::character varying)::text])))
);


ALTER TABLE public.encaissements OWNER TO christian;

--
-- Name: experts_comptables; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.experts_comptables (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    numero_ordre character varying(50) NOT NULL,
    nom_denomination character varying(300) NOT NULL,
    type_ec character varying(10) DEFAULT 'EC'::character varying NOT NULL,
    categorie_personne character varying(50),
    statut_professionnel character varying(50),
    sexe character varying(1),
    telephone character varying(50),
    email character varying(200),
    nif character varying(50),
    cabinet_attache character varying(200),
    nom_employeur character varying(200),
    raison_sociale character varying(300),
    associe_gerant character varying(200),
    import_id uuid,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.experts_comptables OWNER TO christian;

--
-- Name: imports_history; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.imports_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    filename character varying(300) NOT NULL,
    category character varying(50) NOT NULL,
    imported_by uuid,
    rows_imported integer DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'success'::character varying NOT NULL,
    file_data jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.imports_history OWNER TO christian;

--
-- Name: lignes_requisition; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.lignes_requisition (
    id uuid NOT NULL,
    requisition_id uuid NOT NULL,
    rubrique character varying(200) NOT NULL,
    description text NOT NULL,
    quantite integer DEFAULT 1 NOT NULL,
    montant_unitaire numeric(14,2) DEFAULT '0'::numeric NOT NULL,
    montant_total numeric(14,2) DEFAULT '0'::numeric NOT NULL,
    budget_poste_id integer,
    devise character varying(3) DEFAULT 'USD'::character varying NOT NULL
);


ALTER TABLE public.lignes_requisition OWNER TO christian;

--
-- Name: organisation_settings; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.organisation_settings (
    id integer NOT NULL,
    organisation_id integer NOT NULL,
    max_users integer DEFAULT 5 NOT NULL,
    storage_quota_mb integer DEFAULT 1024 NOT NULL,
    is_ai_enabled boolean DEFAULT false NOT NULL,
    is_mobile_money_enabled boolean DEFAULT true NOT NULL,
    fiscal_year_start integer DEFAULT 1 NOT NULL,
    currency_code character varying(10) DEFAULT 'CDF'::character varying NOT NULL,
    is_audit_logs_enabled boolean DEFAULT true NOT NULL,
    theme_primary_color character varying(20) DEFAULT '#4a9079'::character varying NOT NULL,
    theme_sidebar_color character varying(20) DEFAULT '#3d7a66'::character varying NOT NULL,
    theme_accent_color character varying(20) DEFAULT '#eab308'::character varying NOT NULL,
    theme_text_color character varying(20) DEFAULT '#2d3748'::character varying NOT NULL,
    theme_sidebar_text_color character varying(20) DEFAULT '#ffffff'::character varying NOT NULL,
    theme_sidebar_active_color character varying(20) DEFAULT '#1a523f'::character varying NOT NULL,
    theme_button_text_color character varying(20) DEFAULT '#ffffff'::character varying NOT NULL
);


ALTER TABLE public.organisation_settings OWNER TO christian;

--
-- Name: organisation_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.organisation_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.organisation_settings_id_seq OWNER TO christian;

--
-- Name: organisation_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.organisation_settings_id_seq OWNED BY public.organisation_settings.id;


--
-- Name: organisations; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.organisations (
    id integer NOT NULL,
    uuid uuid DEFAULT gen_random_uuid() NOT NULL,
    nom character varying(255) NOT NULL,
    slug character varying(100) NOT NULL,
    logo_url text,
    email_contact character varying(255),
    telephone character varying(50),
    adresse text,
    devise_preferee character varying(3) DEFAULT 'USD'::character varying NOT NULL,
    taux_change_interne numeric(12,4) DEFAULT '0'::numeric NOT NULL,
    plan_type character varying(50) DEFAULT 'FREE'::character varying NOT NULL,
    status_abonnement character varying(20) DEFAULT 'TRIAL'::character varying NOT NULL,
    date_expiration_abonnement timestamp with time zone,
    limite_utilisateurs integer DEFAULT 2 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    icon character varying(20) DEFAULT '🏢'::character varying,
    sort_order integer DEFAULT 0 NOT NULL,
    billing_config jsonb
);


ALTER TABLE public.organisations OWNER TO christian;

--
-- Name: organisations_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.organisations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.organisations_id_seq OWNER TO christian;

--
-- Name: organisations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.organisations_id_seq OWNED BY public.organisations.id;


--
-- Name: participants_transport; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.participants_transport (
    id uuid NOT NULL,
    remboursement_id uuid NOT NULL,
    nom character varying(200) NOT NULL,
    titre_fonction character varying(200) NOT NULL,
    montant numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    type_participant character varying(20) NOT NULL,
    expert_comptable_id uuid,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.participants_transport OWNER TO christian;

--
-- Name: payment_history; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.payment_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    encaissement_id uuid NOT NULL,
    montant numeric(15,2) NOT NULL,
    mode_paiement character varying(30) DEFAULT 'cash'::character varying NOT NULL,
    reference character varying(100),
    notes text,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    organisation_id integer NOT NULL
);


ALTER TABLE public.payment_history OWNER TO christian;

--
-- Name: payment_logs; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.payment_logs (
    id integer NOT NULL,
    organisation_id integer NOT NULL,
    phone_number character varying(32),
    amount numeric(15,2),
    provider character varying(40),
    status character varying(30) NOT NULL,
    raw_response jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.payment_logs OWNER TO christian;

--
-- Name: payment_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.payment_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payment_logs_id_seq OWNER TO christian;

--
-- Name: payment_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.payment_logs_id_seq OWNED BY public.payment_logs.id;


--
-- Name: payment_transactions; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.payment_transactions (
    id uuid NOT NULL,
    provider character varying(60) NOT NULL,
    provider_ref character varying(120) NOT NULL,
    reference character varying(120),
    amount numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    fees numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    currency character varying(3) DEFAULT 'USD'::character varying NOT NULL,
    status character varying(20) DEFAULT 'PENDING'::character varying NOT NULL,
    method character varying(20) NOT NULL,
    phone character varying(30),
    raw_payload jsonb,
    error_message text,
    encaissement_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    organisation_id integer NOT NULL,
    CONSTRAINT ck_payment_tx_currency CHECK (((currency)::text = ANY (ARRAY[('USD'::character varying)::text, ('CDF'::character varying)::text]))),
    CONSTRAINT ck_payment_tx_method CHECK (((method)::text = ANY (ARRAY[('MOMO_AIRTEL'::character varying)::text, ('MOMO_MPESA'::character varying)::text, ('MOMO_ORANGE'::character varying)::text, ('VISA'::character varying)::text]))),
    CONSTRAINT ck_payment_tx_status CHECK (((status)::text = ANY (ARRAY[('PENDING'::character varying)::text, ('SUCCESS'::character varying)::text, ('FAILED'::character varying)::text])))
);


ALTER TABLE public.payment_transactions OWNER TO christian;

--
-- Name: permissions; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.permissions (
    id integer NOT NULL,
    code character varying(80) NOT NULL,
    description character varying(255),
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.permissions OWNER TO christian;

--
-- Name: permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.permissions_id_seq OWNER TO christian;

--
-- Name: permissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.permissions_id_seq OWNED BY public.permissions.id;


--
-- Name: plans; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.plans (
    id integer NOT NULL,
    name character varying(50) NOT NULL,
    monthly_price_usd numeric(10,2) DEFAULT '0'::numeric NOT NULL,
    features jsonb,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    max_users integer DEFAULT 10 NOT NULL,
    ai_features_enabled boolean DEFAULT false NOT NULL
);


ALTER TABLE public.plans OWNER TO christian;

--
-- Name: plans_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.plans_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.plans_id_seq OWNER TO christian;

--
-- Name: plans_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.plans_id_seq OWNED BY public.plans.id;


--
-- Name: platform_settings; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.platform_settings (
    id integer NOT NULL,
    billing_config jsonb,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.platform_settings OWNER TO christian;

--
-- Name: platform_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.platform_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.platform_settings_id_seq OWNER TO christian;

--
-- Name: platform_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.platform_settings_id_seq OWNED BY public.platform_settings.id;


--
-- Name: print_settings; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.print_settings (
    id uuid NOT NULL,
    organization_name character varying(200) DEFAULT ''::character varying NOT NULL,
    organization_subtitle character varying(200) DEFAULT ''::character varying NOT NULL,
    header_text character varying(300) DEFAULT ''::character varying NOT NULL,
    address character varying(300) DEFAULT ''::character varying NOT NULL,
    phone character varying(100) DEFAULT ''::character varying NOT NULL,
    email character varying(200) DEFAULT ''::character varying NOT NULL,
    website character varying(200) DEFAULT ''::character varying NOT NULL,
    bank_name character varying(200) DEFAULT ''::character varying NOT NULL,
    bank_account character varying(200) DEFAULT ''::character varying NOT NULL,
    mobile_money_name character varying(200) DEFAULT ''::character varying NOT NULL,
    mobile_money_number character varying(100) DEFAULT ''::character varying NOT NULL,
    show_header_logo boolean DEFAULT true NOT NULL,
    show_footer_signature boolean DEFAULT true NOT NULL,
    updated_by uuid,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    logo_url character varying(500) DEFAULT ''::character varying NOT NULL,
    stamp_url character varying(500) DEFAULT ''::character varying NOT NULL,
    paper_format character varying(3) DEFAULT 'A5'::character varying NOT NULL,
    compact_header boolean DEFAULT false NOT NULL,
    default_currency character varying(3) DEFAULT 'USD'::character varying NOT NULL,
    secondary_currency character varying(3) DEFAULT 'CDF'::character varying NOT NULL,
    exchange_rate numeric(12,4) DEFAULT '0'::numeric NOT NULL,
    fiscal_year integer DEFAULT 2026 NOT NULL,
    budget_alert_threshold integer DEFAULT 80 NOT NULL,
    budget_block_overrun boolean DEFAULT true NOT NULL,
    budget_force_roles character varying(300) DEFAULT ''::character varying NOT NULL,
    pied_de_page_legal text DEFAULT ''::text NOT NULL,
    afficher_qr_code boolean DEFAULT true NOT NULL,
    recu_label_signature character varying(200) DEFAULT ''::character varying NOT NULL,
    recu_nom_signataire character varying(200) DEFAULT ''::character varying NOT NULL,
    req_titre_officiel character varying(200) DEFAULT ''::character varying NOT NULL,
    req_label_gauche character varying(200) DEFAULT ''::character varying NOT NULL,
    req_nom_gauche character varying(200) DEFAULT ''::character varying NOT NULL,
    req_label_droite character varying(200) DEFAULT ''::character varying NOT NULL,
    req_nom_droite character varying(200) DEFAULT ''::character varying NOT NULL,
    trans_titre_officiel character varying(200) DEFAULT ''::character varying NOT NULL,
    trans_label_gauche character varying(200) DEFAULT ''::character varying NOT NULL,
    trans_nom_gauche character varying(200) DEFAULT ''::character varying NOT NULL,
    trans_label_droite character varying(200) DEFAULT ''::character varying NOT NULL,
    trans_nom_droite character varying(200) DEFAULT ''::character varying NOT NULL,
    sortie_label_signature character varying(200) DEFAULT ''::character varying NOT NULL,
    sortie_nom_signataire character varying(200) DEFAULT ''::character varying NOT NULL,
    show_sortie_qr boolean DEFAULT true NOT NULL,
    sortie_qr_base_url character varying(300) DEFAULT ''::character varying NOT NULL,
    show_sortie_watermark boolean DEFAULT true NOT NULL,
    sortie_watermark_text character varying(50) DEFAULT 'PAYÉ'::character varying NOT NULL,
    sortie_watermark_opacity numeric(4,2) DEFAULT 0.15 NOT NULL,
    sortie_sig_label_1 character varying(200) DEFAULT 'CAISSIER'::character varying NOT NULL,
    sortie_sig_label_2 character varying(200) DEFAULT 'COMPTABLE'::character varying NOT NULL,
    sortie_sig_label_3 character varying(200) DEFAULT 'AUTORITÉ (TRÉSORERIE)'::character varying NOT NULL,
    sortie_sig_hint character varying(200) DEFAULT 'Signature & date'::character varying NOT NULL,
    encaissement_libelle_presets text NOT NULL,
    exchange_rate_cdf numeric(12,4) NOT NULL,
    exchange_rate_eur numeric(12,4) NOT NULL,
    exchange_rate_xof numeric(12,4) NOT NULL,
    organisation_id integer NOT NULL
);


ALTER TABLE public.print_settings OWNER TO christian;

--
-- Name: rec_num_seq_1_2026; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.rec_num_seq_1_2026
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.rec_num_seq_1_2026 OWNER TO christian;

--
-- Name: refresh_tokens; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.refresh_tokens (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    jti character varying(128) NOT NULL,
    token_hash character varying(64) NOT NULL,
    revoked boolean DEFAULT false NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.refresh_tokens OWNER TO christian;

--
-- Name: remboursements_transport; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.remboursements_transport (
    id uuid NOT NULL,
    numero_remboursement character varying(50) NOT NULL,
    instance character varying(100) NOT NULL,
    type_reunion character varying(30) NOT NULL,
    nature_reunion character varying(200) NOT NULL,
    nature_travail jsonb,
    lieu character varying(200) NOT NULL,
    date_reunion timestamp with time zone NOT NULL,
    heure_debut character varying(20),
    heure_fin character varying(20),
    montant_total numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    requisition_id uuid,
    created_by uuid,
    created_at timestamp with time zone NOT NULL,
    trans_titre_officiel_hist character varying(200),
    trans_label_gauche_hist character varying(200),
    trans_nom_gauche_hist character varying(200),
    trans_label_droite_hist character varying(200),
    trans_nom_droite_hist character varying(200),
    signataire_g_label character varying(200),
    signataire_g_nom character varying(200),
    signataire_d_label character varying(200),
    signataire_d_nom character varying(200),
    reference_numero character varying(50),
    pdf_path character varying(500)
);


ALTER TABLE public.remboursements_transport OWNER TO christian;

--
-- Name: requisition_annexes; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.requisition_annexes (
    id uuid NOT NULL,
    requisition_id uuid NOT NULL,
    file_path character varying(500) NOT NULL,
    filename character varying(255) NOT NULL,
    file_type character varying(100) NOT NULL,
    file_size integer DEFAULT 0 NOT NULL,
    upload_date timestamp with time zone NOT NULL
);


ALTER TABLE public.requisition_annexes OWNER TO christian;

--
-- Name: requisition_approvers; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.requisition_approvers (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    active boolean DEFAULT true NOT NULL,
    notes text,
    added_by uuid,
    added_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.requisition_approvers OWNER TO christian;

--
-- Name: requisition_status_history; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.requisition_status_history (
    id integer NOT NULL,
    requisition_id uuid NOT NULL,
    old_status character varying(30),
    new_status character varying(30) NOT NULL,
    comment character varying(500),
    changed_by uuid,
    changed_at timestamp with time zone NOT NULL
);


ALTER TABLE public.requisition_status_history OWNER TO christian;

--
-- Name: requisition_status_history_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.requisition_status_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.requisition_status_history_id_seq OWNER TO christian;

--
-- Name: requisition_status_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.requisition_status_history_id_seq OWNED BY public.requisition_status_history.id;


--
-- Name: requisitions; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.requisitions (
    id uuid NOT NULL,
    numero_requisition character varying(50) NOT NULL,
    objet text NOT NULL,
    mode_paiement character varying(50) NOT NULL,
    type_requisition character varying(50) NOT NULL,
    status character varying(30) NOT NULL,
    montant_total numeric(14,2) DEFAULT '0'::numeric NOT NULL,
    created_by uuid,
    validee_par uuid,
    validee_le timestamp with time zone,
    approuvee_par uuid,
    approuvee_le timestamp with time zone,
    payee_par uuid,
    payee_le timestamp with time zone,
    motif_rejet text,
    a_valoir boolean DEFAULT false NOT NULL,
    instance_beneficiaire character varying(200),
    notes_a_valoir text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    req_titre_officiel_hist character varying(200),
    req_label_gauche_hist character varying(200),
    req_nom_gauche_hist character varying(200),
    req_label_droite_hist character varying(200),
    req_nom_droite_hist character varying(200),
    signataire_g_label character varying(200),
    signataire_g_nom character varying(200),
    signataire_d_label character varying(200),
    signataire_d_nom character varying(200),
    reference_numero character varying(50),
    pdf_path character varying(500),
    is_deleted boolean NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by uuid,
    import_source character varying(50),
    service_id integer,
    signed_by_id uuid,
    signed_at timestamp with time zone,
    dossier_id uuid,
    examen_status character varying(30) DEFAULT 'NON_EXAMINE'::character varying NOT NULL,
    examen_commentaire text,
    examen_par uuid,
    examen_le timestamp with time zone,
    organisation_id integer NOT NULL
);


ALTER TABLE public.requisitions OWNER TO christian;

--
-- Name: role_permissions; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.role_permissions (
    role_id integer NOT NULL,
    permission_id integer NOT NULL
);


ALTER TABLE public.role_permissions OWNER TO christian;

--
-- Name: roles; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.roles (
    id integer NOT NULL,
    code character varying(50) NOT NULL,
    label character varying(100),
    description character varying(255),
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.roles OWNER TO christian;

--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.roles_id_seq OWNER TO christian;

--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;


--
-- Name: rubriques; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.rubriques (
    id uuid NOT NULL,
    code character varying(50) NOT NULL,
    libelle character varying(200) NOT NULL,
    description text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.rubriques OWNER TO christian;

--
-- Name: service_rubriques; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.service_rubriques (
    id integer NOT NULL,
    service_id integer NOT NULL,
    budget_poste_id integer NOT NULL
);


ALTER TABLE public.service_rubriques OWNER TO christian;

--
-- Name: service_rubriques_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.service_rubriques_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.service_rubriques_id_seq OWNER TO christian;

--
-- Name: service_rubriques_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.service_rubriques_id_seq OWNED BY public.service_rubriques.id;


--
-- Name: services; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.services (
    id integer NOT NULL,
    code character varying(20) NOT NULL,
    libelle character varying(150) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    responsable_id uuid,
    organisation_id integer NOT NULL
);


ALTER TABLE public.services OWNER TO christian;

--
-- Name: services_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.services_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.services_id_seq OWNER TO christian;

--
-- Name: services_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.services_id_seq OWNED BY public.services.id;


--
-- Name: sorties_fonds; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.sorties_fonds (
    id uuid NOT NULL,
    type_sortie character varying(50) NOT NULL,
    requisition_id uuid,
    rubrique_code character varying(50),
    montant_paye numeric(14,2) DEFAULT '0'::numeric NOT NULL,
    date_paiement timestamp with time zone,
    mode_paiement character varying(50) NOT NULL,
    reference character varying(100),
    motif text NOT NULL,
    beneficiaire character varying(200) NOT NULL,
    piece_justificative character varying(200),
    commentaire text,
    created_by uuid,
    created_at timestamp with time zone NOT NULL,
    budget_poste_id integer,
    reference_numero character varying(50),
    statut character varying(20) DEFAULT 'VALIDE'::character varying NOT NULL,
    motif_annulation text,
    pdf_path character varying(500),
    exchange_rate_snapshot numeric(12,4),
    annexes jsonb,
    service_id integer,
    budget_poste_code character varying(20),
    budget_poste_libelle character varying(255),
    annulee_le timestamp with time zone,
    canal character varying(10) DEFAULT 'CAISSE'::character varying NOT NULL,
    compte_bancaire_id integer,
    devise character varying(3) DEFAULT 'USD'::character varying NOT NULL,
    organisation_id integer NOT NULL,
    is_reconciled boolean NOT NULL,
    reconciled_at timestamp with time zone,
    reconciled_by_id uuid,
    bank_statement_ref character varying(100),
    CONSTRAINT ck_sorties_fonds_canal CHECK (((canal)::text = ANY (ARRAY[('CAISSE'::character varying)::text, ('BANQUE'::character varying)::text]))),
    CONSTRAINT ck_sorties_fonds_compte_bancaire CHECK (((((canal)::text = 'BANQUE'::text) AND (compte_bancaire_id IS NOT NULL)) OR ((canal)::text = 'CAISSE'::text))),
    CONSTRAINT ck_sorties_fonds_devise CHECK (((devise)::text = ANY (ARRAY[('USD'::character varying)::text, ('CDF'::character varying)::text])))
);


ALTER TABLE public.sorties_fonds OWNER TO christian;

--
-- Name: standard_classifications; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.standard_classifications (
    id integer NOT NULL,
    organisation_id integer NOT NULL,
    raw_label character varying(255) NOT NULL,
    assigned_account character varying(10),
    confidence_score double precision DEFAULT '1'::double precision NOT NULL,
    occurrence_count integer DEFAULT 1 NOT NULL,
    last_used timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.standard_classifications OWNER TO christian;

--
-- Name: standard_classifications_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.standard_classifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.standard_classifications_id_seq OWNER TO christian;

--
-- Name: standard_classifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.standard_classifications_id_seq OWNED BY public.standard_classifications.id;


--
-- Name: subscriptions; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.subscriptions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_id integer NOT NULL,
    plan_id integer NOT NULL,
    status character varying(20) DEFAULT 'PENDING_PAYMENT'::character varying NOT NULL,
    trial_end timestamp with time zone,
    current_period_end timestamp with time zone,
    fedapay_transaction_id character varying(100),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.subscriptions OWNER TO christian;

--
-- Name: system_events; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.system_events (
    id uuid NOT NULL,
    organisation_id integer,
    level character varying(20) DEFAULT 'info'::character varying NOT NULL,
    code character varying(60) DEFAULT ''::character varying NOT NULL,
    message text DEFAULT ''::text NOT NULL,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.system_events OWNER TO christian;

--
-- Name: system_settings; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.system_settings (
    id uuid NOT NULL,
    email_expediteur character varying(200) DEFAULT ''::character varying NOT NULL,
    email_president character varying(200) DEFAULT ''::character varying NOT NULL,
    emails_bureau_cc text DEFAULT ''::text NOT NULL,
    smtp_host character varying(200) DEFAULT 'smtp.gmail.com'::character varying NOT NULL,
    smtp_port integer DEFAULT 465 NOT NULL,
    updated_by uuid,
    updated_at timestamp with time zone NOT NULL,
    smtp_password character varying(200) DEFAULT ''::character varying NOT NULL,
    email_tresorier character varying(200) DEFAULT ''::character varying NOT NULL,
    emails_bureau_sortie_cc text DEFAULT ''::text NOT NULL,
    email_validation_1 character varying(200) DEFAULT ''::character varying NOT NULL,
    email_validation_final character varying(200) DEFAULT ''::character varying NOT NULL,
    max_caisse_amount integer DEFAULT 0 NOT NULL,
    last_weekly_report_sent_at timestamp with time zone,
    last_weekly_report_status character varying(20) DEFAULT 'never'::character varying NOT NULL,
    last_weekly_report_error text DEFAULT ''::text NOT NULL,
    last_weekly_report_success_at timestamp with time zone,
    last_weekly_report_failure_at timestamp with time zone,
    organisation_id integer NOT NULL,
    whatsapp_api_url character varying(255) DEFAULT ''::character varying NOT NULL,
    whatsapp_api_key character varying(255) DEFAULT ''::character varying NOT NULL,
    whatsapp_agents text DEFAULT ''::text NOT NULL
);


ALTER TABLE public.system_settings OWNER TO christian;

--
-- Name: tenant_signups; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.tenant_signups (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_name character varying(200) NOT NULL,
    slug character varying(100) NOT NULL,
    admin_email character varying(255) NOT NULL,
    admin_phone character varying(50),
    plan_id integer NOT NULL,
    status character varying(20) DEFAULT 'pending_payment'::character varying NOT NULL,
    reference character varying(120) NOT NULL,
    fedapay_transaction_id character varying(100),
    error_message text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    organisation_id integer,
    billing_months integer NOT NULL
);


ALTER TABLE public.tenant_signups OWNER TO christian;

--
-- Name: transactions; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.transactions (
    id character varying(36) NOT NULL,
    tenant_id character varying(120) NOT NULL,
    amount double precision NOT NULL,
    currency character varying(8) DEFAULT 'USD'::character varying NOT NULL,
    status public.paymentstatus NOT NULL,
    provider character varying(60),
    external_reference character varying(120),
    metadata_json jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone
);


ALTER TABLE public.transactions OWNER TO christian;

--
-- Name: transferts_internes; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.transferts_internes (
    id integer NOT NULL,
    source_type character varying(10) NOT NULL,
    source_id integer,
    destination_type character varying(10) NOT NULL,
    destination_id integer,
    montant numeric(15,2) NOT NULL,
    devise character varying(3) NOT NULL,
    reference character varying(120),
    date_transfert timestamp with time zone DEFAULT now() NOT NULL,
    execute_par uuid,
    CONSTRAINT ck_transferts_internes_destination_ref CHECK (((((destination_type)::text = 'CAISSE'::text) AND (destination_id IS NULL)) OR (((destination_type)::text = 'BANQUE'::text) AND (destination_id IS NOT NULL)))),
    CONSTRAINT ck_transferts_internes_destination_type CHECK (((destination_type)::text = ANY (ARRAY[('CAISSE'::character varying)::text, ('BANQUE'::character varying)::text]))),
    CONSTRAINT ck_transferts_internes_devise CHECK (((devise)::text = ANY (ARRAY[('USD'::character varying)::text, ('CDF'::character varying)::text]))),
    CONSTRAINT ck_transferts_internes_source_ref CHECK (((((source_type)::text = 'CAISSE'::text) AND (source_id IS NULL)) OR (((source_type)::text = 'BANQUE'::text) AND (source_id IS NOT NULL)))),
    CONSTRAINT ck_transferts_internes_source_type CHECK (((source_type)::text = ANY (ARRAY[('CAISSE'::character varying)::text, ('BANQUE'::character varying)::text])))
);


ALTER TABLE public.transferts_internes OWNER TO christian;

--
-- Name: transferts_internes_id_seq; Type: SEQUENCE; Schema: public; Owner: christian
--

CREATE SEQUENCE public.transferts_internes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.transferts_internes_id_seq OWNER TO christian;

--
-- Name: transferts_internes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: christian
--

ALTER SEQUENCE public.transferts_internes_id_seq OWNED BY public.transferts_internes.id;


--
-- Name: user_roles; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.user_roles (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    role character varying(80) NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.user_roles OWNER TO christian;

--
-- Name: user_services; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.user_services (
    user_id uuid NOT NULL,
    service_id integer NOT NULL
);


ALTER TABLE public.user_services OWNER TO christian;

--
-- Name: users; Type: TABLE; Schema: public; Owner: christian
--

CREATE TABLE public.users (
    id uuid NOT NULL,
    email character varying(320) NOT NULL,
    nom character varying(120),
    prenom character varying(120),
    hashed_password character varying(255),
    role character varying(50) DEFAULT 'reception'::character varying NOT NULL,
    active boolean DEFAULT true NOT NULL,
    must_change_password boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_first_login boolean NOT NULL,
    is_email_verified boolean NOT NULL,
    otp_code character varying(20),
    otp_created_at timestamp with time zone,
    otp_attempts integer NOT NULL,
    role_id integer,
    service_id integer,
    organisation_id integer NOT NULL
);


ALTER TABLE public.users OWNER TO christian;

--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: banques id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.banques ALTER COLUMN id SET DEFAULT nextval('public.banques_id_seq'::regclass);


--
-- Name: budget_audit_logs id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_audit_logs ALTER COLUMN id SET DEFAULT nextval('public.budget_audit_logs_id_seq'::regclass);


--
-- Name: budget_exercices id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_exercices ALTER COLUMN id SET DEFAULT nextval('public.budget_exercices_id_seq'::regclass);


--
-- Name: budget_postes id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_postes ALTER COLUMN id SET DEFAULT nextval('public.budget_lignes_id_seq'::regclass);


--
-- Name: caisse_centrale id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.caisse_centrale ALTER COLUMN id SET DEFAULT nextval('public.caisse_centrale_id_seq'::regclass);


--
-- Name: clotures id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.clotures ALTER COLUMN id SET DEFAULT nextval('public.clotures_id_seq'::regclass);


--
-- Name: commission_members id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.commission_members ALTER COLUMN id SET DEFAULT nextval('public.commission_members_id_seq'::regclass);


--
-- Name: comptes_bancaires id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.comptes_bancaires ALTER COLUMN id SET DEFAULT nextval('public.comptes_bancaires_id_seq'::regclass);


--
-- Name: denominations id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.denominations ALTER COLUMN id SET DEFAULT nextval('public.denominations_id_seq'::regclass);


--
-- Name: organisation_settings id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.organisation_settings ALTER COLUMN id SET DEFAULT nextval('public.organisation_settings_id_seq'::regclass);


--
-- Name: organisations id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.organisations ALTER COLUMN id SET DEFAULT nextval('public.organisations_id_seq'::regclass);


--
-- Name: payment_logs id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.payment_logs ALTER COLUMN id SET DEFAULT nextval('public.payment_logs_id_seq'::regclass);


--
-- Name: permissions id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.permissions ALTER COLUMN id SET DEFAULT nextval('public.permissions_id_seq'::regclass);


--
-- Name: plans id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.plans ALTER COLUMN id SET DEFAULT nextval('public.plans_id_seq'::regclass);


--
-- Name: platform_settings id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.platform_settings ALTER COLUMN id SET DEFAULT nextval('public.platform_settings_id_seq'::regclass);


--
-- Name: requisition_status_history id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisition_status_history ALTER COLUMN id SET DEFAULT nextval('public.requisition_status_history_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);


--
-- Name: service_rubriques id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.service_rubriques ALTER COLUMN id SET DEFAULT nextval('public.service_rubriques_id_seq'::regclass);


--
-- Name: services id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.services ALTER COLUMN id SET DEFAULT nextval('public.services_id_seq'::regclass);


--
-- Name: standard_classifications id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.standard_classifications ALTER COLUMN id SET DEFAULT nextval('public.standard_classifications_id_seq'::regclass);


--
-- Name: transferts_internes id; Type: DEFAULT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.transferts_internes ALTER COLUMN id SET DEFAULT nextval('public.transferts_internes_id_seq'::regclass);


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.alembic_version (version_num) FROM stdin;
20260408_proforma_encaissements
\.


--
-- Data for Name: audit_logs; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.audit_logs (id, user_id, action, target_table, target_id, old_value, new_value, ip_address, created_at, entity_type, entity_id, field_name, organisation_id) FROM stdin;
1	a2375bac-4a9f-4ed8-b674-a1807543c744	CASH_STRESS_ALERT	\N	\N	null	{"pending_total": 0.0, "reserve_threshold": 1000.0, "stress_projection": 0.0}	172.18.0.1	2026-03-20 12:42:38.855694+00	requisitions	7f97d337-7e1e-45c7-807f-d173e7431c58	\N	1
2	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:27:52.877555+00	budget_ligne	1	is_deleted	1
3	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:27:52.978216+00	budget_ligne	2	is_deleted	1
4	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:27:53.035463+00	budget_ligne	3	is_deleted	1
5	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:27:53.090331+00	budget_ligne	4	is_deleted	1
6	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:27:53.149279+00	budget_ligne	5	is_deleted	1
7	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:27:53.184251+00	budget_ligne	6	is_deleted	1
8	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:27:53.20612+00	budget_ligne	7	is_deleted	1
9	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:57:07.955182+00	budget_ligne	8	is_deleted	1
10	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:57:07.994447+00	budget_ligne	9	is_deleted	1
11	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:57:08.024136+00	budget_ligne	10	is_deleted	1
12	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:57:08.055277+00	budget_ligne	11	is_deleted	1
13	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:57:08.081814+00	budget_ligne	12	is_deleted	1
14	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:57:08.108586+00	budget_ligne	13	is_deleted	1
15	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 09:57:08.134025+00	budget_ligne	14	is_deleted	1
16	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"5000.00"	"200.00"	\N	2026-03-23 10:09:42.479674+00	budget_ligne	15	montant_prevu	1
17	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:13:32.146637+00	budget_ligne	22	is_deleted	1
18	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"200.00"	"0"	\N	2026-03-23 10:13:32.175472+00	budget_ligne	15	montant_prevu	1
19	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:13:32.278466+00	budget_ligne	16	is_deleted	1
20	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:13:32.326555+00	budget_ligne	17	is_deleted	1
21	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:13:32.375578+00	budget_ligne	18	is_deleted	1
22	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:13:32.417714+00	budget_ligne	19	is_deleted	1
23	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:13:32.453026+00	budget_ligne	20	is_deleted	1
24	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:13:32.47801+00	budget_ligne	21	is_deleted	1
25	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:13:40.555526+00	budget_ligne	15	is_deleted	1
26	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:22:59.830314+00	budget_ligne	23	is_deleted	1
27	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:22:59.925345+00	budget_ligne	24	is_deleted	1
28	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:22:59.998171+00	budget_ligne	25	is_deleted	1
29	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:23:00.061622+00	budget_ligne	26	is_deleted	1
30	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:23:00.116897+00	budget_ligne	27	is_deleted	1
31	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:23:00.138235+00	budget_ligne	28	is_deleted	1
32	a2375bac-4a9f-4ed8-b674-a1807543c744	soft_delete	\N	\N	false	true	\N	2026-03-23 10:23:00.158927+00	budget_ligne	29	is_deleted	1
33	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"15000.00"	\N	2026-03-23 10:23:11.048306+00	budget_ligne	30	montant_prevu	1
34	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"15000.00"	"20800.00"	\N	2026-03-23 10:23:11.059539+00	budget_ligne	30	montant_prevu	1
35	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"20800.00"	"22000.00"	\N	2026-03-23 10:23:11.065345+00	budget_ligne	30	montant_prevu	1
36	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"29880.00"	\N	2026-03-23 10:23:11.073666+00	budget_ligne	35	montant_prevu	1
37	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"29880.00"	\N	2026-03-23 10:23:11.078195+00	budget_ligne	34	montant_prevu	1
38	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"29880.00"	"43560.00"	\N	2026-03-23 10:23:11.082509+00	budget_ligne	35	montant_prevu	1
39	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"29880.00"	"43560.00"	\N	2026-03-23 10:23:11.084828+00	budget_ligne	34	montant_prevu	1
40	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"43560.00"	"52875.00"	\N	2026-03-23 10:23:11.092171+00	budget_ligne	35	montant_prevu	1
41	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"43560.00"	"52875.00"	\N	2026-03-23 10:23:11.096176+00	budget_ligne	34	montant_prevu	1
42	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"52875.00"	"55575.00"	\N	2026-03-23 10:23:11.100124+00	budget_ligne	35	montant_prevu	1
43	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"52875.00"	"55575.00"	\N	2026-03-23 10:23:11.103254+00	budget_ligne	34	montant_prevu	1
44	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"55575.00"	"100575.00"	\N	2026-03-23 10:23:11.107397+00	budget_ligne	35	montant_prevu	1
45	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"55575.00"	"100575.00"	\N	2026-03-23 10:23:11.110382+00	budget_ligne	34	montant_prevu	1
46	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"100575.00"	"228531.00"	\N	2026-03-23 10:23:11.114954+00	budget_ligne	35	montant_prevu	1
47	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"100575.00"	"228531.00"	\N	2026-03-23 10:23:11.118196+00	budget_ligne	34	montant_prevu	1
48	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"228531.00"	"234381.00"	\N	2026-03-23 10:23:11.122227+00	budget_ligne	35	montant_prevu	1
49	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"228531.00"	"234381.00"	\N	2026-03-23 10:23:11.124747+00	budget_ligne	34	montant_prevu	1
50	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"234381.00"	"234741.00"	\N	2026-03-23 10:23:11.130038+00	budget_ligne	35	montant_prevu	1
51	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"234381.00"	"234741.00"	\N	2026-03-23 10:23:11.132587+00	budget_ligne	34	montant_prevu	1
52	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"234741.00"	"244741.00"	\N	2026-03-23 10:23:11.136455+00	budget_ligne	35	montant_prevu	1
53	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"234741.00"	"244741.00"	\N	2026-03-23 10:23:11.138792+00	budget_ligne	34	montant_prevu	1
54	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"5000.00"	\N	2026-03-23 10:23:11.152071+00	budget_ligne	45	montant_prevu	1
55	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"244741.00"	"249741.00"	\N	2026-03-23 10:23:11.154905+00	budget_ligne	34	montant_prevu	1
56	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"5000.00"	"23000.00"	\N	2026-03-23 10:23:11.159694+00	budget_ligne	45	montant_prevu	1
57	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"249741.00"	"267741.00"	\N	2026-03-23 10:23:11.162488+00	budget_ligne	34	montant_prevu	1
58	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"23000.00"	"24650.00"	\N	2026-03-23 10:23:11.166305+00	budget_ligne	45	montant_prevu	1
59	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"267741.00"	"269391.00"	\N	2026-03-23 10:23:11.17182+00	budget_ligne	34	montant_prevu	1
60	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"24650.00"	"26150.00"	\N	2026-03-23 10:23:11.176096+00	budget_ligne	45	montant_prevu	1
61	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"269391.00"	"270891.00"	\N	2026-03-23 10:23:11.178676+00	budget_ligne	34	montant_prevu	1
62	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"26150.00"	"27150.00"	\N	2026-03-23 10:23:11.183124+00	budget_ligne	45	montant_prevu	1
63	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"270891.00"	"271891.00"	\N	2026-03-23 10:23:11.186019+00	budget_ligne	34	montant_prevu	1
64	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"27150.00"	"28650.00"	\N	2026-03-23 10:23:11.190501+00	budget_ligne	45	montant_prevu	1
65	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"271891.00"	"273391.00"	\N	2026-03-23 10:23:11.192908+00	budget_ligne	34	montant_prevu	1
66	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"28650.00"	"30000.00"	\N	2026-03-23 10:23:11.197206+00	budget_ligne	45	montant_prevu	1
67	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"273391.00"	"274741.00"	\N	2026-03-23 10:23:11.199741+00	budget_ligne	34	montant_prevu	1
68	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"52763.25"	\N	2026-03-23 10:23:11.21657+00	budget_ligne	53	montant_prevu	1
69	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"274741.00"	"327504.25"	\N	2026-03-23 10:23:11.218801+00	budget_ligne	34	montant_prevu	1
70	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"52763.25"	"57263.25"	\N	2026-03-23 10:23:11.224769+00	budget_ligne	53	montant_prevu	1
71	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"327504.25"	"332004.25"	\N	2026-03-23 10:23:11.227476+00	budget_ligne	34	montant_prevu	1
72	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"37790.00"	\N	2026-03-23 10:23:11.236475+00	budget_ligne	58	montant_prevu	1
73	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"332004.25"	"369794.25"	\N	2026-03-23 10:23:11.239631+00	budget_ligne	34	montant_prevu	1
74	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"37790.00"	"45790.00"	\N	2026-03-23 10:23:11.244171+00	budget_ligne	58	montant_prevu	1
75	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"369794.25"	"377794.25"	\N	2026-03-23 10:23:11.246765+00	budget_ligne	34	montant_prevu	1
76	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"7200.00"	\N	2026-03-23 10:23:11.258309+00	budget_ligne	61	montant_prevu	1
77	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"377794.25"	"384994.25"	\N	2026-03-23 10:23:11.261221+00	budget_ligne	34	montant_prevu	1
78	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"7200.00"	"25200.00"	\N	2026-03-23 10:23:11.266258+00	budget_ligne	61	montant_prevu	1
79	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"384994.25"	"402994.25"	\N	2026-03-23 10:23:11.269177+00	budget_ligne	34	montant_prevu	1
80	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"25200.00"	"49200.00"	\N	2026-03-23 10:23:11.273332+00	budget_ligne	61	montant_prevu	1
81	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"402994.25"	"426994.25"	\N	2026-03-23 10:23:11.276569+00	budget_ligne	34	montant_prevu	1
82	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"49200.00"	"65200.00"	\N	2026-03-23 10:23:11.281703+00	budget_ligne	61	montant_prevu	1
83	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"426994.25"	"442994.25"	\N	2026-03-23 10:23:11.284953+00	budget_ligne	34	montant_prevu	1
84	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"65200.00"	"71720.00"	\N	2026-03-23 10:23:11.289785+00	budget_ligne	61	montant_prevu	1
85	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"442994.25"	"449514.25"	\N	2026-03-23 10:23:11.292647+00	budget_ligne	34	montant_prevu	1
86	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"43790.40"	\N	2026-03-23 10:23:11.300052+00	budget_ligne	67	montant_prevu	1
87	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"449514.25"	"493304.65"	\N	2026-03-23 10:23:11.302759+00	budget_ligne	34	montant_prevu	1
88	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"43790.40"	"51652.80"	\N	2026-03-23 10:23:11.306736+00	budget_ligne	67	montant_prevu	1
89	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"493304.65"	"501167.05"	\N	2026-03-23 10:23:11.308984+00	budget_ligne	34	montant_prevu	1
90	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"1800.00"	\N	2026-03-23 10:23:11.320688+00	budget_ligne	71	montant_prevu	1
91	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"501167.05"	"502967.05"	\N	2026-03-23 10:23:11.323037+00	budget_ligne	34	montant_prevu	1
92	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"1800.00"	"13200.00"	\N	2026-03-23 10:23:11.32698+00	budget_ligne	71	montant_prevu	1
93	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"502967.05"	"514367.05"	\N	2026-03-23 10:23:11.329824+00	budget_ligne	34	montant_prevu	1
94	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"13200.00"	"15000.00"	\N	2026-03-23 10:23:11.334713+00	budget_ligne	71	montant_prevu	1
95	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"514367.05"	"516167.05"	\N	2026-03-23 10:23:11.337754+00	budget_ligne	34	montant_prevu	1
96	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"4500.00"	\N	2026-03-23 10:23:11.346552+00	budget_ligne	75	montant_prevu	1
97	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"516167.05"	"520667.05"	\N	2026-03-23 10:23:11.349283+00	budget_ligne	34	montant_prevu	1
98	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"63634.39"	\N	2026-03-23 10:23:11.357985+00	budget_ligne	77	montant_prevu	1
99	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"520667.05"	"584301.44"	\N	2026-03-23 10:23:11.361326+00	budget_ligne	34	montant_prevu	1
100	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"63634.39"	"72238.00"	\N	2026-03-23 10:23:11.366195+00	budget_ligne	77	montant_prevu	1
101	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"584301.44"	"592905.05"	\N	2026-03-23 10:23:11.36949+00	budget_ligne	34	montant_prevu	1
102	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"72238.00"	"79461.80"	\N	2026-03-23 10:23:11.374164+00	budget_ligne	77	montant_prevu	1
103	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"592905.05"	"600128.85"	\N	2026-03-23 10:23:11.376831+00	budget_ligne	34	montant_prevu	1
104	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"1000.00"	\N	2026-03-23 10:23:11.385005+00	budget_ligne	81	montant_prevu	1
105	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"600128.85"	"601128.85"	\N	2026-03-23 10:23:11.38783+00	budget_ligne	34	montant_prevu	1
106	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"1000.00"	"5000.00"	\N	2026-03-23 10:23:11.392127+00	budget_ligne	81	montant_prevu	1
107	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"601128.85"	"605128.85"	\N	2026-03-23 10:23:11.395735+00	budget_ligne	34	montant_prevu	1
108	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"5000.00"	"9000.00"	\N	2026-03-23 10:23:11.401024+00	budget_ligne	81	montant_prevu	1
109	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"605128.85"	"609128.85"	\N	2026-03-23 10:23:11.404129+00	budget_ligne	34	montant_prevu	1
110	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"1000.00"	"1500.00"	\N	2026-03-23 10:23:11.409398+00	budget_ligne	82	montant_prevu	1
111	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"9000.00"	"9500.00"	\N	2026-03-23 10:23:11.412788+00	budget_ligne	81	montant_prevu	1
112	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"609128.85"	"609628.85"	\N	2026-03-23 10:23:11.416206+00	budget_ligne	34	montant_prevu	1
113	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"1500.00"	"4000.00"	\N	2026-03-23 10:23:11.420767+00	budget_ligne	82	montant_prevu	1
114	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"9500.00"	"12000.00"	\N	2026-03-23 10:23:11.424167+00	budget_ligne	81	montant_prevu	1
115	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"609628.85"	"612128.85"	\N	2026-03-23 10:23:11.426733+00	budget_ligne	34	montant_prevu	1
116	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"4000.00"	"5000.00"	\N	2026-03-23 10:23:11.431106+00	budget_ligne	82	montant_prevu	1
117	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"12000.00"	"13000.00"	\N	2026-03-23 10:23:11.436063+00	budget_ligne	81	montant_prevu	1
118	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"612128.85"	"613128.85"	\N	2026-03-23 10:23:11.439772+00	budget_ligne	34	montant_prevu	1
119	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"5000.00"	"6000.00"	\N	2026-03-23 10:23:11.446566+00	budget_ligne	82	montant_prevu	1
120	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"13000.00"	"14000.00"	\N	2026-03-23 10:23:11.450231+00	budget_ligne	81	montant_prevu	1
121	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"613128.85"	"614128.85"	\N	2026-03-23 10:23:11.454003+00	budget_ligne	34	montant_prevu	1
122	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"6000.00"	"7700.00"	\N	2026-03-23 10:23:11.460165+00	budget_ligne	82	montant_prevu	1
123	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"14000.00"	"15700.00"	\N	2026-03-23 10:23:11.463847+00	budget_ligne	81	montant_prevu	1
124	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"614128.85"	"615828.85"	\N	2026-03-23 10:23:11.467514+00	budget_ligne	34	montant_prevu	1
125	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"7700.00"	"12898.00"	\N	2026-03-23 10:23:11.47373+00	budget_ligne	82	montant_prevu	1
126	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"15700.00"	"20898.00"	\N	2026-03-23 10:23:11.47786+00	budget_ligne	81	montant_prevu	1
127	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"615828.85"	"621026.85"	\N	2026-03-23 10:23:11.4814+00	budget_ligne	34	montant_prevu	1
128	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"5000.00"	\N	2026-03-23 10:23:11.492252+00	budget_ligne	91	montant_prevu	1
129	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"621026.85"	"626026.85"	\N	2026-03-23 10:23:11.497173+00	budget_ligne	34	montant_prevu	1
130	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"14000.00"	\N	2026-03-23 10:23:11.535661+00	budget_ligne	94	montant_prevu	1
131	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"626026.85"	"640026.85"	\N	2026-03-23 10:23:11.543135+00	budget_ligne	34	montant_prevu	1
132	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"14000.00"	"64602.00"	\N	2026-03-23 10:23:11.554644+00	budget_ligne	94	montant_prevu	1
133	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"640026.85"	"690628.85"	\N	2026-03-23 10:23:11.561031+00	budget_ligne	34	montant_prevu	1
134	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"64602.00"	"103074.49"	\N	2026-03-23 10:23:11.579268+00	budget_ligne	94	montant_prevu	1
135	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"690628.85"	"729101.34"	\N	2026-03-23 10:23:11.585191+00	budget_ligne	34	montant_prevu	1
136	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"729101.34"	"751664.34"	\N	2026-03-23 10:23:11.593506+00	budget_ligne	34	montant_prevu	1
137	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"89640.00"	\N	2026-03-23 10:35:18.008838+00	budget_ligne	106	montant_prevu	1
138	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"89640.00"	"130680.00"	\N	2026-03-23 10:35:18.023787+00	budget_ligne	106	montant_prevu	1
139	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"130680.00"	"158625.00"	\N	2026-03-23 10:35:18.028147+00	budget_ligne	106	montant_prevu	1
140	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"158625.00"	"166725.00"	\N	2026-03-23 10:35:18.034045+00	budget_ligne	106	montant_prevu	1
141	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"166725.00"	"301725.00"	\N	2026-03-23 10:35:18.038332+00	budget_ligne	106	montant_prevu	1
142	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"301725.00"	"429681.00"	\N	2026-03-23 10:35:18.042211+00	budget_ligne	106	montant_prevu	1
143	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"429681.00"	"447231.00"	\N	2026-03-23 10:35:18.046292+00	budget_ligne	106	montant_prevu	1
144	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"447231.00"	"448311.00"	\N	2026-03-23 10:35:18.050156+00	budget_ligne	106	montant_prevu	1
145	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"30000.00"	\N	2026-03-23 10:35:18.058373+00	budget_ligne	115	montant_prevu	1
146	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"81750.00"	\N	2026-03-23 10:35:18.081209+00	budget_ligne	124	montant_prevu	1
147	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"81750.00"	"123750.00"	\N	2026-03-23 10:35:18.08581+00	budget_ligne	124	montant_prevu	1
148	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"0.00"	"1000.00"	\N	2026-03-23 10:35:18.091659+00	budget_ligne	127	montant_prevu	1
149	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"1000.00"	"13000.00"	\N	2026-03-23 10:35:18.100214+00	budget_ligne	127	montant_prevu	1
150	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"13000.00"	"23200.00"	\N	2026-03-23 10:35:18.104975+00	budget_ligne	127	montant_prevu	1
151	a2375bac-4a9f-4ed8-b674-a1807543c744	update	\N	\N	"23200.00"	"23700.00"	\N	2026-03-23 10:35:18.11151+00	budget_ligne	127	montant_prevu	1
152	a2375bac-4a9f-4ed8-b674-a1807543c744	USER_UPDATED	\N	\N	{"nom": "KIDIKALA", "role": "admin", "email": "kidikala@gmail.com", "prenom": "Christian", "service_id": null, "service_ids": []}	{"nom": "KIDIKALA", "role": "admin", "email": "kidikala@gmail.com", "prenom": "Christian", "service_id": null, "service_ids": [1, 2, 3, 4]}	172.18.0.1	2026-03-23 11:27:20.233836+00	users	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1
153	a2375bac-4a9f-4ed8-b674-a1807543c744	USER_PASSWORD_SET	\N	\N	{"must_change_password": false}	{"must_change_password": false}	172.18.0.1	2026-03-23 11:27:20.514606+00	users	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1
154	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_create_requisition", "can_edit_settings", "can_execute_payment", "can_manage_users", "can_validate_final", "can_verify_technical", "can_view_reports"]}	{"permissions": ["can_create_requisition", "can_edit_settings", "can_execute_payment", "can_manage_users", "can_validate_final", "can_verify_technical", "can_view_reports", "menu_mon_espace", "menu_requisitions", "menu_services", "menu_validation_examens"]}	172.18.0.1	2026-03-23 11:29:08.49797+00	roles	1	\N	1
155	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_execute_payment"]}	{"permissions": ["can_execute_payment"]}	172.18.0.1	2026-03-23 11:29:08.518721+00	roles	4	\N	1
156	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_create_requisition"]}	{"permissions": ["can_create_requisition"]}	172.18.0.1	2026-03-23 11:29:08.525125+00	roles	5	\N	1
157	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_validate_final", "can_view_reports"]}	{"permissions": ["can_validate_final", "can_view_reports"]}	172.18.0.1	2026-03-23 11:29:08.531028+00	roles	6	\N	1
158	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_verify_technical", "can_view_reports"]}	{"permissions": ["can_verify_technical", "can_view_reports"]}	172.18.0.1	2026-03-23 11:29:08.534864+00	roles	2	\N	1
159	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_execute_payment", "can_view_reports"]}	{"permissions": ["can_execute_payment", "can_view_reports"]}	172.18.0.1	2026-03-23 11:29:08.538067+00	roles	3	\N	1
160	a2375bac-4a9f-4ed8-b674-a1807543c744	USER_UPDATED	\N	\N	{"nom": "KIDIKALA", "role": "admin", "email": "kidikala@gmail.com", "prenom": "Christian", "service_id": null, "service_ids": [2, 3, 1, 4]}	{"nom": "KIDIKALA", "role": "admin", "email": "kidikala@gmail.com", "prenom": "Christian", "service_id": null, "service_ids": [1, 2, 3, 4]}	172.18.0.1	2026-03-23 11:29:34.242428+00	users	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1
163	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_CREATED	\N	\N	null	{"code": "secretaire_permanant", "label": "Secrétaire permanant", "description": null}	172.18.0.1	2026-03-23 12:08:06.990194+00	roles	7	\N	1
161	a2375bac-4a9f-4ed8-b674-a1807543c744	USER_PASSWORD_SET	\N	\N	{"must_change_password": false}	{"must_change_password": false}	172.18.0.1	2026-03-23 11:29:34.455293+00	users	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1
162	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_DELETED	\N	\N	{"code": "demandeur", "label": "Demandeur", "description": "Initie des réquisitions"}	null	172.18.0.1	2026-03-23 11:55:27.58725+00	roles	5	\N	1
164	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_create_requisition", "can_edit_settings", "can_execute_payment", "can_manage_users", "can_validate_final", "can_verify_technical", "can_view_reports", "menu_mon_espace", "menu_requisitions", "menu_services", "menu_validation_examens"]}	{"permissions": ["can_create_requisition", "can_edit_settings", "can_execute_payment", "can_manage_users", "can_validate_final", "can_verify_technical", "can_view_reports", "menu_mon_espace", "menu_requisitions", "menu_services", "menu_validation_examens"]}	172.18.0.1	2026-03-23 12:09:05.132734+00	roles	1	\N	1
165	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_execute_payment"]}	{"permissions": ["can_execute_payment"]}	172.18.0.1	2026-03-23 12:09:05.145322+00	roles	4	\N	1
166	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_validate_final", "can_view_reports"]}	{"permissions": ["can_validate_final", "can_view_reports"]}	172.18.0.1	2026-03-23 12:09:05.160193+00	roles	6	\N	1
167	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_verify_technical", "can_view_reports"]}	{"permissions": ["can_verify_technical", "can_view_reports"]}	172.18.0.1	2026-03-23 12:09:05.164115+00	roles	2	\N	1
168	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": []}	{"permissions": ["can_create_requisition", "can_view_reports", "menu_mon_espace", "menu_requisitions", "menu_services"]}	172.18.0.1	2026-03-23 12:09:05.169665+00	roles	7	\N	1
169	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_execute_payment", "can_view_reports"]}	{"permissions": ["can_execute_payment", "can_view_reports"]}	172.18.0.1	2026-03-23 12:09:05.173473+00	roles	3	\N	1
170	a2375bac-4a9f-4ed8-b674-a1807543c744	USER_CREATED	\N	\N	null	{"nom": "LUKA", "role": "secretaire_permanant", "email": "alainluka@onecrdc.com", "active": true, "prenom": "Alain", "service_id": 1, "service_ids": [1]}	172.18.0.1	2026-03-23 12:18:22.873492+00	users	None	\N	1
171	a2375bac-4a9f-4ed8-b674-a1807543c744	USER_CREATED	\N	\N	null	{"nom": "KIDIKALA", "role": "admin", "email": "kidikala@onecrdc.com", "active": true, "prenom": "Christian", "service_id": null, "service_ids": [1, 2, 3, 4, 17]}	172.18.0.1	2026-03-26 11:54:04.69419+00	users	None	\N	1
172	a2375bac-4a9f-4ed8-b674-a1807543c744	USER_PASSWORD_RESET	\N	\N	{"must_change_password": true}	{"must_change_password": true}	172.18.0.1	2026-03-26 11:55:41.520502+00	users	49a1c5f5-2d47-4ad6-8549-13c781a16223	\N	1
173	a2375bac-4a9f-4ed8-b674-a1807543c744	USER_PASSWORD_RESET	\N	\N	{"must_change_password": true}	{"must_change_password": true}	172.18.0.1	2026-03-26 11:56:02.787867+00	users	49a1c5f5-2d47-4ad6-8549-13c781a16223	\N	1
174	a2375bac-4a9f-4ed8-b674-a1807543c744	CASH_STRESS_ALERT	\N	\N	null	{"pending_total": 0.0, "reserve_threshold": 1000.0, "stress_projection": 0.0}	172.18.0.1	2026-03-26 13:30:15.951773+00	requisitions	238a97a0-7b38-4eef-a504-e2de13865da5	\N	1
175	a2375bac-4a9f-4ed8-b674-a1807543c744	status_change	\N	\N	"BROUILLON"	"EN_ATTENTE_COMMISSION"	\N	2026-03-26 13:50:21.081461+00	requisition	238a97a0-7b38-4eef-a504-e2de13865da5	status	1
176	a2375bac-4a9f-4ed8-b674-a1807543c744	status_change	\N	\N	"BROUILLON"	"EN_ATTENTE"	\N	2026-03-26 13:53:10.612948+00	requisition	7f97d337-7e1e-45c7-807f-d173e7431c58	status	1
177	a2375bac-4a9f-4ed8-b674-a1807543c744	REQUISITION_TECH_VALIDATED	\N	\N	{"status": "EN_ATTENTE"}	{"status": "AUTORISEE"}	172.18.0.1	2026-03-26 13:56:38.950515+00	requisitions	7f97d337-7e1e-45c7-807f-d173e7431c58	\N	1
178	a2375bac-4a9f-4ed8-b674-a1807543c744	status_change	\N	\N	"EN_ATTENTE"	"AUTORISEE"	\N	2026-03-26 13:56:38.995281+00	requisition	7f97d337-7e1e-45c7-807f-d173e7431c58	status	1
179	a2375bac-4a9f-4ed8-b674-a1807543c744	CASH_STRESS_ALERT	\N	\N	null	{"pending_total": 60.0, "reserve_threshold": 1000.0, "stress_projection": -60.0}	172.18.0.1	2026-03-26 13:56:39.045902+00	requisitions	7f97d337-7e1e-45c7-807f-d173e7431c58	\N	1
180	49a1c5f5-2d47-4ad6-8549-13c781a16223	status_change	\N	\N	"AUTORISEE"	"APPROUVEE"	\N	2026-03-26 13:57:02.871594+00	requisition	7f97d337-7e1e-45c7-807f-d173e7431c58	status	1
181	49a1c5f5-2d47-4ad6-8549-13c781a16223	REQUISITION_FINAL_APPROVED	\N	\N	{"status": "AUTORISEE"}	{"status": "APPROUVEE"}	172.18.0.1	2026-03-26 13:57:02.877088+00	requisitions	7f97d337-7e1e-45c7-807f-d173e7431c58	\N	1
182	49a1c5f5-2d47-4ad6-8549-13c781a16223	CASH_STRESS_ALERT	\N	\N	null	{"pending_total": 60.0, "reserve_threshold": 1000.0, "stress_projection": -60.0}	172.18.0.1	2026-03-26 13:57:02.896556+00	requisitions	7f97d337-7e1e-45c7-807f-d173e7431c58	\N	1
183	a2375bac-4a9f-4ed8-b674-a1807543c744	USER_CREATED	\N	\N	null	{"nom": "MORO", "role": "admin", "email": "constantmoro@onecrdc.com", "active": true, "prenom": "Constant", "service_id": null, "service_ids": [1, 2, 3, 4, 17]}	172.18.0.1	2026-03-31 09:26:41.747317+00	users	None	\N	1
184	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_CREATED	\N	\N	null	{"code": "secretaire_executif", "label": "Secrétaire Exécutif", "description": null}	172.18.0.1	2026-03-31 09:28:33.319769+00	roles	8	\N	1
185	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_create_requisition", "can_edit_settings", "can_execute_payment", "can_manage_users", "can_validate_final", "can_verify_technical", "can_view_reports", "menu_mon_espace", "menu_requisitions", "menu_services", "menu_validation_examens"]}	{"permissions": ["can_create_requisition", "can_edit_settings", "can_execute_payment", "can_manage_users", "can_validate_final", "can_verify_technical", "can_view_reports", "menu_mon_espace", "menu_requisitions", "menu_services", "menu_validation_examens"]}	172.18.0.1	2026-03-31 09:29:59.16289+00	roles	1	\N	1
186	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_execute_payment"]}	{"permissions": ["can_execute_payment"]}	172.18.0.1	2026-03-31 09:29:59.180248+00	roles	4	\N	1
187	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_validate_final", "can_view_reports"]}	{"permissions": ["can_validate_final", "can_view_reports"]}	172.18.0.1	2026-03-31 09:29:59.189157+00	roles	6	\N	1
188	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_verify_technical", "can_view_reports"]}	{"permissions": ["can_verify_technical", "can_view_reports"]}	172.18.0.1	2026-03-31 09:29:59.202399+00	roles	2	\N	1
189	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": []}	{"permissions": ["can_create_requisition", "can_execute_payment", "can_verify_technical", "can_view_reports", "menu_mon_espace", "menu_services", "menu_validation_examens"]}	172.18.0.1	2026-03-31 09:29:59.221212+00	roles	8	\N	1
190	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_create_requisition", "can_view_reports", "menu_mon_espace", "menu_requisitions", "menu_services"]}	{"permissions": ["can_create_requisition", "can_view_reports", "menu_mon_espace", "menu_requisitions", "menu_services"]}	172.18.0.1	2026-03-31 09:29:59.237662+00	roles	7	\N	1
191	a2375bac-4a9f-4ed8-b674-a1807543c744	ROLE_PERMISSIONS_UPDATED	\N	\N	{"permissions": ["can_execute_payment", "can_view_reports"]}	{"permissions": ["can_execute_payment", "can_view_reports"]}	172.18.0.1	2026-03-31 09:29:59.247425+00	roles	3	\N	1
192	a2375bac-4a9f-4ed8-b674-a1807543c744	USER_CREATED	\N	\N	null	{"nom": "VANGU", "role": "president", "email": "josephvangu71@gmail.com", "active": true, "prenom": "Joseph", "service_id": 2, "service_ids": [2]}	172.18.0.1	2026-03-31 09:49:57.381048+00	users	None	\N	1
193	a2375bac-4a9f-4ed8-b674-a1807543c744	RECONCILE	\N	\N	null	{"is_reconciled": true, "bank_statement_ref": null}	\N	2026-03-31 15:27:47.746879+00	encaissements	c9224e80-c7b2-41f1-9528-218d511d0220	\N	1
194	a2375bac-4a9f-4ed8-b674-a1807543c744	RECONCILE	\N	\N	null	{"is_reconciled": true, "bank_statement_ref": null}	\N	2026-04-03 10:07:04.532064+00	encaissements	963b3dfe-1eb3-4114-afe6-4d6248ef0a60	\N	1
195	a2375bac-4a9f-4ed8-b674-a1807543c744	RECONCILE	\N	\N	null	{"is_reconciled": true, "bank_statement_ref": null}	\N	2026-04-03 10:07:04.59619+00	encaissements	9701ffbf-5be4-4497-8715-d98cc67ffdd8	\N	1
196	a2375bac-4a9f-4ed8-b674-a1807543c744	RECONCILE	\N	\N	null	{"is_reconciled": true, "bank_statement_ref": null}	\N	2026-04-03 10:07:04.600374+00	encaissements	4e1aa171-531e-4021-ac32-8d5d233effff	\N	1
197	a2375bac-4a9f-4ed8-b674-a1807543c744	RECONCILE	\N	\N	null	{"is_reconciled": true, "bank_statement_ref": null}	\N	2026-04-03 10:07:04.6085+00	encaissements	7579cce1-8021-44ca-8628-22a8dcbd1662	\N	1
198	a2375bac-4a9f-4ed8-b674-a1807543c744	RECONCILE	\N	\N	null	{"is_reconciled": true, "bank_statement_ref": null}	\N	2026-04-03 10:07:04.612859+00	encaissements	56d5c07f-d0ab-4a8e-88b1-a84a7723c3ca	\N	1
199	a2375bac-4a9f-4ed8-b674-a1807543c744	status_change	\N	\N	"non_paye"	"complet"	\N	2026-04-08 14:37:19.170185+00	encaissement	03e7c4db-9129-42ef-8a2c-ceb0e161b769	statut_paiement	1
200	a2375bac-4a9f-4ed8-b674-a1807543c744	SORTIE_CREATED	\N	\N	null	{"statut": "VALIDE", "beneficiaire": "ki", "montant_paye": 50.0, "requisition_id": "7f97d337-7e1e-45c7-807f-d173e7431c58", "reference_numero": "PAY-ONEC-CPK-2026-0001"}	172.18.0.1	2026-04-12 10:11:23.231926+00	sorties_fonds	None	\N	1
201	a2375bac-4a9f-4ed8-b674-a1807543c744	CAISSE_CLOTURE_JOURNALIERE	\N	\N	null	{"ecart_cdf": "0.00", "ecart_usd": "0.00", "solde_physique_cdf": "0.00", "solde_physique_usd": "16439.98", "solde_theorique_cdf": "0.00", "solde_theorique_usd": "16439.98"}	172.18.0.1	2026-04-12 10:24:47.779344+00	clotures	CLO-ONEC-CPK-2026-0001	\N	1
\.


--
-- Data for Name: banques; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.banques (id, nom, code, is_active, organisation_id) FROM stdin;
1	Rawbank	\N	t	1
\.


--
-- Data for Name: budget_audit_logs; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.budget_audit_logs (id, exercice_id, budget_poste_id, action, field_name, old_value, new_value, user_id, created_at, organisation_id) FROM stdin;
1	1	1	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:27:52.916207+00	1
2	1	2	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:27:52.985301+00	1
3	1	3	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:27:53.043447+00	1
4	1	4	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:27:53.097292+00	1
5	1	5	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:27:53.158435+00	1
6	1	6	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:27:53.185224+00	1
7	1	7	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:27:53.206813+00	1
8	1	8	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:57:07.961339+00	1
9	1	9	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:57:07.996344+00	1
10	1	10	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:57:08.027015+00	1
11	1	11	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:57:08.058313+00	1
12	1	12	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:57:08.084161+00	1
13	1	13	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:57:08.109489+00	1
14	1	14	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 09:57:08.13472+00	1
15	1	22	create	montant_prevu	\N	200.00	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:09:42.500036+00	1
16	1	22	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:13:32.177602+00	1
17	1	16	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:13:32.283969+00	1
18	1	17	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:13:32.331886+00	1
19	1	18	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:13:32.37981+00	1
20	1	19	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:13:32.424801+00	1
21	1	20	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:13:32.454182+00	1
22	1	21	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:13:32.479298+00	1
23	1	15	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:13:40.556263+00	1
24	1	23	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:22:59.836918+00	1
25	1	24	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:22:59.928968+00	1
26	1	25	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:23:00.000577+00	1
27	1	26	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:23:00.063621+00	1
28	1	27	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:23:00.118681+00	1
29	1	28	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:23:00.139275+00	1
30	1	29	delete	ligne	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-23 10:23:00.159396+00	1
\.


--
-- Data for Name: budget_exercices; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.budget_exercices (id, annee, statut, organisation_id) FROM stdin;
1	2026	Brouillon	1
5	2026	Brouillon	8
6	2026	Brouillon	9
7	2026	Brouillon	10
\.


--
-- Data for Name: budget_postes; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.budget_postes (id, exercice_id, code, libelle, type, montant_prevu, montant_engage, montant_paye, parent_code, active, is_deleted, deleted_at, deleted_by, parent_id, organisation_id, is_global) FROM stdin;
1	1	II.2.2.1	Location salle	DEPENSE	5000.00	0.00	0.00	\N	t	t	2026-03-23 09:27:52.825707+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
2	1	II.2.2.2	Déjeuner + Pause-café	DEPENSE	18000.00	0.00	0.00	\N	t	t	2026-03-23 09:27:52.971977+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
3	1	II.2.2.3	Presse	DEPENSE	1650.00	0.00	0.00	\N	t	t	2026-03-23 09:27:53.030486+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
4	1	II.2.2.4	Fournitures et autres	DEPENSE	1500.00	0.00	0.00	\N	t	t	2026-03-23 09:27:53.082903+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
5	1	II.2.2.5	Protocole	DEPENSE	1000.00	0.00	0.00	\N	t	t	2026-03-23 09:27:53.143604+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
6	1	II.2.2.6	Enseignes (Bâches, Badges, Roll up)	DEPENSE	1500.00	0.00	0.00	\N	t	t	2026-03-23 09:27:53.183372+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
7	1	II.2.2.7	Autres	DEPENSE	1350.00	0.00	0.00	\N	t	t	2026-03-23 09:27:53.205232+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
8	1	II.2.2.1	Location salle	DEPENSE	5000.00	0.00	0.00	\N	t	t	2026-03-23 09:57:07.943528+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
9	1	II.2.2.2	Déjeuner + Pause-café	DEPENSE	18000.00	0.00	0.00	\N	t	t	2026-03-23 09:57:07.993192+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
10	1	II.2.2.3	Presse	DEPENSE	1650.00	0.00	0.00	\N	t	t	2026-03-23 09:57:08.022516+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
11	1	II.2.2.4	Fournitures et autres	DEPENSE	1500.00	0.00	0.00	\N	t	t	2026-03-23 09:57:08.051346+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
12	1	II.2.2.5	Protocole	DEPENSE	1000.00	0.00	0.00	\N	t	t	2026-03-23 09:57:08.080373+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
13	1	II.2.2.6	Enseignes (Bâches, Badges, Roll up)	DEPENSE	1500.00	0.00	0.00	\N	t	t	2026-03-23 09:57:08.107544+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
14	1	II.2.2.7	Autres	DEPENSE	1350.00	0.00	0.00	\N	t	t	2026-03-23 09:57:08.133036+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
33	1	II.1.3	Acquisition Licences logiciel	DEPENSE	1200.00	0.00	0.00	II.1	t	f	\N	\N	30	1	f
22	1	II.2.21.1	TEST	DEPENSE	200.00	0.00	0.00	II.2.2.1	t	t	2026-03-23 10:13:32.10828+00	a2375bac-4a9f-4ed8-b674-a1807543c744	15	1	f
30	1	II.1	DEPENSES D'INVESTISSEMENT	DEPENSE	22000.00	0.00	0.00	\N	t	f	\N	\N	\N	1	f
16	1	II.2.2.2	Déjeuner + Pause-café	DEPENSE	18000.00	0.00	0.00	\N	t	t	2026-03-23 10:13:32.275826+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
17	1	II.2.2.3	Presse	DEPENSE	1650.00	0.00	0.00	\N	t	t	2026-03-23 10:13:32.324393+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
18	1	II.2.2.4	Fournitures et autres	DEPENSE	1500.00	0.00	0.00	\N	t	t	2026-03-23 10:13:32.372734+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
19	1	II.2.2.5	Protocole	DEPENSE	1000.00	0.00	0.00	\N	t	t	2026-03-23 10:13:32.4148+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
20	1	II.2.2.6	Enseignes (Bâches, Badges, Roll up)	DEPENSE	1500.00	0.00	0.00	\N	t	t	2026-03-23 10:13:32.451919+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
21	1	II.2.2.7	Autres	DEPENSE	1350.00	0.00	0.00	\N	t	t	2026-03-23 10:13:32.476785+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
15	1	II.2.2.1	Location salle	DEPENSE	0.00	0.00	0.00	\N	t	t	2026-03-23 10:13:40.554025+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
23	1	II.2.2.1	Location salle	DEPENSE	5000.00	0.00	0.00	\N	t	t	2026-03-23 10:22:59.803769+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
24	1	II.2.2.2	Déjeuner + Pause-café	DEPENSE	18000.00	0.00	0.00	\N	t	t	2026-03-23 10:22:59.922426+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
25	1	II.2.2.3	Presse	DEPENSE	1650.00	0.00	0.00	\N	t	t	2026-03-23 10:22:59.995966+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
26	1	II.2.2.4	Fournitures et autres	DEPENSE	1500.00	0.00	0.00	\N	t	t	2026-03-23 10:23:00.059862+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
27	1	II.2.2.5	Protocole	DEPENSE	1000.00	0.00	0.00	\N	t	t	2026-03-23 10:23:00.114754+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
28	1	II.2.2.6	Enseignes (Bâches, Badges, Roll up)	DEPENSE	1500.00	0.00	0.00	\N	t	t	2026-03-23 10:23:00.137256+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
29	1	II.2.2.7	Autres	DEPENSE	1350.00	0.00	0.00	\N	t	t	2026-03-23 10:23:00.157782+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	1	f
31	1	II.1.1	Acquisition des ouvrages disponibles pour les EC	DEPENSE	15000.00	0.00	0.00	II.1	t	f	\N	\N	30	1	f
32	1	II.1.2	Acquisition Matériels & Mobiliers de bureau, matériels informatiques et autres	DEPENSE	5800.00	0.00	0.00	II.1	t	f	\N	\N	30	1	f
36	1	II.2.1.1	EC-en cabinet	DEPENSE	29880.00	0.00	0.00	II.2.1	t	f	\N	\N	35	1	f
37	1	II.2.1.2	EC-Indépendant	DEPENSE	13680.00	0.00	0.00	II.2.1	t	f	\N	\N	35	1	f
38	1	II.2.1.3	EC-Salariés	DEPENSE	9315.00	0.00	0.00	II.2.1	t	f	\N	\N	35	1	f
39	1	II.2.1.4	Arriérés de Cotisation EC (2020,2021,2022 & 2023)	DEPENSE	2700.00	0.00	0.00	II.2.1	t	f	\N	\N	35	1	f
40	1	II.2.1.5	Sociétés d'Experts-Comptables	DEPENSE	45000.00	0.00	0.00	II.2.1	t	f	\N	\N	35	1	f
41	1	II.2.1.6	Supplément cotisation CA	DEPENSE	127956.00	0.00	0.00	II.2.1	t	f	\N	\N	35	1	f
42	1	II.2.1.7	Sociétés d' Experts-Comptables nouvellement inscrit	DEPENSE	5850.00	0.00	0.00	II.2.1	t	f	\N	\N	35	1	f
43	1	II.2.1.8	Stagiaires	DEPENSE	360.00	0.00	0.00	II.2.1	t	f	\N	\N	35	1	f
44	1	II.2.1.9	Frais d'inscription de SEC	DEPENSE	10000.00	0.00	0.00	II.2.1	t	f	\N	\N	35	1	f
35	1	II.2.1	COTISATION ANNUELLE AU CN (PER CAPITA)	DEPENSE	244741.00	0.00	0.00	II.2	t	f	\N	\N	34	1	f
46	1	II.2.2.1	Location salle	DEPENSE	5000.00	0.00	0.00	II.2.2	t	f	\N	\N	45	1	f
47	1	II.2.2.2	Déjeuner + Pause-café	DEPENSE	18000.00	0.00	0.00	II.2.2	t	f	\N	\N	45	1	f
48	1	II.2.2.3	Presse	DEPENSE	1650.00	0.00	0.00	II.2.2	t	f	\N	\N	45	1	f
49	1	II.2.2.4	Fournitures et autres	DEPENSE	1500.00	0.00	0.00	II.2.2	t	f	\N	\N	45	1	f
50	1	II.2.2.5	Protocole	DEPENSE	1000.00	0.00	0.00	II.2.2	t	f	\N	\N	45	1	f
51	1	II.2.2.6	Enseignes (Bâches, Badges, Roll up)	DEPENSE	1500.00	0.00	0.00	II.2.2	t	f	\N	\N	45	1	f
52	1	II.2.2.7	Autres	DEPENSE	1350.00	0.00	0.00	II.2.2	t	f	\N	\N	45	1	f
45	1	II.2.2	ASSEMBLEES PROVINCIALES (2 AP)	DEPENSE	30000.00	0.00	0.00	II.2	t	f	\N	\N	34	1	f
54	1	II.2.3.1	Organisation Examens de stage (honoraires prof, motivation surveillants, impression questionnaires , location salle & frais connexes)	DEPENSE	0.00	0.00	0.00	II.2.3	t	f	\N	\N	53	1	f
55	1	II.2.3.2	Inscription directe des EC au tableau	DEPENSE	0.00	0.00	0.00	II.2.3	t	f	\N	\N	53	1	f
56	1	II.2.3.3	Organisation de portes ouvertes+Tenue des Conférences débats dans les Universités, Instituts supérieurs et autres Institutions publiques, privés et partenaires institutionnels	DEPENSE	52763.25	0.00	0.00	II.2.3	t	f	\N	\N	53	1	f
57	1	II.2.3.4	Suivi évolution stagiaires	DEPENSE	4500.00	0.00	0.00	II.2.3	t	f	\N	\N	53	1	f
53	1	II.2.3	ORGANISATION DU STAGE & EXAMEN	DEPENSE	57263.25	0.00	0.00	II.2	t	f	\N	\N	34	1	f
59	1	II.2.4.1	Organisation Formation, séminaires, conférences etc.	DEPENSE	37790.00	0.00	0.00	II.2.4	t	f	\N	\N	58	1	f
60	1	II.2.4.2	Organisation échange métier.	DEPENSE	8000.00	0.00	0.00	II.2.4	t	f	\N	\N	58	1	f
58	1	II.2.4	FORMATION (JOURNEES ACADEMIQUES. SEMINAIRES,)	DEPENSE	45790.00	0.00	0.00	II.2	t	f	\N	\N	34	1	f
62	1	II.2.5.1	Réunions du Bureau	DEPENSE	7200.00	0.00	0.00	II.2.5	t	f	\N	\N	61	1	f
63	1	II.2.5.2	Réunions du Conseil	DEPENSE	18000.00	0.00	0.00	II.2.5	t	f	\N	\N	61	1	f
64	1	II.2.5.3	Réunions des Commissions Provinciales Permanentes (CPP)	DEPENSE	24000.00	0.00	0.00	II.2.5	t	f	\N	\N	61	1	f
65	1	II.2.5.4	Réunions commissions Ad Hoc et extra statutaire	DEPENSE	16000.00	0.00	0.00	II.2.5	t	f	\N	\N	61	1	f
66	1	II.2.5.5	Autres invités	DEPENSE	6520.00	0.00	0.00	II.2.5	t	f	\N	\N	61	1	f
61	1	II.2.5	REUNIONS AU CONSEIL PROVINCIAL	DEPENSE	71720.00	0.00	0.00	II.2	t	f	\N	\N	34	1	f
68	1	II.2.6.1	Loyers bureau CPK	DEPENSE	43790.40	0.00	0.00	II.2.6	t	f	\N	\N	67	1	f
69	1	II.2.6.3	Charges locatives (retenue locative)	DEPENSE	7862.40	0.00	0.00	II.2.6	t	f	\N	\N	67	1	f
67	1	II.2.6	LOYERS & CHARGES LOCATIVES	DEPENSE	51652.80	0.00	0.00	II.2	t	f	\N	\N	34	1	f
70	1	II.2.6.4	Autres charges (Electricité, eau, carburant générateur, etc.)	DEPENSE	0.00	0.00	0.00	II.2.6	t	f	\N	\N	67	1	f
72	1	II.2.7.1	Courses pour compte du CPK	DEPENSE	1800.00	0.00	0.00	II.2.7	t	f	\N	\N	71	1	f
73	1	II.2.7.2	Frais de communication	DEPENSE	11400.00	0.00	0.00	II.2.7	t	f	\N	\N	71	1	f
74	1	II.2.7.3	Abonnement internet	DEPENSE	1800.00	0.00	0.00	II.2.7	t	f	\N	\N	71	1	f
71	1	II.2.7	TRANSPORT  & COMMUNICATION	DEPENSE	15000.00	0.00	0.00	II.2	t	f	\N	\N	34	1	f
76	1	II.2.8.1	Aides en cas de décès d'EC ou conjoint( e )	DEPENSE	4500.00	0.00	0.00	II.2.8	t	f	\N	\N	75	1	f
75	1	II.2.8	ASSISTANCE SOCIALE	DEPENSE	4500.00	0.00	0.00	II.2	t	f	\N	\N	34	1	f
78	1	II.2.9.1	Salaires Personnel d'appoint	DEPENSE	63634.39	0.00	0.00	II.2.9	t	f	\N	\N	77	1	f
79	1	II.2.9.2	Charges sociales et fiscales	DEPENSE	8603.61	0.00	0.00	II.2.9	t	f	\N	\N	77	1	f
80	1	II.2.9.3	Autres avantages	DEPENSE	7223.80	0.00	0.00	II.2.9	t	f	\N	\N	77	1	f
77	1	II.2.9	CHARGES DU PERSONNEL	DEPENSE	79461.80	0.00	0.00	II.2	t	f	\N	\N	34	1	f
83	1	II.2.10.2	Fournitures & consommables de Bureau	DEPENSE	4000.00	0.00	0.00	II.2.10	t	f	\N	\N	81	1	f
84	1	II.2.10.3	Petite collation (sucre, thé, café, lait, jus, eau, etc.)+casse croute pendant les réunions	DEPENSE	4000.00	0.00	0.00	II.2.10	t	f	\N	\N	81	1	f
85	1	II.2.10.4	Produits d'entretien et de nettoyage	DEPENSE	1500.00	0.00	0.00	II.2.10.1	t	f	\N	\N	82	1	f
86	1	II.2.10.5	Frais bancaires et autres	DEPENSE	2500.00	0.00	0.00	II.2.10.1	t	f	\N	\N	82	1	f
87	1	II.2.10.6	Petites réparations	DEPENSE	1000.00	0.00	0.00	II.2.10.1	t	f	\N	\N	82	1	f
88	1	II.2.10.7	Petits matériels	DEPENSE	1000.00	0.00	0.00	II.2.10.1	t	f	\N	\N	82	1	f
89	1	II.2.10.8	Carburant véhicule	DEPENSE	1700.00	0.00	0.00	II.2.10.1	t	f	\N	\N	82	1	f
90	1	II.2.10.9	Entretien Véhicule	DEPENSE	5198.00	0.00	0.00	II.2.10.1	t	f	\N	\N	82	1	f
82	1	II.2.10.1	Impression pins, fanions et autres	DEPENSE	12898.00	0.00	0.00	II.2.10	t	f	\N	\N	81	1	f
81	1	II.2.10	AUTRES	DEPENSE	20898.00	0.00	0.00	II.2	t	f	\N	\N	34	1	f
92	1	II.2.12.1	Honoraires CAC et autres prestations extérieures	DEPENSE	5000.00	0.00	0.00	II.2.12	t	f	\N	\N	91	1	f
91	1	II.2.12	HONORAIRES & AUTRES PRESTATIONS EXTERIEURES	DEPENSE	5000.00	0.00	0.00	II.2	t	f	\N	\N	34	1	f
93	1	II.2.12.2	Frais d'actes & contentieux	DEPENSE	0.00	0.00	0.00	II.2.12	t	f	\N	\N	91	1	f
95	1	II.2.13.1	Participation aux rencontres internationales (Congrès OEC France, etc. )	DEPENSE	14000.00	0.00	0.00	II.2.13	t	f	\N	\N	94	1	f
96	1	II.2.13.2	Frais de représentation des invités aux organisations de l'Ordre	DEPENSE	50602.00	0.00	0.00	II.2.13	t	f	\N	\N	94	1	f
97	1	II.2.13.3	Participations aux Organisations Nationales	DEPENSE	0.00	0.00	0.00	II.2.13	t	f	\N	\N	94	1	f
98	1	II.2.13.4	Participations aux Assemblées générales (Conseil national)	DEPENSE	38472.49	0.00	0.00	II.2.13	t	f	\N	\N	94	1	f
94	1	II.2.13	VOYAGES, REPRESENTATIONS & AUTRES FRAIS ASSIMILES	DEPENSE	103074.49	0.00	0.00	II.2	t	f	\N	\N	34	1	f
34	1	II.2	DEPENSES DE FONCTIONNEMENT	DEPENSE	751664.34	0.00	0.00	\N	t	f	\N	\N	\N	1	f
100	1	I.1	EMPRUNTS	RECETTE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	1	f
101	1	I.1.1	Emprunt auprès des IF	RECETTE	0.00	0.00	0.00	I.1	t	f	\N	\N	100	1	f
103	1	I.2	SUBSIDES	RECETTE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	1	f
108	1	I.3.2	EC-Indépendant	RECETTE	41040.00	0.00	0.00	I.3	t	f	\N	\N	106	1	f
109	1	I.3.3	EC-Salariés	RECETTE	27945.00	0.00	0.00	I.3	t	f	\N	\N	106	1	f
110	1	I.3.4	Arriérés de Cotisation EC (2020-2024)	RECETTE	8100.00	0.00	0.00	I.3	t	f	\N	\N	106	1	f
111	1	I.3.5	Sociétés d'Experts-Comptables	RECETTE	135000.00	0.00	0.00	I.3	t	f	\N	\N	106	1	f
104	1	I.2.1	Etat	RECETTE	0.00	0.00	200.00	I.2	t	f	\N	\N	103	1	f
112	1	I.3.6	Supplément cotisation CA	RECETTE	127956.00	0.00	0.00	I.3	t	f	\N	\N	106	1	f
113	1	I.3.7	Sociétés d' Experts-Comptables nouvellement inscrit	RECETTE	17550.00	0.00	0.00	I.3	t	f	\N	\N	106	1	f
114	1	I.3.8	Stagiaires	RECETTE	1080.00	0.00	0.00	I.3	t	f	\N	\N	106	1	f
106	1	I.3	COTISATION ANNUELLE	RECETTE	448311.00	0.00	0.00	\N	t	f	\N	\N	\N	1	f
116	1	I.4.1	Frais de dossier candidats à insc direct	RECETTE	0.00	0.00	0.00	I.4	t	f	\N	\N	115	1	f
117	1	1.4.2	Inscription au tableau des Sociétés d'Experts-Comptables	RECETTE	30000.00	0.00	0.00	I.4	t	f	\N	\N	115	1	f
115	1	I.4	AGREMENTS & PRODUITS CONNEXES	RECETTE	30000.00	0.00	0.00	\N	t	f	\N	\N	\N	1	f
118	1	I.5	STAGE ET PARTICIPATION AUX EXAMENS	RECETTE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	1	f
119	1	I.5.1	Dépôt de dossier des impétrants	RECETTE	0.00	0.00	0.00	I.5	t	f	\N	\N	118	1	f
120	1	I.5.2	Admission / Stage (inscription aux examens)	RECETTE	0.00	0.00	0.00	I.5	t	f	\N	\N	118	1	f
121	1	I.5.3	Sessions / Stage	RECETTE	0.00	0.00	0.00	I.5	t	f	\N	\N	118	1	f
122	1	I.5.4	Examen d'aptitude professionnelle (Jury / Stage)	RECETTE	0.00	0.00	0.00	I.5	t	f	\N	\N	118	1	f
123	1	I.5.5	Admission à l'Ordre / PP étrangère	RECETTE	0.00	0.00	0.00	I.5	t	f	\N	\N	118	1	f
125	1	I.6.1	Organisation Formations, séminaires, conférence etc.	RECETTE	81750.00	0.00	0.00	I.6	t	f	\N	\N	124	1	f
126	1	I.6.2	Formations (échange metier)	RECETTE	42000.00	0.00	0.00	I.6	t	f	\N	\N	124	1	f
124	1	I.6	FORMATIONS	RECETTE	123750.00	0.00	0.00	\N	t	f	\N	\N	\N	1	f
107	1	I.3.1	EC-en cabinet	RECETTE	89640.00	0.00	1799.94	I.3	t	f	\N	\N	106	1	f
102	1	I.1.2	Emprunt auprès des autres organismes	RECETTE	0.00	0.00	5000.00	I.1	t	f	\N	\N	100	1	f
105	1	I.2.2	Autres organismes	RECETTE	0.00	0.00	10200.00	I.2	t	f	\N	\N	103	1	f
99	1	II.2.11	IMPREVUS	DEPENSE	22563.00	20.00	50.00	II.2	t	f	\N	\N	34	1	f
128	1	I.7.1	Produits de vente de brochures (Annuaires, pins, fanion, etc)	RECETTE	1000.00	0.00	0.00	I.7	t	f	\N	\N	127	1	f
129	1	I.7.2	Contribution du Conseil National aux loyers	RECETTE	0.00	0.00	0.00	I.7	t	f	\N	\N	127	1	f
131	1	I.7.4	Pénalité pour absence aux assemblées generales	RECETTE	10200.00	0.00	0.00	I.7	t	f	\N	\N	127	1	f
132	1	I.7.5	Pourcentage vente ouvrage pour tiers	RECETTE	500.00	0.00	0.00	I.7	t	f	\N	\N	127	1	f
127	1	I.7	AUTRES PRODUITS	RECETTE	23700.00	0.00	0.00	\N	t	f	\N	\N	\N	1	f
134	5	PERS-01	Salaires et Gratifications	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	8	t
135	7	ADM-01	Loyer et Charges Locatives	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	10	t
136	6	COM-01	Communication et Internet	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	9	t
137	5	COM-01	Communication et Internet	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	8	t
138	6	PERS-01	Salaires et Gratifications	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	9	t
139	6	DIV-01	Divers et Imprévus	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	9	t
140	7	TRA-01	Carburant et Maintenance	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	10	t
141	5	DIV-01	Divers et Imprévus	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	8	t
142	7	MISS-01	Missions et Per Diem	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	10	t
143	7	PERS-01	Salaires et Gratifications	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	10	t
144	5	ADM-01	Loyer et Charges Locatives	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	8	t
145	7	COM-01	Communication et Internet	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	10	t
146	6	ADM-01	Loyer et Charges Locatives	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	9	t
147	6	TRA-01	Carburant et Maintenance	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	9	t
148	5	TRA-01	Carburant et Maintenance	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	8	t
149	7	DIV-01	Divers et Imprévus	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	10	t
150	6	MISS-01	Missions et Per Diem	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	9	t
151	5	MISS-01	Missions et Per Diem	DEPENSE	0.00	0.00	0.00	\N	t	f	\N	\N	\N	8	t
130	1	I.7.3	Location Espace bureau	RECETTE	12000.00	0.00	89.98	I.7	t	f	\N	\N	127	1	f
\.


--
-- Data for Name: caisse_centrale; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.caisse_centrale (id, solde_usd, solde_cdf, derniere_maj, organisation_id) FROM stdin;
2	0.00	0.00	2026-03-25 12:00:26.300148+00	8
3	0.00	0.00	2026-03-25 12:00:26.763554+00	8
4	0.00	0.00	2026-03-25 12:00:55.253231+00	8
5	0.00	0.00	2026-03-25 12:00:55.665714+00	8
6	0.00	0.00	2026-03-25 12:01:08.063951+00	9
7	0.00	0.00	2026-03-25 12:01:08.460119+00	9
8	0.00	0.00	2026-03-25 12:01:24.005068+00	10
9	0.00	0.00	2026-03-25 12:01:24.409813+00	10
10	0.00	0.00	2026-03-25 12:02:56.696172+00	10
11	0.00	0.00	2026-03-25 12:03:18.338305+00	9
12	0.00	0.00	2026-03-25 12:03:18.774335+00	9
13	0.00	0.00	2026-03-25 12:15:23.590483+00	10
14	0.00	0.00	2026-03-25 12:15:24.063855+00	10
15	0.00	0.00	2026-03-25 12:37:35.283091+00	8
16	0.00	0.00	2026-03-25 12:37:35.678857+00	8
17	0.00	0.00	2026-03-25 12:37:36.030509+00	8
18	0.00	0.00	2026-03-25 12:40:37.987657+00	8
19	0.00	0.00	2026-03-25 12:40:38.378841+00	8
20	0.00	0.00	2026-03-25 12:43:20.842438+00	8
21	0.00	0.00	2026-03-25 12:43:21.279151+00	8
22	0.00	0.00	2026-03-25 12:43:35.892322+00	8
23	0.00	0.00	2026-03-25 12:43:36.289779+00	8
24	0.00	0.00	2026-03-25 12:44:25.787904+00	8
25	0.00	0.00	2026-03-25 12:44:26.193604+00	8
26	0.00	0.00	2026-03-25 12:44:37.392055+00	10
27	0.00	0.00	2026-03-25 12:44:37.879936+00	10
28	0.00	0.00	2026-03-25 12:45:58.0322+00	10
29	0.00	0.00	2026-03-25 12:45:58.406748+00	10
30	0.00	0.00	2026-03-25 12:46:01.423385+00	10
31	0.00	0.00	2026-03-25 12:47:12.294757+00	8
32	0.00	0.00	2026-03-25 12:47:12.706106+00	8
33	0.00	0.00	2026-03-25 12:47:49.839188+00	8
34	0.00	0.00	2026-03-25 12:47:52.423803+00	8
35	0.00	0.00	2026-03-25 12:48:23.749325+00	9
36	0.00	0.00	2026-03-25 12:48:24.142357+00	9
37	0.00	0.00	2026-03-25 12:49:05.920195+00	9
38	0.00	0.00	2026-03-25 12:49:06.367066+00	9
39	0.00	0.00	2026-03-25 12:49:22.130111+00	10
40	0.00	0.00	2026-03-25 12:49:22.507104+00	10
41	0.00	0.00	2026-03-25 12:52:21.194098+00	10
42	0.00	0.00	2026-03-25 12:52:22.055788+00	10
43	0.00	0.00	2026-03-25 12:57:22.82208+00	10
44	0.00	0.00	2026-03-25 13:02:22.334476+00	10
45	0.00	0.00	2026-03-25 13:07:23.56322+00	10
46	0.00	0.00	2026-03-25 13:12:23.041369+00	10
47	0.00	0.00	2026-03-25 13:17:22.980194+00	10
48	0.00	0.00	2026-03-25 13:19:19.316694+00	10
49	0.00	0.00	2026-03-25 13:19:19.472338+00	10
50	0.00	0.00	2026-03-25 13:19:32.039787+00	10
51	0.00	0.00	2026-03-25 13:19:32.479593+00	10
52	0.00	0.00	2026-03-25 13:21:22.694408+00	8
53	0.00	0.00	2026-03-25 13:21:23.0973+00	8
54	0.00	0.00	2026-03-25 13:21:47.940261+00	8
55	0.00	0.00	2026-03-25 13:21:48.335253+00	8
56	0.00	0.00	2026-03-25 13:21:57.147086+00	8
57	0.00	0.00	2026-03-25 13:39:23.696876+00	8
58	0.00	0.00	2026-03-25 13:39:24.115038+00	8
59	0.00	0.00	2026-03-25 13:40:15.859239+00	8
60	0.00	0.00	2026-03-25 13:40:16.380617+00	8
61	0.00	0.00	2026-03-25 13:46:14.010989+00	8
62	0.00	0.00	2026-03-25 13:46:14.437302+00	8
63	0.00	0.00	2026-03-25 13:59:24.294003+00	8
64	0.00	0.00	2026-03-25 13:59:24.911221+00	8
65	0.00	0.00	2026-03-25 14:01:47.499908+00	8
66	0.00	0.00	2026-03-25 14:01:47.913289+00	8
67	0.00	0.00	2026-03-25 14:02:52.453475+00	8
68	0.00	0.00	2026-03-25 14:02:52.866102+00	8
69	0.00	0.00	2026-03-25 14:06:57.789812+00	8
70	0.00	0.00	2026-03-25 14:06:58.279194+00	8
71	0.00	0.00	2026-03-25 14:06:59.919497+00	8
72	0.00	0.00	2026-03-25 14:07:12.176524+00	8
73	0.00	0.00	2026-03-25 14:07:12.54358+00	8
74	0.00	0.00	2026-03-25 14:08:54.708618+00	8
75	0.00	0.00	2026-03-25 14:09:28.523447+00	8
76	0.00	0.00	2026-03-25 14:16:13.26919+00	8
77	0.00	0.00	2026-03-25 14:16:13.710555+00	8
78	0.00	0.00	2026-03-25 14:17:26.969034+00	8
79	0.00	0.00	2026-03-25 14:17:56.110073+00	10
80	0.00	0.00	2026-03-25 14:17:56.528732+00	10
81	0.00	0.00	2026-03-25 14:18:57.939212+00	10
82	0.00	0.00	2026-03-25 14:18:58.383496+00	10
83	0.00	0.00	2026-03-25 14:21:53.348702+00	8
84	0.00	0.00	2026-03-25 14:21:53.743885+00	8
85	0.00	0.00	2026-03-25 14:22:11.009474+00	8
86	0.00	0.00	2026-03-25 14:22:11.391655+00	8
87	0.00	0.00	2026-03-25 15:28:31.412149+00	8
88	0.00	0.00	2026-03-25 15:28:31.844694+00	8
89	0.00	0.00	2026-03-25 15:33:17.3136+00	8
90	0.00	0.00	2026-03-25 15:33:17.721231+00	8
91	0.00	0.00	2026-03-25 15:35:09.292191+00	8
92	0.00	0.00	2026-03-25 15:35:09.807177+00	8
93	0.00	0.00	2026-03-25 15:37:43.859021+00	8
94	0.00	0.00	2026-03-25 15:37:54.689252+00	8
95	0.00	0.00	2026-03-25 15:37:55.10881+00	8
96	0.00	0.00	2026-03-25 15:38:20.655297+00	8
97	0.00	0.00	2026-03-25 15:41:20.630057+00	8
98	0.00	0.00	2026-03-25 15:41:30.764314+00	8
99	0.00	0.00	2026-03-25 15:41:31.510927+00	8
100	0.00	0.00	2026-03-25 15:42:10.682972+00	8
101	0.00	0.00	2026-03-25 15:42:11.087543+00	8
102	0.00	0.00	2026-03-25 15:42:28.279733+00	8
103	0.00	0.00	2026-03-25 15:42:29.492116+00	8
104	0.00	0.00	2026-03-25 15:42:29.944695+00	8
105	0.00	0.00	2026-03-25 15:42:30.732733+00	8
106	0.00	0.00	2026-03-25 15:42:33.305104+00	8
107	0.00	0.00	2026-03-25 15:43:11.202098+00	8
108	0.00	0.00	2026-03-25 15:43:11.628868+00	8
109	0.00	0.00	2026-03-25 15:47:48.380342+00	8
110	0.00	0.00	2026-03-25 15:47:48.82113+00	8
111	0.00	0.00	2026-03-25 15:47:57.326197+00	8
112	0.00	0.00	2026-03-25 15:47:57.73965+00	8
113	0.00	0.00	2026-03-25 15:48:08.551469+00	8
114	0.00	0.00	2026-03-25 15:51:13.922904+00	8
115	0.00	0.00	2026-03-25 15:51:14.48388+00	8
116	0.00	0.00	2026-03-25 15:51:40.060829+00	8
117	0.00	0.00	2026-03-25 15:51:40.514364+00	8
118	0.00	0.00	2026-03-25 15:51:49.357789+00	8
119	0.00	0.00	2026-03-25 15:52:04.378552+00	8
120	0.00	0.00	2026-03-25 15:52:04.754787+00	8
147	0.00	0.00	2026-03-26 08:32:32.917866+00	8
148	0.00	0.00	2026-03-26 08:32:33.636838+00	8
149	0.00	0.00	2026-03-26 09:09:19.960879+00	8
150	0.00	0.00	2026-03-26 09:09:20.832287+00	8
151	0.00	0.00	2026-03-26 09:12:26.113074+00	8
152	0.00	0.00	2026-03-26 09:12:28.300946+00	8
153	0.00	0.00	2026-03-26 09:15:30.402716+00	8
154	0.00	0.00	2026-03-26 09:15:30.78301+00	8
155	0.00	0.00	2026-03-26 09:15:50.612969+00	8
156	0.00	0.00	2026-03-26 09:15:51.058553+00	8
157	0.00	0.00	2026-03-26 09:16:33.671902+00	8
158	0.00	0.00	2026-03-26 09:16:34.139713+00	8
159	0.00	0.00	2026-03-26 09:17:30.052384+00	8
160	0.00	0.00	2026-03-26 09:17:30.427337+00	8
161	0.00	0.00	2026-03-26 09:18:04.381489+00	8
162	0.00	0.00	2026-03-26 09:18:04.741905+00	8
163	0.00	0.00	2026-03-26 09:18:26.609343+00	8
165	0.00	0.00	2026-03-26 09:19:23.036368+00	8
166	0.00	0.00	2026-03-26 09:19:23.440811+00	8
164	0.00	0.00	2026-03-26 09:18:27.000736+00	8
167	0.00	0.00	2026-03-26 09:19:40.533828+00	8
168	0.00	0.00	2026-03-26 09:19:40.890883+00	8
169	0.00	0.00	2026-03-26 11:45:58.108567+00	8
170	0.00	0.00	2026-03-26 11:45:58.629404+00	8
171	0.00	0.00	2026-03-26 11:47:24.888845+00	8
172	0.00	0.00	2026-03-26 11:47:25.435951+00	8
173	0.00	0.00	2026-03-26 13:03:24.358123+00	8
174	0.00	0.00	2026-03-26 13:03:26.787363+00	8
175	0.00	0.00	2026-03-26 13:03:27.201858+00	8
176	0.00	0.00	2026-03-26 13:23:15.107117+00	8
177	0.00	0.00	2026-03-26 13:23:16.761006+00	8
178	0.00	0.00	2026-03-26 15:12:34.878337+00	8
179	0.00	0.00	2026-03-26 15:12:35.619788+00	8
180	0.00	0.00	2026-03-26 15:29:29.731999+00	8
181	0.00	0.00	2026-03-26 15:29:30.145686+00	8
213	0.00	0.00	2026-03-27 08:55:03.652868+00	8
214	0.00	0.00	2026-03-27 08:55:04.123783+00	8
215	0.00	0.00	2026-03-27 08:56:33.467248+00	8
216	0.00	0.00	2026-03-27 08:56:33.891246+00	8
217	0.00	0.00	2026-03-27 09:01:34.105781+00	8
218	0.00	0.00	2026-03-27 09:02:34.337578+00	8
219	0.00	0.00	2026-03-27 11:16:44.975987+00	8
220	0.00	0.00	2026-03-27 11:16:45.377963+00	8
221	0.00	0.00	2026-03-27 11:18:14.146663+00	8
222	0.00	0.00	2026-03-27 11:18:14.557831+00	8
223	0.00	0.00	2026-03-27 11:23:15.373596+00	8
224	0.00	0.00	2026-03-27 11:28:15.64516+00	8
225	0.00	0.00	2026-03-27 11:33:15.594546+00	8
226	0.00	0.00	2026-03-27 11:38:15.538701+00	8
227	0.00	0.00	2026-03-27 11:43:15.813456+00	8
228	0.00	0.00	2026-03-27 11:48:15.39046+00	8
229	0.00	0.00	2026-03-27 11:53:31.597128+00	8
230	0.00	0.00	2026-03-27 11:58:31.752922+00	8
231	0.00	0.00	2026-03-27 12:03:31.349716+00	8
232	0.00	0.00	2026-03-27 12:08:31.710559+00	8
233	0.00	0.00	2026-03-27 12:09:54.72027+00	8
234	0.00	0.00	2026-03-27 12:10:03.900611+00	8
235	0.00	0.00	2026-03-27 12:10:04.282455+00	8
236	0.00	0.00	2026-03-27 13:24:51.69531+00	8
237	0.00	0.00	2026-03-27 13:24:52.171097+00	8
238	0.00	0.00	2026-03-27 13:24:55.753185+00	8
239	0.00	0.00	2026-03-27 13:41:46.218958+00	8
240	0.00	0.00	2026-03-27 13:41:46.754934+00	8
241	0.00	0.00	2026-03-27 14:39:16.474673+00	8
242	0.00	0.00	2026-03-27 14:39:16.955459+00	8
243	0.00	0.00	2026-03-27 14:42:38.418113+00	8
244	0.00	0.00	2026-03-27 14:42:38.947783+00	8
245	0.00	0.00	2026-03-30 08:39:33.252416+00	8
246	0.00	0.00	2026-03-30 08:39:33.668382+00	8
247	0.00	0.00	2026-03-30 08:44:33.969691+00	8
248	0.00	0.00	2026-03-30 08:49:33.871543+00	8
249	0.00	0.00	2026-03-30 08:54:33.868275+00	8
250	0.00	0.00	2026-03-30 08:59:33.874618+00	8
251	0.00	0.00	2026-03-30 09:04:33.806179+00	8
252	0.00	0.00	2026-03-30 09:09:33.854344+00	8
253	0.00	0.00	2026-03-30 09:15:28.803421+00	8
254	0.00	0.00	2026-03-30 09:20:28.794554+00	8
255	0.00	0.00	2026-03-30 09:25:28.829906+00	8
256	0.00	0.00	2026-03-30 09:30:28.807203+00	8
257	0.00	0.00	2026-03-30 09:35:28.808546+00	8
258	0.00	0.00	2026-03-30 09:40:28.813651+00	8
259	0.00	0.00	2026-03-30 09:45:28.8261+00	8
260	0.00	0.00	2026-03-30 09:50:28.799422+00	8
261	0.00	0.00	2026-03-30 09:55:28.973509+00	8
262	0.00	0.00	2026-03-30 10:00:28.832194+00	8
263	0.00	0.00	2026-03-30 10:05:28.825323+00	8
264	0.00	0.00	2026-03-30 10:10:28.845136+00	8
265	0.00	0.00	2026-03-30 10:15:28.798119+00	8
266	0.00	0.00	2026-03-30 10:20:28.858345+00	8
267	0.00	0.00	2026-03-30 10:25:28.801164+00	8
268	0.00	0.00	2026-03-30 10:30:28.840641+00	8
269	0.00	0.00	2026-03-30 10:35:28.801505+00	8
270	0.00	0.00	2026-03-30 10:36:48.075398+00	8
271	0.00	0.00	2026-03-30 10:36:48.523273+00	8
272	0.00	0.00	2026-03-30 10:39:41.048199+00	8
273	0.00	0.00	2026-03-30 10:39:41.580012+00	8
274	0.00	0.00	2026-03-30 10:39:41.943528+00	8
275	0.00	0.00	2026-03-30 15:12:51.706529+00	8
276	0.00	0.00	2026-03-30 15:12:52.328253+00	8
277	0.00	0.00	2026-03-31 10:32:33.484385+00	8
278	0.00	0.00	2026-03-31 10:32:34.054524+00	8
279	0.00	0.00	2026-03-31 10:37:22.140254+00	8
280	0.00	0.00	2026-03-31 10:37:22.998959+00	8
281	0.00	0.00	2026-03-31 12:35:46.346395+00	8
282	0.00	0.00	2026-03-31 12:35:46.982186+00	8
283	0.00	0.00	2026-03-31 13:38:01.96182+00	8
284	0.00	0.00	2026-03-31 13:38:02.482929+00	8
285	0.00	0.00	2026-04-02 08:25:07.217074+00	8
286	0.00	0.00	2026-04-02 08:25:07.625848+00	8
287	0.00	0.00	2026-04-02 08:26:49.166207+00	8
288	0.00	0.00	2026-04-02 08:26:53.348972+00	8
289	0.00	0.00	2026-04-12 10:45:34.426058+00	8
290	0.00	0.00	2026-04-12 10:45:34.927926+00	8
1	16639.98	0.00	2026-04-13 09:10:01.238342+00	1
\.


--
-- Data for Name: category_changes_history; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.category_changes_history (id, expert_id, numero_ordre, old_category, new_category, changed_by, reason, old_data, new_data, created_at) FROM stdin;
\.


--
-- Data for Name: clotures; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.clotures (id, reference_numero, date_cloture, caissier_id, solde_initial_usd, solde_initial_cdf, total_entrees_usd, total_entrees_cdf, total_sorties_usd, total_sorties_cdf, solde_theorique_usd, solde_theorique_cdf, solde_physique_usd, solde_physique_cdf, ecart_usd, ecart_cdf, billetage_usd, billetage_cdf, observation, statut, created_at, date_debut, pdf_path, taux_change_applique, organisation_id) FROM stdin;
1	CLO-ONEC-CPK-2026-0001	2026-04-12 10:24:47.733105+00	a2375bac-4a9f-4ed8-b674-a1807543c744	0.00	0.00	16489.98	0.00	50.00	0.00	16439.98	0.00	16439.98	0.00	0.00	0.00	null	null	ok	VALIDEE	2026-04-12 10:24:47.783331+00	\N	CLO-ONEC-CPK-2026-0001-pv.pdf	225.0000	1
\.


--
-- Data for Name: commission_members; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.commission_members (id, service_id, user_id, full_name, role_type, custom_title, is_signer, created_at, email, matricule) FROM stdin;
1	17	\N	TUMBA KABALAMBI Jean-Marie	PRESIDENT	\N	f	2026-03-26 11:25:14.306477+00	jeanmarie747@hotmail.com	EC/16.00513
2	1	49a1c5f5-2d47-4ad6-8549-13c781a16223	Christian KIDIKALA	MEMBRE	\N	f	2026-03-31 09:37:50.368926+00	kidikala@onecrdc.com	\N
3	1	\N	Constant MORO	PRESIDENT	\N	t	2026-03-31 09:38:59.395477+00	constantmoro@onecrdc.com	\N
4	1	\N	Alain LUKA	MEMBRE	\N	f	2026-03-31 09:40:07.815787+00	alainluka@onecrdc.com	\N
5	2	\N	Alain LUKA	ASSISTANT	\N	f	2026-03-31 09:46:07.491708+00	alainluka@onecrdc.com	\N
6	2	\N	VANGU KI-TULANDA WA BAFUANGA Joseph	PRESIDENT	\N	f	2026-03-31 09:48:32.36778+00	josephvangu71@gmail.com	EC/16.00521
\.


--
-- Data for Name: comptes_bancaires; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.comptes_bancaires (id, banque_id, intitule, numero_compte, devise, solde_initial, is_active, solde_actuel, organisation_id, account_type) FROM stdin;
1	\N	Caisse USD	CASH-USD-1	USD	0.00	t	0.00	1	CASH
2	\N	Caisse CDF	CASH-CDF-1	CDF	0.00	t	0.00	1	CASH
3	1	ONEC	000112646561	USD	50000.00	t	50600.00	1	BANK
\.


--
-- Data for Name: denominations; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.denominations (id, devise, valeur, label, est_actif, ordre) FROM stdin;
1	USD	100.00	100 $	t	1
2	USD	50.00	50 $	t	2
3	USD	20.00	20 $	t	3
4	USD	10.00	10 $	t	4
5	USD	5.00	5 $	t	5
6	USD	1.00	1 $	t	6
7	CDF	20000.00	20 000 FC	t	1
8	CDF	10000.00	10 000 FC	t	2
9	CDF	5000.00	5 000 FC	t	3
10	CDF	1000.00	1 000 FC	t	4
11	CDF	500.00	500 FC	t	5
12	CDF	200.00	200 FC	t	6
13	CDF	100.00	100 FC	t	7
14	CDF	50.00	50 FC	t	8
\.


--
-- Data for Name: document_sequences; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.document_sequences (id, doc_type, year, counter, updated_at, tenant_id) FROM stdin;
adde4a28-cd61-4149-a69f-e12998b5ccf2	REM	2026	1	2026-03-20 12:42:39.111733+00	1
fd7a6544-59f2-4e76-a205-0ca499c199fb	PROF	2026	3	2026-04-08 14:35:42.968736+00	1
b0a115ff-e0d3-49a4-a33a-2a874fc69cef	PAY	2026	1	2026-04-12 10:11:23.164819+00	1
9bb3d2d7-5f91-45db-bab3-0439361b6d04	CLO	2026	1	2026-04-12 10:24:47.77272+00	1
4710e75f-db97-4848-a8b2-5a30c5fea10a	REQ	2026	8	2026-04-13 11:50:29.187048+00	1
\.


--
-- Data for Name: dossiers_requisition; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.dossiers_requisition (id, reference, description, status, commentaires_examen, created_by, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: encaissements; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.encaissements (id, numero_recu, type_client, expert_comptable_id, client_nom, description, montant, montant_total, montant_paye, statut_paiement, mode_paiement, reference, date_encaissement, created_by, created_at, budget_poste_id, montant_percu, devise_perception, taux_change_applique, is_deleted, deleted_at, deleted_by, service_id, budget_poste_code, budget_poste_libelle, libelle, canal, compte_bancaire_id, piece_jointe, organisation_id, is_reconciled, reconciled_at, reconciled_by_id, bank_statement_ref, est_proforma, numero_proforma, date_paiement, source_proforma_id) FROM stdin;
963b3dfe-1eb3-4114-afe6-4d6248ef0a60	REC-ONEC-CPK-2026-A0001	banque_institution	\N	Rawbank	\N	10000.00	10000.00	10000.00	complet	cash	\N	2026-03-26 00:00:00+00	49a1c5f5-2d47-4ad6-8549-13c781a16223	2026-03-26 15:07:29.913209+00	105	10000.00	USD	1.0000	f	\N	\N	\N	I.2.2	Autres organismes	Don volontaire	CAISSE	1	\N	1	t	2026-04-03 10:07:04.457019+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	f	\N	\N	\N
9701ffbf-5be4-4497-8715-d98cc67ffdd8	REC-ONEC-CPK-2026-A   1	expert_comptable	480b5877-aec5-4d63-bed8-bbd17979ae35	\N	\N	600.00	600.00	600.00	complet	cash	\N	2026-03-30 00:00:00+00	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-30 11:49:41.682253+00	107	600.00	USD	1.0000	f	\N	\N	1	I.3.1	EC-en cabinet	Pénalité de retard - Cotisation	CAISSE	1	\N	1	t	2026-04-03 10:07:04.595394+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	f	\N	\N	\N
4e1aa171-531e-4021-ac32-8d5d233effff	REC-ONEC-CPK-2026-A   2	expert_comptable	6b310257-e821-4a8b-8177-6437c01a2d1d	\N	\N	600.00	600.00	600.00	complet	cash	\N	2026-03-30 00:00:00+00	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-30 11:51:52.204258+00	107	600.00	USD	1.0000	f	\N	\N	1	I.3.1	EC-en cabinet	Cotisation annuelle - Expert-Comptable Cabinet	CAISSE	1	\N	1	t	2026-04-03 10:07:04.599406+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	f	\N	\N	\N
7579cce1-8021-44ca-8628-22a8dcbd1662	REC-ONEC-CPK-2026-A   3	client_externe	\N	kidikala	\N	200.00	200.00	200.00	complet	cash	\N	2026-03-30 00:00:00+00	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-30 12:50:36.792019+00	104	200.00	USD	1.0000	f	\N	\N	1	I.2.1	Etat	Cotisation annuelle - Expert-Comptable Salarié	CAISSE	1	\N	1	t	2026-04-03 10:07:04.608055+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	f	\N	\N	\N
56d5c07f-d0ab-4a8e-88b1-a84a7723c3ca	REC-ONEC-CPK-2026-A   5	organisation	\N	eclectic	\N	5000.00	5000.00	5000.00	complet	cash	\N	2026-03-31 00:00:00+00	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-31 13:55:43.750147+00	102	5000.00	USD	1.0000	f	\N	\N	1	I.1.2	Emprunt auprès des autres organismes	Sponsoring événement	CAISSE	1	\N	1	t	2026-04-03 10:07:04.612335+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	f	\N	\N	\N
c9224e80-c7b2-41f1-9528-218d511d0220	REC-ONEC-CPK-2026-A   4	expert_comptable	5a89c377-158b-4a0c-b3c6-f703b124e055	\N	\N	600.00	600.00	600.00	complet	virement	f	2026-03-31 00:00:00+00	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-31 13:49:28.080233+00	107	600.00	USD	1.0000	f	\N	\N	1	I.3.1	EC-en cabinet	Cotisation annuelle - Expert-Comptable Cabinet	BANQUE	3	\N	1	t	2026-03-31 15:27:47.658558+00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	f	\N	\N	\N
f68c65b4-e370-4960-9ce1-f746a3163bb5	REC-ONEC-CPK-2026-A0049	expert_comptable	0ce71fa9-5d1a-4b50-bd5b-4505a0445665	\N	fo	20.00	20.00	20.00	complet	cash	\N	2026-04-08 00:00:00+00	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-04-08 13:17:14.640772+00	130	20.00	USD	1.0000	f	\N	\N	1	I.7.3	Location Espace bureau	Location salle de réunion	CAISSE	1	\N	1	f	\N	\N	\N	f	\N	\N	\N
d8baf738-e09b-4c77-afd9-5cef81c7f72b	REC-ONEC-CPK-2026-A0050	expert_comptable	0ce71fa9-5d1a-4b50-bd5b-4505a0445665	\N	fo	20.00	20.00	20.00	complet	cash	\N	2026-04-08 00:00:00+00	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-04-08 13:17:14.640106+00	130	20.00	USD	1.0000	f	\N	\N	1	I.7.3	Location Espace bureau	Location salle de réunion	CAISSE	1	\N	1	f	\N	\N	\N	f	\N	\N	\N
fc2b5cc4-94e6-4962-b136-51650c6af738	\N	expert_comptable	0ce71fa9-5d1a-4b50-bd5b-4505a0445665	\N	\N	680.00	680.00	0.00	non_paye	cash	\N	2026-04-08 00:00:00+00	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-04-08 14:20:22.019643+00	130	680.00	USD	1.0000	f	\N	\N	1	I.7.3	Location Espace bureau	Location salle de réunion	CAISSE	1	\N	1	f	\N	\N	\N	t	PROF-ONEC-CPK-2026-0002	\N	\N
47adab8d-30f7-4b57-8aac-225b6ebd0b71	\N	expert_comptable	0ce71fa9-5d1a-4b50-bd5b-4505a0445665	\N	\N	650.00	650.00	0.00	non_paye	cash	\N	2026-04-08 00:00:00+00	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-04-08 14:35:42.988499+00	130	650.00	USD	1.0000	f	\N	\N	1	I.7.3	Location Espace bureau	Location salle de réunion	CAISSE	1	\N	1	f	\N	\N	\N	t	PROF-ONEC-CPK-2026-0003	\N	\N
03e7c4db-9129-42ef-8a2c-ceb0e161b769	REC-ONEC-CPK-2026-A0051	expert_comptable	0ce71fa9-5d1a-4b50-bd5b-4505a0445665	\N	test	49.98	49.98	49.98	complet	cash	\N	2026-04-08 14:37:18.966539+00	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-04-08 14:07:51.481774+00	130	49.98	USD	1.0000	f	\N	\N	1	I.7.3	Location Espace bureau	Location salle de réunion	CAISSE	1	\N	1	f	\N	\N	\N	f	PROF-ONEC-CPK-2026-0001	2026-04-08 14:37:18.966539+00	03e7c4db-9129-42ef-8a2c-ceb0e161b769
96ace1b9-fcb1-45db-b844-ae9ec6a096dc	REC-ONEC-CPK-2026-A0052	expert_comptable	6b310257-e821-4a8b-8177-6437c01a2d1d	\N	test	200.00	200.00	200.00	complet	cash	\N	2026-04-13 00:00:00+00	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-04-13 09:10:01.212619+00	105	200.00	USD	1.0000	f	\N	\N	1	I.2.2	Autres organismes	Pénalité absence formation obligatoire	CAISSE	1	\N	1	f	\N	\N	\N	f	\N	2026-04-13 00:00:00+00	\N
\.


--
-- Data for Name: experts_comptables; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.experts_comptables (id, numero_ordre, nom_denomination, type_ec, categorie_personne, statut_professionnel, sexe, telephone, email, nif, cabinet_attache, nom_employeur, raison_sociale, associe_gerant, import_id, active, created_at) FROM stdin;
e832e8a8-62c6-4034-bdde-7fa8d79d1499	EC/18.00055	BUALELU MUKEBA Celestin	EC	Personne Physique	En Cabinet	M	+243998178695	bualelucelestin@gmail.com	\N	K2M PARTNERS SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.029479+00
5a89c377-158b-4a0c-b3c6-f703b124e055	EC/16.00056	BUKASA WA BUKASA Cedrick	EC	Personne Physique	En Cabinet	M	+243815215327	cedric.bukasa@gmail.com	\N	BMA SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.037514+00
de45bf9c-f858-4130-82d4-2ec003329fc1	EC/16.00068	CIZUBU CIAMPOYI Alidor	EC	Personne Physique	En Cabinet	M	+243999905021	fagefi@yahoo.fr	\N	FAGEFI SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.039418+00
893a7c3d-a983-4243-bc55-70f4bffc524f	EC/16.00070	DHENA NDAHORA Joseph	EC	Personne Physique	En Cabinet	M	+243818135566	josephdhena@agec-rdc.com	\N	AGEC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.040969+00
5cef8ec4-028b-4940-a413-0e6703a5caa2	EC/25.00605	DIAMBOKO NDONZUAU Flory	EC	Personne Physique	En Cabinet	M	+243820066556	floridiamboko@gmail.com	\N	FORVIS MAZARS RDC	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.04249+00
f96a3875-7529-40be-86e9-177b4e316339	EC/24.00584	DILU NZINGA Yann	EC	Personne Physique	En Cabinet	M	+243814467918	yanndilu@gmail.com	\N	KPMG RDC SA	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.044208+00
e8cc5a8e-951c-4891-a7b7-26ae89a343d8	EC/18.00077	DIMELO KISOLO Mike	EC	Personne Physique	En Cabinet	M	+243972003910	mike.dimelo@fonarev.cd	\N	INSP SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.045759+00
f0a6c1f0-1833-40d0-af82-0bf55fe53ad6	EC/16.00079	DONGO LISIKA Gauthier	EC	Personne Physique	En Cabinet	M	+243815124970	gdongo@corexrdc.com	\N	COREX SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.04767+00
f1fb71d6-3934-432a-bd53-61bad9f3260c	EC/18.00074	DYKASSADYBY MOUENALONJ Donatien	EC	Personne Physique	En Cabinet	M	+2430821280259	donadykr@yahoo.fr	\N	CRM Sarl	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.049473+00
5765e3ba-dc6d-40cb-b681-075a64bdf019	EC/18.00080	EKOFO BOONA INGANGE Antoine Roger	EC	Personne Physique	En Cabinet	M	+243816081250	ekofoantoineroger@yahoo.fr	\N	PDLC SARLU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.051228+00
dc902121-f1fd-4275-a39f-6396880ddc35	EC/18.00082	ELANGA MONGA MBULI MARCUS	EC	Personne Physique	En Cabinet	M	+243994495452	marcuselanga30@gmail.com	\N	EY RDC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.052549+00
6b310257-e821-4a8b-8177-6437c01a2d1d	EC/16.00086	FATAKI NTULA Zephyrin	EC	Personne Physique	En Cabinet	M	+243973892181	zephirin.fataki@yahoo.fr	\N	HELIAN CONSULTING SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.053948+00
e6c74e11-7f7c-4e15-8fcc-1ac40949e230	EC/16.00089	FOKO TOMENA André	EC	Personne Physique	En Cabinet	M	+243818126663	andre.foko@aftassocies.com	\N	AFT SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.05537+00
d1c4297d-c8a8-427d-833c-731d6462c0eb	EC/25.00607	FUNDI KADIBANGA Benjamin	EC	Personne Physique	En Cabinet	M	+243972615306	benjamin.fundi@cd-insp.com	\N	INSP SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.056768+00
3b24545b-b8e4-4638-86c5-be40a08af3f2	EC/16.00091	FURUME NTALE Benito	EC	Personne Physique	En Cabinet	M	+243829199974	benitofur@gmail.com	\N	LABOTTE FIDUCIA SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.058334+00
dcbf9b74-54b8-45f8-8355-88a624eeab1a	EC/16.00093	FWAMBA BULOBO Jean-Marie	EC	Personne Physique	En Cabinet	M	+243819970599	fwambagm962@gmail.com	\N	ECS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.059374+00
a4fb779f-c12b-4a37-bebb-fe51dcf67dae	EC/17.00098	IFEKA BONKOMO Nelson	EC	Personne Physique	En Cabinet	M	+243817103703	nelson@ibnsarl.com	\N	IBN SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.060362+00
d18583d0-251b-4844-9764-2b9aec560231	EC/17.00100	ILEO BOTINDO Madeleine	EC	Personne Physique	En Cabinet	F	+243990317590	madeleineileo@yahoo.fr	\N	SECOFIA SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.061382+00
9ce1d819-db01-4539-aed2-64361c33a44e	EC/16.00105	ITULAMYA BAZIKA Deo Gracias	EC	Personne Physique	En Cabinet	M	+243907281024	bazikadeo@gmail.com	\N	CECAF SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.06302+00
210b6d2b-01d0-47f2-99e1-a0af151b0e1b	EC/19.00106	IZE KANIKI Johnny	EC	Personne Physique	En Cabinet	M	+243816144948	izejohnny01@yahoo.fr	\N	SECAF SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.064777+00
0a0751fc-96e4-44e2-b05a-8ac50a982f86	EC/19.00108	KABAMBA MBUSU Michel	EC	Personne Physique	En Cabinet	M	+243999920518	mkabamba@corexrdc.com	\N	COREX Sarl	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.066203+00
670bf907-abce-44d1-ae2f-7f3e5f1f1b17	EC/16.00112	KABEMBA BARAKA	EC	Personne Physique	En Cabinet	M	+243993435296	baraka.kabemba@cd.ey.com	\N	EY RDC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.067614+00
1a7a59ab-2474-4b84-9f52-0e472e3e9c5c	EC/17.00539	KABENGELE M'PIEN LEY	EC	Personne Physique	En Cabinet	M	+243998403072	kabeley990@gmail.com	\N	CARECO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.068755+00
030cba5d-197b-4c6c-a41f-4cfe8a642915	EC/17.00562	KABEYA KABAMBI Polycarpe	EC	Personne Physique	En Cabinet	M	+243818132880	p.kabeyakabambi@gmail.com	\N	GINEX SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.069752+00
7f569289-dc06-459c-87fa-b62311e6fcd4	EC/16.00116	KABEYA MUBENGA Blaise	EC	Personne Physique	En Cabinet	M	+243978561342	blaise_kabeya@yahoo.fr	\N	EY RDC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.071012+00
59a03f1f-41ae-47c4-88f4-9fe863967c06	EC/20.00118	KABONGO CIKOLA Dieudonné	EC	Personne Physique	En Cabinet	M	+243893902530	ciko2008@ymail.com	\N	RMB & ASSOCIES	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.07202+00
aa713535-6581-4df8-817c-ebe70d2a8fc1	EC/16.00120	KABUNDA MUSASA Bruno	EC	Personne Physique	En Cabinet	M	+243815090576	brukabmuss1@yahoo.com	\N	BKM COREF & ASSOCIES Sarl	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.073169+00
a4aa8975-3754-4e1b-9fe5-f942f256d09c	EC/16.00122	KABWELA WA KABWELA Didier	EC	Personne Physique	En Cabinet	M	+243812577497	d.kabwela@delpartners.com	\N	DEL PARTNERS SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.074234+00
1929141a-1594-4a92-89cd-9c44a6891ab2	EC/16.00125	KAKESSE TSHIKE MUANA Emile	EC	Personne Physique	En Cabinet	M	+243855732169	tshikemuana@yahoo.fr	\N	AMC PARTNERS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.075281+00
fc5b7198-d615-4d18-a8f8-7c663ae9f2d5	EC/17.00128	KAKULE LWANZO Claude	EC	Personne Physique	En Cabinet	M	+243998273107	ccpaccaf@gmail.com	\N	CCPA SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.076745+00
eb29490e-b36b-49e8-a6ab-49d55eccc621	EC/16.00130	KALAMBAY NYINDU Raphaël	EC	Personne Physique	En Cabinet	M	+243971798907	nyindu@yahoo.fr	\N	E-MAC SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.078228+00
9f223588-1451-4ae4-a5cb-65d038d21048	EC/16.00136	KAMBAJA MUBALAMATA Bruno	EC	Personne Physique	En Cabinet	M	+243818112710	brunokambaja@gmail.com	\N	CAAT SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.079875+00
ea0495aa-773f-4fc1-a122-57085e7ee2fa	EC/16.00142	KAMPANZU MBEKU Cherif	EC	Personne Physique	En Cabinet	M	+243816603731	kampanzuexpert@gmail.com	\N	CBM SARLU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.082417+00
ee1be321-d4e7-4a67-b54e-3ec8c68038a1	EC/19.00147	KANINDA MUKENA Carlos	EC	Personne Physique	En Cabinet	M	+243820677212	ck@kmc-cabinet.com	\N	KMC SASU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.084423+00
6f38e921-8bf8-4331-97e1-54f2a0e99e81	EC/24.00586	KAPUKA LESSY Don Christ	EC	Personne Physique	En Cabinet	M	+243821700499	kapukalessi@gmail.com	\N	DELOITTE SERVICES SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.086277+00
40180ab0-fb35-439c-a38c-8453a5559da8	EC/18.00164	KASHALE NGOY Chris	EC	Personne Physique	En Cabinet	M	+243816904849	kashalechris@gmail.com	\N	JMB CONSULTING SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.087642+00
8123a56b-b2c0-4a8a-9824-16be391dadca	EC/20.00165	KASILEMBO BUJINGA Josué	EC	Personne Physique	En Cabinet	M	+243816896777	jkasilembo@gmail.com	\N	JK AUDIT SARLU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.089119+00
47683003-8c18-4168-8aa9-54dcd50a439b	EC/20.00166	KASONGO BATUSSE Peter	EC	Personne Physique	En Cabinet	M	+243811654496	ptrkasongo2@gmail.com	\N	FIGEFITECH SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.091249+00
965bbf8d-aa50-4657-9f6f-6e5a412fbc9c	EC/17.00167	KASONGO DIEMU Dieudonné	EC	Personne Physique	En Cabinet	M	+243855281200	kamibafor@gmail.com	\N	OKM Consulting SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.092911+00
95e38163-c093-4e3c-a1ae-29661148377f	EC/17.00171	KAYAMBA KAYEMBA Marco	EC	Personne Physique	En Cabinet	M	+243998279301	kayambamarco@yahoo.fr	\N	CAUDITEC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.094578+00
07c48553-224e-44d3-8b9a-434370f83f4e	EC/25.00613	KAYEMBE KABONGO Kennedy	EC	Personne Physique	En Cabinet	M	+243819427070	kenkayembe@yehoo.fr	\N	AAT SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.095708+00
c87ba7ef-59bd-4c09-967a-e9f5e6a9f674	EC/19.00175	KAZADI KOLELA Rocher	EC	Personne Physique	En Cabinet	M	+243998954565	rocherkazadi@gmail.com	\N	AGESFO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.096976+00
1af71950-37a6-4f90-bcbb-f50738ef1df9	EC/16.00184	KIMBEMBE KIAMVU Simon	EC	Personne Physique	En Cabinet	M	+243999916552	s.kimbembe@mmpartnerscongo.com	\N	MMPARTNERS CONGO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.101957+00
f0873d85-fd42-406a-86e0-01ce7ab54757	EC/17.00193	KITENGE KAPENGA Norbert	EC	Personne Physique	En Cabinet	M	+243999947393	norbertkitenge@yahoo.fr	\N	AMC PARTNERS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.10347+00
57962cde-d36d-401a-9363-38144504d577	EC/16.00198	KOMBA MUNGANGA Alain	EC	Personne Physique	En Cabinet	M	+243998087847	alainmunganga@gmail.com	\N	CAEC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.105103+00
4d8c8f3d-8009-4d40-bb36-ba6653ebe07b	EC/18.00203	KUFUTAMA KOY Kafaire	EC	Personne Physique	En Cabinet	M	+243816899788	kafairekoy@gmail.com	\N	CACG SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.106523+00
f77759ec-8b91-427a-b389-c2ba5d97c01e	EC/17.00205	KUSAMA MYESI Gabriel	EC	Personne Physique	En Cabinet	M	+243998379602	kusamamyesi@gmail.com	\N	JASBI SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.10759+00
567e8126-6a29-4405-88e3-09111b9bde62	EC/18.00209	LANDU NZINGA Bill	EC	Personne Physique	En Cabinet	M	+243816879015	landubill77@gmail.com	\N	AMS SARL CONSULTANTS SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.108597+00
9d2c99f4-42d9-424a-95ec-ee6f6196272e	EC/18.00214	LIGBAKELO MAYKPELE Samy	EC	Personne Physique	En Cabinet	M	+243818148848	ligbakelo@yahoo.fr	\N	CTRS SARLU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.11001+00
bdc45b00-f365-45d6-8adf-ad5e8dc8b2d3	EC/16.00215	LIKAMBO KWADJE Dieudonné	EC	Personne Physique	En Cabinet	M	+243998126186	dieudonnelikambo@yahoo.fr	\N	AUDIGEC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.111262+00
dd2f8fd3-a197-41b5-b323-2f5b23317b58	EC/16.00218	LOKESA SUAMUNU Thierry	EC	Personne Physique	En Cabinet	M	+243899501186	thierry_lokesa@yahoo.fr	\N	T.L PARTNERS-CONGO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.112695+00
d848c283-053a-421e-bfe8-4e2b7c66487b	EC/16.00223	LUKIMUENA KUBA Samuelson	EC	Personne Physique	En Cabinet	M	+243819934759	s.lukimuena@cornerstone-cd.com	\N	CFI SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.114062+00
066295f2-2f68-49b0-a912-8155adb5d023	EC/20.00225	LUMANI NGOY Paul	EC	Personne Physique	En Cabinet	M	+243970808709	paul.lumani@cd.ey.com	\N	EY RDC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.116309+00
91e1c772-9743-42f1-abce-966b0ee64386	EC/17.00229	LUMU TCHATA Joseph	EC	Personne Physique	En Cabinet	M	+243815981162	jlumu@yahoo.fr	\N	New ANOU CONSULTING SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.117944+00
b7719a4f-7756-4df0-94e5-846ffeebeb75	EC/16.00231	LUNGANGI KITUNDU Françoise	EC	Personne Physique	En Cabinet	F	+243998046513	flungangi@drcexpertises.net.	\N	DEX SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.119149+00
de2badb9-3b78-4219-945c-ab610c108447	EC/16.00232	LUNGONZO MBUY François	EC	Personne Physique	En Cabinet	M	+243998139161	flungonzo@gmail.com	\N	JVL SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.120149+00
efcd18ea-d3be-4943-a9ed-d75dc7331b07	EC/16.00236	LUVUEZO BIKINDU Simon	EC	Personne Physique	En Cabinet	M	+243998242892	sluvuezobikindu@yahoo.com	\N	LMN & ASSOCIES SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.122141+00
0dbbfd23-9a46-419d-b9eb-9f720de3ab3d	EC/16.00243	MABATA NTANTU Nico	EC	Personne Physique	En Cabinet	M	+243828504935	nmabata@kpmg.cd	\N	KPMG RDC SA	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.124197+00
bc82b22c-d4ee-4016-859e-5017f851898b	EC/16.00246	MABIALA MAVINGA Jules	EC	Personne Physique	En Cabinet	M	+243999907257	m.jules@mmpartnerscongo.com	\N	MMPARTNERS CONGO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.125833+00
8b539e3e-d640-4dc0-95e4-5b2901725579	EC/16.00247	MABIZA MAKAYI Delord	EC	Personne Physique	En Cabinet	M	+243971050212	delord.mabiza@bdo-ea.com	\N	BDO AUDIT SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.126937+00
65314abc-4ab1-423e-8750-fc18d9a68fb7	EC/18.00248	MABULU BENANKAZI LOLO Jean-Pierre	EC	Personne Physique	En Cabinet	M	+243820831745	lolojpmabulu@gmail.com	\N	CAAF SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.127933+00
cb56664e-7aa7-4ef3-9664-6652b1a23dff	EC/17.00252	MAKENGO MANUNGA Emmanuel	EC	Personne Physique	En Cabinet	M	+243810549470	emmanuelmakengo2@yahoo.fr	\N	AGEC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.128924+00
51a6d07e-71fd-4c6a-b812-28a71e910e75	EC/25.00615	MAKONDA TEKASALA Blanchard	EC	Personne Physique	En Cabinet	M	+24385119389	tekamakonda@gmail.com	\N	J.K. AUDIT SARLU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.131075+00
ee84c944-0862-4465-a0ef-d9465444cd56	EC/16.00253	MAKUNGA NIANGI Max Simon	EC	Personne Physique	En Cabinet	M	+243820019906	max_mkga@befac-mkga.com	\N	BEFAC MKGA & Associés SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.133283+00
7c1e1783-ec8f-47a0-bb9c-e0871b62f196	EC/18.00259	MAMBU LUYALU MUSONGA'KEL Egide	EC	Personne Physique	En Cabinet	M	+243824682000	egide.mambu@africamel.net	\N	ECCE SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.134661+00
84ad9e00-8445-411d-b7dc-7898e87bc371	EC/16.00261	MAMPASI MABAYA Dieudonné	EC	Personne Physique	En Cabinet	M	+243817007176	dieudonne.mampasi@strong-nkv.cd	\N	MGI STRONG NKV SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.136504+00
b01ec74a-cf48-48a2-abf1-7b7251b67912	EC/17.00262	MAMPUYA KALENGA Robert	EC	Personne Physique	En Cabinet	M	+243817925079	mampuya.robertk@gmail.com	\N	TECPRO EXPERTISE SARLU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.137945+00
8912726f-443d-4b23-ad06-2c52620672df	EC/16.00264	MANKENDA NANSINA Sébastien	EC	Personne Physique	En Cabinet	M	+243898975959	nmankenda@hotmail.com	\N	K2M PARTNERS SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.139143+00
d53f392a-b5c3-47ae-9662-4d5379cba185	EC/16.00270	MASIALA FINDUO Blaise	EC	Personne Physique	En Cabinet	M	+243816866913	masialab@gmail.com	\N	F COMPTA SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.140081+00
475c0a46-f35e-4d5b-8b8e-76e8dae28bd6	EC/16.00272	MATAKA BILANGA Paul	EC	Personne Physique	En Cabinet	M	+243824557661	merjesmataka@gmail.com	\N	RMC-MAT EXPERTISES SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.141079+00
e9ae5975-cea5-4a01-a4bb-ff5c5c8009f6	EC/20.00275	MATONDO MAVUANDA José	EC	Personne Physique	En Cabinet	M	+243824226879	jose.matondo@strong-nkv.cd	\N	MGI STRONG NKV SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.142051+00
0e9690c9-b838-4150-bc0d-98ec28e68690	EC/17.00276	MATONDO MIOKO Jean	EC	Personne Physique	En Cabinet	M	+243828293887	mickmatondo1@yahoo.fr	\N	AAS SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.143713+00
4f6064b8-8dfa-4071-8728-ce9a02ac166e	EC/16.00277	MATUNGA KAPONGO Ted	EC	Personne Physique	En Cabinet	M	+243813151513	tedmatunga@gmail.com	\N	BDO AUDIT SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.146133+00
a26f7f45-6e4d-4987-8100-e1c0c4fa58cd	EC/19.00278	MATUTALA KULA PITSHOU	EC	Personne Physique	En Cabinet	M	+243899418535	matutalakula@yahoo.fr	\N	COFICA SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.148548+00
8f088574-c711-4fad-b76f-059aa7d75bf3	EC/16.00281	MAVUNGU MAVWANGA Gervais	EC	Personne Physique	En Cabinet	M	+243859998004	gmavungu@deloitte.fr	\N	DELOITTE SERVICES SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.150056+00
ec405476-d1e5-42b2-a5fe-7c25651a92d8	EC/19.00282	MAWALA NYIMI Antoine	EC	Personne Physique	En Cabinet	M	+243999959958	manyimi@hotmail.com	\N	AMN'S SARL Sarl	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.151102+00
b6f4e370-0da1-4e14-8114-d9ff8f88c240	EC/19.00283	MAWANGU NDOLUVUALU Anderson	EC	Personne Physique	En Cabinet	M	+243998397801	anderson@taaex.net	\N	TAAEX SARLU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.152121+00
a59d974d-cff6-48a8-8248-08c7b83bc118	EC/17.00286	MAYI KAYIMBONGE Désiré	EC	Personne Physique	En Cabinet	M	+243816432674	desimayi@gmail.com	\N	CASOL SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.153126+00
e22e061d-91e6-44d6-af4b-2093c4a8524a	EC/16.00293	MBATSHI TOVO Blaise	EC	Personne Physique	En Cabinet	M	+243813391217	blaise.mbatshi@bdo-ea.com	\N	BDO AUDIT SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.154239+00
f00ffe6a-1f58-43ca-a215-c8181448f90e	EC/16.00294	MBAYA KANGOMBA MBABU Maurice	EC	Personne Physique	En Cabinet	M	+243819847478	mauricembaya80@gmail.com	\N	CAAT SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.155199+00
42b02745-0c5d-4a01-a030-849701f8b8b9	EC/16.00295	MBAYA MBAYA Célestin	EC	Personne Physique	En Cabinet	M	+243995901291	celestin.mbaya@secofic.cd	\N	SECOFIC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.156332+00
2f94f4d9-6a2a-44df-b7ef-1471e7dd377f	EC/18.00553	MBODO BUASA Anaclet	EC	Personne Physique	En Cabinet	M	+243813170409	anaclet.secofic@gmail.com	\N	ATAH SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.158134+00
73a61bc4-6f0b-4ea7-b92e-d6c3c9ee623a	EC/16.00297	MBOYO NKULI Jean Rigobert	EC	Personne Physique	En Cabinet	M	+243814037383	jrmboyodigo@gmail.com	\N	SORECA SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.160767+00
fe955790-3a8c-44b1-afab-f8c7c382cb62	EC/17.00300	MBUMBA MBUDI Joseph	EC	Personne Physique	En Cabinet	M	+243998686125	josembumba@yahoo.fr	\N	JMB CONSULTING SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.161907+00
a925dd79-d743-4f88-ab5c-46be92d7d12c	EC/17.00302	MBUWA MONGELE Cyrille	EC	Personne Physique	En Cabinet	M	+243815208327	c.mbuwa@cpmconsultingsarl.com	\N	CPM CONSULTING SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.163217+00
23881bb2-6866-4831-8285-ccc2552f5ad7	EC/16.00305	MENA NKUABILEKO Nadine	EC	Personne Physique	En Cabinet	F	+243898953548	nadine.mena@bdo-ea.com	\N	BDO AUDIT SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.16445+00
0a06d0e2-25a1-49a3-b9ad-f9f1221c5702	EC/19.00308	MFUMUMPOKO MONSEMPO Eddy	EC	Personne Physique	En Cabinet	M	+243818127630	e.mfumu@mmpartnerscongo.com	\N	MMPARTNERS CONGO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.166339+00
2f59c370-3a92-4895-b15b-9f6f5e4af9ce	EC/19.00310	MINGASHANGA MIKOBI Emmanuel	EC	Personne Physique	En Cabinet	M	+243851727465	mingaemma@hotmail.com	\N	MMPARTNERS CONGO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.167716+00
6b31a9c3-3217-4d4f-9eb4-fd7eaf22cb4f	EC/24.00593	MOLELE BOFOTOLA Gabriel	EC	Personne Physique	En Cabinet	M	+243822848422	molelebofotola@outlook.fr	\N	MGI STRONG NKV SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.168852+00
cc696b8e-2bd8-43d2-b526-38179de34b56	EC/16.00318	MPANYA KI'EPENDA Nyckain	EC	Personne Physique	En Cabinet	M	+243998745885	mpanyanyckain@yahoo.fr	\N	FAGEFI SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.170039+00
5c09922f-357f-40d3-97b8-69323c2da56e	EC/16.00321	MPOP AWUNG Florent	EC	Personne Physique	En Cabinet	M	+243827275187	florentmpop45@gmail.com	\N	EMERGENCE CONSULTING SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.17178+00
6e7ce52e-5e04-42a9-96c5-cd7d11a3b3b9	EC/19.00322	MUAKA MULENDA Gerard	EC	Personne Physique	En Cabinet	M	+243815261939	muakagerard18@gmail.com	\N	SECFA SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.173143+00
14a93edd-ea6c-43cc-a9a3-f331074af2cf	EC/17.00324	MUAMBA TSHILUMBA Simon	EC	Personne Physique	En Cabinet	M	+243995961063	simon_master@yahoo.fr	\N	SMA	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.174181+00
e655cd5e-586a-48fc-aa14-76ca4cc21a5c	EC/19.00342	MUKAWA NINGA Nanou	EC	Personne Physique	En Cabinet	M	+243811918798	mukawananou20@gmail.com	\N	DACO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.175415+00
629b6a30-0856-4e33-8a7f-95dfcee8bf67	EC/18.00343	MUKE NTAMWANGA Grâce	EC	Personne Physique	En Cabinet	M	+243818281698	mukegracentamwa@gmail.com	\N	BDO AUDIT SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.176543+00
5287d614-9864-4449-8d4f-d23f699adf74	EC/17.00346	MUKENDI LUTULU François	EC	Personne Physique	En Cabinet	M	+243810492183	mukendifrancois13@gmail.com	\N	ACOFIG SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.177599+00
480b5877-aec5-4d63-bed8-bbd17979ae35	EC/16.00350	MUKOTA MUTEBA MBAYO	EC	Personne Physique	En Cabinet	M	+243978003703	m.mukota@mmpartnerscongo.com	\N	MMPARTNERS CONGO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.178559+00
d2613dbb-179c-4b96-95d8-533bcb1ef82c	EC/19.00353	MULEMVO BIDUAKA Bienvenu	EC	Personne Physique	En Cabinet	M	+243821860057	bienvenubiduaka2@gmail.com	\N	CREDES EXCO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.179591+00
01ef81b8-8a83-4a29-a40b-1186f49c7c63	EC/16.00360	MUNKENI KIEKIE Eliane	EC	Personne Physique	En Cabinet	F	+243810558370	eliane.mk@hotmail.fr	\N	ACF SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.180658+00
9dc60f03-5ee0-4bb6-a04e-2860e1362011	EC/16.00366	MUSOLE MWANAMUPENZI Moïse	EC	Personne Physique	En Cabinet	M	+243816111705	musolemoise2019@gmail.com	\N	GMC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.182891+00
e7353d9b-c2c4-44f5-8694-c5e1a18497cf	EC/18.00369	MUTANDA NGOY-MUANA Jean-Antoine	EC	Personne Physique	En Cabinet	M	+243812037727	jean.antoine.mutanda@cd.ey.com	\N	EY RDC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.185014+00
d8fde4eb-d4da-403b-9fc0-4057c5ab9c33	EC/24.00594	MUTANGILAYI MUTEBA Yorick	EC	Personne Physique	En Cabinet	M	+243812311068	ymutangilay@gmail.com	\N	BELKAS GROUP SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.186622+00
62757a1c-dd33-445c-a778-bba112161a1d	EC/19.00371	MUTEBA MUKENDI Yollande	EC	Personne Physique	En Cabinet	F	+243998452332	myollande@gmail.com	\N	DACO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.187662+00
e6e62571-9908-49e7-a920-45b477f90272	EC/20.00556	MUTOMBO NASALININI Yves	EC	Personne Physique	En Cabinet	M	+243812211828	yves213@gmail.com	\N	CAUDITEC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.188677+00
e7d16ca4-5ea0-4e70-8261-6eeb61226662	EC/17.00377	MUYEKA KAZANGA Leki	EC	Personne Physique	En Cabinet	M	+243858514660	l.muyeka@z-finances.com	\N	GMC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.190002+00
52c82095-5832-4adf-9e88-5828abe2ac57	EC/24.00595	MUZABA MAMBAMBA Eric	EC	Personne Physique	En Cabinet	M	+243811947418	emuzaba@kpmg.cd	\N	KPMG RDC SA	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.190978+00
19344edb-ca8b-4491-bba8-e5771b9de75a	EC/16.00473	MWANANZAMBI Daniel Ephraïm	EC	Personne Physique	En Cabinet	M	+243824538441	d.mwananzambi@mmpartnerscongo.com	\N	MMPARTNERS CONGO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.192024+00
52e80229-ab9a-4b43-bc77-02dd18f7fc98	EC/16.00387	NDANGI NDANGANI Théophile	EC	Personne Physique	En Cabinet	M	+243823573788	tndanguy@gmail.com	\N	FORVIS MAZARS RDC	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.193288+00
40effd13-f4ba-4932-a5c9-de736042ef92	EC/19.00391	NDOKO FUMU Odon	EC	Personne Physique	En Cabinet	M	+243814847070	odonndoko8@gmail.com	\N	ONF SARLU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.194431+00
11e6189d-7318-4666-8231-af5b5a59a54e	EC/16.00392	NDONGO NTIERE Gaby	EC	Personne Physique	En Cabinet	M	+243854348339	ndongogaby30@gmail.com	\N	NN SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.195641+00
87c63f5d-83e5-4954-a3d3-8626214ed955	EC/18.00393	NDUMB MBANG Didier	EC	Personne Physique	En Cabinet	M	+243819591098	didiermbang@gmail.com	\N	B.E SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.196989+00
8a41011f-3ff2-419f-9386-b4a92521da67	EC/16.00394	NDUSHA BIRHAFANWA Xavier	EC	Personne Physique	En Cabinet	M	+243815086052	ndusha@quitusconsult.cd	\N	QC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.199022+00
9260926d-6695-4822-b131-c5fbf7b8bd5f	EC/16.00397	NGANDU LHOME Benjamin	EC	Personne Physique	En Cabinet	M	+243815295713	benjamin.ngandu@bdo-ea.com	\N	BDO AUDIT SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.20058+00
27e463f8-68d0-47a6-b59c-8dea142d4a56	EC/16.00400	NGANDU WA NGANDU Jean-Marie	EC	Personne Physique	En Cabinet	M	+243818145122	jean-marie.ngandu@caf-consulting.com	\N	CAF CONSULTING SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.202068+00
322f7d3c-e2cc-427d-8684-a4e1aceb599c	EC/16.00404	NGOIE WA KASONGO Augustin	EC	Personne Physique	En Cabinet	M	+243818130580	cecaf_nwk@yahoo.fr	\N	CECAF SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.203448+00
17816d60-90fe-4369-9c51-78c3e0ae5d57	EC/16.00408	NGOYI KABEMBA Benjamin	EC	Personne Physique	En Cabinet	M	+243819593692	ngoyibenjamin11@gmail.com	\N	LACOURCELLE SARLU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.204629+00
c326db00-c2b6-4934-8f5a-b9112785d5ae	EC/18.00409	NGUBI LUTETE Mac	EC	Personne Physique	En Cabinet	M	+243972009548	cmngubi@gmail.com	\N	DWAC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.205769+00
2f6753a0-7fac-4913-8adf-18088cbd04bd	EC/17.00414	NKENKO NDOMBELE Blaise	EC	Personne Physique	En Cabinet	M	+243815792319	blaisenkenko@gmail.com	\N	ACF SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.206946+00
e62aca02-7919-4208-94a2-d041ab2ca874	EC/19.00417	NKOLELA KABULU Joel	EC	Personne Physique	En Cabinet	M	+243822992661	joelnkolela@yahoo.fr	\N	PDLC SARLU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.207941+00
081ca2df-6daa-48c7-b311-e54b6b96424f	EC/25.00603	NKUANGA MBUINGA Jean Paul	EC	Personne Physique	En Cabinet	M	+243999309712	jeanpaulnkuangambuinga@gmail.com	\N	LMN & ASSOCIES SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.208949+00
461b5cc9-b979-4024-a162-7aab8545ac5e	EC/16.00420	NKUMBA LUMFUAKIADI Francis	EC	Personne Physique	En Cabinet	M	+243976059437	francis.nkumba@cd-insp.com	\N	INSP SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.209973+00
6723fc8d-2bcd-4e3e-b827-9e39e3dad5e2	EC/16.00422	NKUVU WENA Daddy	EC	Personne Physique	En Cabinet	M	+243894506861	daddy.nkuvu@strong-nkv.cd	\N	MGI STRONG NKV SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.211891+00
4ab729d7-218c-4c19-9d4e-cc55a05435b3	EC/16.00423	NKUVU-A-MBINDA WENA Danny	EC	Personne Physique	En Cabinet	M	+243818117654	danny.nkuvu@strong-nkv.cd	\N	MGI STRONG NKV SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.213295+00
6f67b03b-0590-4aa2-b8fc-31df2a920af6	EC/16.00425	NSAYI LUKOMBO Rubens	EC	Personne Physique	En Cabinet	M	+243999124915	rubensentreprise@gmail.com	\N	CCS SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.214665+00
0c63485a-2bcc-4f23-8d76-f6f653b5a284	EC/24.00598	NSIKU DIASIVI Jonathan	EC	Personne Physique	En Cabinet	M	+243972615307	jonathan.nsiku@cd-insp.com	\N	INSP SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.216147+00
cc31e00b-1304-4075-acaf-f9650a0795a6	EC/16.00427	NSILULU BAHELELE Gabriel	EC	Personne Physique	En Cabinet	M	+243998921784	bureau_cefao@yahoo.fr	\N	CEFAO	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.217477+00
0a5cd707-aa5c-4764-baa7-bab355ca7f93	EC/16.00435	NTUMBA MPUTU Odilon	EC	Personne Physique	En Cabinet	M	+243824448070	odilontumba@ecrrdc.com	\N	ECR SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.218469+00
ed62d23d-ba73-4e7b-983c-c023209b62e6	EC/19.00437	NTUMBA MUTAMBAYI Claude	EC	Personne Physique	En Cabinet	M	+243828504968	claudenntumba@gmail.com	\N	KPMG RDC SA	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.219464+00
bfa3041b-92e5-46a2-801a-f59ce26a674c	EC/25.00624	NYOK KABUL SADEL	EC	Personne Physique	En Cabinet	M	+243813378264	sadelnyok@gmail.com	\N	DELOITTE SERVICES SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.220519+00
1a12b25d-a877-4661-8e4b-e368bc80032a	EC/16.00441	NZAILU BASINSA Benjamin	EC	Personne Physique	En Cabinet	M	+243998188585	benjamin.nzailu@abncd.com	\N	ABN SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.221668+00
f5b8b832-8f5d-48ba-b25b-835748b85f9c	EC/24.00599	NZAILU NSIMBA Herbert	EC	Personne Physique	En Cabinet	M	+243820407403	hnzailu@gmail.com	\N	ABN SAS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.222612+00
73a559d9-5682-4d22-b68e-936e443bf3a3	EC/19.00448	NZITA TSASA Gary	EC	Personne Physique	En Cabinet	M	+243811837388	nzitagary@gmail.com	\N	DACO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.223568+00
43af04b3-ed8c-413c-b681-45b54bf44c42	EC/16.00449	NZOIMBENGENE LUYINDULA Bob David	EC	Personne Physique	En Cabinet	M	+243859998032	bnzoimbengene@deloitte.fr	\N	DELOITTE SERVICES SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.225365+00
5c4b8764-e641-4026-ada8-45006d964ade	EC/16.00454	OKENDE MBUNGU Adolphe	EC	Personne Physique	En Cabinet	M	+243810837185	adolphe.okende@lapradellec.com	\N	PDLC SARLU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.226795+00
916a9938-955c-47a0-a22a-0cccd19514a3	EC/17.00459	OPOKI YAMO Mathieu	EC	Personne Physique	En Cabinet	M	+243894297246	opokyam@gmail.com	\N	SECOFIA SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.227828+00
99db0279-7fed-4f1f-810e-b0e8f5205eea	EC/19.00460	OVO YATUIKWAMO-FUKIAU Ranield	EC	Personne Physique	En Cabinet	F	+243998946925	oranield@gmail.com	\N	R.O&PARTNERS	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.229272+00
24f82547-80a4-4c55-be75-19cd00ca30a8	EC/17.00465	PATI NDOMPETELO Jean-Marie	EC	Personne Physique	En Cabinet	M	+243818143839	jeanmariepati2004@yahoo.fr	\N	AAT SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.230497+00
7582aa7b-1471-4d8c-97cc-05e121af3c2f	EC/16.00466	PAY-PAY  MULINDU Pascal	EC	Personne Physique	En Cabinet	M	+243999928202	paypay_ppm@yahoo.fr	\N	ACGC SARLU	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.23146+00
1387e0ca-1961-4ff1-8e76-747a71dc814c	EC/16.00467	PFINGU NSUAMI Jean-Pierre	EC	Personne Physique	En Cabinet	M	+243817005092	jppfingu@jpp-associes.com	\N	JPP & Associés SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.233504+00
05520b5a-a877-4df4-a21e-51f90b779328	EC/19.00468	PFINGU SIMBU Rosette	EC	Personne Physique	En Cabinet	F	+243814444705	rpfingu@jpp-associes.com	\N	JPP & Associés SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.234656+00
fb3dccd8-9cad-459f-aad0-6eeeb712bdf3	EC/19.00470	PHANZU NLANDU Philippe	EC	Personne Physique	En Cabinet	M	+243818149744	pphanzu@gpopartners.com	\N	GPO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.235727+00
aa0aa7d4-e28b-4e5e-94e1-037d14469bf1	EC/25.00623	PUNGA ALANGA Joël	EC	Personne Physique	En Cabinet	M	+243826808889	joelpunga1@gmail.com	\N	DELOITTE SERVICES SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.237344+00
f73cc17a-312e-470b-8f27-de215bbe83c7	EC/16.00476	SAMBA ZAMAMBU Louis	EC	Personne Physique	En Cabinet	M	+243811400614	louissamba56@yahoo.fr	\N	AAS SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.24007+00
792ccb11-fdee-4336-a649-ef1d14c3dfaa	EC/18.00488	TANDU ROVAT Jean-Pierre	EC	Personne Physique	En Cabinet	M	+243829784500	jean_pierre.tandu@trusttbg.com	\N	TRUST BUSINESS GUARANTEE RDC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.241475+00
c6608079-8c24-4f53-a4f5-274bb884a049	EC/17.00499	TSHIBANDA SABWA Jean-Pierre	EC	Personne Physique	En Cabinet	M	+243972854747	focalpoint.dg@gmail.com	\N	SECOFISC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.24261+00
f801eeb5-c2c2-4eca-84ce-496251b46be5	EC/24.00600	TSHIEBWE KADISHA Olivier	EC	Personne Physique	En Cabinet	M	+243823927981	olivier.tshiebwe@gmail.com	\N	DELOITTE SERVICES SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.243604+00
e74a4e89-d0b0-4638-8f60-3e0ef943f625	EC/18.00505	TSHILENGE MWINDILA Pitshou	EC	Personne Physique	En Cabinet	M	+243815133564	tshilengepitshou@gmail.com	\N	ACF SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.244578+00
68bf30be-b96b-4a0b-a794-4de45a61ac05	EC/16.00509	TSHIYOYO DJIBA Honoré	EC	Personne Physique	En Cabinet	M	+243998519742	tshiyoyohonore@yahoo.fr	\N	SECOFIC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.245595+00
25070ffb-23dd-4d22-b549-3bae013debdf	EC/19.00512	TULENGULULA MULUMBA Jean-Marie	EC	Personne Physique	En Cabinet	M	+243843989500	jtulengulula@gmail.com	\N	MMPARTNERS CONGO SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.247181+00
d2e46b9e-1359-42ff-a20a-a19690c23937	EC/16.00513	TUMBA KABALAMBI Jean-Marie	EC	Personne Physique	En Cabinet	M	+243998208011	jeanmarie747@hotmail.com	\N	AMS SARL CONSULTANTS SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.249533+00
c85021ae-74f3-4652-aed9-eeeb85074c72	EC/18.00514	TUNDA NGIEFU Yves	EC	Personne Physique	En Cabinet	M	+243818970523	yves.tunda@lacoteadvisory.com	\N	LACOTE AAT SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.251875+00
c478322c-331f-425d-a71e-8e241af16b2a	EC/16.00521	VANGU KI-TULANDA WA BAFUANGA Joseph	EC	Personne Physique	En Cabinet	M	+243816528164	josephvangu71@gmail.com	\N	AACS SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.253601+00
13225b6f-6cbe-4140-a839-852ca8b4c9ff	EC/25.00626	WAULA BALOMBA Merveille	EC	Personne Physique	En Cabinet	M	+243816889866	yanzambe@gmail.com	\N	DELOITTE SERVICES SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.254762+00
a268eec5-2ae6-4052-92f1-5cc1bdbcb6f6	EC/16.00524	YANGA LUMBAHE Simon	EC	Personne Physique	En Cabinet	M	+243999910998	cagescom2002@gmail.com	\N	CAGESCOM	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.255826+00
a0e88bcf-a7c7-4dd4-815d-220b4971e197	EC/16.00525	YATALA NGOY Constantin	EC	Personne Physique	En Cabinet	M	+243818124322	cyatala7333@gmail.com	\N	FIGEFITECH SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.257146+00
b9543ead-2dc0-4591-81dd-7949424d815e	EC/16.00526	YONGA ONAKOY Jean-Jacques	EC	Personne Physique	En Cabinet	M	+243810037298	burocof@yahoo.fr	\N	ACF SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.258488+00
a27723ff-699b-49ca-9d3a-0babbaec841a	EC/25.00627	YRUNG KAPALANG SARAH	EC	Personne Physique	En Cabinet	F	+243810782296	sarah.yrung@cd.ey.com	\N	EY RDC SARL	\N	\N	\N	8817ee0f-d190-4406-bd5e-036a1fa34e38	t	2026-03-20 10:24:08.259387+00
72e4cb45-fe6b-4026-9824-a97f4282a938	SEC/18.00001	ABN NZAILU & CO SAS	SEC	Personne Morale	Cabinet	\N	+243829000113	benjamin.nzailu@abncd.com	\N	\N	\N	ABN SAS	NZAILU BASINSA Benjamin	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.360833+00
45e4f628-404d-413c-9ed8-bc08c13c4249	SEC/17.00002	AFT CONSULTING ASSOCIES SARL	SEC	Personne Morale	Cabinet	\N	+243818126663	andre.foko@aftassocies.com	\N	\N	\N	AFT SARL	FOKO TOMENA André	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.371569+00
7fc16f61-51be-499b-bd43-c96b253fcaa5	SEC/16.00003	AJM & ASSOCIATES SARL	SEC	Personne Morale	Cabinet	\N	+243992006191	cboshabo@ajm-associates.org	\N	\N	\N	AJM & ASSOCIATES SARL	BOSHABO NKONGO COLOMBO	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.373453+00
0ce71fa9-5d1a-4b50-bd5b-4505a0445665	SEC/20.00005	AMS CONSULTANTS SARL	SEC	Personne Morale	Cabinet	\N	+243998208011	contact@amsconsultantscongo.com	\N	\N	\N	AMS SARL	TUMBA KABALAMBI Jean Marie	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.378872+00
e0337ac9-4563-4a73-a1f0-a2a4068516fa	SEC/19.00006	ANALYSES & CONSEILS EN GESTION AU CONGO SARLU	SEC	Personne Morale	Cabinet	\N	+243999928202	acgcongo@yahoo.fr	\N	\N	\N	ACGC SARLU	PAY-PAY MULINDU Pascal	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.380993+00
63e6163d-0283-4601-a414-20a52cf6fb15	SEC/24.00106	AUDIT & MANAGEMENT NETWORK SERVICES SARL	SEC	Personne Morale	Cabinet	\N	+243819959958	mawalaantoine@gmail.com	\N	\N	\N	AMN'S SARL	MAWALA NYIMI Antoine	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.38279+00
01a4577f-33f0-4ef9-877f-b9ebe7d6273d	SEC/24.00107	AUDIT ACCOUNTS AND TAXE ADVISOR SARL	SEC	Personne Morale	Cabinet	\N	+243818143839	infoaatadvisor@gmail.com	\N	\N	\N	AAT SARL	PATI NDOMPETELO Jean-Marie	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.384501+00
ce15de49-0235-4885-a49c-3e3793033981	SEC/16.00007	AUDIT COMPTABILITE FISCALITE SARL	SEC	Personne Morale	Cabinet	\N	+243846670935	christian.m@acf-conseil.com	\N	\N	\N	ACF SARL	MUNKENI KIEKE Eliane	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.386066+00
8fe5d8b3-e7a1-49b1-9c67-257b680feade	SEC/18.00008	AUDIT GESTION ET COMPTABILITE	SEC	Personne Morale	Cabinet	\N	+243811601052	audigec1995@yahoo.fr	\N	\N	\N	AUDIGEC	LIKAMBO KWADJE Dieudonné	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.388344+00
88514d67-22d9-44a9-a5c0-6c39a1149356	SEC/18.00019	AUDIT GESTION ET CONSEILS SARL	SEC	Personne Morale	Cabinet	\N	+243815260623	agec@agec-rdc.com	\N	\N	\N	AGeC SARL	BENGA NSUNGI Jolie Rachel	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.39083+00
84dea427-1576-4dbd-8b04-74cac51c9aee	SEC/18.00009	AUDIT GESTION FORMATION	SEC	Personne Morale	Cabinet	\N	+243998540358	agesfodrc@gmail.com	\N	\N	\N	AGESFO SARL	KAZADI KOLELA Rocher	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.392525+00
68f03646-b035-44df-90b4-17e2de6def4a	SEC/19.00010	AUDIT MANAGEMENT AND CONSULTING PARTNERS	SEC	Personne Morale	Cabinet	\N	+243999947393	amc.partners2020@gmail.com	\N	\N	\N	AMC PARTNERS	KITENGE KAPENGA Norbert	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.393812+00
21f07531-3e78-4b74-95cb-1121f5471de2	SEC/23.00102	AUDIT, TAX AND ACOUTING HOUSE SARL	SEC	Personne Morale	Cabinet	\N	+243813170409	atahrdc@gmail.com	\N	\N	\N	ATAH SARL	MBODO BUASA ANACLET	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.39528+00
10fa1843-3f9c-40f0-9a9a-8e073d1b059e	SEC/19.00013	BDO AUDIT SARL	SEC	Personne Morale	Cabinet	\N	+243813391217	blaise.mbatshi@bdo-ea.com	\N	\N	\N	BDO	MBATSHI TOVO Blaise	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.397435+00
da6c03d7-5657-4f1a-9f75-87c72426e08e	SEC/17.00015	BEFAC MKGA & Associés SARL	SEC	Personne Morale	Cabinet	\N	+243815976339	contact@befac-mkga.com	\N	\N	\N	BEFAC MKGA & A	MAKUNGA NIANGI Max Simon	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.400115+00
d473ae08-5600-4ad3-9d3a-81221153ae4b	SEC/23.00098	BELKAS GROUP SAS	SEC	Personne Morale	Cabinet	\N	+243842111970	info@belkasgroup.com	\N	\N	\N	BELKAS GROUP SAS	MUTANGILAYI MUTEBA  Yorick	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.402867+00
7b514344-264c-40ca-a39e-35252730bc08	SEC/23.00103	BM ASSOCIATES SARL	SEC	Personne Morale	Cabinet	\N	+243815215327	cedrick.bukasa@bma-cd.com	\N	\N	\N	BMA SARL	BUKASA WA BUKASA Cedrick	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.405648+00
97ee4d4e-2632-4ae4-879b-217e55cef031	SEC/24.00109	BMM CONSULTING SARL	SEC	Personne Morale	Cabinet	\N	+243852614301	bmmconsulte@gmail.com	\N	\N	\N	BMM CONSULTING SARL	BILOLO PANU MPAKOLE Augustin	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.40755+00
696b8985-b45b-4bec-a5c3-05795f447ba5	SEC/24.00120	BRUNO KABUNDA MUSASA CONSEIL, REVISION, EXPERTISE, FORMATION & ASSOCIES SARL	SEC	Personne Morale	Cabinet	\N	+243815090576	brukabmuss@yahoo.com	\N	\N	\N	BKM COREF & ASSOCIES Sarl	KABUNDA MUSASA Bruno	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.408853+00
e5165d00-3d0c-4595-978b-5cf9abef3214	SEC/25.00129	BUREAU D'EXPERTISE SARL	SEC	Personne Morale	Cabinet	\N	+243819591098	didiermbang@gmail.com	\N	\N	\N	B.E SARL	NDUMB MBANG Didier	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.409913+00
073c5f86-1cef-4607-a07a-547c7dc55b80	SEC/21.00069	CABINET D’AUDIT DE REVISION ET D’EXPERTISE COMPTABLE	SEC	Personne Morale	Cabinet	\N	+243998403072	kabeley@hotmail.fr	\N	\N	\N	CARECO SARL	KABENGELE M'PIEN LEY Gilbert	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.410942+00
6d8d1b6b-90ee-4cda-b690-97cfbd33931a	SEC/24.00110	CABINET D'AUDIT COMPTABLE ET CONSEILS	SEC	Personne Morale	Cabinet	\N	+243818109079	cacosarl22@gmail.com	\N	\N	\N	CACO SARL	AKINDOA MALEBO Eugène Robert	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.411917+00
ec53bbfa-4acb-4e3e-91ce-6e44343fdb16	SEC/22.00087	CABINET D'AUDIT DE GESTION ET DE COMPTABILITE SARL	SEC	Personne Morale	Cabinet	\N	+243999910998	cagescom2002@gmail.com	\N	\N	\N	CAGESCOM	YANGA LUMBAHE Simon	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.413291+00
9dab130c-5d5b-4603-abc3-7ee222a65ebf	SEC/23.00105	CABINET D'AUDIT ET CONSEILS EN GESTION	SEC	Personne Morale	Cabinet	\N	+243824977188	cabinetcacg14@gmail.com	\N	\N	\N	CACG SARL	NAMUTUTU KUNGWA Diane Esther	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.414814+00
b3af7c79-6ca8-4248-982d-b90ecbb563ba	SEC/16.00017	CABINET D'AUDIT ET D'EXPERTISE COMPTABLE	SEC	Personne Morale	Cabinet	\N	+243998087847	alainmunganga@hotmail.com	\N	\N	\N	CAEC SARL	KOMBA MUNGANGA Alain	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.415935+00
23505b3c-81ba-448e-af90-91b1c875a94a	SEC/18.00018	CABINET D'AUDIT ET D'EXPERTISE COMPTABLE	SEC	Personne Morale	Cabinet	\N	+243825337520	cauditec1@gmail.com	\N	\N	\N	CAUDITEC SARL	KAYAMBA KAYEMBA Marco	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.417619+00
c3c82a4e-7bd8-4209-87ea-eeafa36f6d6c	SEC/16.00021	CABINET D'EXPERTISE COMPTABLE, AUDIT ET FISCALITE	SEC	Personne Morale	Cabinet	\N	+243818130580	cecaf_nwk@yahoo.fr	\N	\N	\N	CECAF SARL	NGOIE WA KASONGO Augustin	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.418766+00
7c5905e0-8b33-4a65-b77c-2f18f132b0a5	SEC/21.00081	CABINET J.K. AUDIT SARLU	SEC	Personne Morale	Cabinet	\N	+243816896777	josuekasilembo@cabinetjkauditsarlu.com	\N	\N	\N	J.K. AUDIT SARLU	KASILEMBO BUJINGA Josué	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.41985+00
d52fccef-9653-41c3-97d1-b108c66cded5	SEC/21.00076	CABINET LA COURCELLE SARLU	SEC	Personne Morale	Cabinet	\N	+243819593692	ngoyibenjamin11@gmail.com	\N	\N	\N	LA COURCELLE SARLU	NGOYI KABEMBA Benjamin	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.421453+00
6c2e25d1-45a3-4afc-b848-c9646f0540c7	SEC/23.00095	CABINET SOLUTION SARL	SEC	Personne Morale	Cabinet	\N	+243816432674	casolrdc@gmail.com	\N	\N	\N	CASOL SARL	MAYI KAYIMBONGE Désiré	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.422814+00
237ba71a-a577-4ea9-b2c9-48fd3535240d	SEC/21.00079	CABINET TRANSPARENCY SARLU	SEC	Personne Morale	Cabinet	\N	+243818148848	contact@ctrsrdc.com	\N	\N	\N	CTRS	LIGBAKELO MAYKPELE Samy	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.428481+00
e868ceff-1257-4ddc-b631-9fe731a871af	SEC/22.00083	CAF CONSULTING SARL	SEC	Personne Morale	Cabinet	\N	+243818145122	jean-marie.ngandu@caf-consulting.com	\N	\N	\N	CAF CONSULTING SARL	NGANDU WA NGANDU Jean Marie	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.429669+00
fa993295-4054-4297-a629-e922f2559185	SEC/24.00112	COMPANY OF BROTHERS MANAGERS SARLU	SEC	Personne Morale	Cabinet	\N	+243816603731	kampanzuexpert@gmail.com	\N	\N	\N	CBM SARLU	KAMPANZU MBEKU Cherif	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.43126+00
dbcb8133-fed8-42cb-a8a8-cef821b0bf74	SEC/18.00023	CONGO CONSULTING SERVICES SARL	SEC	Personne Morale	Cabinet	\N	+243999124915	congoconsulting@gmail.com	\N	\N	\N	CCS SARL	NSAYI LUKOMBO Rubens	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.432613+00
49e3e8cc-c3ae-41ae-8a35-4ea397c9f2f9	SEC/21.00077	CONSEIL DES CONCITOYENS POUR LA PERFORMANCE DES AFFAIRES SARL	SEC	Personne Morale	Cabinet	\N	+243998273107	ccpaccaf@gmail.com	\N	\N	\N	CCPA SARL	KAKULE LWANZO Claude	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.433693+00
74ef4250-e435-4829-bb54-9546a9155e1f	SEC/18.00025	CONSEIL, FISCALITE, COMPTABILITE ET AUDIT	SEC	Personne Morale	Cabinet	\N	+243999964440	infos.cofica@gmail.com	\N	\N	\N	COFICA SARL	MATUTALA KULA PITSHOU	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.43469+00
c9c97752-0ee0-4da1-9ed3-c35ab4bebc4a	SEC/21.00070	CONSEIL-ETUDE-FISCALITE-AUDIT-ORGANISATION	SEC	Personne Morale	Cabinet	\N	+243998921784	bureau_cefao@yahoo.fr	\N	\N	\N	CEFAO	NSILULU BAHELELE Gabriel	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.43575+00
6fcba9a8-7ef2-4d37-b588-db2064c71240	SEC/24.00113	CONSULTING RESOURCES MANAGEMENT	SEC	Personne Morale	Cabinet	\N	+243812457797	crm1942@yahoo.fr	\N	\N	\N	CRM SARL	DIKASSADYBY MOUENALONJ Donatien	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.438344+00
e738fa94-eb68-4c64-8a0f-ace7e714e93a	SEC/24.00125	CONSULTING, AUDITING, ACCOUNTING & TAX SAS	SEC	Personne Morale	Cabinet	\N	+243818112710	brunokambaja@gmail.com	\N	\N	\N	CAAT SAS	KAMBAJA MUBALAMATA Bruno	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.440313+00
ed846c57-96be-430d-a49f-2985b6aef242	SEC/17.00028	CORNERSTONE FOREVER INTERNATIONAL	SEC	Personne Morale	Cabinet	\N	+243992454996	cornerstone@cornerstone-cd.com	\N	\N	\N	CFI SARL	LUKIMUENA KUBA Samuelson	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.441415+00
2a64587a-0fbe-4150-91a3-bd5a7890618a	SEC/21.00080	CPM CONSULTING SARL	SEC	Personne Morale	Cabinet	\N	+243815208327	cyrille_mongele@yahoo.fr	\N	\N	\N	CC	MBUWA MONGELE Cyrille	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.442602+00
330f90e2-fb48-4db2-b958-d846813b8e37	SEC/17.00029	DA CONSULTING OFFICE	SEC	Personne Morale	Cabinet	\N	+243817068908	daco2sarl@gmail.com	\N	\N	\N	DACO SARL	MUKAWA NINGA Nanou	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.444809+00
91c9a7b9-e0c7-4786-ae20-eb1ad842e354	SEC/16.00030	DEL PARTNERS SARL	SEC	Personne Morale	Cabinet	\N	+243812577497	info@delpartners.com	\N	\N	\N	DEL PARTNERS SARL	KABWELA WA KABWELA Didier	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.44604+00
acd24b27-95eb-4ac5-91e2-987e0a5c0ebd	SEC/16.00031	DELOITTE SERVICES SARL	SEC	Personne Morale	Cabinet	\N	+243859998006	rdc@deloitte.fr	\N	\N	\N	DELOITTE SERVICES SARL	NZOIMBENGENE LUYINDULA Bob David	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.447073+00
0ac7bad3-4159-4af8-bef7-9a142074fd2e	SEC/25.00132	DIVINE WISDOM FOR ASSISTING AND CONSULTING SARL	SEC	Personne Morale	Cabinet	\N	+243972009548	cmngubi@gmail.com	\N	\N	\N	DWAC SARL	NGUBI LUTETE Mac	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.448364+00
2eedc1d6-881b-4178-b237-7d9f1e33b1e2	SEC/18.00032	DRC EXPERTISES SAS	SEC	Personne Morale	Cabinet	\N	+243813421009	contact@drcexpertises.net	\N	\N	\N	DEX SAS	LUNGANGI KITUNDU Françoise	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.449551+00
81db05ab-68e9-4004-8e20-eac21b5458dd	SEC/18.00033	EMERGENCE CONSULTING SARL	SEC	Personne Morale	Cabinet	\N	+243827275187	emergenceconsult2024@gmail.com	\N	\N	\N	EMERGENCE CONSULTING SARL	MPOP AWUNG Florent	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.450982+00
3055c5ca-ea5f-4046-b7fe-2a14facd4909	SEC/18.00034	ERNST & YOUNG RDC SARL	SEC	Personne Morale	Cabinet	\N	+243993435296	baraka.kabemba@cd.ey.com	\N	\N	\N	EY RDC	KABEMBA BARAKA	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.452235+00
916c2f7c-8b84-4760-a67d-ded97632b864	SEC/19.00035	ETUDES CONSEILS AUDIT DEVELOPPEMENT TECHNOLOGIE ET FORMATION	SEC	Personne Morale	Cabinet	\N	+243997992150	ecautef.kinshasa@yahoo.fr	\N	\N	\N	ECAUTEF SARL	KAKULE VAHIMBI Guillain	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.453479+00
cee88874-9220-46cd-b90b-2532ee560729	SEC/25.00153	EXPERT-COMPTABLE CONSEIL D'ENTREPRISE	SEC	Personne Morale	Cabinet	\N	+243824682000	egide.mambu@africamel.net	\N	\N	\N	ECCE SARL	MAMBU LUYALU MUSONGA KEL	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.455413+00
fed5d027-1873-4db7-9c37-dda92d57b4bd	SEC/17.00038	EXPERTS COMPTABLES REUNIS SARL	SEC	Personne Morale	Cabinet	\N	+243824448070	contact@ecrrdc.com	\N	\N	\N	ECR SARL	NTUMBA MPUTU Odilon	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.457374+00
91a0cdea-eb8c-4f65-92f6-252858a23e70	SEC/19.00039	EXPERTS MAC CD SAS	SEC	Personne Morale	Cabinet	\N	+243971798907	rkalambay2936@gmail.com	\N	\N	\N	E-MAC SAS	KALAMBAY NYINDU Raphaël	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.45904+00
48a04c71-e2b0-4cb6-9537-b79ab0b8248f	SEC/19.00040	F.COMPTA SARL	SEC	Personne Morale	Cabinet	\N	+243816866913	contact@fcompta.com	\N	\N	\N	FCOMPTA	MASIALA FINDUO Blaise	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.460609+00
26345fa2-0727-4dea-a0fd-e4b872b9cf2a	SEC/25.00130	FIDUCIAIRE AUDIT-GESTION ET FISCALITE SARL	SEC	Personne Morale	Cabinet	\N	+243999905021	fagefi@yahoo.fr	\N	\N	\N	FAGEFI SARL	CIZUBU CIAMPOYI Alidor	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.461847+00
3a7b247c-072d-4212-a745-3b4d7acae175	SEC/24.00114	FIDUCIAIRE DE COORDINATION D'AUDIT ET D'EXPERTISE COMPTABLE AFRIQUE CONGO RDC	SEC	Personne Morale	Cabinet	\N	+243976537921	ficadexrdc@yahoo.com	\N	\N	\N	FICADEX AFRIQUE CONGO RDC	ABEDI ABD'ALLAH ASSAD	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.463348+00
8751b45b-e8a7-4706-b8f6-729e26fb222c	SEC/23.00099	FIGEFITECH SARL	SEC	Personne Morale	Cabinet	\N	+243820647189	figefitechsarl@gmail.com	\N	\N	\N	FIGEFITECH SARL	KASONGO BATUSSE Peter	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.464516+00
e6706825-1df9-4fa8-baae-afe8d03117e2	SEC/17.00051	FORVIS MAZARS RDC	SEC	Personne Morale	Cabinet	\N	+243999785240	jemima.bazola@forvismazars.com	\N	\N	\N	FORVIS MAZARS RDC	NDANGI NDANGANI Théophile	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.465578+00
62109f32-db00-4255-8f6f-b9c1442cdcf4	SEC/25.00131	GENERALE D'AFFAIRES ET CONSEILS	SEC	Personne Morale	Cabinet	\N	+243815117683	jbetombo5@gmail.com	\N	\N	\N	GEDAF-Conseil SARL	BETOMBO NGANDO Joseph	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.467042+00
00b78195-a7fe-4486-939a-769b030d2839	SEC/22.00084	GPO CONGO EXPERTISES SARL	SEC	Personne Morale	Cabinet	\N	+243832307387	gpoce@gpopartners.com	\N	\N	\N	GPO CONGO EXPERTISES SARL	PHANZU NLANDU Philippe	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.468193+00
e56cf34d-1ae4-4dc3-9438-99d347eef67b	SEC/21.00078	HELIAN CONSULTING SARL	SEC	Personne Morale	Cabinet	\N	+243973892181	helianconsulting@gmail.com	\N	\N	\N	HELIAN CONSULTING SARL	FATAKI NTULA Zephirin	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.469233+00
758aa43d-daff-48f9-a53c-18b77ffba8d5	SEC/23.00100	IBN SARL	SEC	Personne Morale	Cabinet	\N	+243998121510	contact@ibnsarl.com	\N	\N	\N	IBN SARL	IFEKA BONKOMO Nelson	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.471722+00
0a1ccd0b-f54f-40b7-8bc9-2295c4129126	SEC/21.00082	IN SERVICE PARTNERS SARL	SEC	Personne Morale	Cabinet	\N	+243818112781	cyprien.bongulumata@cd-insp.com	\N	\N	\N	INSP SARL	BONGULUMATA LOKELE Cyprien	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.473693+00
0ac74d93-7b10-4901-9e53-cee2635c9318	SEC/17.00043	INVESTORS ADVICE OFFICE	SEC	Personne Morale	Cabinet	\N	+243811828663	inadof@yahoo.fr	\N	\N	\N	INADOF	BOKIE NDWAYA Norbert	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.474919+00
158d0ea0-a46b-4581-805e-319d8827da41	SEC/17.00044	JASBI CONSULTANTS SARL	SEC	Personne Morale	Cabinet	\N	+243998379602	infos@jasbisarl.com	\N	\N	\N	JASBI SARL	KUSAMA MIEZI Gabriel	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.475988+00
bde41e4f-d222-488d-953f-879c5a14b8e1	SEC/20.00066	JMB CONSULTING SARL	SEC	Personne Morale	Cabinet	\N	+243858475078	secretariat@jmbconsulting.cd	\N	\N	\N	JMB CONSULTING SARL	MBUMBA MBUDI Joseph	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.477166+00
87a86a17-5410-4bf7-a906-a4fdd38a0e34	SEC/25.00126	JVL SAS	SEC	Personne Morale	Cabinet	\N	+243998139161	jvlconsuting26@gmail.com	\N	\N	\N	JVL SAS	LUNGONZO MBUY François	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.478702+00
aa193027-c852-40a3-8a0f-5e357b1c7b54	SEC/19.00046	K2M PARTNERS SARL	SEC	Personne Morale	Cabinet	\N	+243992722376	contact@k2m-partners.com	\N	\N	\N	K2M PARTNERS SARL	MANKENDA NANSINA Sébastien	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.479727+00
76922762-e7ce-4f11-bb2d-06c6191be23a	SEC/22.00088	KMC Advice & Partners SASU	SEC	Personne Morale	Cabinet	\N	+243893992457	infos@kmc-cabinet.com	\N	\N	\N	KMC SASU	KANINDA MUKENA Carlos	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.480751+00
fec394c3-3f3c-4a4f-964e-a53a4a443db7	SEC/16.00047	KPMG RDC SA	SEC	Personne Morale	Cabinet	\N	+243990010021	tfashingabo@kpmg.cd	\N	\N	\N	KPMG	KIYOMBO MANGA Louison	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.481777+00
33f55574-cd0b-49a6-b81c-9a747eb7e865	SEC/17.00049	LA PRADELLE CONSULTING SARLU	SEC	Personne Morale	Cabinet	\N	+243810837185	info@lapradellec.com	\N	\N	\N	PDLC SARLU	OKENDE MBUNGU Adolphe	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.483478+00
4212236d-d929-4d8b-b2d1-963c5c3a0dba	SEC/24.00116	LABOTTE FIDUCIA SARL	SEC	Personne Morale	Cabinet	\N	+243829199974	labottefiducia@gmail.com	\N	\N	\N	LABOTTE FIDUCIA SARL	FURUME NTALE Benito	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.485124+00
7a5a968a-e8c0-4fde-94eb-873df1952bd4	SEC/19.00048	LACOTE ADVISORY AUDIT AND TAX	SEC	Personne Morale	Cabinet	\N	+243818970523	contact@lacoteadvisory.com	\N	\N	\N	LACOTE AAT SARL	TUNDA NGIEFU Yves	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.486333+00
9e905b3f-a191-4605-af2d-59dfb400cd2d	SEC/17.00052	mgi STRONG NKV SAS	SEC	Personne Morale	Cabinet	\N	+243898919645	audit@strong-nkv.cd	\N	\N	\N	mgi STRONG NKV SAS	NKUVU-A-MBINDA WENA Danny	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.489085+00
38c8a3be-de60-49d5-8ae1-416b0b27058a	SEC/16.00053	MMPARTNERS CONGO SARL	SEC	Personne Morale	Cabinet	\N	+243999916552	contact@mmpartnerscongo.com	\N	\N	\N	M&MP	KIMBEMBE KIAMVU Simon	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.491303+00
1cff01a1-b967-4333-adb7-db4e9f09761a	SEC/25.00135	NDONGO NTIERE SARL	SEC	Personne Morale	Cabinet	\N	+243854348339	ndongogaby30@gmail.com	\N	\N	\N	NN SARL	NDONGO NTIERE Gaby	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.493299+00
d4745375-7d27-49ac-92dd-7adb0920691d	SEC/24.00121	NEW ANOU CONSULTING Sarl	SEC	Personne Morale	Cabinet	\N	+243815981162	lu.tchata@gmail.com	\N	\N	\N	NEW ANOU	LUMU TCHATA Joseph	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.494853+00
502f500e-bf2d-4644-ab63-db273521d079	SEC/23.00104	ODON NDOKO FIRME	SEC	Personne Morale	Cabinet	\N	+243814847070	odonndoko8@gmail.com	\N	\N	\N	ONF SARLU	NDOKO FUMU Odon	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.495979+00
ff081316-1183-4725-ae43-2dcebf860e83	SEC/23.00097	OKM CONSULTING SAS	SEC	Personne Morale	Cabinet	\N	+243855281200	kamibafor@gmail.com	\N	\N	\N	OKM CONSULTING SAS	KASONGO DIEMU Dieudonné	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.498522+00
6ecd3956-519f-4904-b25e-7fe523acded4	SEC/22.00085	PROSPER & Associates Sarl	SEC	Personne Morale	Cabinet	\N	+243818122030	prosper.bongongu@pros-rdc.com	\N	\N	\N	PROSPER & Associates Sarl	BONGUNGU MATONDO Prosper	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.500516+00
b0436742-cd53-4a81-b6c6-9c796d16aaaa	SEC/17.00056	QUITUS CONSULT SARL	SEC	Personne Morale	Cabinet	\N	+243815086052	contact@quitusconsult.cd	\N	\N	\N	QC SARL	NDUSHA BIRHAFANWA Xavier	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.502434+00
3858fc1c-99e6-4cf2-94a7-beb019302c39	SEC/21.00074	R.O & PARTNERS SARL	SEC	Personne Morale	Cabinet	\N	+243998946925	ropartnersrdc@gmail.com	\N	\N	\N	R.O & PARTNERS SARL	OVO YATUIKWAMO FUKIAU Ranield	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.506594+00
9d882e44-55f2-4081-8004-f4d233a6d707	SEC/18.00058	SM ACCOUNTING & ASSOCIES	SEC	Personne Morale	Cabinet	\N	+243995961063	simon@smaccounting.net	\N	\N	\N	SMA	MUAMBA TSHILUMBA Simon	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.513071+00
2b698b48-bf9f-4d4a-9fc7-c2bed3eae877	SEC/19.00027	SOCIETE DE CONSEIL, REVISION ET EXPERTISE COMPTABLES	SEC	Personne Morale	Cabinet	\N	+243815124970	contact@corexrdc.com	\N	\N	\N	COREX SARL	DONGO LISIKA Gauthier	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.514964+00
bb7fff00-2906-4a05-9e03-00cc81d1ceb0	SEC/19.00059	SOCIETE D'EXPERTISE COMPTABLE ET COMMISSARIAT AUX COMPTES	SEC	Personne Morale	Cabinet	\N	+243821860057	credesexco@gmail.com	\N	\N	\N	CREDES EXCO SARL	MULEMVO BIDUAKA Bienvenu	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.516462+00
1a8104e3-bfdc-41ff-bb59-073b6d370e10	SEC/19.00060	SOCIETE D'EXPERTISE COMPTABLE ET FISCALE "IMAGE FIDELE" SARL	SEC	Personne Morale	Cabinet	\N	+243810888189	focalpoint.dg@gmail.com	\N	\N	\N	SECOFISC SARL	TSHIBANDA SABWA Jean-Pierre	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.517943+00
a9481bb7-5646-4b0c-9e2e-05d854cb6e20	SEC/16.00061	SOCIETE D'EXPERTISE COMPTABLE FISCALITE ET CONSEILS	SEC	Personne Morale	Cabinet	\N	+243818757078	infos@secofic.cd	\N	\N	\N	SECOFIC SARL	MBAYA MBAYA Célestin	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.519815+00
b83e82a1-4f16-4033-b288-4c8c936abc5d	SEC/19.00062	SOCIETE D'EXPERTISE COMPTABLE, D'AUDIT ET DE FISCALITE	SEC	Personne Morale	Cabinet	\N	+243816144948	secafsarl4@gmail.com	\N	\N	\N	SECAF	IZE KANIKI Johnny	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.52351+00
02f6d3f4-f935-4bb1-9004-6357b20fab56	SEC/18.00063	SOCIETE D'EXPERTISE COMPTABLE, FISCALITE ET D'AUDIT	SEC	Personne Morale	Cabinet	\N	+243990317590	secofia.secofia@yahoo.com	\N	\N	\N	SECOFIA SARL	ILEO BOTINDO Madeleine	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.526665+00
29caab16-1ddd-43a6-a1af-1b7782a01313	SEC/25.00128	T.L PARTNERS-CONGO SARL	SEC	Personne Morale	Cabinet	\N	+243899501186	thierry_lokesa@yahoo.fr	\N	\N	\N	T.L PARTNERS-CONGO SARL	LOKESA SUAMUNU Thierry	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.530423+00
6b459e30-fcd5-4b0a-bfdd-5f10bf1dffdf	SEC/25.00133	TAX ACCOUNTING AND AUDIT EXPERTS SARLU	SEC	Personne Morale	Cabinet	\N	+243998397801	anderson@taaex.net	\N	\N	\N	TAAEX SARLU	MAWANGU NDOLUVUALU Anderson	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.533662+00
b5a8f767-a0b5-462f-9255-c0778627d0c1	SEC/24.00118	TECPRO EXPERTISE SARLU	SEC	Personne Morale	Cabinet	\N	+243820057638	info.tecpro.fiduciaire@gmail.com	\N	\N	\N	TECPRO EXPERTISE SARLU	MAMPUYA KALENGA Robert	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.53589+00
1198d385-cc95-418e-b4bb-69542574b377	SEC/23.00096	TRUST BUSINESS GUARANTEE RDC SARL	SEC	Personne Morale	Cabinet	\N	+243810532936	admin-tbg@trusttbg.com	\N	\N	\N	TRUST BUSINESS GUARANTEE RDC SARL	TANDU ROVAT Jean-Pierre	36072e6c-2e76-49fe-b162-4740e0c970ee	t	2026-03-20 10:49:59.539356+00
642b33aa-af97-4582-a22b-08a7dc917568	EC/18.00185	KIMBI ILENDA Michel	EC	Personne Physique	Indépendant	M	+243842339577	michelkimbi@gmail.com	A2320927Y	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.153639+00
7221417e-9571-4e70-bd92-30b4a4357e14	EC/17.00186	KIMBULU KAMWENI André	EC	Personne Physique	Indépendant	M	+243903774232	audicomcabinet@gmail.com	A1402050U	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.159823+00
b0e93452-c8bc-494e-a989-f069d8471e2a	EC/18.00187	KINDU MUNDEKE MUSHAGALUSA Jean Chirac	EC	Personne Physique	Indépendant	M	+243976332205	jckindu2019@gmail.com	A2032437F	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.161814+00
79c8b168-6505-4861-8c5e-6db1d46cf708	EC/19.00189	KINKELA MIANGU Gilbert	EC	Personne Physique	Indépendant	M	+243999226581	gilkinkela@hotmail.com	A0708999Q	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.163365+00
c79dfa42-4487-4a18-bf9e-5b08727317b2	EC/16.00200	KONKO NDONTONI NTUMPI Joseph Dieudonné	EC	Personne Physique	Indépendant	M	+243998511001	codipro_cd@yahoo.fr	A1612573K	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.164572+00
f23c2724-7d51-46e4-9718-255405f926a3	EC/17.00206	KUTELAMA BATWA Ignace	EC	Personne Physique	Indépendant	M	+243820893568	ignacekutelama@gmail.com	A0902535S	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.165715+00
7ab8a09b-9d3c-4812-a0fd-21d8069a9e51	EC/16.00212	LEVO NKUANGA JEAN Thomas	EC	Personne Physique	Indépendant	M	+243814443300	cabinetlevocompte@gmail.com	A1709114B	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.167266+00
1958da41-69a4-4442-a1cf-c381bf4b20a1	EC/17.00217	LOANGO BOELUA BAENDAFE Honoré	EC	Personne Physique	Indépendant	M	+243999939791	honoreloango@yahoo.fr	A1210316C	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.168931+00
d53f8f38-6317-44a3-8ded-de101a3a3f77	EC/17.00239	LUYINDULA MAVAMBU Felly	EC	Personne Physique	Indépendant	M	+243816629429	fellyluyindula@yahoo.fr	A2409121R	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.170518+00
f258e871-8427-40dc-8e16-7182bb092eb5	EC/19.00242	LWELA MAKOSO Evariste	EC	Personne Physique	Indépendant	M	+243819041687	evalwela@yahoo.fr	A0805529U	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.171683+00
8270cf39-ec0d-4949-a4ae-fd2f2aa3dcde	EC/19.00260	MAMONA PHEZO Nathalis	EC	Personne Physique	Indépendant	M	+243817005489	mamonaphezo@yahoo.fr	A2207503F	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.172798+00
b4ebe024-1da4-486b-8910-68013fdca285	EC/19.00271	MASSALA PANGU Guelord	EC	Personne Physique	Indépendant	M	+243820291101	guelordmassala08@gmail.com	B2293204K	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.173915+00
413dd4b8-c388-4acb-b652-6e3542e63dbb	EC/18.00288	MAYO BOKWANGO Daniel	EC	Personne Physique	Indépendant	M	+243857000191	danbokwa@gmail.com	A2302481Y	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.174847+00
af887065-b308-4986-a3cd-862819e9b13e	EC/16.00292	MBANGALA MAPAPA Augustin	EC	Personne Physique	Indépendant	M	+243997625788	mmbangala@yahoo.fr	1508462Q	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.176722+00
c417c93a-466c-4ebd-80a6-2eca007dd06c	EC/16.00298	MBUDI MASUNDA Martin	EC	Personne Physique	Indépendant	M	+243855179505	mmbudimasunda@gmail.com	A0705673A	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.178663+00
c173fdc9-fea7-4ef4-9610-a385fc92b019	EC/16.00306	MFUAMBA KEYAMONOKO Désiré	EC	Personne Physique	Indépendant	M	+243812550110	desire.mfuamba@gmail.com	A2534646M	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.179967+00
ae403c38-09c9-40b1-8873-64f732dff4d0	EC/19.00313	MOKELO MAYO Flory	EC	Personne Physique	Indépendant	M	+243814245488	florymokelo65@gmail.com	A1923398E	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.181072+00
2857e70e-f475-46be-99ec-bc7b22b52dc5	EC/16.00333	MUHINDO MUHONGYA Albert	EC	Personne Physique	Indépendant	M	+243852809802	mkmuhindo@yahoo.fr	A2402749Q	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.182275+00
61eac0d6-e984-44b2-92df-429e121c9d1d	EC/24.00602	MUKADI KAPINGA NTUMBA Biby	EC	Personne Physique	Indépendant	M	+243854719696	mukadibiby@gmail.com	A2526187S	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.184312+00
05e24aa5-b2cc-4987-9aa0-cf35f1e8c668	EC/16.00532	MUKANDILA ILUNGA José François	EC	Personne Physique	Indépendant	M	+243999920160	francoismukandila@yahoo.fr	A0702340C	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.186463+00
3036e96c-f45d-4b79-8833-992e3a7bb6b1	EC/19.00356	MULONGO MUKWINDI Ruben Freddy	EC	Personne Physique	Indépendant	M	+243813395652	mulongo_freddy@yahoo.fr	A0802485L	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.18758+00
03e499f0-cfc9-4541-89a0-9ffae607d643	EC/16.00357	MULUMBA KOLOMONI André	EC	Personne Physique	Indépendant	M	+243821023840	andmulko@gmail.com	A2207534P	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.188868+00
80d1721c-c514-47c9-aeae-0329e314cf0e	EC/16.00362	MUPEPE LEBO Jean Baptiste	EC	Personne Physique	Indépendant	M	+243819702022	jblebo40@gmail.com	A0193194C	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.189874+00
1d2c09b7-e18c-43b5-a319-5fa2c3470140	EC/17.00375	MUTUMBU ZA MAMBU Simon	EC	Personne Physique	Indépendant	M	+243896455730	simon.mutumbu@yahoo.fr	A0806854K	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.190889+00
3427fc85-117e-4021-ac77-caf8182b9c5c	EC/17.00382	MWAMBO KASANZA Georges	EC	Personne Physique	Indépendant	M	+243815256181	georgesmwambo4@gmail.com	A0803833B	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.19188+00
666d5d2f-33c7-412c-9bc3-9d6ea34247ab	EC/16.00412	NIATI MATONA Omer	EC	Personne Physique	Indépendant	M	+243812347377	oniati@gmail.com	A0903949D	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.193492+00
1f064608-4669-4c80-9bfa-0b39877271ff	EC/16.00424	NLANDU NKIAWETE Jean Pierre	EC	Personne Physique	Indépendant	M	+243856253534	dnlandu1@gmail.com	A2216881Z	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.195897+00
0fe347a7-3be6-4fc1-98af-992e01ce7aed	EC/24.00597	NSENSELE KANGONDO Jacqueline	EC	Personne Physique	Indépendant	F	+2438810346426	nsenselejacqueline@gmail.com	B228179F	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.198257+00
d73658ba-af11-480f-8e24-e5eea788c87e	EC/17.00428	NSIMBA MBAKI Edmond	EC	Personne Physique	Indépendant	M	+243815192269	edmondnsimba44@gmail.com	A0807524G	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.19948+00
415c24df-30e8-4a16-8852-7f11af1c40de	EC/17.00438	NTUMBA WA NTUMBA Joseph	EC	Personne Physique	Indépendant	M	+243825532814	jnwntumba@gmail.com	A601640B	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.20059+00
ffc7495c-9608-4c30-bb33-6e9fdf3101cb	EC/19.00445	NZEZA ZI NGETI Claude	EC	Personne Physique	Indépendant	M	+243811861940	clauvenant@hotmail.com	A90171761L	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.20166+00
3ca4ffed-76d7-48e7-a92e-96eaca1d42f1	EC/17.00450	NZUZI MAYIFILUA Donat Claude	EC	Personne Physique	Indépendant	M	+243818930700	nzuzimayifilua@gmail.com	A1000232P	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.202648+00
319c4f98-a984-44b1-a643-9a9f61e6f25c	EC/18.00451	NZUZI NZUZI Baudouin	EC	Personne Physique	Indépendant	M	+243843371771	nzuzibaudouin1@gmail.com	A2031263E	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.203607+00
d2cd4379-20b0-4fa3-a705-d826a8664a7d	EC/16.00474	RUKUYENGE KASHUGI Willy Anselme	EC	Personne Physique	Indépendant	M	+243815164872	willyanselme.rk@live.be	A1000503J	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.204737+00
fd45d46b-654e-40b3-ad07-82d425d056e4	EC/18.00487	SUMBA BADIMANI Boniface	EC	Personne Physique	Indépendant	M	+243974614855	sumbaboniface580@gmail.com	A0801686S	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.205854+00
82a0c766-67ac-4550-b2ce-ba43d413d1bb	EC/16.00491	TRIBUNALI SEMBAITO CHRISPIN	EC	Personne Physique	Indépendant	M	+243825392061	christribun219@gmail.com	A0801990Y	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.206835+00
26ee891e-d5f3-439a-8cd3-10017d6be92e	EC/18.00496	TSHIALA BONGO Macaire	EC	Personne Physique	Indépendant	M	+243976929659	macairebongo2@gmail.com	48150	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.207797+00
2c39b43a-4b6f-44c5-8932-4a76437a677e	EC/16.00498	TSHIBAMBE TAMBWE Noah	EC	Personne Physique	Indépendant	M	+243999955207	tshibambenoah@yahoo.fr	A0803842L	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.209136+00
788c8f8a-d67d-499e-841d-8b1a5a617d29	EC/16.00506	TSHILOMBA MUSOKAY Paulin	EC	Personne Physique	Indépendant	M	+243819383884	tshilombap@yahoo.com	A1107701J	\N	\N	\N	\N	8e3dfba2-7b44-4bb6-8a00-a35c6c781619	t	2026-03-20 11:01:03.210708+00
de5647b8-17fb-4e7c-9267-b82dd328a7b1	SEC/24.00122	AFRICAN ACCOUNT SERVICES	SEC	Personne Morale	Cabinet	\N	+243828293887	mickmatondo@yahoo.fr	\N	\N	\N	AAS SARL	MATONDO MIOKO Jean Pierre	36072e6c-2e76-49fe-b162-4740e0c970ee	f	2026-03-20 10:49:59.369309+00
\.


--
-- Data for Name: imports_history; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.imports_history (id, filename, category, imported_by, rows_imported, status, file_data, created_at) FROM stdin;
8817ee0f-d190-4406-bd5e-036a1fa34e38	modele_en_cabinet (1).xlsx	en_cabinet	a2375bac-4a9f-4ed8-b674-a1807543c744	157	success	[{"Noms": "BUALELU MUKEBA Celestin", "Sexe": "M", "E-mail": "bualelucelestin@gmail.com", "N° d'ordre": "EC/18.00055", "Cabinet d'attache": "K2M PARTNERS SARL", "N° de téléphone": "(+243)998178695"}, {"Noms": "BUKASA WA BUKASA Cedrick", "Sexe": "M", "E-mail": "cedric.bukasa@gmail.com", "N° d'ordre": "EC/16.00056", "Cabinet d'attache": "BMA SARL", "N° de téléphone": "(+243)815215327"}, {"Noms": "CIZUBU CIAMPOYI Alidor", "Sexe": "M", "E-mail": "fagefi@yahoo.fr", "N° d'ordre": "EC/16.00068", "Cabinet d'attache": "FAGEFI SARL", "N° de téléphone": "(+243)999905021"}, {"Noms": "DHENA NDAHORA Joseph", "Sexe": "M", "E-mail": "josephdhena@agec-rdc.com", "N° d'ordre": "EC/16.00070", "Cabinet d'attache": "AGEC SARL", "N° de téléphone": "(+243)818135566"}, {"Noms": "DIAMBOKO NDONZUAU Flory", "Sexe": "M", "E-mail": "floridiamboko@gmail.com", "N° d'ordre": "EC/25.00605", "Cabinet d'attache": "FORVIS MAZARS RDC", "N° de téléphone": "(+243)820066556"}, {"Noms": "DILU NZINGA Yann", "Sexe": "M", "E-mail": "yanndilu@gmail.com", "N° d'ordre": "EC/24.00584", "Cabinet d'attache": "KPMG RDC SA", "N° de téléphone": "(+243)814467918"}, {"Noms": "DIMELO KISOLO Mike", "Sexe": "M", "E-mail": "mike.dimelo@fonarev.cd", "N° d'ordre": "EC/18.00077", "Cabinet d'attache": "INSP SARL", "N° de téléphone": "(+243)972003910"}, {"Noms": "DONGO LISIKA Gauthier", "Sexe": "M", "E-mail": "gdongo@corexrdc.com", "N° d'ordre": "EC/16.00079", "Cabinet d'attache": "COREX SARL", "N° de téléphone": "(+243)815124970"}, {"Noms": "DYKASSADYBY MOUENALONJ Donatien", "Sexe": "M", "E-mail": "donadykr@yahoo.fr", "N° d'ordre": "EC/18.00074   ", "Cabinet d'attache": "CRM Sarl", "N° de téléphone": "(+243)0821280259"}, {"Noms": "EKOFO BOONA INGANGE Antoine Roger", "Sexe": "M", "E-mail": "ekofoantoineroger@yahoo.fr", "N° d'ordre": "EC/18.00080", "Cabinet d'attache": "PDLC SARLU", "N° de téléphone": "(+243)816081250"}, {"Noms": "ELANGA MONGA MBULI MARCUS ", "Sexe": "M", "E-mail": "marcuselanga30@gmail.com", "N° d'ordre": "EC/18.00082", "Cabinet d'attache": "EY RDC SARL", "N° de téléphone": "(+243)994495452"}, {"Noms": "FATAKI NTULA Zephyrin", "Sexe": "M", "E-mail": "zephirin.fataki@yahoo.fr", "N° d'ordre": "EC/16.00086", "Cabinet d'attache": "HELIAN CONSULTING SARL", "N° de téléphone": "(+243)973892181"}, {"Noms": "FOKO TOMENA André", "Sexe": "M", "E-mail": "andre.foko@aftassocies.com", "N° d'ordre": "EC/16.00089", "Cabinet d'attache": "AFT SARL", "N° de téléphone": "(+243)818126663"}, {"Noms": "FUNDI KADIBANGA Benjamin", "Sexe": "M", "E-mail": "benjamin.fundi@cd-insp.com", "N° d'ordre": "EC/25.00607", "Cabinet d'attache": "INSP SARL", "N° de téléphone": "(+243)972615306"}, {"Noms": "FURUME NTALE Benito", "Sexe": "M", "E-mail": "benitofur@gmail.com", "N° d'ordre": "EC/16.00091", "Cabinet d'attache": "LABOTTE FIDUCIA SARL", "N° de téléphone": "(+243)829199974"}, {"Noms": "FWAMBA BULOBO Jean-Marie", "Sexe": "M", "E-mail": "fwambagm962@gmail.com", "N° d'ordre": "EC/16.00093", "Cabinet d'attache": "ECS", "N° de téléphone": "(+243)819970599"}, {"Noms": "IFEKA BONKOMO Nelson", "Sexe": "M", "E-mail": "nelson@ibnsarl.com", "N° d'ordre": "EC/17.00098", "Cabinet d'attache": "IBN SARL", "N° de téléphone": "(+243)817103703"}, {"Noms": "ILEO BOTINDO Madeleine", "Sexe": "F", "E-mail": "madeleineileo@yahoo.fr", "N° d'ordre": "EC/17.00100", "Cabinet d'attache": "SECOFIA SARL", "N° de téléphone": "(+243)990317590"}, {"Noms": "ITULAMYA BAZIKA Deo Gracias", "Sexe": "M", "E-mail": "bazikadeo@gmail.com", "N° d'ordre": "EC/16.00105", "Cabinet d'attache": "CECAF SARL", "N° de téléphone": "(+243)907281024"}, {"Noms": "IZE KANIKI Johnny", "Sexe": "M", "E-mail": "izejohnny01@yahoo.fr", "N° d'ordre": "EC/19.00106", "Cabinet d'attache": "SECAF SARL", "N° de téléphone": "(+243)816144948"}, {"Noms": "KABAMBA MBUSU Michel", "Sexe": "M", "E-mail": "mkabamba@corexrdc.com", "N° d'ordre": "EC/19.00108", "Cabinet d'attache": "COREX Sarl", "N° de téléphone": "(+243)999920518"}, {"Noms": "KABEMBA BARAKA", "Sexe": "M", "E-mail": "baraka.kabemba@cd.ey.com", "N° d'ordre": "EC/16.00112", "Cabinet d'attache": "EY RDC SARL", "N° de téléphone": "(+243)993435296"}, {"Noms": "KABENGELE M'PIEN LEY ", "Sexe": "M", "E-mail": "kabeley990@gmail.com", "N° d'ordre": "EC/17.00539", "Cabinet d'attache": "CARECO SARL", "N° de téléphone": "(+243)998403072"}, {"Noms": "KABEYA KABAMBI Polycarpe", "Sexe": "M", "E-mail": "p.kabeyakabambi@gmail.com", "N° d'ordre": "EC/17.00562", "Cabinet d'attache": "GINEX SARL", "N° de téléphone": "(+243)818132880"}, {"Noms": "KABEYA MUBENGA Blaise", "Sexe": "M", "E-mail": "blaise_kabeya@yahoo.fr", "N° d'ordre": "EC/16.00116", "Cabinet d'attache": "EY RDC SARL", "N° de téléphone": "(+243)978561342"}, {"Noms": "KABONGO CIKOLA Dieudonné", "Sexe": "M", "E-mail": "ciko2008@ymail.com", "N° d'ordre": "EC/20.00118", "Cabinet d'attache": "RMB & ASSOCIES", "N° de téléphone": "(+243)893902530"}, {"Noms": "KABUNDA MUSASA Bruno", "Sexe": "M", "E-mail": "brukabmuss1@yahoo.com", "N° d'ordre": "EC/16.00120", "Cabinet d'attache": "BKM COREF & ASSOCIES Sarl", "N° de téléphone": "(+243)815090576"}, {"Noms": "KABWELA WA KABWELA Didier", "Sexe": "M", "E-mail": "d.kabwela@delpartners.com", "N° d'ordre": "EC/16.00122", "Cabinet d'attache": "DEL PARTNERS SARL", "N° de téléphone": "(+243)812577497"}, {"Noms": "KAKESSE TSHIKE MUANA Emile", "Sexe": "M", "E-mail": "tshikemuana@yahoo.fr", "N° d'ordre": "EC/16.00125", "Cabinet d'attache": "AMC PARTNERS", "N° de téléphone": "(+243)855732169"}, {"Noms": "KAKULE LWANZO Claude", "Sexe": "M", "E-mail": "ccpaccaf@gmail.com", "N° d'ordre": "EC/17.00128", "Cabinet d'attache": "CCPA SARL", "N° de téléphone": "(+243)998273107"}, {"Noms": "KALAMBAY NYINDU Raphaël", "Sexe": "M", "E-mail": "nyindu@yahoo.fr", "N° d'ordre": "EC/16.00130", "Cabinet d'attache": "E-MAC SAS", "N° de téléphone": "(+243)971798907"}, {"Noms": "KAMBAJA MUBALAMATA Bruno", "Sexe": "M", "E-mail": "brunokambaja@gmail.com", "N° d'ordre": "EC/16.00136", "Cabinet d'attache": "CAAT SAS", "N° de téléphone": "(+243)818112710"}, {"Noms": "KAMPANZU MBEKU Cherif", "Sexe": "M", "E-mail": "kampanzuexpert@gmail.com", "N° d'ordre": "EC/16.00142", "Cabinet d'attache": "CBM SARLU", "N° de téléphone": "(+243)816603731"}, {"Noms": "KANINDA MUKENA Carlos", "Sexe": "M", "E-mail": "ck@kmc-cabinet.com", "N° d'ordre": "EC/19.00147", "Cabinet d'attache": "KMC SASU", "N° de téléphone": "(+243)820677212"}, {"Noms": "KAPUKA LESSY Don Christ", "Sexe": "M", "E-mail": "kapukalessi@gmail.com", "N° d'ordre": "EC/24.00586", "Cabinet d'attache": "DELOITTE SERVICES SARL", "N° de téléphone": "(+243)821700499"}, {"Noms": "KASHALE NGOY Chris", "Sexe": "M", "E-mail": "kashalechris@gmail.com", "N° d'ordre": "EC/18.00164", "Cabinet d'attache": "JMB CONSULTING SARL", "N° de téléphone": "(+243)816904849"}, {"Noms": "KASILEMBO BUJINGA Josué", "Sexe": "M", "E-mail": "jkasilembo@gmail.com", "N° d'ordre": "EC/20.00165", "Cabinet d'attache": "JK AUDIT SARLU", "N° de téléphone": "(+243)816896777"}, {"Noms": "KASONGO BATUSSE Peter", "Sexe": "M", "E-mail": "ptrkasongo2@gmail.com", "N° d'ordre": "EC/20.00166   ", "Cabinet d'attache": "FIGEFITECH SARL", "N° de téléphone": "(+243)811654496"}, {"Noms": "KASONGO DIEMU Dieudonné", "Sexe": "M", "E-mail": "kamibafor@gmail.com", "N° d'ordre": "EC/17.00167", "Cabinet d'attache": "OKM Consulting SAS", "N° de téléphone": "(+243)855281200"}, {"Noms": "KAYAMBA KAYEMBA Marco", "Sexe": "M", "E-mail": "kayambamarco@yahoo.fr", "N° d'ordre": "EC/17.00171", "Cabinet d'attache": "CAUDITEC SARL", "N° de téléphone": "(+243)998279301"}, {"Noms": "KAYEMBE KABONGO Kennedy", "Sexe": "M", "E-mail": "kenkayembe@yehoo.fr", "N° d'ordre": "EC/25.00613", "Cabinet d'attache": "AAT SARL", "N° de téléphone": "(+243)819427070"}, {"Noms": "KAZADI KOLELA Rocher", "Sexe": "M", "E-mail": "rocherkazadi@gmail.com", "N° d'ordre": "EC/19.00175", "Cabinet d'attache": "AGESFO SARL", "N° de téléphone": "(+243)998954565"}, {"Noms": "KIMBEMBE KIAMVU Simon", "Sexe": "M", "E-mail": "s.kimbembe@mmpartnerscongo.com", "N° d'ordre": "EC/16.00184", "Cabinet d'attache": "MMPARTNERS CONGO SARL", "N° de téléphone": "(+243)999916552"}, {"Noms": "KITENGE KAPENGA Norbert", "Sexe": "M", "E-mail": "norbertkitenge@yahoo.fr", "N° d'ordre": "EC/17.00193", "Cabinet d'attache": "AMC PARTNERS", "N° de téléphone": "(+243)999947393"}, {"Noms": "KOMBA MUNGANGA Alain", "Sexe": "M", "E-mail": "alainmunganga@gmail.com", "N° d'ordre": "EC/16.00198", "Cabinet d'attache": "CAEC SARL", "N° de téléphone": "(+243)998087847"}, {"Noms": "KUFUTAMA KOY Kafaire", "Sexe": "M", "E-mail": "kafairekoy@gmail.com", "N° d'ordre": "EC/18.00203", "Cabinet d'attache": "CACG SARL", "N° de téléphone": "(+243)816899788"}, {"Noms": "KUSAMA MYESI Gabriel", "Sexe": "M", "E-mail": "kusamamyesi@gmail.com", "N° d'ordre": "EC/17.00205", "Cabinet d'attache": "JASBI SARL", "N° de téléphone": "(+243)998379602"}, {"Noms": "LANDU NZINGA Bill", "Sexe": "M", "E-mail": "landubill77@gmail.com", "N° d'ordre": "EC/18.00209", "Cabinet d'attache": "AMS SARL CONSULTANTS SARL", "N° de téléphone": "(+243)816879015"}, {"Noms": "LIGBAKELO MAYKPELE Samy", "Sexe": "M", "E-mail": "ligbakelo@yahoo.fr", "N° d'ordre": "EC/18.00214", "Cabinet d'attache": "CTRS SARLU", "N° de téléphone": "(+243)818148848"}, {"Noms": "LIKAMBO KWADJE Dieudonné", "Sexe": "M", "E-mail": "dieudonnelikambo@yahoo.fr", "N° d'ordre": "EC/16.00215", "Cabinet d'attache": "AUDIGEC SARL", "N° de téléphone": "(+243)998126186"}, {"Noms": "LOKESA SUAMUNU Thierry", "Sexe": "M", "E-mail": "thierry_lokesa@yahoo.fr", "N° d'ordre": "EC/16.00218", "Cabinet d'attache": "T.L PARTNERS-CONGO SARL", "N° de téléphone": "(+243)899501186"}, {"Noms": "LUKIMUENA KUBA Samuelson", "Sexe": "M", "E-mail": "s.lukimuena@cornerstone-cd.com", "N° d'ordre": "EC/16.00223", "Cabinet d'attache": "CFI SARL", "N° de téléphone": "(+243)819934759"}, {"Noms": "LUMANI NGOY Paul", "Sexe": "M", "E-mail": "paul.lumani@cd.ey.com", "N° d'ordre": "EC/20.00225", "Cabinet d'attache": "EY RDC SARL", "N° de téléphone": "(+243)970808709"}, {"Noms": "LUMU TCHATA Joseph", "Sexe": "M", "E-mail": "jlumu@yahoo.fr", "N° d'ordre": "EC/17.00229", "Cabinet d'attache": "New ANOU CONSULTING SARL", "N° de téléphone": "(+243)815981162"}, {"Noms": "LUNGANGI KITUNDU Françoise", "Sexe": "F", "E-mail": "flungangi@drcexpertises.net.", "N° d'ordre": "EC/16.00231", "Cabinet d'attache": "DEX SAS", "N° de téléphone": "(+243)998046513"}, {"Noms": "LUNGONZO MBUY François", "Sexe": "M", "E-mail": "flungonzo@gmail.com        ", "N° d'ordre": "EC/16.00232", "Cabinet d'attache": "JVL SAS", "N° de téléphone": "(+243)998139161"}, {"Noms": "LUVUEZO BIKINDU Simon", "Sexe": "M", "E-mail": "sluvuezobikindu@yahoo.com", "N° d'ordre": "EC/16.00236", "Cabinet d'attache": "LMN & ASSOCIES SAS", "N° de téléphone": "(+243)998242892"}, {"Noms": "MABATA NTANTU Nico", "Sexe": "M", "E-mail": "nmabata@kpmg.cd", "N° d'ordre": "EC/16.00243", "Cabinet d'attache": "KPMG RDC SA", "N° de téléphone": "(+243)828504935"}, {"Noms": "MABIALA MAVINGA Jules", "Sexe": "M", "E-mail": "m.jules@mmpartnerscongo.com", "N° d'ordre": "EC/16.00246", "Cabinet d'attache": "MMPARTNERS CONGO SARL", "N° de téléphone": "(+243)999907257"}, {"Noms": "MABIZA MAKAYI Delord", "Sexe": "M", "E-mail": "delord.mabiza@bdo-ea.com", "N° d'ordre": "EC/16.00247", "Cabinet d'attache": "BDO AUDIT SARL", "N° de téléphone": "(+243)971050212"}, {"Noms": "MABULU BENANKAZI LOLO Jean-Pierre", "Sexe": "M", "E-mail": "lolojpmabulu@gmail.com", "N° d'ordre": "EC/18.00248", "Cabinet d'attache": "CAAF SAS", "N° de téléphone": "(+243)820831745"}, {"Noms": "MAKENGO MANUNGA Emmanuel", "Sexe": "M", "E-mail": "emmanuelmakengo2@yahoo.fr", "N° d'ordre": "EC/17.00252", "Cabinet d'attache": "AGEC SARL", "N° de téléphone": "(+243)810549470"}, {"Noms": "MAKONDA TEKASALA Blanchard", "Sexe": "M", "E-mail": "tekamakonda@gmail.com", "N° d'ordre": "EC/25.00615", "Cabinet d'attache": "J.K. AUDIT SARLU", "N° de téléphone": "(+243)85119389"}, {"Noms": "MAKUNGA NIANGI Max Simon", "Sexe": "M", "E-mail": "max_mkga@befac-mkga.com", "N° d'ordre": "EC/16.00253", "Cabinet d'attache": "BEFAC MKGA & Associés SARL   ", "N° de téléphone": "(+243)820019906"}, {"Noms": "MAMBU LUYALU MUSONGA'KEL Egide", "Sexe": "M", "E-mail": "egide.mambu@africamel.net", "N° d'ordre": "EC/18.00259", "Cabinet d'attache": "ECCE SARL", "N° de téléphone": "(+243)824682000"}, {"Noms": "MAMPASI MABAYA Dieudonné", "Sexe": "M", "E-mail": "dieudonne.mampasi@strong-nkv.cd", "N° d'ordre": "EC/16.00261", "Cabinet d'attache": "MGI STRONG NKV SAS", "N° de téléphone": "(+243)817007176"}, {"Noms": "MAMPUYA KALENGA Robert", "Sexe": "M", "E-mail": "mampuya.robertk@gmail.com", "N° d'ordre": "EC/17.00262", "Cabinet d'attache": "TECPRO EXPERTISE SARLU", "N° de téléphone": "(+243)817925079"}, {"Noms": "MANKENDA NANSINA Sébastien", "Sexe": "M", "E-mail": "nmankenda@hotmail.com", "N° d'ordre": "EC/16.00264", "Cabinet d'attache": "K2M PARTNERS SARL", "N° de téléphone": "(+243)898975959"}, {"Noms": "MASIALA FINDUO Blaise", "Sexe": "M", "E-mail": "masialab@gmail.com", "N° d'ordre": "EC/16.00270", "Cabinet d'attache": "F COMPTA SARL", "N° de téléphone": "(+243)816866913"}, {"Noms": "MATAKA BILANGA Paul", "Sexe": "M", "E-mail": "merjesmataka@gmail.com", "N° d'ordre": "EC/16.00272", "Cabinet d'attache": "RMC-MAT EXPERTISES SARL", "N° de téléphone": "(+243)824557661"}, {"Noms": "MATONDO MAVUANDA José", "Sexe": "M", "E-mail": "jose.matondo@strong-nkv.cd", "N° d'ordre": "EC/20.00275", "Cabinet d'attache": "MGI STRONG NKV SAS", "N° de téléphone": "(+243)824226879"}, {"Noms": "MATONDO MIOKO Jean", "Sexe": "M", "E-mail": "mickmatondo1@yahoo.fr", "N° d'ordre": "EC/17.00276", "Cabinet d'attache": "AAS SARL", "N° de téléphone": "(+243)828293887"}, {"Noms": "MATUNGA KAPONGO Ted", "Sexe": "M", "E-mail": "tedmatunga@gmail.com", "N° d'ordre": "EC/16.00277", "Cabinet d'attache": "BDO AUDIT SARL", "N° de téléphone": "(+243)813151513"}, {"Noms": "MATUTALA KULA PITSHOU", "Sexe": "M", "E-mail": "matutalakula@yahoo.fr", "N° d'ordre": "EC/19.00278", "Cabinet d'attache": "COFICA SARL", "N° de téléphone": "(+243)899418535"}, {"Noms": "MAVUNGU MAVWANGA Gervais", "Sexe": "M", "E-mail": "gmavungu@deloitte.fr", "N° d'ordre": "EC/16.00281", "Cabinet d'attache": "DELOITTE SERVICES SARL", "N° de téléphone": "(+243)859998004"}, {"Noms": "MAWALA NYIMI Antoine", "Sexe": "M", "E-mail": "manyimi@hotmail.com", "N° d'ordre": "EC/19.00282", "Cabinet d'attache": "AMN'S SARL Sarl", "N° de téléphone": "(+243)999959958"}, {"Noms": "MAWANGU NDOLUVUALU Anderson", "Sexe": "M", "E-mail": "anderson@taaex.net", "N° d'ordre": "EC/19.00283", "Cabinet d'attache": "TAAEX SARLU", "N° de téléphone": "(+243)998397801"}, {"Noms": "MAYI KAYIMBONGE Désiré", "Sexe": "M", "E-mail": "desimayi@gmail.com", "N° d'ordre": "EC/17.00286", "Cabinet d'attache": "CASOL SARL", "N° de téléphone": "(+243)816432674"}, {"Noms": "MBATSHI TOVO Blaise", "Sexe": "M", "E-mail": "blaise.mbatshi@bdo-ea.com", "N° d'ordre": "EC/16.00293", "Cabinet d'attache": "BDO AUDIT SARL", "N° de téléphone": "(+243)813391217"}, {"Noms": "MBAYA KANGOMBA MBABU Maurice", "Sexe": "M", "E-mail": "mauricembaya80@gmail.com", "N° d'ordre": "EC/16.00294", "Cabinet d'attache": "CAAT SAS", "N° de téléphone": "(+243)819847478"}, {"Noms": "MBAYA MBAYA Célestin", "Sexe": "M", "E-mail": "celestin.mbaya@secofic.cd", "N° d'ordre": "EC/16.00295", "Cabinet d'attache": "SECOFIC SARL", "N° de téléphone": "(+243)995901291"}, {"Noms": "MBODO BUASA Anaclet", "Sexe": "M", "E-mail": "anaclet.secofic@gmail.com", "N° d'ordre": "EC/18.00553", "Cabinet d'attache": "ATAH SARL", "N° de téléphone": "(+243)813170409"}, {"Noms": "MBOYO NKULI Jean Rigobert", "Sexe": "M", "E-mail": "jrmboyodigo@gmail.com", "N° d'ordre": "EC/16.00297", "Cabinet d'attache": "SORECA SARL", "N° de téléphone": "(+243)814037383"}, {"Noms": "MBUMBA MBUDI Joseph", "Sexe": "M", "E-mail": "josembumba@yahoo.fr", "N° d'ordre": "EC/17.00300", "Cabinet d'attache": "JMB CONSULTING SARL", "N° de téléphone": "(+243)998686125"}, {"Noms": "MBUWA MONGELE Cyrille", "Sexe": "M", "E-mail": "c.mbuwa@cpmconsultingsarl.com", "N° d'ordre": "EC/17.00302", "Cabinet d'attache": "CPM CONSULTING SARL", "N° de téléphone": "(+243)815208327"}, {"Noms": "MENA NKUABILEKO Nadine", "Sexe": "F", "E-mail": "nadine.mena@bdo-ea.com", "N° d'ordre": "EC/16.00305", "Cabinet d'attache": "BDO AUDIT SARL", "N° de téléphone": "(+243)898953548"}, {"Noms": "MFUMUMPOKO MONSEMPO Eddy", "Sexe": "M", "E-mail": "e.mfumu@mmpartnerscongo.com", "N° d'ordre": "EC/19.00308", "Cabinet d'attache": "MMPARTNERS CONGO SARL", "N° de téléphone": "(+243)818127630"}, {"Noms": "MINGASHANGA MIKOBI Emmanuel", "Sexe": "M", "E-mail": "mingaemma@hotmail.com", "N° d'ordre": "EC/19.00310", "Cabinet d'attache": "MMPARTNERS CONGO SARL", "N° de téléphone": "(+243)851727465"}, {"Noms": "MOLELE BOFOTOLA Gabriel", "Sexe": "M", "E-mail": "molelebofotola@outlook.fr", "N° d'ordre": "EC/24.00593", "Cabinet d'attache": "MGI STRONG NKV SAS", "N° de téléphone": "(+243)822848422"}, {"Noms": "MPANYA KI'EPENDA Nyckain", "Sexe": "M", "E-mail": "mpanyanyckain@yahoo.fr", "N° d'ordre": "EC/16.00318", "Cabinet d'attache": "FAGEFI SARL", "N° de téléphone": "(+243)998745885"}, {"Noms": "MPOP AWUNG Florent", "Sexe": "M", "E-mail": "florentmpop45@gmail.com", "N° d'ordre": "EC/16.00321", "Cabinet d'attache": "EMERGENCE CONSULTING SARL", "N° de téléphone": "(+243)827275187"}, {"Noms": "MUAKA MULENDA Gerard", "Sexe": "M", "E-mail": "muakagerard18@gmail.com", "N° d'ordre": "EC/19.00322", "Cabinet d'attache": "SECFA SARL", "N° de téléphone": "(+243)815261939"}, {"Noms": "MUAMBA TSHILUMBA Simon", "Sexe": "M", "E-mail": "simon_master@yahoo.fr", "N° d'ordre": "EC/17.00324", "Cabinet d'attache": "SMA", "N° de téléphone": "(+243)995961063"}, {"Noms": "MUKAWA NINGA Nanou", "Sexe": "M", "E-mail": "mukawananou20@gmail.com", "N° d'ordre": "EC/19.00342", "Cabinet d'attache": "DACO SARL", "N° de téléphone": "(+243)811918798"}, {"Noms": "MUKE NTAMWANGA Grâce", "Sexe": "M", "E-mail": "mukegracentamwa@gmail.com", "N° d'ordre": "EC/18.00343", "Cabinet d'attache": "BDO AUDIT SARL", "N° de téléphone": "(+243)818281698"}, {"Noms": "MUKENDI LUTULU François", "Sexe": "M", "E-mail": "mukendifrancois13@gmail.com", "N° d'ordre": "EC/17.00346    ", "Cabinet d'attache": "ACOFIG SARL", "N° de téléphone": "(+243)810492183"}, {"Noms": "MUKOTA MUTEBA MBAYO", "Sexe": "M", "E-mail": "m.mukota@mmpartnerscongo.com", "N° d'ordre": "EC/16.00350", "Cabinet d'attache": "MMPARTNERS CONGO SARL", "N° de téléphone": "(+243)978003703"}, {"Noms": "MULEMVO BIDUAKA Bienvenu", "Sexe": "M", "E-mail": "bienvenubiduaka2@gmail.com", "N° d'ordre": "EC/19.00353", "Cabinet d'attache": "CREDES EXCO SARL", "N° de téléphone": "(+243)821860057"}, {"Noms": "MUNKENI KIEKIE Eliane", "Sexe": "F", "E-mail": "eliane.mk@hotmail.fr", "N° d'ordre": "EC/16.00360", "Cabinet d'attache": "ACF SARL", "N° de téléphone": "(+243)810558370"}, {"Noms": "MUSOLE MWANAMUPENZI Moïse", "Sexe": "M", "E-mail": "musolemoise2019@gmail.com", "N° d'ordre": "EC/16.00366", "Cabinet d'attache": "GMC SARL", "N° de téléphone": "(+243)816111705"}, {"Noms": "MUTANDA NGOY-MUANA Jean-Antoine", "Sexe": "M", "E-mail": "jean.antoine.mutanda@cd.ey.com", "N° d'ordre": "EC/18.00369", "Cabinet d'attache": "EY RDC SARL", "N° de téléphone": "(+243)812037727"}, {"Noms": "MUTANGILAYI MUTEBA Yorick", "Sexe": "M", "E-mail": "ymutangilay@gmail.com", "N° d'ordre": "EC/24.00594", "Cabinet d'attache": "BELKAS GROUP SAS", "N° de téléphone": "(+243)812311068"}, {"Noms": "MUTEBA MUKENDI Yollande", "Sexe": "F", "E-mail": "myollande@gmail.com", "N° d'ordre": "EC/19.00371", "Cabinet d'attache": "DACO SARL", "N° de téléphone": "(+243)998452332"}, {"Noms": "MUTOMBO NASALININI Yves ", "Sexe": "M", "E-mail": "yves213@gmail.com", "N° d'ordre": "EC/20.00556", "Cabinet d'attache": "CAUDITEC SARL", "N° de téléphone": "(+243)812211828"}, {"Noms": "MUYEKA KAZANGA Leki", "Sexe": "M", "E-mail": "l.muyeka@z-finances.com", "N° d'ordre": "EC/17.00377", "Cabinet d'attache": "GMC SARL", "N° de téléphone": "(+243)858514660"}, {"Noms": "MUZABA MAMBAMBA Eric", "Sexe": "M", "E-mail": "emuzaba@kpmg.cd", "N° d'ordre": "EC/24.00595", "Cabinet d'attache": "KPMG RDC SA", "N° de téléphone": "(+243)811947418"}, {"Noms": "MWANANZAMBI Daniel Ephraïm", "Sexe": "M", "E-mail": "d.mwananzambi@mmpartnerscongo.com", "N° d'ordre": "EC/16.00473", "Cabinet d'attache": "MMPARTNERS CONGO SARL", "N° de téléphone": "(+243)824538441"}, {"Noms": "NDANGI NDANGANI Théophile", "Sexe": "M", "E-mail": "tndanguy@gmail.com", "N° d'ordre": "EC/16.00387", "Cabinet d'attache": "FORVIS MAZARS RDC", "N° de téléphone": "(+243)823573788"}, {"Noms": "NDOKO FUMU Odon", "Sexe": "M", "E-mail": "odonndoko8@gmail.com", "N° d'ordre": "EC/19.00391", "Cabinet d'attache": "ONF SARLU", "N° de téléphone": "(+243)814847070"}, {"Noms": "NDONGO NTIERE Gaby", "Sexe": "M", "E-mail": "ndongogaby30@gmail.com", "N° d'ordre": "EC/16.00392", "Cabinet d'attache": "NN SARL", "N° de téléphone": "(+243)854348339"}, {"Noms": "NDUMB MBANG Didier", "Sexe": "M", "E-mail": "didiermbang@gmail.com", "N° d'ordre": "EC/18.00393", "Cabinet d'attache": " B.E SARL", "N° de téléphone": "(+243)819591098"}, {"Noms": "NDUSHA BIRHAFANWA Xavier", "Sexe": "M", "E-mail": "ndusha@quitusconsult.cd", "N° d'ordre": "EC/16.00394", "Cabinet d'attache": "QC SARL", "N° de téléphone": "(+243)815086052"}, {"Noms": "NGANDU LHOME Benjamin", "Sexe": "M", "E-mail": "benjamin.ngandu@bdo-ea.com", "N° d'ordre": "EC/16.00397", "Cabinet d'attache": "BDO AUDIT SARL", "N° de téléphone": "(+243)815295713"}, {"Noms": "NGANDU WA NGANDU Jean-Marie", "Sexe": "M", "E-mail": "jean-marie.ngandu@caf-consulting.com", "N° d'ordre": "EC/16.00400", "Cabinet d'attache": "CAF CONSULTING SARL", "N° de téléphone": "(+243)818145122"}, {"Noms": "NGOIE WA KASONGO Augustin", "Sexe": "M", "E-mail": "cecaf_nwk@yahoo.fr", "N° d'ordre": "EC/16.00404", "Cabinet d'attache": "CECAF SARL", "N° de téléphone": "(+243)818130580"}, {"Noms": "NGOYI KABEMBA Benjamin", "Sexe": "M", "E-mail": "ngoyibenjamin11@gmail.com", "N° d'ordre": "EC/16.00408", "Cabinet d'attache": "LACOURCELLE SARLU", "N° de téléphone": "(+243)819593692"}, {"Noms": "NGUBI LUTETE Mac", "Sexe": "M", "E-mail": "cmngubi@gmail.com", "N° d'ordre": "EC/18.00409   ", "Cabinet d'attache": "DWAC SARL", "N° de téléphone": " (+243)972009548"}, {"Noms": "NKENKO NDOMBELE Blaise", "Sexe": "M", "E-mail": "blaisenkenko@gmail.com", "N° d'ordre": "EC/17.00414", "Cabinet d'attache": "ACF SARL", "N° de téléphone": "(+243)815792319"}, {"Noms": "NKOLELA KABULU Joel", "Sexe": "M", "E-mail": "joelnkolela@yahoo.fr", "N° d'ordre": "EC/19.00417", "Cabinet d'attache": "PDLC SARLU", "N° de téléphone": "(+243)822992661"}, {"Noms": "NKUANGA MBUINGA Jean Paul", "Sexe": "M", "E-mail": "jeanpaulnkuangambuinga@gmail.com", "N° d'ordre": "EC/25.00603", "Cabinet d'attache": "LMN & ASSOCIES SAS", "N° de téléphone": "(+243)999309712"}, {"Noms": "NKUMBA LUMFUAKIADI Francis", "Sexe": "M", "E-mail": "francis.nkumba@cd-insp.com", "N° d'ordre": "EC/16.00420", "Cabinet d'attache": "INSP SARL", "N° de téléphone": "(+243)976059437"}, {"Noms": "NKUVU WENA Daddy", "Sexe": "M", "E-mail": "daddy.nkuvu@strong-nkv.cd", "N° d'ordre": "EC/16.00422", "Cabinet d'attache": "MGI STRONG NKV SAS", "N° de téléphone": "(+243)894506861"}, {"Noms": "NKUVU-A-MBINDA WENA Danny", "Sexe": "M", "E-mail": "danny.nkuvu@strong-nkv.cd", "N° d'ordre": "EC/16.00423", "Cabinet d'attache": "MGI STRONG NKV SAS", "N° de téléphone": "(+243)818117654"}, {"Noms": "NSAYI LUKOMBO Rubens", "Sexe": "M", "E-mail": "rubensentreprise@gmail.com", "N° d'ordre": "EC/16.00425", "Cabinet d'attache": "CCS SARL", "N° de téléphone": "(+243)999124915"}, {"Noms": "NSIKU DIASIVI Jonathan", "Sexe": "M", "E-mail": "jonathan.nsiku@cd-insp.com", "N° d'ordre": "EC/24.00598", "Cabinet d'attache": "INSP SARL", "N° de téléphone": "(+243)972615307"}, {"Noms": "NSILULU BAHELELE Gabriel", "Sexe": "M", "E-mail": "bureau_cefao@yahoo.fr", "N° d'ordre": "EC/16.00427", "Cabinet d'attache": "CEFAO", "N° de téléphone": "(+243)998921784"}, {"Noms": "NTUMBA MPUTU Odilon", "Sexe": "M", "E-mail": "odilontumba@ecrrdc.com", "N° d'ordre": "EC/16.00435", "Cabinet d'attache": "ECR SARL", "N° de téléphone": "(+243)824448070"}, {"Noms": "NTUMBA MUTAMBAYI Claude ", "Sexe": "M", "E-mail": "claudenntumba@gmail.com", "N° d'ordre": "EC/19.00437   ", "Cabinet d'attache": "KPMG RDC SA", "N° de téléphone": "(+243)828504968"}, {"Noms": "NYOK KABUL SADEL", "Sexe": "M", "E-mail": "sadelnyok@gmail.com", "N° d'ordre": "EC/25.00624", "Cabinet d'attache": "DELOITTE SERVICES SARL", "N° de téléphone": "(+243)813378264"}, {"Noms": "NZAILU BASINSA Benjamin", "Sexe": "M", "E-mail": "benjamin.nzailu@abncd.com", "N° d'ordre": "EC/16.00441", "Cabinet d'attache": "ABN SAS ", "N° de téléphone": "(+243)998188585"}, {"Noms": "NZAILU NSIMBA Herbert", "Sexe": "M", "E-mail": "hnzailu@gmail.com", "N° d'ordre": "EC/24.00599", "Cabinet d'attache": "ABN SAS", "N° de téléphone": "(+243)820407403"}, {"Noms": "NZITA TSASA Gary", "Sexe": "M", "E-mail": "nzitagary@gmail.com", "N° d'ordre": "EC/19.00448", "Cabinet d'attache": "DACO SARL", "N° de téléphone": "(+243)811837388"}, {"Noms": "NZOIMBENGENE LUYINDULA Bob David", "Sexe": "M", "E-mail": "bnzoimbengene@deloitte.fr", "N° d'ordre": "EC/16.00449", "Cabinet d'attache": "DELOITTE SERVICES SARL", "N° de téléphone": "(+243)859998032"}, {"Noms": "OKENDE MBUNGU Adolphe", "Sexe": "M", "E-mail": "adolphe.okende@lapradellec.com", "N° d'ordre": "EC/16.00454", "Cabinet d'attache": "PDLC SARLU", "N° de téléphone": "(+243)810837185"}, {"Noms": "OPOKI YAMO Mathieu", "Sexe": "M", "E-mail": "opokyam@gmail.com", "N° d'ordre": "EC/17.00459", "Cabinet d'attache": "SECOFIA SARL", "N° de téléphone": "(+243)894297246"}, {"Noms": "OVO YATUIKWAMO-FUKIAU Ranield", "Sexe": "F", "E-mail": "oranield@gmail.com", "N° d'ordre": "EC/19.00460", "Cabinet d'attache": "R.O&PARTNERS ", "N° de téléphone": "(+243)998946925"}, {"Noms": "PATI NDOMPETELO Jean-Marie", "Sexe": "M", "E-mail": "jeanmariepati2004@yahoo.fr", "N° d'ordre": "EC/17.00465", "Cabinet d'attache": "AAT SARL", "N° de téléphone": "(+243)818143839"}, {"Noms": "PAY-PAY  MULINDU Pascal", "Sexe": "M", "E-mail": "paypay_ppm@yahoo.fr", "N° d'ordre": "EC/16.00466", "Cabinet d'attache": "ACGC SARLU", "N° de téléphone": "(+243)999928202"}, {"Noms": "PFINGU NSUAMI Jean-Pierre", "Sexe": "M", "E-mail": "jppfingu@jpp-associes.com", "N° d'ordre": "EC/16.00467", "Cabinet d'attache": "JPP & Associés SARL", "N° de téléphone": "(+243)817005092"}, {"Noms": "PFINGU SIMBU Rosette", "Sexe": "F", "E-mail": "rpfingu@jpp-associes.com", "N° d'ordre": "EC/19.00468", "Cabinet d'attache": "JPP & Associés SARL", "N° de téléphone": "(+243)814444705"}, {"Noms": "PHANZU NLANDU Philippe", "Sexe": "M", "E-mail": "pphanzu@gpopartners.com", "N° d'ordre": "EC/19.00470", "Cabinet d'attache": "GPO SARL", "N° de téléphone": "(+243)818149744"}, {"Noms": "PUNGA ALANGA Joël", "Sexe": "M", "E-mail": "joelpunga1@gmail.com", "N° d'ordre": "EC/25.00623", "Cabinet d'attache": "DELOITTE SERVICES SARL", "N° de téléphone": "(+243)826808889"}, {"Noms": "SAMBA ZAMAMBU Louis", "Sexe": "M", "E-mail": "louissamba56@yahoo.fr", "N° d'ordre": "EC/16.00476", "Cabinet d'attache": "AAS SARL", "N° de téléphone": "(+243)811400614"}, {"Noms": "TANDU ROVAT Jean-Pierre", "Sexe": "M", "E-mail": "jean_pierre.tandu@trusttbg.com", "N° d'ordre": "EC/18.00488", "Cabinet d'attache": "TRUST BUSINESS GUARANTEE RDC SARL", "N° de téléphone": "(+243)829784500"}, {"Noms": "TSHIBANDA SABWA Jean-Pierre", "Sexe": "M", "E-mail": "focalpoint.dg@gmail.com", "N° d'ordre": "EC/17.00499", "Cabinet d'attache": "SECOFISC SARL", "N° de téléphone": "(+243)972854747"}, {"Noms": "TSHIEBWE KADISHA Olivier", "Sexe": "M", "E-mail": "olivier.tshiebwe@gmail.com", "N° d'ordre": "EC/24.00600", "Cabinet d'attache": "DELOITTE SERVICES SARL", "N° de téléphone": "(+243)823927981"}, {"Noms": "TSHILENGE MWINDILA Pitshou", "Sexe": "M", "E-mail": "tshilengepitshou@gmail.com", "N° d'ordre": "EC/18.00505", "Cabinet d'attache": "ACF SARL", "N° de téléphone": "(+243)815133564"}, {"Noms": "TSHIYOYO DJIBA Honoré", "Sexe": "M", "E-mail": "tshiyoyohonore@yahoo.fr", "N° d'ordre": "EC/16.00509", "Cabinet d'attache": "SECOFIC SARL", "N° de téléphone": "(+243)998519742"}, {"Noms": "TULENGULULA MULUMBA Jean-Marie", "Sexe": "M", "E-mail": "jtulengulula@gmail.com", "N° d'ordre": "EC/19.00512", "Cabinet d'attache": "MMPARTNERS CONGO SARL", "N° de téléphone": "(+243)843989500"}, {"Noms": "TUMBA KABALAMBI Jean-Marie", "Sexe": "M", "E-mail": "jeanmarie747@hotmail.com", "N° d'ordre": "EC/16.00513", "Cabinet d'attache": "AMS SARL CONSULTANTS SARL", "N° de téléphone": "(+243)998208011"}, {"Noms": "TUNDA NGIEFU Yves", "Sexe": "M", "E-mail": "yves.tunda@lacoteadvisory.com", "N° d'ordre": "EC/18.00514", "Cabinet d'attache": "LACOTE AAT SARL ", "N° de téléphone": "(+243)818970523"}, {"Noms": "VANGU KI-TULANDA WA BAFUANGA Joseph", "Sexe": "M", "E-mail": "josephvangu71@gmail.com", "N° d'ordre": "EC/16.00521", "Cabinet d'attache": "AACS SARL", "N° de téléphone": "(+243)816528164"}, {"Noms": "WAULA BALOMBA Merveille", "Sexe": "M", "E-mail": "yanzambe@gmail.com", "N° d'ordre": "EC/25.00626", "Cabinet d'attache": "DELOITTE SERVICES SARL", "N° de téléphone": "(+243)816889866"}, {"Noms": "YANGA LUMBAHE Simon", "Sexe": "M", "E-mail": "cagescom2002@gmail.com ", "N° d'ordre": "EC/16.00524", "Cabinet d'attache": "CAGESCOM", "N° de téléphone": "(+243)999910998"}, {"Noms": "YATALA NGOY Constantin", "Sexe": "M", "E-mail": "cyatala7333@gmail.com", "N° d'ordre": "EC/16.00525", "Cabinet d'attache": "FIGEFITECH SARL", "N° de téléphone": "(+243)818124322 "}, {"Noms": "YONGA ONAKOY Jean-Jacques", "Sexe": "M", "E-mail": "burocof@yahoo.fr", "N° d'ordre": "EC/16.00526", "Cabinet d'attache": "ACF SARL", "N° de téléphone": "(+243)810037298"}, {"Noms": "YRUNG KAPALANG SARAH", "Sexe": "F", "E-mail": "sarah.yrung@cd.ey.com", "N° d'ordre": "EC/25.00627", "Cabinet d'attache": "EY RDC SARL", "N° de téléphone": "(+243)810782296"}]	2026-03-20 10:24:07.937909+00
36072e6c-2e76-49fe-b162-4740e0c970ee	modele_sec (4).xlsx	sec	a2375bac-4a9f-4ed8-b674-a1807543c744	93	success	[{"E-mail": "benjamin.nzailu@abncd.com", "N° d'ordre": "SEC/18.00001", "Dénomination": "ABN NZAILU & CO SAS", "Raison sociale": "ABN SAS", "Associé gérant": "NZAILU BASINSA Benjamin", "N° de téléphone": "(+243)829000113"}, {"E-mail": "mickmatondo@yahoo.fr", "N° d'ordre": "SEC/24.00122", "Dénomination": "AFRICAN ACCOUNT SERVICES ", "Raison sociale": "AAS SARL", "Associé gérant": "MATONDO MIOKO Jean Pierre", "N° de téléphone": "(+243)828293887"}, {"E-mail": "andre.foko@aftassocies.com", "N° d'ordre": "SEC/17.00002", "Dénomination": "AFT CONSULTING ASSOCIES SARL", "Raison sociale": "AFT SARL", "Associé gérant": "FOKO TOMENA André", "N° de téléphone": "(+243)818126663"}, {"E-mail": "cboshabo@ajm-associates.org", "N° d'ordre": "SEC/16.00003", "Dénomination": "AJM & ASSOCIATES SARL", "Raison sociale": "AJM & ASSOCIATES SARL", "Associé gérant": "BOSHABO NKONGO COLOMBO", "N° de téléphone": "(+243)992006191"}, {"E-mail": "contact@amsconsultantscongo.com", "N° d'ordre": "SEC/20.00005", "Dénomination": "AMS CONSULTANTS SARL", "Raison sociale": "AMS SARL", "Associé gérant": "TUMBA KABALAMBI Jean Marie", "N° de téléphone": "(+243)998208011"}, {"E-mail": "acgcongo@yahoo.fr", "N° d'ordre": "SEC/19.00006", "Dénomination": "ANALYSES & CONSEILS EN GESTION AU CONGO SARLU", "Raison sociale": "ACGC SARLU", "Associé gérant": "PAY-PAY MULINDU Pascal", "N° de téléphone": "(+243)999928202"}, {"E-mail": "mawalaantoine@gmail.com", "N° d'ordre": "SEC/24.00106", "Dénomination": "AUDIT & MANAGEMENT NETWORK SERVICES SARL ", "Raison sociale": "AMN'S SARL", "Associé gérant": "MAWALA NYIMI Antoine", "N° de téléphone": "(+243)819959958"}, {"E-mail": "infoaatadvisor@gmail.com", "N° d'ordre": "SEC/24.00107", "Dénomination": "AUDIT ACCOUNTS AND TAXE ADVISOR SARL", "Raison sociale": "AAT SARL", "Associé gérant": "PATI NDOMPETELO Jean-Marie", "N° de téléphone": "(+243)818143839"}, {"E-mail": "christian.m@acf-conseil.com", "N° d'ordre": "SEC/16.00007", "Dénomination": "AUDIT COMPTABILITE FISCALITE SARL", "Raison sociale": "ACF SARL", "Associé gérant": "MUNKENI KIEKE Eliane", "N° de téléphone": "(+243)846670935"}, {"E-mail": "audigec1995@yahoo.fr", "N° d'ordre": "SEC/18.00008", "Dénomination": "AUDIT GESTION ET COMPTABILITE", "Raison sociale": "AUDIGEC", "Associé gérant": "LIKAMBO KWADJE Dieudonné", "N° de téléphone": "(+243)811601052"}, {"E-mail": "agec@agec-rdc.com", "N° d'ordre": "SEC/18.00019", "Dénomination": "AUDIT GESTION ET CONSEILS SARL", "Raison sociale": "AGeC SARL", "Associé gérant": "BENGA NSUNGI Jolie Rachel", "N° de téléphone": "(+243)815260623"}, {"E-mail": "agesfodrc@gmail.com", "N° d'ordre": "SEC/18.00009", "Dénomination": "AUDIT GESTION FORMATION", "Raison sociale": "AGESFO SARL", "Associé gérant": "KAZADI KOLELA Rocher", "N° de téléphone": "(+243)998540358"}, {"E-mail": "amc.partners2020@gmail.com", "N° d'ordre": "SEC/19.00010", "Dénomination": "AUDIT MANAGEMENT AND CONSULTING PARTNERS", "Raison sociale": "AMC PARTNERS", "Associé gérant": "KITENGE KAPENGA Norbert", "N° de téléphone": "(+243)999947393"}, {"E-mail": "atahrdc@gmail.com", "N° d'ordre": "SEC/23.00102", "Dénomination": "AUDIT, TAX AND ACOUTING HOUSE SARL", "Raison sociale": "ATAH SARL", "Associé gérant": "MBODO BUASA ANACLET", "N° de téléphone": "(+243)813170409"}, {"E-mail": "blaise.mbatshi@bdo-ea.com", "N° d'ordre": "SEC/19.00013", "Dénomination": "BDO AUDIT SARL", "Raison sociale": "BDO ", "Associé gérant": "MBATSHI TOVO Blaise", "N° de téléphone": "(+243)813391217"}, {"E-mail": "contact@befac-mkga.com", "N° d'ordre": "SEC/17.00015", "Dénomination": "BEFAC MKGA & Associés SARL", "Raison sociale": "BEFAC MKGA & A", "Associé gérant": "MAKUNGA NIANGI Max Simon", "N° de téléphone": "(+243)815976339"}, {"E-mail": "info@belkasgroup.com", "N° d'ordre": "SEC/23.00098", "Dénomination": "BELKAS GROUP SAS", "Raison sociale": "BELKAS GROUP SAS", "Associé gérant": "MUTANGILAYI MUTEBA  Yorick", "N° de téléphone": "(+243)842111970"}, {"E-mail": "cedrick.bukasa@bma-cd.com", "N° d'ordre": "SEC/23.00103", "Dénomination": "BM ASSOCIATES SARL", "Raison sociale": "BMA SARL", "Associé gérant": "BUKASA WA BUKASA Cedrick", "N° de téléphone": "(+243)815215327"}, {"E-mail": "bmmconsulte@gmail.com", "N° d'ordre": "SEC/24.00109", "Dénomination": "BMM CONSULTING SARL", "Raison sociale": "BMM CONSULTING SARL", "Associé gérant": "BILOLO PANU MPAKOLE Augustin", "N° de téléphone": "(+243)852614301"}, {"E-mail": "brukabmuss@yahoo.com", "N° d'ordre": "SEC/24.00120", "Dénomination": "BRUNO KABUNDA MUSASA CONSEIL, REVISION, EXPERTISE, FORMATION & ASSOCIES SARL", "Raison sociale": "BKM COREF & ASSOCIES Sarl", "Associé gérant": "KABUNDA MUSASA Bruno", "N° de téléphone": "(+243)815090576"}, {"E-mail": "didiermbang@gmail.com", "N° d'ordre": "SEC/25.00129", "Dénomination": "BUREAU D'EXPERTISE SARL", "Raison sociale": " B.E SARL", "Associé gérant": "NDUMB MBANG Didier", "N° de téléphone": "(+243)819591098"}, {"E-mail": "kabeley@hotmail.fr", "N° d'ordre": "SEC/21.00069", "Dénomination": "CABINET D’AUDIT DE REVISION ET D’EXPERTISE COMPTABLE", "Raison sociale": "CARECO SARL", "Associé gérant": "KABENGELE M'PIEN LEY Gilbert", "N° de téléphone": "(+243)998403072"}, {"E-mail": "cacosarl22@gmail.com", "N° d'ordre": "SEC/24.00110", "Dénomination": "CABINET D'AUDIT COMPTABLE ET CONSEILS", "Raison sociale": "CACO SARL", "Associé gérant": "AKINDOA MALEBO Eugène Robert", "N° de téléphone": "(+243)818109079"}, {"E-mail": "cagescom2002@gmail.com", "N° d'ordre": "SEC/22.00087", "Dénomination": "CABINET D'AUDIT DE GESTION ET DE COMPTABILITE SARL", "Raison sociale": "CAGESCOM", "Associé gérant": "YANGA LUMBAHE Simon", "N° de téléphone": "(+243)999910998"}, {"E-mail": "cabinetcacg14@gmail.com", "N° d'ordre": "SEC/23.00105", "Dénomination": "CABINET D'AUDIT ET CONSEILS EN GESTION", "Raison sociale": "CACG SARL", "Associé gérant": "NAMUTUTU KUNGWA Diane Esther", "N° de téléphone": "(+243)824977188"}, {"E-mail": "alainmunganga@hotmail.com", "N° d'ordre": "SEC/16.00017", "Dénomination": "CABINET D'AUDIT ET D'EXPERTISE COMPTABLE   ", "Raison sociale": "CAEC SARL", "Associé gérant": "KOMBA MUNGANGA Alain", "N° de téléphone": "(+243)998087847"}, {"E-mail": "cauditec1@gmail.com", "N° d'ordre": "SEC/18.00018", "Dénomination": "CABINET D'AUDIT ET D'EXPERTISE COMPTABLE   ", "Raison sociale": "CAUDITEC SARL", "Associé gérant": "KAYAMBA KAYEMBA Marco", "N° de téléphone": "(+243)825337520"}, {"E-mail": "cecaf_nwk@yahoo.fr", "N° d'ordre": "SEC/16.00021", "Dénomination": "CABINET D'EXPERTISE COMPTABLE, AUDIT ET FISCALITE", "Raison sociale": "CECAF SARL", "Associé gérant": "NGOIE WA KASONGO Augustin", "N° de téléphone": "(+243)818130580"}, {"E-mail": "josuekasilembo@cabinetjkauditsarlu.com", "N° d'ordre": "SEC/21.00081", "Dénomination": "CABINET J.K. AUDIT SARLU", "Raison sociale": "J.K. AUDIT SARLU", "Associé gérant": "KASILEMBO BUJINGA Josué", "N° de téléphone": "(+243)816896777"}, {"E-mail": "ngoyibenjamin11@gmail.com", "N° d'ordre": "SEC/21.00076", "Dénomination": "CABINET LA COURCELLE SARLU", "Raison sociale": "LA COURCELLE SARLU", "Associé gérant": "NGOYI KABEMBA Benjamin", "N° de téléphone": "(+243)819593692"}, {"E-mail": "casolrdc@gmail.com", "N° d'ordre": "SEC/23.00095", "Dénomination": "CABINET SOLUTION SARL", "Raison sociale": "CASOL SARL", "Associé gérant": "MAYI KAYIMBONGE Désiré", "N° de téléphone": "(+243)816432674"}, {"E-mail": "contact@ctrsrdc.com", "N° d'ordre": "SEC/21.00079", "Dénomination": "CABINET TRANSPARENCY SARLU", "Raison sociale": "CTRS", "Associé gérant": "LIGBAKELO MAYKPELE Samy", "N° de téléphone": "(+243)818148848"}, {"E-mail": "jean-marie.ngandu@caf-consulting.com", "N° d'ordre": "SEC/22.00083", "Dénomination": "CAF CONSULTING SARL", "Raison sociale": "CAF CONSULTING SARL", "Associé gérant": "NGANDU WA NGANDU Jean Marie", "N° de téléphone": "(+243)818145122"}, {"E-mail": "kampanzuexpert@gmail.com", "N° d'ordre": "SEC/24.00112", "Dénomination": "COMPANY OF BROTHERS MANAGERS SARLU", "Raison sociale": "CBM SARLU", "Associé gérant": "KAMPANZU MBEKU Cherif", "N° de téléphone": "(+243)816603731"}, {"E-mail": "congoconsulting@gmail.com", "N° d'ordre": "SEC/18.00023", "Dénomination": "CONGO CONSULTING SERVICES SARL", "Raison sociale": "CCS SARL", "Associé gérant": "NSAYI LUKOMBO Rubens", "N° de téléphone": "(+243)999124915"}, {"E-mail": "ccpaccaf@gmail.com", "N° d'ordre": "SEC/21.00077", "Dénomination": "CONSEIL DES CONCITOYENS POUR LA PERFORMANCE DES AFFAIRES SARL", "Raison sociale": "CCPA SARL", "Associé gérant": "KAKULE LWANZO Claude", "N° de téléphone": "(+243)998273107"}, {"E-mail": "infos.cofica@gmail.com", "N° d'ordre": "SEC/18.00025", "Dénomination": "CONSEIL, FISCALITE, COMPTABILITE ET AUDIT", "Raison sociale": "COFICA SARL", "Associé gérant": "MATUTALA KULA PITSHOU", "N° de téléphone": "(+243)999964440"}, {"E-mail": "bureau_cefao@yahoo.fr", "N° d'ordre": "SEC/21.00070", "Dénomination": "CONSEIL-ETUDE-FISCALITE-AUDIT-ORGANISATION", "Raison sociale": "CEFAO", "Associé gérant": "NSILULU BAHELELE Gabriel", "N° de téléphone": "(+243)998921784"}, {"E-mail": "crm1942@yahoo.fr", "N° d'ordre": "SEC/24.00113", "Dénomination": "CONSULTING RESOURCES MANAGEMENT", "Raison sociale": "CRM SARL", "Associé gérant": "DIKASSADYBY MOUENALONJ Donatien", "N° de téléphone": "(+243)812457797"}, {"E-mail": "brunokambaja@gmail.com", "N° d'ordre": "SEC/24.00125", "Dénomination": "CONSULTING, AUDITING, ACCOUNTING & TAX SAS", "Raison sociale": "CAAT SAS", "Associé gérant": "KAMBAJA MUBALAMATA Bruno", "N° de téléphone": "(+243)818112710"}, {"E-mail": "cornerstone@cornerstone-cd.com", "N° d'ordre": "SEC/17.00028", "Dénomination": "CORNERSTONE FOREVER INTERNATIONAL ", "Raison sociale": "CFI SARL", "Associé gérant": "LUKIMUENA KUBA Samuelson", "N° de téléphone": "(+243)992454996"}, {"E-mail": "cyrille_mongele@yahoo.fr", "N° d'ordre": "SEC/21.00080", "Dénomination": "CPM CONSULTING SARL", "Raison sociale": "CC", "Associé gérant": "MBUWA MONGELE Cyrille", "N° de téléphone": "(+243)815208327"}, {"E-mail": "daco2sarl@gmail.com", "N° d'ordre": "SEC/17.00029", "Dénomination": "DA CONSULTING OFFICE ", "Raison sociale": "DACO SARL", "Associé gérant": "MUKAWA NINGA Nanou", "N° de téléphone": "(+243)817068908"}, {"E-mail": "info@delpartners.com", "N° d'ordre": "SEC/16.00030", "Dénomination": "DEL PARTNERS SARL", "Raison sociale": "DEL PARTNERS SARL", "Associé gérant": "KABWELA WA KABWELA Didier", "N° de téléphone": "(+243)812577497"}, {"E-mail": "rdc@deloitte.fr", "N° d'ordre": "SEC/16.00031", "Dénomination": "DELOITTE SERVICES SARL", "Raison sociale": "DELOITTE SERVICES SARL", "Associé gérant": "NZOIMBENGENE LUYINDULA Bob David", "N° de téléphone": "(+243)859998006"}, {"E-mail": "cmngubi@gmail.com", "N° d'ordre": "SEC/25.00132", "Dénomination": "DIVINE WISDOM FOR ASSISTING AND CONSULTING SARL", "Raison sociale": "DWAC SARL", "Associé gérant": "NGUBI LUTETE Mac", "N° de téléphone": "(+243)972009548"}, {"E-mail": "contact@drcexpertises.net", "N° d'ordre": "SEC/18.00032", "Dénomination": "DRC EXPERTISES SAS", "Raison sociale": "DEX SAS", "Associé gérant": "LUNGANGI KITUNDU Françoise", "N° de téléphone": "(+243)813421009"}, {"E-mail": "emergenceconsult2024@gmail.com", "N° d'ordre": "SEC/18.00033", "Dénomination": "EMERGENCE CONSULTING SARL", "Raison sociale": "EMERGENCE CONSULTING SARL", "Associé gérant": "MPOP AWUNG Florent", "N° de téléphone": "(+243)827275187"}, {"E-mail": "baraka.kabemba@cd.ey.com", "N° d'ordre": "SEC/18.00034", "Dénomination": "ERNST & YOUNG RDC SARL", "Raison sociale": "EY RDC", "Associé gérant": "KABEMBA BARAKA", "N° de téléphone": "(+243)993435296"}, {"E-mail": "ecautef.kinshasa@yahoo.fr", "N° d'ordre": "SEC/19.00035", "Dénomination": "ETUDES CONSEILS AUDIT DEVELOPPEMENT TECHNOLOGIE ET FORMATION", "Raison sociale": "ECAUTEF SARL", "Associé gérant": "KAKULE VAHIMBI Guillain", "N° de téléphone": "(+243)997992150"}, {"E-mail": "egide.mambu@africamel.net", "N° d'ordre": "SEC/25.00153", "Dénomination": "EXPERT-COMPTABLE CONSEIL D'ENTREPRISE", "Raison sociale": "ECCE SARL", "Associé gérant": "MAMBU LUYALU MUSONGA KEL ", "N° de téléphone": "(+243)824682000"}, {"E-mail": "contact@ecrrdc.com", "N° d'ordre": "SEC/17.00038", "Dénomination": "EXPERTS COMPTABLES REUNIS SARL", "Raison sociale": "ECR SARL", "Associé gérant": "NTUMBA MPUTU Odilon", "N° de téléphone": "(+243)824448070"}, {"E-mail": "rkalambay2936@gmail.com", "N° d'ordre": "SEC/19.00039", "Dénomination": "EXPERTS MAC CD SAS", "Raison sociale": "E-MAC SAS", "Associé gérant": "KALAMBAY NYINDU Raphaël", "N° de téléphone": "(+243)971798907"}, {"E-mail": "contact@fcompta.com", "N° d'ordre": "SEC/19.00040", "Dénomination": "F.COMPTA SARL", "Raison sociale": "FCOMPTA", "Associé gérant": "MASIALA FINDUO Blaise", "N° de téléphone": "(+243)816866913"}, {"E-mail": "fagefi@yahoo.fr", "N° d'ordre": "SEC/25.00130", "Dénomination": "FIDUCIAIRE AUDIT-GESTION ET FISCALITE SARL ", "Raison sociale": "FAGEFI SARL", "Associé gérant": "CIZUBU CIAMPOYI Alidor", "N° de téléphone": "(+243)999905021"}, {"E-mail": "ficadexrdc@yahoo.com", "N° d'ordre": "SEC/24.00114", "Dénomination": "FIDUCIAIRE DE COORDINATION D'AUDIT ET D'EXPERTISE COMPTABLE AFRIQUE CONGO RDC", "Raison sociale": "FICADEX AFRIQUE CONGO RDC", "Associé gérant": "ABEDI ABD'ALLAH ASSAD ", "N° de téléphone": "(+243)976537921"}, {"E-mail": "figefitechsarl@gmail.com", "N° d'ordre": "SEC/23.00099", "Dénomination": "FIGEFITECH SARL", "Raison sociale": "FIGEFITECH SARL", "Associé gérant": "KASONGO BATUSSE Peter", "N° de téléphone": "(+243)820647189"}, {"E-mail": "Jemima.bazola@forvismazars.com", "N° d'ordre": "SEC/17.00051", "Dénomination": "FORVIS MAZARS RDC", "Raison sociale": "FORVIS MAZARS RDC", "Associé gérant": "NDANGI NDANGANI Théophile", "N° de téléphone": "(+243)999785240"}, {"E-mail": "jbetombo5@gmail.com", "N° d'ordre": "SEC/25.00131", "Dénomination": "GENERALE D'AFFAIRES ET CONSEILS", "Raison sociale": "GEDAF-Conseil SARL", "Associé gérant": "BETOMBO NGANDO Joseph", "N° de téléphone": "(+243)815117683 "}, {"E-mail": "gpoce@gpopartners.com", "N° d'ordre": "SEC/22.00084", "Dénomination": "GPO CONGO EXPERTISES SARL", "Raison sociale": "GPO CONGO EXPERTISES SARL", "Associé gérant": "PHANZU NLANDU Philippe", "N° de téléphone": "(+243)832307387"}, {"E-mail": "helianconsulting@gmail.com", "N° d'ordre": "SEC/21.00078", "Dénomination": "HELIAN CONSULTING SARL", "Raison sociale": "HELIAN CONSULTING SARL", "Associé gérant": "FATAKI NTULA Zephirin", "N° de téléphone": "(+243)973892181"}, {"E-mail": "contact@ibnsarl.com", "N° d'ordre": "SEC/23.00100", "Dénomination": "IBN SARL", "Raison sociale": "IBN SARL", "Associé gérant": "IFEKA BONKOMO Nelson", "N° de téléphone": "(+243)998121510"}, {"E-mail": "cyprien.bongulumata@cd-insp.com", "N° d'ordre": "SEC/21.00082", "Dénomination": "IN SERVICE PARTNERS SARL", "Raison sociale": "INSP SARL", "Associé gérant": "BONGULUMATA LOKELE Cyprien", "N° de téléphone": "(+243)818112781"}, {"E-mail": "inadof@yahoo.fr", "N° d'ordre": "SEC/17.00043", "Dénomination": "INVESTORS ADVICE OFFICE ", "Raison sociale": "INADOF", "Associé gérant": "BOKIE NDWAYA Norbert", "N° de téléphone": "(+243)811828663"}, {"E-mail": "infos@jasbisarl.com", "N° d'ordre": "SEC/17.00044", "Dénomination": "JASBI CONSULTANTS SARL", "Raison sociale": "JASBI SARL", "Associé gérant": "KUSAMA MIEZI Gabriel", "N° de téléphone": "(+243)998379602"}, {"E-mail": "secretariat@jmbconsulting.cd", "N° d'ordre": "SEC/20.00066", "Dénomination": "JMB CONSULTING SARL", "Raison sociale": "JMB CONSULTING SARL", "Associé gérant": "MBUMBA MBUDI Joseph", "N° de téléphone": "(+243)858475078"}, {"E-mail": "jvlconsuting26@gmail.com", "N° d'ordre": "SEC/25.00126", "Dénomination": "JVL SAS", "Raison sociale": "JVL SAS", "Associé gérant": "LUNGONZO MBUY François", "N° de téléphone": "(+243)998139161"}, {"E-mail": "contact@k2m-partners.com", "N° d'ordre": "SEC/19.00046", "Dénomination": "K2M PARTNERS SARL", "Raison sociale": "K2M PARTNERS SARL", "Associé gérant": "MANKENDA NANSINA Sébastien", "N° de téléphone": "(+243)992722376"}, {"E-mail": "infos@kmc-cabinet.com", "N° d'ordre": "SEC/22.00088", "Dénomination": "KMC Advice & Partners SASU", "Raison sociale": "KMC SASU", "Associé gérant": "KANINDA MUKENA Carlos", "N° de téléphone": "(+243)893992457"}, {"E-mail": "tfashingabo@kpmg.cd", "N° d'ordre": "SEC/16.00047", "Dénomination": "KPMG RDC SA", "Raison sociale": "KPMG", "Associé gérant": "KIYOMBO MANGA Louison", "N° de téléphone": "(+243)990010021"}, {"E-mail": "info@lapradellec.com", "N° d'ordre": "SEC/17.00049", "Dénomination": "LA PRADELLE CONSULTING SARLU", "Raison sociale": "PDLC SARLU", "Associé gérant": "OKENDE MBUNGU Adolphe", "N° de téléphone": "(+243)810837185"}, {"E-mail": "labottefiducia@gmail.com", "N° d'ordre": "SEC/24.00116", "Dénomination": "LABOTTE FIDUCIA SARL", "Raison sociale": "LABOTTE FIDUCIA SARL", "Associé gérant": "FURUME NTALE Benito", "N° de téléphone": "(+243)829199974"}, {"E-mail": "contact@lacoteadvisory.com", "N° d'ordre": "SEC/19.00048", "Dénomination": "LACOTE ADVISORY AUDIT AND TAX ", "Raison sociale": "LACOTE AAT SARL", "Associé gérant": "TUNDA NGIEFU Yves", "N° de téléphone": "(+243)818970523"}, {"E-mail": "audit@strong-nkv.cd", "N° d'ordre": "SEC/17.00052", "Dénomination": "mgi STRONG NKV SAS", "Raison sociale": "mgi STRONG NKV SAS", "Associé gérant": "NKUVU-A-MBINDA WENA Danny", "N° de téléphone": "(+243)898919645"}, {"E-mail": "contact@mmpartnerscongo.com", "N° d'ordre": "SEC/16.00053", "Dénomination": "MMPARTNERS CONGO SARL", "Raison sociale": "M&MP", "Associé gérant": "KIMBEMBE KIAMVU Simon", "N° de téléphone": "(+243)999916552"}, {"E-mail": "ndongogaby30@gmail.com", "N° d'ordre": "SEC/25.00135", "Dénomination": "NDONGO NTIERE SARL", "Raison sociale": "NN SARL", "Associé gérant": "NDONGO NTIERE Gaby ", "N° de téléphone": "(+243)854348339"}, {"E-mail": "lu.tchata@gmail.com", "N° d'ordre": "SEC/24.00121", "Dénomination": "NEW ANOU CONSULTING Sarl", "Raison sociale": "NEW ANOU", "Associé gérant": "LUMU TCHATA Joseph", "N° de téléphone": "(+243)815981162"}, {"E-mail": "odonndoko8@gmail.com", "N° d'ordre": "SEC/23.00104", "Dénomination": "ODON NDOKO FIRME", "Raison sociale": "ONF SARLU", "Associé gérant": "NDOKO FUMU Odon", "N° de téléphone": "(+243)814847070"}, {"E-mail": "kamibafor@gmail.com", "N° d'ordre": "SEC/23.00097", "Dénomination": "OKM CONSULTING SAS", "Raison sociale": "OKM CONSULTING SAS", "Associé gérant": "KASONGO DIEMU Dieudonné", "N° de téléphone": "(+243)855281200"}, {"E-mail": "prosper.bongongu@pros-rdc.com", "N° d'ordre": "SEC/22.00085", "Dénomination": "PROSPER & Associates Sarl", "Raison sociale": "PROSPER & Associates Sarl", "Associé gérant": "BONGUNGU MATONDO Prosper", "N° de téléphone": "(+243)818122030"}, {"E-mail": "contact@quitusconsult.cd", "N° d'ordre": "SEC/17.00056", "Dénomination": "QUITUS CONSULT SARL ", "Raison sociale": "QC SARL", "Associé gérant": "NDUSHA BIRHAFANWA Xavier", "N° de téléphone": "(+243)815086052"}, {"E-mail": "ropartnersrdc@gmail.com", "N° d'ordre": "SEC/21.00074", "Dénomination": "R.O & PARTNERS SARL", "Raison sociale": "R.O & PARTNERS SARL", "Associé gérant": "OVO YATUIKWAMO FUKIAU Ranield", "N° de téléphone": "(+243)998946925"}, {"E-mail": "simon@smaccounting.net", "N° d'ordre": "SEC/18.00058", "Dénomination": "SM ACCOUNTING & ASSOCIES", "Raison sociale": "SMA", "Associé gérant": "MUAMBA TSHILUMBA Simon", "N° de téléphone": "(+243)995961063"}, {"E-mail": "contact@corexrdc.com", "N° d'ordre": "SEC/19.00027", "Dénomination": "SOCIETE DE CONSEIL, REVISION ET EXPERTISE COMPTABLES", "Raison sociale": "COREX SARL", "Associé gérant": "DONGO LISIKA Gauthier", "N° de téléphone": "(+243)815124970"}, {"E-mail": "credesexco@gmail.com", "N° d'ordre": "SEC/19.00059", "Dénomination": "SOCIETE D'EXPERTISE COMPTABLE ET COMMISSARIAT AUX COMPTES", "Raison sociale": "CREDES EXCO SARL", "Associé gérant": "MULEMVO BIDUAKA Bienvenu", "N° de téléphone": "(+243)821860057"}, {"E-mail": "focalpoint.dg@gmail.com", "N° d'ordre": "SEC/19.00060", "Dénomination": "SOCIETE D'EXPERTISE COMPTABLE ET FISCALE \\"IMAGE FIDELE\\" SARL", "Raison sociale": "SECOFISC SARL", "Associé gérant": "TSHIBANDA SABWA Jean-Pierre", "N° de téléphone": "(+243)810888189"}, {"E-mail": "infos@secofic.cd", "N° d'ordre": "SEC/16.00061", "Dénomination": "SOCIETE D'EXPERTISE COMPTABLE FISCALITE ET CONSEILS", "Raison sociale": "SECOFIC SARL", "Associé gérant": "MBAYA MBAYA Célestin", "N° de téléphone": "(+243)818757078"}, {"E-mail": "secafsarl4@gmail.com", "N° d'ordre": "SEC/19.00062", "Dénomination": "SOCIETE D'EXPERTISE COMPTABLE, D'AUDIT ET DE FISCALITE", "Raison sociale": "SECAF", "Associé gérant": "IZE KANIKI Johnny", "N° de téléphone": "(+243)816144948"}, {"E-mail": "secofia.secofia@yahoo.com", "N° d'ordre": "SEC/18.00063", "Dénomination": "SOCIETE D'EXPERTISE COMPTABLE, FISCALITE ET D'AUDIT", "Raison sociale": "SECOFIA SARL", "Associé gérant": "ILEO BOTINDO Madeleine", "N° de téléphone": "(+243)990317590"}, {"E-mail": "thierry_lokesa@yahoo.fr", "N° d'ordre": "SEC/25.00128", "Dénomination": "T.L PARTNERS-CONGO SARL", "Raison sociale": "T.L PARTNERS-CONGO SARL", "Associé gérant": "LOKESA SUAMUNU Thierry", "N° de téléphone": "(+243)899501186"}, {"E-mail": "anderson@taaex.net", "N° d'ordre": "SEC/25.00133", "Dénomination": "TAX ACCOUNTING AND AUDIT EXPERTS SARLU", "Raison sociale": "TAAEX SARLU", "Associé gérant": "MAWANGU NDOLUVUALU Anderson", "N° de téléphone": "(+243)998397801"}, {"E-mail": "info.tecpro.fiduciaire@gmail.com", "N° d'ordre": "SEC/24.00118", "Dénomination": "TECPRO EXPERTISE SARLU", "Raison sociale": "TECPRO EXPERTISE SARLU", "Associé gérant": "MAMPUYA KALENGA Robert", "N° de téléphone": "(+243)820057638"}, {"E-mail": "admin-tbg@trusttbg.com", "N° d'ordre": "SEC/23.00096", "Dénomination": "TRUST BUSINESS GUARANTEE RDC SARL", "Raison sociale": "TRUST BUSINESS GUARANTEE RDC SARL", "Associé gérant": "TANDU ROVAT Jean-Pierre ", "N° de téléphone": "(+243)810532936"}]	2026-03-20 10:49:59.305018+00
8e3dfba2-7b44-4bb6-8a00-a35c6c781619	modele_independant (2).xlsx	independant	a2375bac-4a9f-4ed8-b674-a1807543c744	39	success	[{"NIF": "A2320927Y", "Noms": "KIMBI ILENDA Michel", "Sexe": "M", "E-mail": "michelkimbi@gmail.com", "__rowIndex": 2, "N° d'ordre": "EC/18.00185", "N° de téléphone": "(+243)842339577"}, {"NIF": "A1402050U", "Noms": "KIMBULU KAMWENI André", "Sexe": "M", "E-mail": "audicomcabinet@gmail.com", "__rowIndex": 3, "N° d'ordre": "EC/17.00186", "N° de téléphone": "(+243)903774232"}, {"NIF": "A2032437F", "Noms": "KINDU MUNDEKE MUSHAGALUSA Jean Chirac", "Sexe": "M", "E-mail": "jckindu2019@gmail.com", "__rowIndex": 4, "N° d'ordre": "EC/18.00187", "N° de téléphone": "(+243)976332205"}, {"NIF": "A0708999Q", "Noms": "KINKELA MIANGU Gilbert", "Sexe": "M", "E-mail": "gilkinkela@hotmail.com", "__rowIndex": 5, "N° d'ordre": "EC/19.00189", "N° de téléphone": "(+243)999226581"}, {"NIF": "A1612573K", "Noms": "KONKO NDONTONI NTUMPI Joseph Dieudonné", "Sexe": "M", "E-mail": "codipro_cd@yahoo.fr", "__rowIndex": 6, "N° d'ordre": "EC/16.00200", "N° de téléphone": "(+243)998511001"}, {"NIF": "A0902535S", "Noms": "KUTELAMA BATWA Ignace", "Sexe": "M", "E-mail": "ignacekutelama@gmail.com", "__rowIndex": 7, "N° d'ordre": "EC/17.00206", "N° de téléphone": "(+243)820893568"}, {"NIF": "A1709114B", "Noms": "LEVO NKUANGA JEAN Thomas", "Sexe": "M", "E-mail": "cabinetlevocompte@gmail.com", "__rowIndex": 8, "N° d'ordre": "EC/16.00212", "N° de téléphone": "(+243)814443300"}, {"NIF": "A1210316C", "Noms": "LOANGO BOELUA BAENDAFE Honoré", "Sexe": "M", "E-mail": "honoreloango@yahoo.fr", "__rowIndex": 9, "N° d'ordre": "EC/17.00217", "N° de téléphone": "(+243)999939791"}, {"NIF": "A2409121R", "Noms": "LUYINDULA MAVAMBU Felly", "Sexe": "M", "E-mail": "fellyluyindula@yahoo.fr", "__rowIndex": 10, "N° d'ordre": "EC/17.00239", "N° de téléphone": "(+243)816629429"}, {"NIF": "A0805529U", "Noms": "LWELA MAKOSO Evariste", "Sexe": "M", "E-mail": "evalwela@yahoo.fr", "__rowIndex": 11, "N° d'ordre": "EC/19.00242", "N° de téléphone": "(+243)819041687"}, {"NIF": "A2207503F", "Noms": "MAMONA PHEZO Nathalis", "Sexe": "M", "E-mail": "mamonaphezo@yahoo.fr", "__rowIndex": 12, "N° d'ordre": "EC/19.00260", "N° de téléphone": "(+243)817005489"}, {"NIF": "B2293204K", "Noms": "MASSALA PANGU Guelord", "Sexe": "M", "E-mail": "guelordmassala08@gmail.com", "__rowIndex": 13, "N° d'ordre": "EC/19.00271", "N° de téléphone": "(+243)820291101"}, {"NIF": "A2302481Y", "Noms": "MAYO BOKWANGO Daniel", "Sexe": "M", "E-mail": "danbokwa@gmail.com", "__rowIndex": 14, "N° d'ordre": "EC/18.00288", "N° de téléphone": "(+243)857000191"}, {"NIF": "1508462Q", "Noms": "MBANGALA MAPAPA Augustin", "Sexe": "M", "E-mail": "mmbangala@yahoo.fr", "__rowIndex": 15, "N° d'ordre": "EC/16.00292", "N° de téléphone": "(+243)997625788"}, {"NIF": "A0705673A", "Noms": "MBUDI MASUNDA Martin", "Sexe": "M", "E-mail": "mmbudimasunda@gmail.com", "__rowIndex": 16, "N° d'ordre": "EC/16.00298", "N° de téléphone": "(+243)855179505"}, {"NIF": "A2534646M", "Noms": "MFUAMBA KEYAMONOKO Désiré", "Sexe": "M", "E-mail": "desire.mfuamba@gmail.com", "__rowIndex": 17, "N° d'ordre": "EC/16.00306", "N° de téléphone": "(+243)812550110"}, {"NIF": "A1923398E", "Noms": "MOKELO MAYO Flory", "Sexe": "M", "E-mail": "florymokelo65@gmail.com", "__rowIndex": 18, "N° d'ordre": "EC/19.00313", "N° de téléphone": "(+243)814245488"}, {"NIF": "A2402749Q", "Noms": "MUHINDO MUHONGYA Albert", "Sexe": "M", "E-mail": "mkmuhindo@yahoo.fr", "__rowIndex": 19, "N° d'ordre": "EC/16.00333    ", "N° de téléphone": "(+243)852809802"}, {"NIF": "A2526187S", "Noms": "MUKADI KAPINGA NTUMBA Biby", "Sexe": "M", "E-mail": "mukadibiby@gmail.com", "__rowIndex": 20, "N° d'ordre": "EC/24.00602", "N° de téléphone": "(+243)854719696"}, {"NIF": "A0702340C", "Noms": "MUKANDILA ILUNGA José François", "Sexe": "M", "E-mail": "francoismukandila@yahoo.fr", "__rowIndex": 21, "N° d'ordre": "EC/16.00532", "N° de téléphone": "(+243)999920160"}, {"NIF": "A0802485L", "Noms": "MULONGO MUKWINDI Ruben Freddy", "Sexe": "M", "E-mail": "mulongo_freddy@yahoo.fr", "__rowIndex": 22, "N° d'ordre": "EC/19.00356", "N° de téléphone": "(+243)813395652"}, {"NIF": "A2207534P", "Noms": "MULUMBA KOLOMONI André", "Sexe": "M", "E-mail": "andmulko@gmail.com", "__rowIndex": 23, "N° d'ordre": "EC/16.00357", "N° de téléphone": "(+243)821023840"}, {"NIF": "A0193194C", "Noms": "MUPEPE LEBO Jean Baptiste", "Sexe": "M", "E-mail": "jblebo40@gmail.com", "__rowIndex": 24, "N° d'ordre": "EC/16.00362", "N° de téléphone": "(+243)819702022"}, {"NIF": "A0806854K", "Noms": "MUTUMBU ZA MAMBU Simon", "Sexe": "M", "E-mail": "simon.mutumbu@yahoo.fr", "__rowIndex": 25, "N° d'ordre": "EC/17.00375", "N° de téléphone": "(+243)896455730"}, {"NIF": "A0803833B", "Noms": "MWAMBO KASANZA Georges", "Sexe": "M", "E-mail": "georgesmwambo4@gmail.com", "__rowIndex": 26, "N° d'ordre": "EC/17.00382", "N° de téléphone": "(+243)815256181"}, {"NIF": "A0903949D", "Noms": "NIATI MATONA Omer", "Sexe": "M", "E-mail": "oniati@gmail.com", "__rowIndex": 27, "N° d'ordre": "EC/16.00412", "N° de téléphone": "(+243)812347377"}, {"NIF": "A2216881Z", "Noms": "NLANDU NKIAWETE Jean Pierre", "Sexe": "M", "E-mail": "dnlandu1@gmail.com", "__rowIndex": 28, "N° d'ordre": "EC/16.00424", "N° de téléphone": "(+243)856253534"}, {"NIF": "B228179F", "Noms": "NSENSELE KANGONDO Jacqueline", "Sexe": "f", "E-mail": "nsenselejacqueline@gmail.com", "__rowIndex": 29, "N° d'ordre": "EC/24.00597", "N° de téléphone": "(+243)8810346426"}, {"NIF": "A0807524G", "Noms": "NSIMBA MBAKI Edmond", "Sexe": "M", "E-mail": "edmondnsimba44@gmail.com", "__rowIndex": 30, "N° d'ordre": "EC/17.00428", "N° de téléphone": "(+243)815192269"}, {"NIF": "A601640B", "Noms": "NTUMBA WA NTUMBA Joseph", "Sexe": "M", "E-mail": "jnwntumba@gmail.com", "__rowIndex": 31, "N° d'ordre": "EC/17.00438", "N° de téléphone": "(+243)825532814"}, {"NIF": "A90171761L", "Noms": "NZEZA ZI NGETI Claude", "Sexe": "M", "E-mail": "clauvenant@hotmail.com", "__rowIndex": 32, "N° d'ordre": "EC/19.00445", "N° de téléphone": "(+243)811861940"}, {"NIF": "A1000232P", "Noms": "NZUZI MAYIFILUA Donat Claude", "Sexe": "M", "E-mail": "nzuzimayifilua@gmail.com", "__rowIndex": 33, "N° d'ordre": "EC/17.00450", "N° de téléphone": "(+243)818930700"}, {"NIF": "A2031263E", "Noms": "NZUZI NZUZI Baudouin", "Sexe": "M", "E-mail": "nzuzibaudouin1@gmail.com", "__rowIndex": 34, "N° d'ordre": "EC/18.00451", "N° de téléphone": "(+243)843371771"}, {"NIF": "A1000503J", "Noms": "RUKUYENGE KASHUGI Willy Anselme", "Sexe": "M", "E-mail": "willyanselme.rk@live.be", "__rowIndex": 35, "N° d'ordre": "EC/16.00474", "N° de téléphone": "(+243)815164872"}, {"NIF": "A0801686S", "Noms": "SUMBA BADIMANI Boniface", "Sexe": "M", "E-mail": "sumbaboniface580@gmail.com", "__rowIndex": 36, "N° d'ordre": "EC/18.00487", "N° de téléphone": "(+243)974614855"}, {"NIF": "A0801990Y", "Noms": "TRIBUNALI SEMBAITO CHRISPIN ", "Sexe": "M", "E-mail": "christribun219@gmail.com", "__rowIndex": 37, "N° d'ordre": "EC/16.00491", "N° de téléphone": "(+243)825392061"}, {"NIF": 48150, "Noms": "TSHIALA BONGO Macaire", "Sexe": "M", "E-mail": "macairebongo2@gmail.com", "__rowIndex": 38, "N° d'ordre": "EC/18.00496", "N° de téléphone": "(+243)976929659"}, {"NIF": "A0803842L", "Noms": "TSHIBAMBE TAMBWE Noah", "Sexe": "M", "E-mail": "tshibambenoah@yahoo.fr", "__rowIndex": 39, "N° d'ordre": "EC/16.00498", "N° de téléphone": "(+243)999955207"}, {"NIF": "A1107701J", "Noms": "TSHILOMBA MUSOKAY Paulin", "Sexe": "M", "E-mail": "tshilombap@yahoo.com", "__rowIndex": 40, "N° d'ordre": "EC/16.00506", "N° de téléphone": "(+243)819383884"}]	2026-03-20 11:01:03.122341+00
\.


--
-- Data for Name: lignes_requisition; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.lignes_requisition (id, requisition_id, rubrique, description, quantite, montant_unitaire, montant_total, budget_poste_id, devise) FROM stdin;
e69b56ee-330d-4321-bfe3-911cb113425b	238a97a0-7b38-4eef-a504-e2de13865da5	II.2.11 - IMPREVUS	test	1	10.00	10.00	99	USD
6e56ddad-ec82-493d-b2e1-a893acaf935d	349d8fc1-c86a-445d-b77c-728c27259ae8	II.2.11 - IMPREVUS	test	1	10.00	10.00	99	USD
\.


--
-- Data for Name: organisation_settings; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.organisation_settings (id, organisation_id, max_users, storage_quota_mb, is_ai_enabled, is_mobile_money_enabled, fiscal_year_start, currency_code, is_audit_logs_enabled, theme_primary_color, theme_sidebar_color, theme_accent_color, theme_text_color, theme_sidebar_text_color, theme_sidebar_active_color, theme_button_text_color) FROM stdin;
3	9	5	1024	f	t	1	CDF	t	#660700	#6a1601	#000000	#2d3748	#ffffff	#1a523f	#ffffff
4	10	5	1024	f	t	1	CDF	t	#000000	#000000	#ffffff	#2d3748	#ffffff	#1a523f	#ffffff
2	8	5	1024	f	t	1	CDF	t	#000000	#000000	#eab308	#0d4537	#ffffff	#0a4330	#052912
1	1	5	1024	t	t	1	CDF	t	#4a9079	#3d7a66	#eab308	#2d3748	#ffffff	#1a523f	#ffffff
\.


--
-- Data for Name: organisations; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.organisations (id, uuid, nom, slug, logo_url, email_contact, telephone, adresse, devise_preferee, taux_change_interne, plan_type, status_abonnement, date_expiration_abonnement, limite_utilisateurs, is_active, created_at, updated_at, icon, sort_order, billing_config) FROM stdin;
10	fedd970d-00d9-43bb-a58e-cd98f15c3c96	Conseil Provincial de Sud-Kivu	cpsk	\N	\N	\N	\N	USD	0.0000	FREE	SUSPENDED	\N	2	f	2026-03-24 13:41:52.110712+00	2026-03-25 14:22:41.272176+00	🌋	3	{"plan": {"name": "Premium", "price": 273.0, "currency": "USD", "interval": "monthly"}, "payment_methods": {"bank": {"enabled": true, "bank_name": "EquityBCDC", "swift_code": "", "account_name": "Gestion ONEC", "account_number": "111200214185932"}, "mobile_money": {"enabled": true, "provider": "M-pesa", "instructions": "Test", "merchant_number": "0818080946"}}, "support_contact": "kidikala@gmail.com", "billing_portal_url": "https://console-saas/tenants/{slug}/billing"}
9	d03f2153-e021-47cf-82e1-e15dd60ab0a9	Conseil Provincial du Haut-Katanga	cphk	\N	\N	\N	\N	CDF	0.0000	FREE	SUSPENDED	\N	5	f	2026-03-24 13:41:52.110712+00	2026-03-27 15:29:08.52148+00	🏭	2	{"plan": {"name": "Premium", "price": 250.0, "currency": "USD", "interval": "monthly"}, "payment_methods": {"bank": {"enabled": true, "bank_name": "EquityBCDC", "swift_code": "", "account_name": "Gestion ONEC", "account_number": "111200214185932"}, "mobile_money": {"enabled": true, "provider": "M-pesa", "instructions": "Test", "merchant_number": "0818080946"}}, "support_contact": "kidikala@gmail.com", "billing_portal_url": "https://console-saas/tenants/{slug}/billing"}
1	056909a8-ee0f-454f-9b6b-728c73077d55	Conseil Provincial de Kinshasa	cpk	\N	\N	\N	\N	CDF	0.0000	FREE	TRIAL	\N	5	t	2026-03-19 10:20:26.982965+00	2026-03-31 08:57:54.937966+00	🏢	0	{"plan": {"name": "Premium", "price": 273.0, "currency": "USD", "interval": "monthly"}, "payment_methods": {"bank": {"enabled": true, "bank_name": "EquityBCDC", "swift_code": "", "account_name": "Gestion ONEC", "account_number": "111200214185932"}, "mobile_money": {"enabled": true, "provider": "M-pesa", "instructions": "Test", "merchant_number": "0818080946"}}, "support_contact": "kidikala@gmail.com", "billing_portal_url": "https://console-saas/tenants/{slug}/billing"}
8	dc2fcf82-a1b8-46d4-8b8f-04c0d172139f	Conseil National	cn	\N	\N	\N	\N	USD	0.0000	FREE	ACTIVE	\N	2	t	2026-03-24 13:41:52.110712+00	2026-03-25 15:27:53.884763+00	🏢	1	{"plan": {"name": "Premium", "price": 273.0, "currency": "USD", "interval": "monthly"}, "payment_methods": {"bank": {"enabled": true, "bank_name": "EquityBCDC", "swift_code": "", "account_name": "Gestion ONEC", "account_number": "111200214185932"}, "mobile_money": {"enabled": true, "provider": "M-pesa", "instructions": "Test", "merchant_number": "0818080946"}}, "support_contact": "kidikala@gmail.com", "billing_portal_url": "https://console-saas/tenants/{slug}/billing"}
\.


--
-- Data for Name: participants_transport; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.participants_transport (id, remboursement_id, nom, titre_fonction, montant, type_participant, expert_comptable_id, created_at) FROM stdin;
43b841bc-84d2-4893-8c20-63d2218c05bc	96dbc622-acfe-4486-8543-1296dd2c538d	bukasa	membre	50.00	principal	\N	2026-03-20 12:42:39.180776+00
f354f254-c18e-46fe-9a8e-6524de3f392f	96dbc622-acfe-4486-8543-1296dd2c538d	kidikala	sec adam	0.00	assistant	\N	2026-03-20 12:42:39.180784+00
\.


--
-- Data for Name: payment_history; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.payment_history (id, encaissement_id, montant, mode_paiement, reference, notes, created_by, created_at, organisation_id) FROM stdin;
b83fe00f-8cf0-4e7c-addd-4ea7c8115672	d8baf738-e09b-4c77-afd9-5cef81c7f72b	20.00	cash	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-04-08 13:17:14.688197+00	1
17a7613b-cc53-4e1f-8aca-b49c1e4eca47	f68c65b4-e370-4960-9ce1-f746a3163bb5	20.00	cash	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-04-08 13:17:14.688974+00	1
a3f5110c-3324-4377-9442-fa0a1f29dcd4	03e7c4db-9129-42ef-8a2c-ceb0e161b769	49.98	cash	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-04-08 14:37:19.140311+00	1
717019fb-712c-48c9-9bea-1d1dbaba9d34	96ace1b9-fcb1-45db-b844-ae9ec6a096dc	200.00	cash	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-04-13 09:10:01.2308+00	1
\.


--
-- Data for Name: payment_logs; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.payment_logs (id, organisation_id, phone_number, amount, provider, status, raw_response, created_at) FROM stdin;
\.


--
-- Data for Name: payment_transactions; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.payment_transactions (id, provider, provider_ref, reference, amount, fees, currency, status, method, phone, raw_payload, error_message, encaissement_id, created_at, updated_at, organisation_id) FROM stdin;
\.


--
-- Data for Name: permissions; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.permissions (id, code, description, created_at) FROM stdin;
1	can_create_requisition	Créer une réquisition	2026-03-19 10:20:26.982965+00
2	can_verify_technical	Avis technique	2026-03-19 10:20:26.982965+00
3	can_validate_final	Validation finale	2026-03-19 10:20:26.982965+00
4	can_execute_payment	Exécuter la sortie de fonds	2026-03-19 10:20:26.982965+00
5	can_manage_users	Gérer les utilisateurs	2026-03-19 10:20:26.982965+00
6	can_edit_settings	Gérer les paramètres	2026-03-19 10:20:26.982965+00
7	can_view_reports	Accès aux rapports	2026-03-19 10:20:26.982965+00
8	menu_requisitions	Accès au module Réquisitions	2026-03-19 10:20:26.982965+00
9	menu_services	Accès aux commissions (Services)	2026-03-19 10:20:26.982965+00
10	menu_mon_espace	Accès au portail Commission (Mon espace)	2026-03-19 10:20:26.982965+00
11	menu_validation_examens	Accès aux dossiers d'examen	2026-03-19 10:20:26.982965+00
\.


--
-- Data for Name: plans; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.plans (id, name, monthly_price_usd, features, is_active, created_at, updated_at, max_users, ai_features_enabled) FROM stdin;
1	Essentiel	280.00	{"max_users": 5, "ai_reports": false}	t	2026-03-19 10:20:26.982965+00	2026-03-19 10:20:26.982965+00	10	f
2	Premium	390.00	{"max_users": 20, "ai_reports": true}	t	2026-03-19 10:20:26.982965+00	2026-03-19 10:20:26.982965+00	10	f
\.


--
-- Data for Name: platform_settings; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.platform_settings (id, billing_config, updated_at) FROM stdin;
1	{"plan": {"name": "Premium", "price": 273.0, "currency": "USD", "interval": "monthly"}, "payment_methods": {"bank": {"enabled": true, "bank_name": "EquityBCDC", "swift_code": "", "account_name": "Gestion ONEC", "account_number": "111200214185932"}, "mobile_money": {"enabled": true, "provider": "M-pesa", "instructions": "Test", "merchant_number": "0818080946"}}, "support_contact": "kidikala@gmail.com", "billing_portal_url": "https://console-saas/tenants/{slug}/billing"}	2026-03-27 15:01:54.231681+00
\.


--
-- Data for Name: print_settings; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.print_settings (id, organization_name, organization_subtitle, header_text, address, phone, email, website, bank_name, bank_account, mobile_money_name, mobile_money_number, show_header_logo, show_footer_signature, updated_by, updated_at, logo_url, stamp_url, paper_format, compact_header, default_currency, secondary_currency, exchange_rate, fiscal_year, budget_alert_threshold, budget_block_overrun, budget_force_roles, pied_de_page_legal, afficher_qr_code, recu_label_signature, recu_nom_signataire, req_titre_officiel, req_label_gauche, req_nom_gauche, req_label_droite, req_nom_droite, trans_titre_officiel, trans_label_gauche, trans_nom_gauche, trans_label_droite, trans_nom_droite, sortie_label_signature, sortie_nom_signataire, show_sortie_qr, sortie_qr_base_url, show_sortie_watermark, sortie_watermark_text, sortie_watermark_opacity, sortie_sig_label_1, sortie_sig_label_2, sortie_sig_label_3, sortie_sig_hint, encaissement_libelle_presets, exchange_rate_cdf, exchange_rate_eur, exchange_rate_xof, organisation_id) FROM stdin;
d6bb397c-0921-4ce0-b958-774e70ddeb0b	Conseil Provincial du Haut-Katanga											t	t	\N	2026-03-25 12:48:58.628017+00			A5	f	USD	CDF	0.0000	2026	80	t			t															t		t	PAYÉ	0.15	CAISSIER	COMPTABLE	AUTORITÉ (TRÉSORERIE)	Signature & date	Cotisation annuelle - Expert-Comptable Cabinet\nCotisation annuelle - Expert-Comptable Indépendant\nCotisation annuelle - Expert-Comptable Salarié\nCotisation annuelle - Stagiaire (SEC)\nArriérés de cotisation\nPénalité de retard - Cotisation\nRégularisation cotisation antérieure\nFrais de participation - Formation fiscale\nFrais de participation - Co-commissariat\nInscription - Séminaire professionnel\nAttestation de formation\nContribution FORCO annuelle\nPénalité absence formation obligatoire\nFrais d'inscription au Tableau\nFrais de réinscription\nFrais d'étude de dossier\nDélivrance attestation d'inscription\nDélivrance duplicata carte professionnelle\nMutation / Transfert de cabinet\nFrais de stage professionnel\nDélivrance certificat professionnel\nLégalisation de signature\nCertification de documents\nAttestation de conformité\nVente de formulaire officiel\nAmende disciplinaire\nPénalité administrative\nRégularisation décision disciplinaire\nContribution Commission Tableau\nContribution Commission FORCO\nContribution Commission Discipline\nContribution événement institutionnel\nParticipation activité spéciale ONEC\nLocation salle de réunion\nContribution partenaire institutionnel\nSponsoring événement\nSubvention reçue\nDon volontaire\nRecette exceptionnelle\nVente matériel usagé\nRemboursement frais\nAutres recettes	0.0000	0.0000	0.0000	9
211475d2-7c0c-4a47-9421-55618e133358	Conseil Provincial de Sud-Kivu											t	t	\N	2026-03-25 14:20:46.087207+00			A5	f	USD	CDF	0.0000	2026	80	t			t															t		t	PAYÉ	0.15	CAISSIER	COMPTABLE	AUTORITÉ (TRÉSORERIE)	Signature & date	Cotisation annuelle - Expert-Comptable Cabinet\nCotisation annuelle - Expert-Comptable Indépendant\nCotisation annuelle - Expert-Comptable Salarié\nCotisation annuelle - Stagiaire (SEC)\nArriérés de cotisation\nPénalité de retard - Cotisation\nRégularisation cotisation antérieure\nFrais de participation - Formation fiscale\nFrais de participation - Co-commissariat\nInscription - Séminaire professionnel\nAttestation de formation\nContribution FORCO annuelle\nPénalité absence formation obligatoire\nFrais d'inscription au Tableau\nFrais de réinscription\nFrais d'étude de dossier\nDélivrance attestation d'inscription\nDélivrance duplicata carte professionnelle\nMutation / Transfert de cabinet\nFrais de stage professionnel\nDélivrance certificat professionnel\nLégalisation de signature\nCertification de documents\nAttestation de conformité\nVente de formulaire officiel\nAmende disciplinaire\nPénalité administrative\nRégularisation décision disciplinaire\nContribution Commission Tableau\nContribution Commission FORCO\nContribution Commission Discipline\nContribution événement institutionnel\nParticipation activité spéciale ONEC\nLocation salle de réunion\nContribution partenaire institutionnel\nSponsoring événement\nSubvention reçue\nDon volontaire\nRecette exceptionnelle\nVente matériel usagé\nRemboursement frais\nAutres recettes	0.0000	0.0000	0.0000	10
8e244adc-e516-4d35-95c7-4125a72679d9	Conseil National											t	t	\N	2026-03-26 15:15:21.155331+00			A5	f	USD	CDF	225.0000	2026	80	t			t															t		t	PAYÉ	0.15	CAISSIER	COMPTABLE	AUTORITÉ (TRÉSORERIE)	Signature & date	Cotisation annuelle - Expert-Comptable Cabinet\nCotisation annuelle - Expert-Comptable Indépendant\nCotisation annuelle - Expert-Comptable Salarié\nCotisation annuelle - Stagiaire (SEC)\nArriérés de cotisation\nPénalité de retard - Cotisation\nRégularisation cotisation antérieure\nFrais de participation - Formation fiscale\nFrais de participation - Co-commissariat\nInscription - Séminaire professionnel\nAttestation de formation\nContribution FORCO annuelle\nPénalité absence formation obligatoire\nFrais d'inscription au Tableau\nFrais de réinscription\nFrais d'étude de dossier\nDélivrance attestation d'inscription\nDélivrance duplicata carte professionnelle\nMutation / Transfert de cabinet\nFrais de stage professionnel\nDélivrance certificat professionnel\nLégalisation de signature\nCertification de documents\nAttestation de conformité\nVente de formulaire officiel\nAmende disciplinaire\nPénalité administrative\nRégularisation décision disciplinaire\nContribution Commission Tableau\nContribution Commission FORCO\nContribution Commission Discipline\nContribution événement institutionnel\nParticipation activité spéciale ONEC\nLocation salle de réunion\nContribution partenaire institutionnel\nSponsoring événement\nSubvention reçue\nDon volontaire\nRecette exceptionnelle\nVente matériel usagé\nRemboursement frais\nAutres recettes	225.0000	0.0000	0.0000	8
88720a71-4c5e-4f80-93d1-60f8061018a6	Conseil Provincial de Kinshasa	République Démocratique du Congo				contact@onecrdc.com	www.onecrdc.com	Rawbank	1111111111111111111111111	M-pesa	+243818080946	t	t	\N	2026-04-12 10:02:00.538599+00			A5	t	USD	CDF	225.0000	2026	80	t		Ce reçu fait foi de paiement. Conservez-le précieusement.	t				 Revue par la Trésorière	Jolie Rachel BENGA NSUNGI	Approuvée par le Rapporteur 	Adolphe OKENDE MBUNGU		Revue par la Trésorière	Jolie Rachel BENGA NSUNGI	Approuvée par le Rapporteur	Adolphe OKENDE MBUNGU			t		t	PAYÉ	0.15	CAISSIER	COMPTABLE	AUTORITÉ (TRÉSORERIE)	Signature & date	Cotisation annuelle - Expert-Comptable Cabinet\nCotisation annuelle - Expert-Comptable Indépendant\nCotisation annuelle - Expert-Comptable Salarié\nCotisation annuelle - Stagiaire (SEC)\nArriérés de cotisation\nPénalité de retard - Cotisation\nRégularisation cotisation antérieure\nFrais de participation - Formation fiscale\nFrais de participation - Co-commissariat\nInscription - Séminaire professionnel\nAttestation de formation\nContribution FORCO annuelle\nPénalité absence formation obligatoire\nFrais d'inscription au Tableau\nFrais de réinscription\nFrais d'étude de dossier\nDélivrance attestation d'inscription\nDélivrance duplicata carte professionnelle\nMutation / Transfert de cabinet\nFrais de stage professionnel\nDélivrance certificat professionnel\nLégalisation de signature\nCertification de documents\nAttestation de conformité\nVente de formulaire officiel\nAmende disciplinaire\nPénalité administrative\nRégularisation décision disciplinaire\nContribution Commission Tableau\nContribution Commission FORCO\nContribution Commission Discipline\nContribution événement institutionnel\nParticipation activité spéciale ONEC\nLocation salle de réunion\nContribution partenaire institutionnel\nSponsoring événement\nSubvention reçue\nDon volontaire\nRecette exceptionnelle\nVente matériel usagé\nRemboursement frais\nAutres recettes\ncarnet\npaquet de stylos\npile pour micro	225.0000	0.0000	0.0000	1
\.


--
-- Data for Name: refresh_tokens; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.refresh_tokens (id, user_id, jti, token_hash, revoked, expires_at, created_at) FROM stdin;
af2a27b3-5681-4842-9266-e10ecd779cac	a2375bac-4a9f-4ed8-b674-a1807543c744	51Fw40CEiyvZ0kGzcmB_6mGx0Up_XhSFp-x5Rve-AP4	6238daaf75f4530174834a0636e0cd9a83a77a6975e460b8625a1d3f04d593b7	f	2026-03-26 10:53:55.514405+00	2026-03-19 10:53:55.577196+00
b60c5d95-a3f4-4d01-873c-a11a52b7ae17	a2375bac-4a9f-4ed8-b674-a1807543c744	gQseOKhaAWGweYt0J6rE0vigNhaIjqmVU1diR37hUOo	4c52de8310868d3b3b866d03f0a2d23db164410a6bd49b6956e05aec808afc28	f	2026-03-26 10:58:45.933413+00	2026-03-19 10:58:45.952475+00
ab0a1e87-2d63-4c45-aec9-cb64cdfac9c3	a2375bac-4a9f-4ed8-b674-a1807543c744	YPA9EDwK-Ej0Z0JFuWRz2o_h_oMc_c1aOsLbNrL1Zsw	848f0df222f3c155958d4d16689e906552af6ea1205cc6783eb64f5e6d65883e	f	2026-03-26 11:07:16.168794+00	2026-03-19 11:07:16.195976+00
0f3cde77-2a97-4993-ba4c-e2db1092c885	a2375bac-4a9f-4ed8-b674-a1807543c744	cBX1hb8Qo_7Xpx7idO4MKX-EmB_SEtYzeuvQADs1BvI	82b553d8ec52b37d5b8e96b94ee50c8435c676385f2b52dd12ca2611859d6346	f	2026-03-26 11:50:48.131245+00	2026-03-19 11:50:48.219239+00
8f9c3c17-d729-4260-8abb-fb621664e778	a2375bac-4a9f-4ed8-b674-a1807543c744	XZ6dSNXizICVE8Y0KL0V3R-UHJUnQQ5XIpHgZ6V2884	3a39f21b2ae8b648c1957373106abf3cee47bb74dbbcd734c90038189f2dc3e6	f	2026-03-26 12:13:41.659002+00	2026-03-19 12:13:41.687479+00
e24c4b0b-e2e5-411f-91a7-a7aff55672c1	a2375bac-4a9f-4ed8-b674-a1807543c744	-83sSeQROlTqAdlfriHXSLdlvZZkFbVT4bG7UcaC-V0	dd430efd531dd899fda16a8c5b382fb001b7c0cf91a8ca1acf1548bd57a79c14	t	2026-03-26 13:49:36.995516+00	2026-03-19 13:49:36.995955+00
ff674286-e409-4639-a017-9feed8c9537d	a2375bac-4a9f-4ed8-b674-a1807543c744	iIICTP_K7JQMokPMOjAk92kHxxnuf84q7OxlNfuiX-s	dd34fb0eb130ff69cc1283da2a2e64a9677590983ad2dd1e594fc5e3a15ff82c	f	2026-03-26 12:17:25.94893+00	2026-03-19 12:17:25.953843+00
568e860b-d850-48c7-88c2-40dfa1097399	a2375bac-4a9f-4ed8-b674-a1807543c744	PYs3BdmgT3f6kg9thCqYw33gOwGKuqmtXiQy8rLCO90	7d3626c14582fb81eda8a910c240114ecab7db37afe5928511f1392a872c5270	t	2026-03-26 12:09:05.607169+00	2026-03-19 12:09:05.629601+00
d9f18377-8f01-4175-ac2b-8c4b652c9cd9	a2375bac-4a9f-4ed8-b674-a1807543c744	ZrmsQCHl-hekWMgvZ7cb2yjlSWs3ZzYNREUxzLALpCc	c3280121b82c932e7328e4b6e02fa7f869cac9da2b6605004b582e3b1af4920e	f	2026-03-26 12:42:18.873698+00	2026-03-19 12:42:18.88624+00
1a3fa3e4-619b-4f69-8bc0-e13a233e7dd2	a2375bac-4a9f-4ed8-b674-a1807543c744	seXFISiacZj0XNO3opQULdKaktAkavE2Q_ztGOpU2mM	65716997617ca805f1fb1e006909c6169952df93587b920ab2fe02ba1ca3f8c0	f	2026-03-26 12:20:32.379002+00	2026-03-19 12:20:32.383499+00
fb72fa11-5d40-46af-8564-310064ba9e9d	a2375bac-4a9f-4ed8-b674-a1807543c744	MoW-y5BfoRd_taShPnOlCg8QsI0aeFDv30oGI2-o5yk	a490ab1ec37867ce555d530a2523b720d752443da50e703f466e1f696c5ec3b5	t	2026-03-26 12:17:25.978526+00	2026-03-19 12:17:25.979116+00
7d10bfd2-8860-492c-a57b-18339f75d6e5	a2375bac-4a9f-4ed8-b674-a1807543c744	Ah7m3Afrx-bmPRP9IueSM76dMDBCxL1d6BkxaeF_tt0	ac2c18f156562aebe206eb16e92db53d1be19be24a36cf0fbf5f3bd2dbcd4b5a	t	2026-03-26 12:39:23.030912+00	2026-03-19 12:39:23.031307+00
e5d456e0-47f2-42c8-9718-78e001fd5c4e	a2375bac-4a9f-4ed8-b674-a1807543c744	ikjHAP0fOPyJjv78Z5rQ2qT-uAMSvgKHvVq6brF9Oic	49829dc796a038fd36e9f0b4440791ff9313e4af75359eefb8eded1abbda7e13	f	2026-03-26 12:21:05.932747+00	2026-03-19 12:21:05.933057+00
d9a0e534-6c06-40e3-b325-7fe1e2d338cb	a2375bac-4a9f-4ed8-b674-a1807543c744	2mtKXX2DliohL26AZV16iIOp45S331Aa88INuLnh-AY	566b89032d6098b1c182f74c4fb63519506831a89653fedcce1bd0926c9d172c	t	2026-03-26 12:20:32.404846+00	2026-03-19 12:20:32.405594+00
a1de68bf-a1bf-4879-b74b-afd2f6527b2b	a2375bac-4a9f-4ed8-b674-a1807543c744	slprZ2ecSlmpLWAi4mdrJ3T8v73GLR1cx3cbdvrKlFA	bdcd9189b4f1621f310d20503dd4896a76320860a5b76f36b1e2ff72c8c86dc7	f	2026-03-26 12:26:07.123118+00	2026-03-19 12:26:07.133929+00
a0cab59c-be5c-49bc-8d49-64d9fbda5ca1	a2375bac-4a9f-4ed8-b674-a1807543c744	K749lL_Gjzj5Qu6VJNAbxRRiZ2Q3HwD1Kpy2opkclV4	448b8d28a15afed74bb919ecf67d3c38d73f202735cc0bd2dcfab357359c3a0f	t	2026-03-26 12:21:05.938287+00	2026-03-19 12:21:05.940307+00
cc553436-bd95-4fc1-9a4a-d34c7fba23bf	a2375bac-4a9f-4ed8-b674-a1807543c744	vYmNbu1-ohCutkLIYno5U4Y-sboBC-T3FFYm-6lyLrw	554826ba39208a7b3f9097890cb34391772b2937cfaba55058c796cc92673520	f	2026-03-26 13:05:37.903846+00	2026-03-19 13:05:37.908715+00
c28305bb-fad6-4f36-9427-4e9faa45a920	a2375bac-4a9f-4ed8-b674-a1807543c744	lexE-ZGfTXVbgGmVSYFj-Pr6XCBcosGvtvIg7thdAss	5c6dfcd120b676356aed4d4c8a72df941ef9e57ef76322248337a9bfbed61f0f	f	2026-03-26 12:31:06.270198+00	2026-03-19 12:31:06.27154+00
05fc840a-157b-4cc1-a24d-731493e2ed25	a2375bac-4a9f-4ed8-b674-a1807543c744	4snKTA2tFbzNGgdezzvDEmYDsNOs-CpuMgY3EXaBVxE	5bcfbdb695cfc47cc21ee2f2926cddfe3df3c6b5cc482266b79d21da8b8ed978	t	2026-03-26 12:26:07.164822+00	2026-03-19 12:26:07.165375+00
36e8b799-9dbe-44d6-a69c-7957c52efbf5	a2375bac-4a9f-4ed8-b674-a1807543c744	UpGqgxk8OwCfEnmhtn4JfwM_NT1wkJoeiDuHOiQMUCM	bd8f966df9b8a919329690e5d1b0ce524e8e42aca38a6ff10d94b7a81f2486cc	f	2026-03-26 12:44:52.112445+00	2026-03-19 12:44:52.132085+00
03bd0ecb-2d45-4f8b-a878-3d27e72332be	a2375bac-4a9f-4ed8-b674-a1807543c744	3yUrMDipivBwNwzQK9zNblrTAkZxtYVK7YYAiKVuR8s	95cefaadfd49ea4c310d399e379251fbac531c8585da76781ab7d9b5dae860fa	f	2026-03-26 12:33:46.3378+00	2026-03-19 12:33:46.350028+00
32ae8117-22c5-4531-a580-6ee1c197101c	a2375bac-4a9f-4ed8-b674-a1807543c744	SbrUxQwokQxWK3WAnld0uPvZcaFB0p5-OlYgXNwvDgA	49c73d620ebfc5973d4590271f75b213bf70c0637c3cd93df6ab82bccd11b107	t	2026-03-26 12:31:06.284121+00	2026-03-19 12:31:06.284544+00
efe4c597-18b0-4bff-8d7d-5fc16502b3cc	a2375bac-4a9f-4ed8-b674-a1807543c744	Qg_R9MlgINnkcwK4m1aPe4FN3tvZYIQIfz02eghgjlI	c1f433591b82460a7b4e999b00c1dc65cdbd0075cdb2a76f76798427db4aaf7d	f	2026-03-26 12:38:02.25144+00	2026-03-19 12:38:02.260385+00
691a2848-763b-4034-ae5c-bce28bb45a9f	a2375bac-4a9f-4ed8-b674-a1807543c744	-96BV67a3gzEaxSxiT50nmQzR4QgrLRe1IX5RA6eauo	fa560e7b7776c3d9f122f99cfa742a99e13d2f737169af7571d5762d9410588f	t	2026-03-26 12:33:46.391677+00	2026-03-19 12:33:46.392003+00
3b415001-4f1c-4512-aea4-3b260015ce88	a2375bac-4a9f-4ed8-b674-a1807543c744	BCTbjdIb--F5ynG-n-roNSG9SzZEEhEA9EhFgH1EBNo	3a4d3f0d0c89ba7b4c2a8e2e0e15bcafad38ef8f6b34a123071f66e4432db22c	t	2026-03-26 12:42:18.922494+00	2026-03-19 12:42:18.923577+00
655dd22a-ebf7-4784-96d5-40b5ec6a4298	a2375bac-4a9f-4ed8-b674-a1807543c744	e0k3d68PpBvXOlwsZQIFh3oziE7x0ttjBfY7s0vj5OY	6e4bba61690213c28ed8c9aa08ead749c2a809505773cb0235bc8de7565b55ab	f	2026-03-26 12:39:22.650515+00	2026-03-19 12:39:22.652023+00
3030807b-149f-40dc-99b9-fe2fa4db1177	a2375bac-4a9f-4ed8-b674-a1807543c744	GU4M52HIj61EAAuxzGPNQvy52v0ptXzIkxSZlBU_Vd0	7977bba64567eea8b43b0f268eb3fb0fe88bd93fad71ebe17ab1e9b3700e1871	t	2026-03-26 12:39:14.770086+00	2026-03-19 12:39:14.807491+00
d29163bb-d76b-4292-90c2-8ad6742e7271	a2375bac-4a9f-4ed8-b674-a1807543c744	bG3VeC608xW2Sqrc5Wvy43yzOqET_JXQ7N67WJfICP0	0602cd7ac84265986b6a8d44825375a99c48fbf56fe8d6105e9cd1ae148950e7	f	2026-03-26 12:39:22.670949+00	2026-03-19 12:39:22.671702+00
ff23ed29-ea41-4bf1-9abc-70f4c40c68aa	a2375bac-4a9f-4ed8-b674-a1807543c744	YTR4fvlmr1-k-N_qOYnbtfYkL8viY-Re5GQc2LDxZDE	49ea133aa37434bce4c6f208ebd2b3f712527bb52b3c8c74a32dd186f8d9c8aa	f	2026-03-26 12:39:23.019482+00	2026-03-19 12:39:23.01998+00
2300c6cc-8c6e-4086-b2ab-8c8401fb6211	a2375bac-4a9f-4ed8-b674-a1807543c744	ysZ2p_f-VGzZ4cysv65wF-Yh1iWZm44wQVfdkMcunow	2c630d2a9d1649b5dedade5889963dd641b55459d4b5bde3a533f36354ce9c9c	t	2026-03-26 12:39:22.911169+00	2026-03-19 12:39:22.911555+00
f48b40ae-abd2-4a92-999e-aec0e98d41b8	a2375bac-4a9f-4ed8-b674-a1807543c744	Zn4loMe3Nn2A9obG9zp-Xle6Ox7WMy_21r3roHg1BuY	376a87fc2629b8922836437524309d2b25b7361855dcd3a1afaeefc867180893	t	2026-03-26 12:47:01.385829+00	2026-03-19 12:47:01.38627+00
753d13fa-631b-4d0f-adb7-d444b75ed31c	a2375bac-4a9f-4ed8-b674-a1807543c744	d4wc20l90G4BM8gPol97rcsPC0oqNtziXvIaVzpgrw0	72c95938e779b089f6f7bc1103769ee483dd6501a7fb417dd81caef5447e41af	f	2026-03-26 12:45:45.211247+00	2026-03-19 12:45:45.234463+00
cbec6acd-504a-4726-959e-6f7e5a9675ba	a2375bac-4a9f-4ed8-b674-a1807543c744	szQbuVvS03-MNpAgdxD2S7Z-tJuTMLXi09OZrAOi8QA	4f70c2613e60a0f1b3b0d1b5275183bdd26a9af1f98032fd5cd53ae0d62a8a5b	t	2026-03-26 12:44:52.178222+00	2026-03-19 12:44:52.179115+00
b46d3a40-cdf7-473e-8704-44283c963ea8	a2375bac-4a9f-4ed8-b674-a1807543c744	rtZ5cikMsahtkf0DqOULgOpwUtFpTNAJnWF_aORiVC8	a57b31bc3f593b501971aec77477227042064eba5be885635646c3f51b897b79	f	2026-03-26 12:47:01.332149+00	2026-03-19 12:47:01.357502+00
1a946a5e-3998-46b8-bed3-57f2f5649ff0	a2375bac-4a9f-4ed8-b674-a1807543c744	tXUEqL--k8MY1OBcG6cYwIUlHZHRQS5KebTpL9CQ-yQ	a42b2073904bdb7575dab3b4c5ba71f888c953ff40e31add8e4c7fe4ff1cb5c0	t	2026-03-26 12:45:45.285732+00	2026-03-19 12:45:45.286366+00
7df3645d-16e2-44ee-a49d-10d98e16845f	a2375bac-4a9f-4ed8-b674-a1807543c744	i1O1MnzzHQw6EcrSRrXXlsWADPJc8vxgyN3eppLREWc	0fb68f43377b89e67ce0231e26408e8022757b36e84f305fc0790ccf63261108	f	2026-03-26 13:49:36.935458+00	2026-03-19 13:49:36.948921+00
9d32a30b-925c-438d-94bd-041fd15446e3	a2375bac-4a9f-4ed8-b674-a1807543c744	hw3BQpQl8A7eAN7dSdsvAr5m1PBbzUr8G3uPvR2YUkU	f986291e8df9cd958cb25c197e4a560c29533084c8e6c39e577fcf304acb77b6	f	2026-03-26 13:48:52.431365+00	2026-03-19 13:48:52.438056+00
7584737c-70cc-4a3a-b8a2-0bb5187c428c	a2375bac-4a9f-4ed8-b674-a1807543c744	8rqZgZv-p3-gAmhGI96YQkhthR07KgGzQx6M6YtuVIA	0db00da4ef42c629846e259374b52427eed35d77384e1f599dcc3767739aa11d	t	2026-03-26 13:05:37.935702+00	2026-03-19 13:05:37.9362+00
d960cf80-8f3b-4fed-a526-6e70dcf4d924	a2375bac-4a9f-4ed8-b674-a1807543c744	xw6IAwMl6VFyqhcvyg4FEeWl71NxHTlio1VVmc8nurQ	e2a7bad8f25a1c9fc7b8197cc9f431d8fb777b8910a0f273f98b6c6e2f7d3abf	t	2026-03-26 13:48:52.458032+00	2026-03-19 13:48:52.458464+00
2ac5f2a5-1dec-4a00-b26c-c0bd85b02f53	a2375bac-4a9f-4ed8-b674-a1807543c744	Iy1sECb-zAsHlH94dMTH1cYP1P31-ltiQ6mz4N79wL8	e7d7f945630bee53d3a758afd02f659a59b85084298fd79bf998a183bbb4530c	t	2026-03-26 13:51:08.532469+00	2026-03-19 13:51:08.537506+00
d058884c-471a-46c0-9b64-a194fbd0b63c	a2375bac-4a9f-4ed8-b674-a1807543c744	74Uao4OC-RYPyupzUjNM98_uMfkXqznUo9JaWh1LwIo	5599294885e87709074bc179bfe07ca00485908b34e1f8c0a677fad529895488	t	2026-03-26 14:30:09.564609+00	2026-03-19 14:30:09.567421+00
f567cd1d-0124-4b55-9640-84b04ef59c7f	a2375bac-4a9f-4ed8-b674-a1807543c744	PIfy8igy-uKyZ7zXJHk2hJjL58q9FvDFnlZzSr9fAMM	d79ac232675c879c8884746e2a05032b49ed6c9cd9b7b0894a4671fad6d4b443	t	2026-03-26 14:30:18.072785+00	2026-03-19 14:30:18.07325+00
54a193b0-942b-4fc3-bf52-c217cdbd65dd	a2375bac-4a9f-4ed8-b674-a1807543c744	TKQdvadxBgGKsm8yzk1HdmIOj4TX39zaZ6vQAWqK1I8	85a8c19c80ab75d2e699165aab2aee1db46f4e57bcab8ad7beae9841a60430d7	t	2026-03-26 17:11:08.946454+00	2026-03-19 17:11:08.9486+00
ec171ac6-a022-4bff-b585-1e923ef33340	a2375bac-4a9f-4ed8-b674-a1807543c744	pOfqihU3sz1gG7lYGOkg1vaqhDqjA6I_ks-4aMvT88A	5b53cd86278b1283fd9e7ef3efca23e69271b6e0d2c6e51cd83dd1801112ef15	f	2026-03-26 15:33:07.592422+00	2026-03-19 15:33:07.604574+00
c39b4a0b-b7f1-45e7-a7a3-3b36af27ec8e	a2375bac-4a9f-4ed8-b674-a1807543c744	PdtCpXVI9qMjuZU9R7agk2b09e09zu9NogVg0BCVXBg	2fa3db2af9ee77d828d47e76d3ff8f812564d266aaa34a18c39215e50b10d4da	t	2026-03-26 14:31:57.6657+00	2026-03-19 14:31:57.682883+00
44415568-e832-449c-a41c-08e43fa49b72	a2375bac-4a9f-4ed8-b674-a1807543c744	4HJY_xTRYgawwUyxLAbaip5VcTiE-f9_NIDGEiclhHQ	afe93452bf0f52a158c76d809aea68e03bcdb1e02c535aaba70590e711cf1d4f	f	2026-03-26 15:35:47.085889+00	2026-03-19 15:35:47.095787+00
141f95f3-a9d6-4b0b-b2b0-9fd88979cda7	a2375bac-4a9f-4ed8-b674-a1807543c744	_AJJ0iPmJO-lsXcXjJt9_wZ9I4wmCKp46g1AtpECcc4	cd1f816cbe810645eea394524b5214e724baa58a7ae083e9d97b0a47cd48b0d3	t	2026-03-26 15:33:07.649405+00	2026-03-19 15:33:07.649895+00
2fd23b09-89c2-4115-b63f-f537bd19762b	a2375bac-4a9f-4ed8-b674-a1807543c744	MLbkHdxsGfEjn_KclT6159OZweRx7DmccC4tylhYkBg	e5549b121f79fabe7dc89fec283dd3d43860d5116aec75350f145f7ba42a3e31	t	2026-03-26 15:35:47.125687+00	2026-03-19 15:35:47.126123+00
ff13d376-80ab-4e17-912a-d40afc1cb010	a2375bac-4a9f-4ed8-b674-a1807543c744	-2tZcWGKpW7GeWsG7g3sQf_BnX97g9PNgzDyupW3Vfs	ce3c98c1f30033545278db83122962999bb4de600ffe6ba6783c8ebe77c9f5e2	f	2026-03-26 16:14:46.04049+00	2026-03-19 16:14:46.059293+00
515bd09a-734f-40f3-8604-9d6b8ac1a8a5	a2375bac-4a9f-4ed8-b674-a1807543c744	K0ELo5EXIV4v48oDxgJsbI-f4Jt6XJ5XfsAmpHUu7KQ	4cd47dd16c1a438fabf63434937f0ba65797e405ea0bc444f2af68c779f5553e	f	2026-03-26 16:18:28.737291+00	2026-03-19 16:18:28.746651+00
da4b26e9-62be-4f5e-8ba4-38be7a1df5eb	a2375bac-4a9f-4ed8-b674-a1807543c744	aee9cDfgabdgmy4wXfyJNE8xszgu5c4EZd0fnaiACLk	4f3a194ec5b75d36d1deac5eb1fa86da5489512a0a21077b024bd379c84c1733	f	2026-03-26 16:26:49.565468+00	2026-03-19 16:26:49.568577+00
7059d20d-8956-4f3e-8764-4a2e17779356	a2375bac-4a9f-4ed8-b674-a1807543c744	shQYyQBG0ARb3nq2nO1qtPZJMwELTtcLQacAQgQ-F1c	f369cdd075ead91b3fc637637bb95c55dc1c33eccb2004fd2d931391f77235fa	f	2026-03-26 16:29:39.258443+00	2026-03-19 16:29:39.262315+00
cfda0439-370b-4ef4-98da-8dcd891edf40	a2375bac-4a9f-4ed8-b674-a1807543c744	WZ8rLWOoQvdV79SGvaTwAZ7GZLQVR2vPlRIq3cuLRBs	66151da48b1771a59bd58c4a339b8d402985da947b6ea8af80687a76ea44bb5f	t	2026-03-26 16:26:18.70676+00	2026-03-19 16:26:18.727601+00
750c2818-5e0d-4afc-aa03-cc44b4e9d562	a2375bac-4a9f-4ed8-b674-a1807543c744	V5o4FV01GSCPee6BM1qJqIiclnx29GgYV2k4CaU596k	947a2dea91d29bea7c5752ce06c59fab73d8af8bcae612f40b02e0d6ba31bde2	t	2026-03-26 17:11:09.267483+00	2026-03-19 17:11:09.272706+00
5d51647d-f51c-476c-9087-ff3132aaf4d2	a2375bac-4a9f-4ed8-b674-a1807543c744	7I4vu4zhDyIzs_WWvBXDyqcZ186SALfo8_2wMKSfVtI	683e00422c67ef3602bef080689e8398950c37aa2e28b4e68902f3c6d7d3a0cb	f	2026-03-26 16:29:48.219312+00	2026-03-19 16:29:48.219828+00
5c786d7c-15d0-4d26-b535-cb81dec7ee48	a2375bac-4a9f-4ed8-b674-a1807543c744	345RVW1XAFr8Y69fRPQiJ2Chxg6bfna_7Al2BJjwBOA	e157c582735aa7324bebcb45fe05117c4b25a8aa4864cdd17e68224fbda83d82	t	2026-03-26 16:29:39.283344+00	2026-03-19 16:29:39.283981+00
2c34d254-690c-4275-9a89-af75faf86869	a2375bac-4a9f-4ed8-b674-a1807543c744	RmkLnaCBhGN50jENWrYsYrUPA7qknYoO-USgpwa8wyw	0b7280345c025f836952b11ad0c7a6cd9014f531d28c6456e7fb0f65d80c60aa	f	2026-03-26 16:31:19.53892+00	2026-03-19 16:31:19.555743+00
1a2f92db-66ae-4f43-acfb-a5f806b330ea	a2375bac-4a9f-4ed8-b674-a1807543c744	4PonOZbwsf3Th2T44KKad_DdtGxxf8BKspXyQfgnyTY	6cc3edfcfaeebbf5802212589a300043d00ba6fb9ebb2052c85b1065b8012a8b	t	2026-03-26 16:29:48.232589+00	2026-03-19 16:29:48.233041+00
f19eb66a-0a64-4f73-b63f-6d3ece09297a	a2375bac-4a9f-4ed8-b674-a1807543c744	cNh4RSUizr33ImVEoo29MsY9T4amqd_1mpVjy0IGvms	8ed87cd34e92fc703b498919b3cfc5731132b003bacbb4097293ad99f2fe1067	t	2026-03-26 17:11:09.350973+00	2026-03-19 17:11:09.3517+00
6cb5e279-598d-481d-9569-95e5f8fbd52f	a2375bac-4a9f-4ed8-b674-a1807543c744	pNSyWqMYf3U4tXBhvRL4M1wlr8CvpEAy73odYzR6Bm8	5a9dc3cb9057d9399b67594282f6a7d3f4a7a3444a751cedab8a50100c6136f1	f	2026-03-26 16:31:29.919788+00	2026-03-19 16:31:29.920557+00
c82b4d0c-dc28-4bcf-8f29-bddf1a7ee935	a2375bac-4a9f-4ed8-b674-a1807543c744	DU5u4-OpslCU-7uwo4uPCIwcTkjgs9L_9SsM9nJt9Q4	7ecf19576681694d3ef8707617030013ea7307d78c7d47b3ac99668a358500e3	t	2026-03-26 16:31:19.591757+00	2026-03-19 16:31:19.592879+00
2cbcd9a2-c88c-4e56-b301-984d97ab820d	a2375bac-4a9f-4ed8-b674-a1807543c744	on5k76gsz0vhpGTROLUgU7uR_bCaT5rdemUi2QW28Ec	51a5ee44b819eb96e74f5c7f385d5bd674f4e01d41d149f5a7c803bd0053ec84	f	2026-03-26 16:35:24.343169+00	2026-03-19 16:35:24.345153+00
47296b84-3865-4d19-80e3-7b86cddf184e	a2375bac-4a9f-4ed8-b674-a1807543c744	mg1R4Zw5sRjn9-Fe5xd21bN6Cec67xLC3ThSLDwqLT0	fcc099ef701a1f3d828428a01206a4b6bfe439b818c1828a1a43a0a9de86bfd4	f	2026-03-26 17:11:19.323072+00	2026-03-19 17:11:19.325069+00
8222ac82-bcf1-400a-aaa5-a2d589fa6837	a2375bac-4a9f-4ed8-b674-a1807543c744	liV7Sk24biswIJ2k00MpkhOiyn19Chp70oD6Nsz1OmM	a29c1544f40e7494fb6a0fce926032cb49d777feb76dff6859756d1533bad5e5	f	2026-03-26 16:35:38.596369+00	2026-03-19 16:35:38.600275+00
f9b89b7a-5dff-4060-9f46-6f7b0db6b1c5	a2375bac-4a9f-4ed8-b674-a1807543c744	zZaPkmLraLovKiMoa2LIMVascBL1VGYm94xRKezcLTY	eac09af0aaa5a5df403c9f5c3673fb1a286ddb19295dd09f5f438e54263587e2	t	2026-03-26 16:31:29.931297+00	2026-03-19 16:31:29.932188+00
a045e57f-53f6-421b-a86b-7f3faf769e63	a2375bac-4a9f-4ed8-b674-a1807543c744	5WOU6Xv7M5g3AAJcmhrW8PreOd7ZcopandDT72LGMq8	3128754a19e53035d700df9c16dad32a86f7fc765faaf02a97c8090e4487511f	f	2026-03-26 16:35:38.629138+00	2026-03-19 16:35:38.630361+00
63602736-52e4-471f-a5d3-39e0da19d5ec	a2375bac-4a9f-4ed8-b674-a1807543c744	HY3mJ2j7omTJNCmg6LrP-GEqgviKOW94yrHaNk7nUjA	9d8a938e9b5c201254c01ed03ae8f1ad439a62a90b404de2c88e33daf566c2a4	f	2026-03-27 09:53:49.597406+00	2026-03-20 09:53:49.600482+00
ada33e9c-332c-45f7-8257-c5bd7e31c05c	a2375bac-4a9f-4ed8-b674-a1807543c744	OXdxbzszgVTe7Qd27Uf5RcStRIZqrWo74I5NLhl_12E	5f37639d3a375c71f6590be4f1674ed5816a176b33502c3af734e5a141513916	f	2026-03-26 17:11:08.543697+00	2026-03-19 17:11:08.544826+00
82b2e275-95b8-48ac-85f5-8f4c7fbad6f3	a2375bac-4a9f-4ed8-b674-a1807543c744	_Nn861PsMrxTe9vqqCLeFeq_mJ9nLAiGuiD887iib-0	79537817e1e7d3a5c50e1c9531bba08dca4ba269ba7bcd5ea97ed4d13875b841	t	2026-03-26 17:10:47.186522+00	2026-03-19 17:10:47.219219+00
0925dbb0-b94e-476a-b6bc-6ce2046fbe29	a2375bac-4a9f-4ed8-b674-a1807543c744	aI4WB_L8Cbk7UYS3y4tyKK3vlRZ2ZjTfH8w82RpGn6w	4389c5f8944d7113e275e58f8f2af1cde892c3f7979a8d18ef1ac6d2dd51025d	t	2026-03-26 17:11:08.558799+00	2026-03-19 17:11:08.559212+00
3c8624f8-8d78-4c0d-84f5-2b9fa8d63a9b	a2375bac-4a9f-4ed8-b674-a1807543c744	2E6mvEoNGcLkZUVIZxSy5fZwaBwPImzrY4EnbtS3thY	d36123ee8f737117b66161264753c06f47575f158d3060ecea3f2a4b7fa7aa45	f	2026-03-27 10:20:55.059843+00	2026-03-20 10:20:55.108198+00
2802f5e0-fd4f-41bd-8e51-2bfb192dd830	a2375bac-4a9f-4ed8-b674-a1807543c744	aBnXgDJMYD5v6wOka3kSQ9z7fk-LtxwOZwivq250r5g	2f99462de848d432b4392688749f2e34872f09ba237da63d9ddb535c26f02160	f	2026-03-27 10:24:15.83276+00	2026-03-20 10:24:15.834534+00
67b96591-9a38-49c7-97c3-014b3b24e4a7	a2375bac-4a9f-4ed8-b674-a1807543c744	HYnRKLt4YCTGi6SfK2SGXlYMOE5jvPrFJhCpKVty1n8	e816ef2f0c81fe0de45f382ffb3959c768921739ca6ad4600f16a1baececbbaa	f	2026-03-27 10:30:39.1021+00	2026-03-20 10:30:39.125839+00
58ed3fe8-6647-4e8e-a519-94faa1d838bc	a2375bac-4a9f-4ed8-b674-a1807543c744	FBPZ_1PNZuew7xGA3d04m1-cBlHdrelBrUVDo1QYqyM	6018cb02af6ad847caac2325713e0e1fbad13d9030c749ee3c6fd913024780d5	f	2026-03-27 10:46:38.03189+00	2026-03-20 10:46:38.038043+00
7d3d128f-4966-4f4f-bb5f-584e9b2af81d	a2375bac-4a9f-4ed8-b674-a1807543c744	Sru9x-UjFphRfKFcvYWYxQmHFX53-BpBRIuPrskyPTY	00c5453eafb5cce76713499ea6fbc88a84d428da40532b15f7b9b42a17fae37d	f	2026-03-27 10:58:18.923621+00	2026-03-20 10:58:18.949219+00
c5c145c8-5792-4622-8899-ccf39672c8c1	a2375bac-4a9f-4ed8-b674-a1807543c744	iOgrYuw-38GBYqe1eTe4zoRjKU07YuilsPcsMRNHbxU	ff89acb6710878020c0f7951709d982e9e7805f88490376b85727f299ef25c33	f	2026-03-27 11:26:08.613061+00	2026-03-20 11:26:08.627577+00
20fd6645-9b04-4d30-a375-bca9eaf02f4d	a2375bac-4a9f-4ed8-b674-a1807543c744	NiNvQLLfz1JC7gJW_uIw7gzlptva7cVXwzFowRfn3wI	e7997c8780bdcdf45f0b343e371b94904f3cb35df95d4132e52aa8990a922090	f	2026-03-27 11:40:06.553467+00	2026-03-20 11:40:06.565185+00
4859972b-b3d6-453f-88b8-edeecb3c578d	a2375bac-4a9f-4ed8-b674-a1807543c744	chYH1U-GCTJE5AsNvxGj9GmRWzWPkgfNhHgyuhj1Kbw	00947563e8cfff5ea874fa926b7beb024f3fbe899531c1990e1f120749780974	f	2026-03-27 11:45:53.739851+00	2026-03-20 11:45:53.74874+00
de2aa504-0857-4f6d-9f08-0f28ea016405	a2375bac-4a9f-4ed8-b674-a1807543c744	YIfFGa9TRi0PYTGS1E012qf9RPJQ4YMh2RvM8J9Oj3c	405872f04f63e271cdd538e508ec50d528f2f74474916508ba5875035e92c89b	f	2026-03-27 11:55:32.710367+00	2026-03-20 11:55:32.720884+00
16773733-6150-4122-a52f-34d84f7aa853	a2375bac-4a9f-4ed8-b674-a1807543c744	cCGqzcnHeBFUwdzuy4eBVzjqJkhTrqwU_HSX33GENCw	7d32fe121791303872dde1ac68a9cde9006950d0716e0f9b189f2405ea7f94c4	f	2026-03-27 12:02:12.443657+00	2026-03-20 12:02:12.456369+00
a7a639dd-d898-4265-9beb-b2dcb77d997d	a2375bac-4a9f-4ed8-b674-a1807543c744	SuiAryM1vqJ0ELK4z77G3KlEXvwCPO9DXd8Xn6HXTZY	c375c5ed0d47b250bd34eb5a4f188da88d00e3c3b42f9146e64b6abd8143835e	f	2026-03-27 12:32:58.217172+00	2026-03-20 12:32:58.218979+00
f72a9f5f-8597-47c2-9552-2f6036dda3f1	a2375bac-4a9f-4ed8-b674-a1807543c744	pZuonXmJ3q92yMEJXjvbENyf5YsoqqZcVdEAcsiB10k	2436492f36802bcaef8e4c4e37f7a8e9e8f362ee128ca8a4ef2e86433449bb68	f	2026-03-27 12:36:01.112682+00	2026-03-20 12:36:01.126729+00
3c7b3d85-1735-4552-8979-9097f4fbf7bd	a2375bac-4a9f-4ed8-b674-a1807543c744	1Xb8hboxZ4yRVZXGUahg52gIK0BRqArLTVr7GSArbSs	2df9cce4a3a5e13d5961ee4ac7c0da30c58dbe0f168db6f64fca38424d8624cf	f	2026-03-27 12:38:49.667237+00	2026-03-20 12:38:49.673739+00
7b61055f-e76b-4434-ac80-ad21e9993d96	a2375bac-4a9f-4ed8-b674-a1807543c744	oLUVrTX9uQutKsy_SXAPDudCCmuJC9xwb3wO9asX9wc	ec7114486b4be4e7d6dcbab02f994ec3581a760fe817dbfa7725001671280c8b	f	2026-03-27 12:47:32.198905+00	2026-03-20 12:47:32.211491+00
7fd8dad7-33aa-4277-9877-99a184fe5cd8	a2375bac-4a9f-4ed8-b674-a1807543c744	i2ozPQgRQWxL5neLQCc3SHmEaIGNUJKCVWREbjJ5h60	45eedcd39bc8f2323b32c3567e37bbce2369f15411c01a6958f4bd5f22c5ddf9	f	2026-03-27 13:51:49.53633+00	2026-03-20 13:51:49.563826+00
5f7d5c44-1aad-479f-8005-2e9de556afd5	a2375bac-4a9f-4ed8-b674-a1807543c744	8cpznZKbnpIVr_xgMCP2T3xgGFB6Fz_3Ee7II1InJ7M	2826ea81270e039ce482b9f2f98f27c73b7ac0bb916e36122ded7293d1f1ee04	f	2026-03-27 15:01:38.523932+00	2026-03-20 15:01:38.548963+00
dacba055-c8b1-43f8-875d-13dc9d69922e	a2375bac-4a9f-4ed8-b674-a1807543c744	ss48xX0qyjoPkaYwScD69G3veArROwLwsRFl5JghAzo	768db15f69783ea759051199d465ddae9ccd0d6e34d6820f0cfd1c6d9b68cbcf	f	2026-03-27 15:02:32.391581+00	2026-03-20 15:02:32.392006+00
f65a913e-7e6e-4444-9cfa-5ceb866d107e	a2375bac-4a9f-4ed8-b674-a1807543c744	MLtQ0pLLxA6sN2DJc2jSUmLLZWNulZHlTmhxCH3Sy4A	77932ab08b4f9ce02b26aba72e4bac15c3a37f53aed4c6d4ec96c991a13c8584	f	2026-03-30 08:42:36.786263+00	2026-03-23 08:42:36.811545+00
687aebc5-51e2-481c-aa64-1008455d8d08	a2375bac-4a9f-4ed8-b674-a1807543c744	aNjeIuGo2--1rt08EjM8tpJyTdFDA45hbooUHF-MQ3c	f44279460d7b4ed26628c9c027bce7bf8abb738ddb939a7771dc5eab9679bccf	f	2026-03-30 08:43:03.498753+00	2026-03-23 08:43:03.499383+00
1dded656-a7ca-4df7-89a2-3c2bb6019dfa	a2375bac-4a9f-4ed8-b674-a1807543c744	MTnPEk5zR66swP3fQgt-uiI2cYxjsW4prZnZApV6q-A	2959157eea4a48c320d6fc1b3732d47fb53c7c5dc45576035141a1ba9abe379e	f	2026-03-30 09:28:28.232457+00	2026-03-23 09:28:28.240375+00
c89473f2-5fb7-406b-9b77-25c446310bd8	a2375bac-4a9f-4ed8-b674-a1807543c744	l4nbGy20RXxoONfIDCbFHf9-XZOvI0jdd4VdOlqKkU8	91438f4f1b73df50a1a1053a3a70548f21e3fa8e4091e784cfcfb961aff7e1e2	f	2026-03-30 09:56:55.803233+00	2026-03-23 09:56:55.811162+00
5d934e92-f22a-4209-82b1-452e58f771f6	a2375bac-4a9f-4ed8-b674-a1807543c744	QgLhRlpCR6uq8QmSlMaXIqPbwhOkpd248LEAFGikNBM	d7ff3f5869129c7c0a3f933efc344a682b9c8aac8d110cce5b23244770d09f78	f	2026-03-30 10:04:57.461164+00	2026-03-23 10:04:57.480294+00
df555d8c-ac55-49ab-8e6d-825f1004f955	a2375bac-4a9f-4ed8-b674-a1807543c744	GHtmHxscfmdeO7JT6gJcDMyABHazpJaratFQXZ9v2vA	c61785093b94cb1a185d13aa70bcdbf96bcc1a46ad78b143ef7808eac21cd8aa	f	2026-03-30 10:08:33.531921+00	2026-03-23 10:08:33.540796+00
cbf4aba4-ff15-4f57-b6ab-2935a51bdcd0	a2375bac-4a9f-4ed8-b674-a1807543c744	4fNIWnO-wI0zJkMPfFw1rJqi0-lHB7nJe_jLNYTGC9s	bbe5e06e95de0002e58a3441b1df55cd4c6f8db1337502df727a92d8e7fa56b3	f	2026-03-30 10:54:04.987805+00	2026-03-23 10:54:05.001503+00
0233143e-88bf-4231-bb39-b97eb4c63dee	a2375bac-4a9f-4ed8-b674-a1807543c744	ZU1fCNugKbf4HPmdKBkPOamHdn6NWRu_qPgeNoMwEyo	7d56f40e31951bb459afdaa0bb13a060ea402111d62785f8de3bb291d5d0a796	f	2026-03-30 11:03:04.831294+00	2026-03-23 11:03:04.884418+00
eb91dbf6-d15a-47d8-ae0e-fd7782dbc9b5	a2375bac-4a9f-4ed8-b674-a1807543c744	V-oNhLgQwVlmA7Q16qpoGhftqVEL_S977p2LaHv0fqM	34df26fc3d6d05ff143adfc071c8a5dc4e3ef31f7d2ee76ae1b037e520d98c45	f	2026-03-30 11:04:35.681707+00	2026-03-23 11:04:35.69437+00
9be2289f-fb31-48cc-8876-78b09a12d82b	a2375bac-4a9f-4ed8-b674-a1807543c744	ZYYGqgZ9nikAJglgCKOglTCszpec8Y-F15QYfNTi1pA	0b59b9899c03fb1eb281a2398180e4292eec2bc4a2f772361bad0b54ee59078a	f	2026-03-30 11:07:59.122619+00	2026-03-23 11:07:59.126751+00
953d7722-92a0-4e63-ad20-58c3d553b020	a2375bac-4a9f-4ed8-b674-a1807543c744	pdWuiyuO3xO_qRGj-5yvWSylnR819cNbC1ERCrXC5nU	85ba4809f03a392b861741aa7f7523fae834f3375cc16936404a3ab33281efae	f	2026-03-30 11:15:52.743499+00	2026-03-23 11:15:52.757649+00
0e045ad9-3176-4351-893a-74ec83daca2d	a2375bac-4a9f-4ed8-b674-a1807543c744	yORzB-B1eQY9Ah2aXxS5HGfDeClEPqmcf5j29aG4Bkk	22029b0541fc22ae48f6a33b2cc99b1afb15e9ab315cd34e4d108c2043fc024f	f	2026-03-30 11:23:58.600106+00	2026-03-23 11:23:58.60503+00
e12b8b9b-f445-4dc5-b32a-7d5f4cf535ff	a2375bac-4a9f-4ed8-b674-a1807543c744	mztYKO5LNns7xiaREvUTUq1hSJF5GDZxgz6reDBIRJY	ff1f6a2fba81af693b1404bd7de847e9619cb068956a82868b691ed3fd56337a	f	2026-03-30 11:27:41.6577+00	2026-03-23 11:27:41.660888+00
1e0d6d7f-b386-42ad-b299-d870f93a4f33	a2375bac-4a9f-4ed8-b674-a1807543c744	l4JPD29UC8rY2fXDxg8nwDvciLVNtSNsZqo9ILlpR3E	927dbb72387766027de3e39bfd27dcf7de4e72c7f079173a8ce7ac3a15103297	f	2026-03-30 11:30:00.336048+00	2026-03-23 11:30:00.337764+00
448d11cd-672d-4075-b375-92b6d486baf5	a2375bac-4a9f-4ed8-b674-a1807543c744	f42rtPg4kmMmh_bWUOYJ0Vg1e9tmk6uSsOcOAmh0xgM	b2466827bd5f41634720ff409262361073e2a3b0862d41e98bccbce58929637c	f	2026-03-30 11:36:59.174107+00	2026-03-23 11:36:59.193147+00
b6197c4d-afa7-4a5c-82e2-885556d9f72a	a2375bac-4a9f-4ed8-b674-a1807543c744	L66ph8bLreCv56G5vGSjBwYiu3GG7iGN4mIib9u7RfE	92cf9e8c5b87f36699ddad76ed9919dec5134566e06f7398944cab0433fed166	f	2026-03-30 11:37:37.122811+00	2026-03-23 11:37:37.130915+00
722b723a-3540-4bca-b019-6f40a29b6830	a2375bac-4a9f-4ed8-b674-a1807543c744	-K8E2Tm2Ks9AvirXRvR6hksmOJO5QPVoiWPaKO8l8Po	00a8b26702ada35acf506c22b5b280ae730e30d71a23d2690cba9d1e37074577	f	2026-03-30 11:40:14.537509+00	2026-03-23 11:40:14.552915+00
b60cb399-2609-462d-844f-bc05323ff735	a2375bac-4a9f-4ed8-b674-a1807543c744	XBf1IZOK-yVZKy8DaFTnw8Pbx1RPXfUKB2sle8DwHuo	f2e017b0dc06d3bfa2aab03ac44ac7c7c8ab8b531b0d97b4753dd13f2ebf15d0	f	2026-03-30 11:43:44.195468+00	2026-03-23 11:43:44.208624+00
509d0d05-2e74-4df0-bc2e-ff2403d6e839	a2375bac-4a9f-4ed8-b674-a1807543c744	vc168C_eLbSR_8eO7KwPfI45kI2NKOuSYazEaQJHUvA	43fd6e4e71a2c880521e1979b62b8b5ca3f229c03c24c039633126b372e72246	f	2026-03-30 11:45:30.919812+00	2026-03-23 11:45:30.925606+00
5030eafe-2257-4471-924a-e62e92eeb427	a2375bac-4a9f-4ed8-b674-a1807543c744	pElFcqqZ-k7mcEGFkmjjsolaqjzv3bPKC8dacAm5uwY	335d37ee5d51780665bc2bb3c9a06d9d97671fea3e70b8bcf18a7438c7b77c92	f	2026-03-30 12:07:39.684905+00	2026-03-23 12:07:39.698648+00
fbda3b39-79c1-4cbf-bfd1-47c95b6ef4c3	a2375bac-4a9f-4ed8-b674-a1807543c744	0Vna1Nlh-66dkfK0-4qmUmXVaoy2y8sl7n6Bnt8bxbY	f004523cf441f3ec907da0feeb8ba5ea9e20a51065d3fe96859a1786c72beebb	f	2026-03-30 12:15:50.518661+00	2026-03-23 12:15:50.521281+00
0007365d-41cf-4ba3-8c9f-6c296daeb8a4	a2375bac-4a9f-4ed8-b674-a1807543c744	J8v9QlV_x8N8PxnUMRoOHN5-eYjIf0qWzdBK9wMjFw0	99605352f64cb75f843d98a932b601f75e043f673da5535f0415d4b9cc0a41e7	f	2026-03-31 12:11:53.438972+00	2026-03-24 12:11:53.48525+00
9f5217e4-ba88-43bd-a060-c8e8caaf5b0d	a2375bac-4a9f-4ed8-b674-a1807543c744	XnjhxDE05B781NAXN_utM-RkFlgwtSe__3TXHm7Pdec	94fc44034e658eadb398d6ff1467b5cf9126df1c344819cce039c8e3341edf1c	f	2026-03-31 13:18:44.545226+00	2026-03-24 13:18:44.602259+00
18c51129-ae52-419f-8ade-1d7c8e245f91	a2375bac-4a9f-4ed8-b674-a1807543c744	3bnRP40YWyxtisXn6MyhSW5de2UEfMxnmnuZ9RP3wrI	80cf3a09277f198e70d8adc67d9daeb21083fad04601b8ac1754ceed684ce72e	f	2026-03-31 13:45:09.076992+00	2026-03-24 13:45:09.089876+00
77b31cfe-dcff-4e14-a4fc-a61eaf9f410d	a2375bac-4a9f-4ed8-b674-a1807543c744	xuV-8NV2eBhMz1A0TxST0AuEbjB9_Vjga-ReGdPujGc	d440ac0596a872a791756a74e1e6ffad0de60ee6221a5488db68f09592e9b50b	f	2026-03-31 14:26:54.355754+00	2026-03-24 14:26:54.396287+00
247bc97b-dbe7-45ba-944a-3cd89a012738	a2375bac-4a9f-4ed8-b674-a1807543c744	gc9NoLeOlSTWvs4sBQ14C4_j-aH9qmy6GLJUMaoHVHY	1809e12d629fe464f5ee194f1de1d60ee7bbb64abec3f17dadfadb60f766a9f1	f	2026-03-31 14:33:11.633268+00	2026-03-24 14:33:11.673583+00
075482e4-46f4-4bd5-a7c0-c7b4f83c503f	a2375bac-4a9f-4ed8-b674-a1807543c744	bLkZrBbrCY9uHcAABGl-uvAyRPVBaiKOtvXipH5d0LE	6538d0ae0b3da85105f1ce7c24b12635eb60d8f8b51de86ebbf886fb3b779e2d	f	2026-03-31 14:36:15.187548+00	2026-03-24 14:36:15.192658+00
6393a3b9-01ec-4ce6-9017-df4d166d60b4	a2375bac-4a9f-4ed8-b674-a1807543c744	OGaaEEEwAHaVM6vMB4dXwP7Nmrzpj8C6ATBrLjFHLnQ	cf10cd62e73220eb80094410f6ab1e9f67cd194a3a5d1110448067ad0dc3bb7b	f	2026-03-31 14:39:37.212809+00	2026-03-24 14:39:37.241257+00
7b987637-19f5-4c92-8699-84e360c00e8f	a2375bac-4a9f-4ed8-b674-a1807543c744	HXW8Kzf3_y1XiuDfWE377zhJuObu-ptXj907dBWHNr8	c0fd6b1fad58012ea0e9209d60a0b528e7cb820fd8a2a08fece1d95269b5fa17	f	2026-03-31 14:40:15.525735+00	2026-03-24 14:40:15.566971+00
c4f7153b-8c7b-454f-a731-a8504013dc72	a2375bac-4a9f-4ed8-b674-a1807543c744	z7felbWl3b2PPaYMQVBCbSvOc0ZwqF3dMUQtIvCEeAE	22f47b7c6102cad1352e6b0476c2396ac2c638de5e04c73d549bb5601b0ca1da	f	2026-03-31 15:07:35.988585+00	2026-03-24 15:07:36.021307+00
e418b2ba-c380-4d51-8686-5d652fe2a8bd	a2375bac-4a9f-4ed8-b674-a1807543c744	mkq_7cDYTmr8sthZVwSVwqYt2sHj8ZWsQeNnPL-HFa8	90ef18a321731faf1fbfd08f20e19a4363cf647666e22a267c3547f61d7e47df	f	2026-03-31 15:08:04.629049+00	2026-03-24 15:08:04.633335+00
83efc969-16ce-4857-ad49-75582cc930b4	a2375bac-4a9f-4ed8-b674-a1807543c744	qa7z8fNnwxkbpJQPOPL1HUyfpRTP8jFAobzZmAdp59c	3e59100473f3e1c51198b9a3735f7a42c31cb3b7c76c40ab6c7d0bbad3b0066e	f	2026-03-31 15:16:10.843353+00	2026-03-24 15:16:10.879434+00
70127eb6-5d4b-47ba-8bc3-dfcaf7f983c6	a2375bac-4a9f-4ed8-b674-a1807543c744	jjmvlBtwrW6I_K7vkYWVsRIPPNeGv9mDvrgk3uuQTIk	03ebdd51159636e9f52cc32777f655803bec8b68ce66baf1511b83c89da2c6db	f	2026-04-01 09:13:25.578701+00	2026-03-25 09:13:25.595684+00
ec75982c-9721-4dc0-bb92-7d90545c0ccf	a2375bac-4a9f-4ed8-b674-a1807543c744	FOxB3WfVpOdhxP-I7JskhSHQ3tvjuvrcJmQxLxTPkH0	41c3475a5e3058ea518ecf0cfa75d8f928b10fcc3a3ccdda8b776fa7b385fea0	f	2026-04-01 09:30:37.309763+00	2026-03-25 09:30:37.332283+00
4a4343e9-0084-40b4-b191-cfe971bad5cc	a2375bac-4a9f-4ed8-b674-a1807543c744	5ULkRqZJZsPahS1ELdXgSVmijDxSa9dZJZuCXbTV4iI	06ffc0744c02e157f6d019eff5a7cb73d3e1dea9624309929f9681308e3b85b0	f	2026-04-01 10:27:13.723116+00	2026-03-25 10:27:13.725052+00
091fa4f8-05d5-4222-994c-74544e7a1727	a2375bac-4a9f-4ed8-b674-a1807543c744	qensXx0PYL3_Yt38iFXCasjFXaWtUrckUoQIOgXATTA	07f2ec9ca8284f101b725f0ee2b9e29b841054335370a8e15e26dec1c626104a	f	2026-04-01 10:27:21.917132+00	2026-03-25 10:27:21.917863+00
958b7e69-4710-40ca-b852-b396332c41c8	a2375bac-4a9f-4ed8-b674-a1807543c744	aiZzlxl8jyFTeX2uVa7P8ew3llufvvCLhGQRPEOSLZc	bebf432ebfe1544aa6433b8c1570f45b6b0f42584443f8d51aef0420f89d425e	f	2026-04-01 10:27:24.860567+00	2026-03-25 10:27:24.861314+00
2426837e-f77b-429c-857d-873bb7a84aa3	a2375bac-4a9f-4ed8-b674-a1807543c744	7Ij5mc-AyBhzV6dsL0j7V1c2gUN36S6giwyqZ2mj0y4	849afb526720db4c598e3bc78d883ff82adb6dfacf3716260bbaefbf2c3bf84e	f	2026-04-01 10:27:30.109908+00	2026-03-25 10:27:30.110408+00
5f657ae0-9c2a-492c-a09f-81780ce478f1	a2375bac-4a9f-4ed8-b674-a1807543c744	Y36tBrEWRsAak7rOlSH1F6P3ZeUsQ6tfElsiQElPeTg	e0e1d56badcedb8a95763abcfc6b0510c9472abe130fdb3746233cf9e6aaface	f	2026-04-01 10:27:36.687425+00	2026-03-25 10:27:36.687862+00
27472f7b-1216-42f2-9faf-c385404307b3	a2375bac-4a9f-4ed8-b674-a1807543c744	zPBaGZh5pIRoZBdPLHD_C6HIb7trdJQUYH_hCxZ74Fc	1f0c9022447e898154ec6edaad9186cebedb327181179be2598bff9fb6207e7b	f	2026-04-01 11:04:54.517873+00	2026-03-25 11:04:54.519529+00
d67823cf-d14d-4e8a-a498-769637623baa	a2375bac-4a9f-4ed8-b674-a1807543c744	HmY9jb0T8x_sh88Plvj0w8VihgUQyQxofxF--Rchq-k	8c99d5d6c0e8b6cd0683e5d5b697cc04a6e1ef8711c50a2b1b3cd70895712592	f	2026-04-01 11:05:11.251719+00	2026-03-25 11:05:11.252563+00
c8e1070c-6870-49a8-aff0-8c5502ed71a8	a2375bac-4a9f-4ed8-b674-a1807543c744	l6xGOpO1Ysqb2sSVb9ne1YRHfL_71rploZd8DQIkWQA	a5b52f7c12e1e53d50457520ab5d6263d8338cb11cf054e3763a2ce1b6e17139	f	2026-04-01 11:05:15.259708+00	2026-03-25 11:05:15.260246+00
bbc47211-043d-480d-8f19-12776a721042	a2375bac-4a9f-4ed8-b674-a1807543c744	rZb2VdIFNTxZmqWKi-JKXyEI4KwI6oRbUADQVoqlSAU	a60ce898ad67b37c21adc1d4c00bb92d7cfc37e04477d6e1e203be5d42a0f83d	f	2026-04-01 11:05:24.071078+00	2026-03-25 11:05:24.071585+00
b955cee3-dd30-4de5-8a29-efa64de52944	a2375bac-4a9f-4ed8-b674-a1807543c744	uvh6YHyjAmWRFEmmQB335y_GynbZ44gR3xiBfxXZsxk	709fd6594c98037555e680e723fc6acc2552acd448728ea85dd78ac770a54ab3	f	2026-04-01 11:05:36.885478+00	2026-03-25 11:05:36.88606+00
f78539cb-5877-4885-8d74-c265a9373d2a	a2375bac-4a9f-4ed8-b674-a1807543c744	DZJSX4Y8VQD-vbCkryvJO_qS8D31ui6hP01K433rhVA	ee1eb8ad223002480ead849f6958c52e15bec097547b6a6c980546fd2b50df07	f	2026-04-01 11:28:18.493432+00	2026-03-25 11:28:18.52198+00
a819dba4-bd3b-4e97-8a9b-9a1103742f92	a2375bac-4a9f-4ed8-b674-a1807543c744	_kYel9oqpLlY1bf7LIICyRd0arPTyCe7MeFFin3e2lI	a5a79c6c91ca6f0a8be7548d4f835b5b1bf51a3b497b20fe623f1fd8781030dd	f	2026-04-01 11:30:12.726853+00	2026-03-25 11:30:12.731053+00
65387a25-d527-4a9c-beeb-3b30a52e829f	a2375bac-4a9f-4ed8-b674-a1807543c744	KSaTfOwbV_oRBxU3vL3aHl_l47GvvIZCcP4raG8FlqM	9ce87a495ff21ba750a8fcb65731ad6d53d1ad33643bc2ca9139f2cd45a321c3	f	2026-04-01 11:31:59.866757+00	2026-03-25 11:31:59.879168+00
73bf0576-31c4-46ef-808f-23335ee0622b	a2375bac-4a9f-4ed8-b674-a1807543c744	3oaqqT3bv1mUrF4N6VLk0cMaiSXE7bu-5Lv42gA83y4	8e5d9d16b437a3d4abd61b42140fb9a9f80685a297fe207935f03fd070611996	f	2026-04-01 11:40:01.082537+00	2026-03-25 11:40:01.084429+00
abf27731-4458-48a5-bf7e-9bdf7a7af403	a2375bac-4a9f-4ed8-b674-a1807543c744	KHl6mT3pAxClFN9RnCubb4Jivhh5ek0XkrcAhA4YvA4	c7a92c91b0f560848a2c703a4752c67fff094c27e5d6e80eed9cbe0b9107b25d	f	2026-04-01 11:40:02.848572+00	2026-03-25 11:40:02.849093+00
ef6f4068-633d-4950-9ce4-fa774de4c3e6	a2375bac-4a9f-4ed8-b674-a1807543c744	0ULeBUqhcNhVTKzcFd6yc0kpqs-Yob6WYo_mkpxW1LE	647eeb1cea829d8e9f229a4980b89c5e4e7cacf90ee58f505289cc6bca531b54	f	2026-04-01 11:40:25.058513+00	2026-03-25 11:40:25.059053+00
b0655477-a790-4ec7-bda5-e6cf1687f055	a2375bac-4a9f-4ed8-b674-a1807543c744	RyG-l1by98O8zOY7yNgspfuJkiu-j4d5w90OebmCg4w	0665249eb19b53c3c5130922a8dc231ce6898e089ed4ebd7e0d60c9fdd1de1b2	f	2026-04-01 11:40:53.551306+00	2026-03-25 11:40:53.551931+00
b4fe9d9d-8317-4165-8412-867451cdfed8	a2375bac-4a9f-4ed8-b674-a1807543c744	iyypEQ7zJmYF8hC1DnBV63YbkWZ_mxk3TGDyWK1D1ts	a7694506cd84d21621541db45accda6700c0c7998a27f3414fdbb06bcdbf9e87	f	2026-04-01 11:42:44.418588+00	2026-03-25 11:42:44.42963+00
db0d41cf-6fa7-4bd9-90e2-207ef0ffa0cd	a2375bac-4a9f-4ed8-b674-a1807543c744	iuIAMeE3X_rYJH25Uti_aVty5fMRlEg6U8EnRQmYh78	c7e6d4025befcfdb211b564aed88da376d6cbe5f3833d072199b06b464c72176	f	2026-04-01 11:42:48.611886+00	2026-03-25 11:42:48.612368+00
546f53ca-c630-4c6f-a8b5-d860ed217f67	a2375bac-4a9f-4ed8-b674-a1807543c744	hW95CZHOJvkgdgDwW_s3787bfavK4O9visjAS1PB7Ks	033252b770ef1a1f3a444410985006bad792da9a005b5583f5a5b877218ca4f4	f	2026-04-01 11:44:22.254326+00	2026-03-25 11:44:22.259345+00
f4dd2325-f51b-46c6-9b66-2c0e1cf8efa0	a2375bac-4a9f-4ed8-b674-a1807543c744	hzLb1jY7yMcb8h8EKDqa4vnNle4xR42_GvMOnQmgNz0	b06cf80546b19a291bee451bb8d63c702c018c70ec251e31eb391790a5a8adac	t	2026-04-01 11:54:05.141837+00	2026-03-25 11:54:05.143462+00
568aa154-9b83-43bd-a011-fe3a71dfa04c	a2375bac-4a9f-4ed8-b674-a1807543c744	rFrsyXN4StL9fkKZvdNh6bnomWyBRQCp-GySE3w9zGA	d444f205e6f07b4cc5b016c212e5bf6d67a7edc3e358aa53324d91fe641130a9	f	2026-04-01 11:54:16.659637+00	2026-03-25 11:54:16.660409+00
ec84c644-d6f7-4ff0-aa24-bc96b26539b5	a2375bac-4a9f-4ed8-b674-a1807543c744	Ndp-HieH83slkCxSIT8q-RDAhwJFU8YehhorTngXpT8	fd646c6a946874fdc696fed5f3f3b44149f608046b9864a8620ea141b5205ba9	t	2026-04-01 12:44:10.074473+00	2026-03-25 12:44:10.074817+00
5fc89ad9-9de8-41d0-a256-40c4c5c9d5dc	a2375bac-4a9f-4ed8-b674-a1807543c744	WONugsgfbAz7I3hh6rnTxdpBDrZj2grK2z_sfMamzyI	b6712068b1ba35bb06237bc45ac0568e831840fbae3cecd1fd46a66a03088f4f	f	2026-04-01 12:00:22.754773+00	2026-03-25 12:00:22.757756+00
2e86f162-5599-4f57-8622-4932488f6f65	a2375bac-4a9f-4ed8-b674-a1807543c744	5kMA9GqovMHBTRKO_yUS1eA-kIfnfXQuDjghTIafrRA	ff05ba94ada4e41bc0e1c0b0586f49bafa7ce3f76fcae436b278b8d1f94f2409	t	2026-04-01 11:54:24.676785+00	2026-03-25 11:54:24.67728+00
9a2ee212-8d8c-41e0-bb33-54174360d0c6	a2375bac-4a9f-4ed8-b674-a1807543c744	5LXjkmRxDO_4oRRcPVQsVQKJiOmbwCy4cmbesuwF6D0	7d9b656cc7222ed65af3395c952ef26a2238ac5a6fde8372ab0559b542f288de	t	2026-04-01 12:00:22.774248+00	2026-03-25 12:00:22.775168+00
2e1c7c2b-8719-478a-b94c-0450ce192d99	a2375bac-4a9f-4ed8-b674-a1807543c744	t5vcAflOm1O_D0f_M3g9ayBrEptVlPBPcZk-d6XQnhU	2d2059602f5f3a5d0a912773ee374dc118616094c300c3e1a7f956313a761145	t	2026-04-01 12:00:34.90417+00	2026-03-25 12:00:34.904623+00
565297ca-e33b-4233-bab1-671fcba7fa43	a2375bac-4a9f-4ed8-b674-a1807543c744	nsYIzf8C3Vmsee5CMCKpova18GTLSTmzJQICNWPXRFQ	d8984f082846bc2f7348f5a3d0edf73bd1724c811d30eac5112ace7e8b69cfee	t	2026-04-01 12:00:53.409485+00	2026-03-25 12:00:53.409937+00
7e78f925-3820-4e8f-8f11-8b9711a9489c	a2375bac-4a9f-4ed8-b674-a1807543c744	XXqulIYXguc4IOrWtqPhwP6hSOHerWGyExWF3i151pw	cc62f0afe3a591a119bfb156f455b5b1610a2ad51e3c65e6cf645eb3f2122060	t	2026-04-01 12:01:06.253912+00	2026-03-25 12:01:06.254368+00
94173d25-e859-44f6-94d7-63c860628c62	a2375bac-4a9f-4ed8-b674-a1807543c744	XVytiK6XTGXcMbKtEHB1_2TbbxQ4K46Ab-GoDueu7vY	5de1f2c884f86b6b7940ba78bdcaf30a96f964300ed23cbb2735bf5fa876b79d	t	2026-04-01 12:01:22.193897+00	2026-03-25 12:01:22.194367+00
a22d9d6b-8f1b-4d0f-97a5-b2e2fb547a7c	a2375bac-4a9f-4ed8-b674-a1807543c744	Ip2iYW2en8aQ_pxxZn1gyjYE99t2yfEJ1N9KiAIgvnc	7cab9a0988962883e9fdb6b2a3bb66c51cefe1e126b3e9f6c73f940c8f0a9b84	f	2026-04-01 12:40:35.888087+00	2026-03-25 12:40:35.889649+00
dc1f1fbd-253b-4da2-aa00-4d9044fb51f1	a2375bac-4a9f-4ed8-b674-a1807543c744	Qw9rX6TLD5F9-gTJdUYOcPCL_k4f_BbNnTqSuNVO0tc	ce36624262b0431133af7e570b13efe53fae889aada9a549d5aeaaf93840ebaa	f	2026-04-01 12:14:56.640491+00	2026-03-25 12:14:56.641845+00
a54521c8-fb65-4cd4-aabb-8e667addc04b	a2375bac-4a9f-4ed8-b674-a1807543c744	n6ZcVVQRHBPRrT6ASEsr2RKjO1inlDP8LMNJjUZrj7c	4763c5ba377c0902b780fb176696a2b5a8d4b6976288299b16e54c1d7f447528	t	2026-04-01 12:03:16.51524+00	2026-03-25 12:03:16.516813+00
88597750-4581-4051-819b-bfa9e83d1788	a2375bac-4a9f-4ed8-b674-a1807543c744	PANvtDGLTGDfbI-DIpZNza5SNyV9Ww5_25hInftUhU8	6e65c1c931cce933a0281396f1c1361bb57c8ed6e0c957997f4a0831e67fec76	t	2026-04-01 12:14:56.654006+00	2026-03-25 12:14:56.654937+00
cb95525e-16df-408c-b22a-479af05f063b	a2375bac-4a9f-4ed8-b674-a1807543c744	Ty479y7EfvKlqhovDx0fMhgdRapwKXL2KUmrh7pXHGE	a6ba7357a339f9878b35d85d8f870a4b2b42307e7647f7d8e4942b6b1cdf339b	t	2026-04-01 12:37:31.923365+00	2026-03-25 12:37:31.932391+00
8044c297-ddac-4d66-9134-42e9d094b4f1	a2375bac-4a9f-4ed8-b674-a1807543c744	5mgmthgLQMM9QxxPV90ctGTLqSFJVIM-bQJc9JtITnw	7574c16a2ec00c88dbf1bf5db921b75dec67489aad37f11d5bb9d5219d4dc1e7	t	2026-04-01 12:40:35.898786+00	2026-03-25 12:40:35.899334+00
4d0f4050-3040-449c-9e9d-39b4ca5ba464	a2375bac-4a9f-4ed8-b674-a1807543c744	xCO6QBLgt_iI3_6PYUFx4G_0JvXw2dZOqvsdIR-0OW4	80ee4c223cae3261360191404ee0784803e214fdc5d1e934145f0542a4047b31	t	2026-04-01 12:43:34.146258+00	2026-03-25 12:43:34.147214+00
c15a55b4-c69e-41eb-bed8-21f9398d4626	a2375bac-4a9f-4ed8-b674-a1807543c744	wTshIA8a_Cp3yBz98Sy3wZ3qUHpibLUoQvUV5jS_mr0	f5884d5a6787c30d98500de028a1ff7d7b155d728fd607cbcd7d03825dbc704a	f	2026-04-01 12:44:10.067701+00	2026-03-25 12:44:10.069519+00
43610825-332d-4ad8-a8e9-ad31b8686145	a2375bac-4a9f-4ed8-b674-a1807543c744	2e7MVulTSeBBPikXfsR4kDazvSAUtTU9d3pSkHDlr1Y	a561b06b59f39e148493c0be75ea3507ac498da2b3a85368848ecde12f4bb41f	t	2026-04-01 12:15:21.481809+00	2026-03-25 12:15:21.482427+00
d13ce376-7b2f-4066-96c5-bbc1b44ad73c	a2375bac-4a9f-4ed8-b674-a1807543c744	ax7kElwJ5LWRNDd5v-bU6SH5OkLP_rKYMmkvvVz9Kqw	56e6d6be8054f33ef53d6e87027fe542a71f07f1ee7de0b92558d7e94864b270	t	2026-04-01 12:44:15.604227+00	2026-03-25 12:44:15.604743+00
69c60cbd-f512-4117-a7b8-2a441cb74b1a	a2375bac-4a9f-4ed8-b674-a1807543c744	vvJXIkNZDYaH1P9cTYpconH3MKP3R5-b3iEMKt2q3sE	8c1787ecb22a81f612aa1a2d76d6259dc24d280a5b42402f625e65078e2a32c7	t	2026-04-01 12:44:23.945757+00	2026-03-25 12:44:23.946398+00
8e401fe2-bba0-454d-aa07-86963167f53c	a2375bac-4a9f-4ed8-b674-a1807543c744	mns8PKdGjuTOmhpiSFx6kJFxmdOGKFHMlCCGbuGfewU	d495394c53deac9f5648a7fd0b98f31a33db825ed061401cf90964e0388fed35	t	2026-04-01 12:45:56.746317+00	2026-03-25 12:45:56.74657+00
bac6b9da-a9c8-4053-abb2-08da9ae403ce	a2375bac-4a9f-4ed8-b674-a1807543c744	veOg5WfqCDJugrCbp0Ab6LDhWbEXORyGuaRdPBbnY-Q	530d3f2ad33fcd6cd549ceee9ca80e2988f5b8c64f8975921232dc0dc9c812dd	f	2026-04-01 12:45:56.740167+00	2026-03-25 12:45:56.74051+00
c9d1925c-8811-45e4-9dd6-f6a1264a8b2a	a2375bac-4a9f-4ed8-b674-a1807543c744	JdZ3p1TbPoEJoUFgrK5dVN7WhtbRTVPNnIu_D1Zy4j0	3b4a7ebe06de2c865043d4581dc4c367798f66ede589d921051d1148516861b9	t	2026-04-01 12:44:35.546111+00	2026-03-25 12:44:35.546567+00
55fdb309-41aa-4e0c-a05b-4042fdf82746	a2375bac-4a9f-4ed8-b674-a1807543c744	jFYzwiJvitzAdcRdmvxF1qLLRCDEgnAgeCQTenvAq4E	8883085f60211cb78d2ec4bd6a8cdf0d4199eb338fbc8d806ccf563fe905547b	t	2026-04-01 12:47:10.941768+00	2026-03-25 12:47:10.942573+00
c6beb79a-d0b3-4257-b03d-4df346581b89	a2375bac-4a9f-4ed8-b674-a1807543c744	0h6TwRIYfK7B-lZtpYeU-_zIo-k4UAcgh_eTotCcs5k	2be535406626f9ea3455fce7266e0b542b3d206c033d10a8d4f6652701c320b8	t	2026-04-01 12:48:21.924353+00	2026-03-25 12:48:21.924918+00
b15c5f43-5cae-431f-9442-dece1448522b	a2375bac-4a9f-4ed8-b674-a1807543c744	UwNur9rhScobWZGsdMjk5TBLC1LpK_Je2Akqq8GaCZk	960251438b6108bfdcf62e0117a5fa747b1ef4e83095a6516ee3dc7c3bd59475	t	2026-04-01 14:18:56.131296+00	2026-03-25 14:18:56.132132+00
a527d24e-1762-4e5c-b363-e51cc4b6f177	a2375bac-4a9f-4ed8-b674-a1807543c744	b960SNBlqcNs9Go7ox4rP1IgC_VzWue5aKq6yH8aSJI	d3d3d53b02424ebadb4cdf9b9625a554beaa5c89aa2b4ce174b2c062afb2df0c	f	2026-04-01 13:19:30.295037+00	2026-03-25 13:19:30.306814+00
f33f921e-3d8b-4bc2-abe6-62cc3be1d0b9	a2375bac-4a9f-4ed8-b674-a1807543c744	K5IOfM4JNkJcj4qW8iM-RTJ_RREXPW2yl_yKSZyvcZQ	4314566110b3dd8d52fa9a259bcb1f63027640507f8ba6f41280c18d5aed8863	t	2026-04-01 12:49:20.071856+00	2026-03-25 12:49:20.07231+00
96d41f49-215f-48b1-8443-41e8b0721f5d	a2375bac-4a9f-4ed8-b674-a1807543c744	G7u4icJ8CvcxMuA9ojoqqemW96tyOHRhE2UWcn3KxnE	d965228b02fec9824f7fc84eeb403ff7176813a4da45dc2e914d28b687e58ebd	t	2026-04-01 13:19:30.336336+00	2026-03-25 13:19:30.337522+00
d0e2a4c0-0148-4a22-a266-9c2770bff77a	a2375bac-4a9f-4ed8-b674-a1807543c744	gbFaKwZO59SoNiG6PrOQWExLLEePy3hgE2uMCphYSIs	39d7a91e715152e0f75b844d402b1826cb09f76328819b4c04de47ff59a22e42	t	2026-04-01 13:20:18.671084+00	2026-03-25 13:20:18.671931+00
f8bf502a-8c3c-4129-b52d-2de44edda260	a2375bac-4a9f-4ed8-b674-a1807543c744	g7BhkFWSZIiXErcO-mcwYqso8xO43myoJoNHod2YFdQ	5c7c555af64ef629109126e7fecb391b3845ebb8152ed7bbc6289bbe7627e150	t	2026-04-01 13:20:27.844121+00	2026-03-25 13:20:27.844582+00
d652aa08-adc1-4107-99a1-035875ce8d39	a2375bac-4a9f-4ed8-b674-a1807543c744	tGeu41YFPLivLSuS_S0q4CVDJaqrajBirn-fMb5p-Zc	ada46cc3baa4069cb94e1a65793e00954c318f537a41b9d4fcfebf0dcd36951e	t	2026-04-01 13:20:44.22869+00	2026-03-25 13:20:44.229179+00
ba590c5e-6974-4fc6-8626-868269afabb5	a2375bac-4a9f-4ed8-b674-a1807543c744	JkowrVWir_DNkt4azQl-xnQghyZ-NBclgAd42bfCTPs	cf2da8a06a630843e7188202f9e8ccd75e4acb6a1f3a53ba0746deec87e01535	t	2026-04-01 13:21:20.922416+00	2026-03-25 13:21:20.922882+00
708207b0-dcf4-43aa-8cd0-a2a02bf08798	a2375bac-4a9f-4ed8-b674-a1807543c744	3mZ2lg2pLw5-R5YqIriBdRWiShU7WVM_8Q9vRd2yXi0	f74eb5e40076646bebe15b5ed1ee9955431714a2151c94114265c09fa389d220	t	2026-04-01 13:21:46.209004+00	2026-03-25 13:21:46.209578+00
f7466aa2-965c-4330-9ac3-c0f3cccd4517	a2375bac-4a9f-4ed8-b674-a1807543c744	VT0MDIKhPXYK3Aigw9dxQgZUs_P-s0Uvwx3GG9s_Dl4	f885a668764a44947f6aaf9c318db12b30e484b25039b17aeb659ac4327803e9	t	2026-04-01 13:21:55.40982+00	2026-03-25 13:21:55.410196+00
badad1dd-9671-4915-9d95-ea7cc4f997e1	a2375bac-4a9f-4ed8-b674-a1807543c744	wZYA92q414CxdbBkiuAUpo4GR46GQafdEQ8h25va2uQ	810a52f27c1c928b4dd723c70b66b87037fba9470830d116dbc368c6e626f56a	t	2026-04-01 13:22:01.058816+00	2026-03-25 13:22:01.059205+00
c0785c1e-df5c-4cb4-b60b-f02e4897720d	a2375bac-4a9f-4ed8-b674-a1807543c744	9CW6IbPAcrOL4rin5efMK4fZqESEfaDjaT9n3LtIajk	49de3aec3330a311409612d3faeadfb1d97188403fc8c4ca2c1401788de10ca6	f	2026-04-01 14:00:10.717444+00	2026-03-25 14:00:10.718055+00
62b9e846-40d9-4f14-9f5f-4a6882cf40e5	a2375bac-4a9f-4ed8-b674-a1807543c744	7jj0NaahF-INRhh1Qk0YtjjeFm-xEY6H0qcrMiKbxrE	104f433bd8f394d45c2c651af11f7d6e977dbbae287890f42d3879bf2e2aaf59	f	2026-04-01 13:39:08.186371+00	2026-03-25 13:39:08.187451+00
c0381ff4-325c-40b6-a0c3-ebc8b8753a75	a2375bac-4a9f-4ed8-b674-a1807543c744	-PQ2nJvHaypmWsC8CwUxtBQ1tzoUtaHy5l7n5nKhpEI	c3711b70659aadde4c40ca6136a9a9ac20ce71572156d6f428d15a39ed127625	t	2026-04-01 13:22:35.548888+00	2026-03-25 13:22:35.549332+00
d14acf37-4d3b-4462-9bc6-b441f92b2357	a2375bac-4a9f-4ed8-b674-a1807543c744	fCiwvCM0YMaWFKOY1uAbpy-Qc48y5j-XkAdh0xv0Ecg	7d4ce0b81ec6b2bb1d83069c363e453798d0aa31df2bcabea3ade07125d812b6	t	2026-04-01 13:39:08.195057+00	2026-03-25 13:39:08.195537+00
92840baf-9158-4e2c-867b-65908bf137f3	a2375bac-4a9f-4ed8-b674-a1807543c744	7J5-9o4lyg3NSMc-JQwwN-7JVXH-Th0chY3Orm5VGnk	e1c969a7a29221a6dc1e03f0f79a505bcc351a5a85ce912a8226d71127cb9537	t	2026-04-01 13:59:52.528747+00	2026-03-25 13:59:52.533115+00
7a72d69c-3a79-4fcf-bc5c-80a20bfc0e5c	a2375bac-4a9f-4ed8-b674-a1807543c744	WRmgnA2UlYooYRACeScT7edJBlOy1gEXUp7nD9sQXMw	b96c0983f983024438ebc345587bd8b3436ac92286dc62c17c3c78b966187ad1	f	2026-04-01 13:45:55.273623+00	2026-03-25 13:45:55.287032+00
d0a9443c-1f47-4253-bcfc-6afb28d46b83	a2375bac-4a9f-4ed8-b674-a1807543c744	IvPxtiaLb23rR8og8j3W6zAiTYJX_GotvemycHqsurU	e926bb5bb5184aeb2d3d987d1e4d8114c121c87166e197c05b38cfe4a3a6c540	t	2026-04-01 13:39:21.893458+00	2026-03-25 13:39:21.893902+00
458ebcb4-c7b0-42fe-a078-4ece436d0cfc	a2375bac-4a9f-4ed8-b674-a1807543c744	P78RyTxL0do_5x55IasxVrihqBxTd8XGj15GiCFexpE	638fafc2fe73b78eb84727897868e267afa78a6988e0e7c2bde2f2addeb21db9	t	2026-04-01 13:45:55.314769+00	2026-03-25 13:45:55.317641+00
aba76f27-07e2-41f2-a343-a1c6d9ff6800	a2375bac-4a9f-4ed8-b674-a1807543c744	1gqbWCZyTlF2_MM-OODoNcyE5AYhiEUKoZ5d3Kte2qk	b022f625853a450bdfc60fbd7c36caa4860d47c0246d1d90ac220c43a723046e	f	2026-04-01 13:46:12.227687+00	2026-03-25 13:46:12.228153+00
3c445fe1-66ec-4526-b26c-493dff57f5c1	a2375bac-4a9f-4ed8-b674-a1807543c744	q5FB6NWTlIPnU10ZzAa3kCRrKaZX9QebFj9WXt4Av2Y	6d16d5b7d11d073801d98648ceecc9505cb430fbc984362845f93ab977502945	t	2026-04-01 13:59:22.262028+00	2026-03-25 13:59:22.263533+00
2c1b2503-fe6a-4952-94ff-e9006244d781	a2375bac-4a9f-4ed8-b674-a1807543c744	dfkolD96585b0QDrHFWzHYrabyqTym8rVYYxDNv4qO8	ec858acbac5cfc0d95e35519d0ad32e50f4d7b63a19a03ed44ac034b703be2e7	f	2026-04-01 13:59:52.52014+00	2026-03-25 13:59:52.520588+00
e90b0373-d8af-4583-a617-8617d2c9b57a	a2375bac-4a9f-4ed8-b674-a1807543c744	Hpd516eQ5CfLGNhr18LR9qW_ug2PbbGcjnQ1xx6G4uc	4a6ca431575df38c6f64a634eb1bb6874a17d6eb911e3d2dd5c0215662dc7048	t	2026-04-01 13:59:31.704925+00	2026-03-25 13:59:31.705468+00
fa8ade1c-8445-4c66-b111-18b6ec286772	a2375bac-4a9f-4ed8-b674-a1807543c744	1CwOMwwUNVs7eRVfmYf66eeLxJX83U1F4ONKeAi5MNo	a223b25c62f1c6c413151a69c642a4a0cd6eb078e1e869457b4f2c383653303e	t	2026-04-01 14:00:10.723719+00	2026-03-25 14:00:10.724021+00
7bbc9fb4-9cd7-4a95-b844-02f931386321	a2375bac-4a9f-4ed8-b674-a1807543c744	kEudANcpCZaroOnHqS0Yl8QiJjdrmaiZOXPW55Fyh_s	fafd29e7c6098bfce7ea3497518c2c5629e61b4b4066e155053efbc299e68796	f	2026-04-01 14:06:56.118556+00	2026-03-25 14:06:56.125722+00
1626b863-bb1e-4d4f-88fd-88e0a91b2c4c	a2375bac-4a9f-4ed8-b674-a1807543c744	Hw3M2SlDtufSK81R5WJ1v91T91aGNxBM8K-Bz5tNSs8	1f5ebbc761a5884df3cc5622816b02e5d5b6b5fb4ff0e21628aa3753b7c8e47f	t	2026-04-01 14:01:45.46503+00	2026-03-25 14:01:45.465619+00
0a4ff568-1870-474b-8237-645a348c6d21	a2375bac-4a9f-4ed8-b674-a1807543c744	w6khvuYltbWE8gtGczyl6miw0UTChCvWPCF3MXoqU3k	65ef27192a0a091257dbfde4bc841d4267f1a1e57635fc6af70ececaf18df876	t	2026-04-01 14:06:56.149744+00	2026-03-25 14:06:56.150273+00
d567b6e0-8b9b-4620-9fbe-9056398d64ba	a2375bac-4a9f-4ed8-b674-a1807543c744	_XqmP0I6dEOKFjX4hyG2NdE96mdXRtQZ5TuqxqZghC4	f34648e0a00f45b573233751e03489f034875f8e1e9382d0798cd1c7b0c76da9	t	2026-04-01 14:17:30.571903+00	2026-03-25 14:17:30.574358+00
ea292c98-a61c-4bd3-ad1c-fd6c5d02c0a0	a2375bac-4a9f-4ed8-b674-a1807543c744	wdE0tyKtkZaFd8iuEB3WeH7Kon5rbKETTwDGpkRIonk	20fbcd6a5f7c332268fa556b47a18f5c8c744b073a591bca2c2042d555b6b8dd	t	2026-04-01 14:17:54.304207+00	2026-03-25 14:17:54.304688+00
1909cbf7-d679-4e7c-bc2b-b96355121b60	a2375bac-4a9f-4ed8-b674-a1807543c744	M9AxNHl2h4pNhm24oHBB4qEkoJYORzDA6fYOANOu-oc	3157be0887118d4b1af5f3a8594eb3c2b5333ed9bd6349e0b6c56ede71f51ff3	t	2026-04-01 14:18:45.88194+00	2026-03-25 14:18:45.882398+00
eb8eabe1-83d0-41c7-b6d9-8a11f202411d	a2375bac-4a9f-4ed8-b674-a1807543c744	FlF3MAfRvYtczpMUo6M-2lPGiNlZ-9HLKeOnjlVGlAw	97091cbc769a1f8cce6b71731a539d83a5215a9a80e984806090d0818a310687	t	2026-04-01 14:21:22.733319+00	2026-03-25 14:21:22.73439+00
a960e6d0-60c6-4f20-9a50-5f1ae6a06688	a2375bac-4a9f-4ed8-b674-a1807543c744	fcvUXbPpL8_3RbQfZ2TBxUjvTZOaJQc7z-z-qdiA7us	22cde43894be4c0ba2a7835f8149cacf998530cb9efea6efc9eb01ddfb295789	t	2026-04-01 14:21:51.548617+00	2026-03-25 14:21:51.549155+00
9d3e5866-9fcd-46aa-a012-ce108b42a4cc	a2375bac-4a9f-4ed8-b674-a1807543c744	gSjPkZZrtgT6ro9R79cMxXl9Aefx_aKCYRT_LRfDdBM	f578be2d473670fbc76bbde0a515be6c04be18c9a97fff166a63c7b3c4632b53	t	2026-04-01 14:22:35.127564+00	2026-03-25 14:22:35.128016+00
efcbd7c1-1279-4125-bfde-25bd02376af0	a2375bac-4a9f-4ed8-b674-a1807543c744	SW-ohiyMYuloLhIiFfKtv0DY7kMcrPLpxyQ8Pg7ihkQ	096309a2efb9816e4b62c11a09e123b4e90d8bdfbafaabd0d9292d5e681a0367	t	2026-04-01 14:22:58.914068+00	2026-03-25 14:22:58.914538+00
61ececc3-0883-4a0c-a096-b8cc6af39277	a2375bac-4a9f-4ed8-b674-a1807543c744	aMWW1OtQjAt-zNy3CEUdb5WjC31whJsZo7KgFUR9Vlw	52533dcae8ea2ad33dbf96db5dfc5a37b4ac91938a1e6ffb3f069b147f7d16e3	t	2026-04-01 15:27:42.470494+00	2026-03-25 15:27:42.470894+00
b293760b-fdb3-4aad-9794-888e68e9e717	a2375bac-4a9f-4ed8-b674-a1807543c744	JX7unfIC83fjzwwzdYcR6F-TuDaLmyT6-0tkZwFYEHI	22dd989e4780752489577ba422c122f6c49530dbc00ace7c122ece327c62adca	f	2026-04-01 15:27:42.401489+00	2026-03-25 15:27:42.404316+00
12557406-896c-4c4b-9ff6-33523897f501	a2375bac-4a9f-4ed8-b674-a1807543c744	A4ApdlXKzqhaCXWsJDzIWf-aWByDlohnmHWGBjgmMRI	53c888f898a5dc5963124980653a4cf72f65b5c00f70c36f573b8e8acb076f4a	t	2026-04-01 14:45:57.962043+00	2026-03-25 14:45:58.009578+00
a7acc472-8bc3-43fd-9ddb-8fc1ff4ad9b3	a2375bac-4a9f-4ed8-b674-a1807543c744	4UlQQasDMmRtLFIZ0da0wPocWqX9JYu8K47j1iuSafQ	3215347ac442eb979f4074856c1355ab29c48779b55d26859b0b0dc810d22af4	t	2026-04-01 15:28:29.832613+00	2026-03-25 15:28:29.833203+00
15d6de49-83ab-420e-bb19-5d8b2460b5f8	a2375bac-4a9f-4ed8-b674-a1807543c744	EmVKZv-RQUv1OzYg79t9V8aEvlegdes7mmSK5DoVOGY	b7d7dc95793f4f6b39589f649a896a5f81e5b4e218bfe41c38489df1df8bd416	t	2026-04-01 15:32:49.390702+00	2026-03-25 15:32:49.403963+00
7ef9af1a-987f-4a31-b366-046ce264982b	a2375bac-4a9f-4ed8-b674-a1807543c744	Selrwe2BBSH-kc82ju09D6QgB5X4TxFy5gSETPBpTbM	144c90ce22384d84cfa2c21586175d12a7cd4afd41892ed15d04cddb36331681	f	2026-04-01 15:37:53.244381+00	2026-03-25 15:37:53.245197+00
71551a28-4d6e-4bd8-9c37-e3f24f8c833e	a2375bac-4a9f-4ed8-b674-a1807543c744	x7d8WbZItnNAnnYuopxB76G2neAzu3YcAdHBsszQbAc	6c317f63a239cce4a5c7553bc6a216e73d602d37eb6ebe3fc87011bb8f28ccce	t	2026-04-01 15:33:15.556096+00	2026-03-25 15:33:15.55658+00
ca1cc043-b2b8-4253-8d01-19b131a2cc4b	a2375bac-4a9f-4ed8-b674-a1807543c744	9XHFJLzQmVt1D0iMHkS5aLBprILYXleli4qwjFeC4vM	7170204dc70438acd5417788826662ae3151e24968d0c2293151163071234e0c	f	2026-04-01 15:41:29.162378+00	2026-03-25 15:41:29.163201+00
3b52ef55-9115-4666-ba2b-c077a52997cb	a2375bac-4a9f-4ed8-b674-a1807543c744	eDUcpB9tmIbLsHSEm45CH_BarIrua6WD9e2iHmZ0y6Q	316385d33f387b05c34c41b091916edd61bc96d1344fc9b6622f018044b850e1	t	2026-04-01 15:37:53.256005+00	2026-03-25 15:37:53.256428+00
1d3422b1-fdd3-4b3c-8ec3-b62a78ae0a68	a2375bac-4a9f-4ed8-b674-a1807543c744	AZa-2ds7gGYNYi9Xz-kYxwyL2yS7eRxUC_17m-5rvrA	d2eef3a6f3e43da0e5258f7a24671c5558234f8fdc3caba98aadd90b7bc8ecd1	t	2026-04-01 15:47:46.611326+00	2026-03-25 15:47:46.611867+00
aab0742d-81f5-4b1d-bdde-ffa1874b9e7d	a2375bac-4a9f-4ed8-b674-a1807543c744	BY82DOYLpyR6tLyn3jpwsGIeD38ilMUKiBoqSrFpYHw	34a27980a9bb952b5f183c32854d647c1e2343437dd7c61ceb5816371daf8286	t	2026-04-01 15:41:29.172025+00	2026-03-25 15:41:29.172482+00
ecd33538-0046-4109-a8be-61d2c152ebb4	a2375bac-4a9f-4ed8-b674-a1807543c744	pz6yZIlJMBk-aUO6bpVPB52ocSRoVPb45EqSXP3upkU	197814f7390ce4e7ae49676ec7f8f37abae798af7dd668dcba716711a118cbf5	t	2026-04-01 15:47:21.687006+00	2026-03-25 15:47:21.695835+00
80158f43-a29f-49e3-a5bf-7746df782b1b	a2375bac-4a9f-4ed8-b674-a1807543c744	ccbA32hxmoV3YPaK9dttrEstZl2blAgab8u3VNVinBM	1f9280ceb449e1631e777464990d83fd7de0ce8808cda6d0f15e627e81662dc8	f	2026-04-02 08:32:31.429075+00	2026-03-26 08:32:31.430255+00
5c1c0e6e-c930-4a5c-8b67-cf2970ccdb15	a2375bac-4a9f-4ed8-b674-a1807543c744	AMc6YXzaZTf4IF5--F7EH12eKj2JHviXDNFzBGDvu3o	f7ee88e8aaeb29c37085d730ca31ea8f1d4b6e5c507d51f5ad0c847b3fef15cd	t	2026-04-02 11:43:46.060637+00	2026-03-26 11:43:46.061142+00
0eeb13ba-7bcb-4e44-b3b0-67b544bc36a0	a2375bac-4a9f-4ed8-b674-a1807543c744	l9bpKB6eUQLgLOxL_dLuT7H29SgcnnSnelKmCcR0LPI	1ae977d8fa2d284108adcbb453002efbfe0f6bb3e8d0a05b03496a11b2072a02	f	2026-04-02 09:08:41.423643+00	2026-03-26 09:08:41.425206+00
24d5ce61-7750-4417-ab87-bc5c5a5299af	a2375bac-4a9f-4ed8-b674-a1807543c744	8bYLjIxQI3MgtR018eFc77oza5K5XvmaB4qJFyeutpE	2b84da6652c8690e4d8038835488735cbf6f0818892e2468def82006a1f3c9af	t	2026-04-02 08:32:31.440731+00	2026-03-26 08:32:31.441132+00
7406c952-4774-42e4-a65b-0a493d599f35	a2375bac-4a9f-4ed8-b674-a1807543c744	sQNTgTvFYk37EegngIUrXotrWFAUwofhDFtAzYIuuNQ	9e8ea6f8e76897887cfb39b34fb9f410856dab08c30ba0f2fe2bebdfa692821c	t	2026-04-02 09:08:41.43476+00	2026-03-26 09:08:41.435135+00
e84805c9-cd9e-4a4f-9ca4-cce93ba4b2d8	a2375bac-4a9f-4ed8-b674-a1807543c744	8kbGIIQ2kf5yU4SVEv3d57jcwm-sq8d3PaGAsuVVj-4	5be5f785d1b7885745f7307e6804daa271623f2550e46ffc7dfaefed7d093f4c	t	2026-04-02 09:11:14.511499+00	2026-03-26 09:11:14.519805+00
00d88d93-8f40-4cac-95a0-53ee718696f0	a2375bac-4a9f-4ed8-b674-a1807543c744	AnRztLBJoPDjdc5dZ9sDSDjgVntFithE-w460zohEJQ	74f8e0bb00e1fec7b112b793507e2cd041c6ab6fd1b3c9a72dbd9a4f3b21150d	t	2026-04-02 09:12:24.42036+00	2026-03-26 09:12:24.42082+00
190327f8-bcac-43f9-9e3f-f61ccf1bec86	a2375bac-4a9f-4ed8-b674-a1807543c744	hMTNPmdMCOZD8tR6Eg2AgEzUGtL3385oH3wwon6_6dc	296d2b663273ba4502c6e08ec4012cd29c9ca0786a6e7dbb3e8c6466ae71e4dd	f	2026-04-02 09:32:32.96759+00	2026-03-26 09:32:32.968857+00
7c0daab7-1d19-456c-9dd5-c2a0b0d938ee	a2375bac-4a9f-4ed8-b674-a1807543c744	goFd_EmA5G2mekxKRSZR1Kjad-BTLYP01oKfS_7UNQM	8d097fbe5f1ac11cb90a48d0fded480ac740c0b5bdd97dab5a90bb62370fdf09	t	2026-04-02 09:19:46.849021+00	2026-03-26 09:19:46.852039+00
b5637c39-0eb5-49df-a48d-dd4dbfc35f8e	a2375bac-4a9f-4ed8-b674-a1807543c744	o5u4NJgX_E6N64QhxaV6UPeIkLPuKTyPTYXYMfpNCqs	47cef6fc2aba68efcf39ab466e62c25075153ac54ae7049583c94994f32a30dd	t	2026-04-02 13:27:23.308323+00	2026-03-26 13:27:23.308687+00
9d2c1e12-1fb1-456e-ae8c-64512759d5a1	a2375bac-4a9f-4ed8-b674-a1807543c744	9jBf8V-Jxv14iK30sVMKkfjfJaCyiP3JPtPHlOSdge8	1d46e68a039de11b257480e18887c14f89607a435b1a96b2ad435c0210085c08	f	2026-04-02 10:17:44.184643+00	2026-03-26 10:17:44.185666+00
cc5772c6-4914-4da1-9d3e-d2e7075e2269	a2375bac-4a9f-4ed8-b674-a1807543c744	XGni8wVXGCYzEsI4Idh0I5LqKYQdJHWVvE2kMkmq2Mg	6964962234df562fd7c21a4091ca639c448a0ca154f4ae1182c2e5101574906d	t	2026-04-02 09:32:32.978451+00	2026-03-26 09:32:32.978827+00
e85e3ebc-7996-43af-879f-7c069fdd6d1a	a2375bac-4a9f-4ed8-b674-a1807543c744	EfT1LzxcAZ9qt5WBNIYcQcfCE_D1tE0eu3AXWiBHYj8	0b559fcbd5d4d6ad398116f02a0900f4e0f36b335cd8b3288bd3706ca3a6f9de	f	2026-04-02 11:47:23.170475+00	2026-03-26 11:47:23.171775+00
3f76bae5-10d5-4150-a5b8-781f487f28f0	a2375bac-4a9f-4ed8-b674-a1807543c744	rctcW66SrBK2XkU8Y8Hutc1fTXcsfHL8-citdRt_AJ4	fb9ba0e84fe272a9442e29eba90ac8c854f65af1e738f6ce08248ba79e19c7c1	f	2026-04-02 11:02:02.413464+00	2026-03-26 11:02:02.416777+00
c80f5e70-8bb5-413c-b34d-4cf52be62c3f	a2375bac-4a9f-4ed8-b674-a1807543c744	Thql49urj-JD4jflgDfzjSI0TZI5RW05L00xggsB9jg	e84683e337275dc9fd11d1552e97cd121eaa100bf44879dd81a99d65328524c6	t	2026-04-02 10:17:44.195905+00	2026-03-26 10:17:44.196289+00
75fa7597-767f-4437-9bac-1cc7d4b81951	a2375bac-4a9f-4ed8-b674-a1807543c744	jLgwtA4N4mQMHBMkbt-HOLoIUJaFLIUMYsbD4P-WXiw	170a8d60ee2ce2fa20a743f50eefcda286fc7203fc1844cfb675b0fb7cae0378	t	2026-04-02 11:02:02.427089+00	2026-03-26 11:02:02.427568+00
8bf0d5db-dbac-45b7-84b7-e2c179a1677d	a2375bac-4a9f-4ed8-b674-a1807543c744	KvzNnK-Omswl9USpVLMpZ2zuVoCuBy3Pxw1T6-OO4Sc	4bd784b591a1e2f4e853f8652aa1fd1ee5935db61f7965ff8f96f3505a9fcf74	t	2026-04-02 11:02:12.547216+00	2026-03-26 11:02:12.54777+00
e99b37a9-b6b8-40d7-8808-b9a4a2b3169c	a2375bac-4a9f-4ed8-b674-a1807543c744	opWad9ooth6scX2T8-siIFtezk7Tg2A0KEKYmfDZpXw	a0d0c8020d8386a77c8ba6747680d97d5a0cebcda9d331fe643cd0ca9ae14053	t	2026-04-02 11:45:54.85309+00	2026-03-26 11:45:54.854486+00
90e7069a-8d0b-47c8-878e-7cef2d7a0f45	a2375bac-4a9f-4ed8-b674-a1807543c744	GrLAO8zREWl9n_-d5FoTSv_19kFkrfJY_7ThJN7HnMw	5158b9d9d56ef0798c34e3d622f0e890e4c88ddeb215afe2ad731d50ddea4bff	f	2026-04-02 11:39:13.361153+00	2026-03-26 11:39:13.36344+00
1819664b-d1d7-403c-92a1-bbc3a9767ac7	a2375bac-4a9f-4ed8-b674-a1807543c744	2A0yxd05I6OySIjFOKUmLy0vwntBvbARJE50tE_Qo3Y	32a543578a92bddcfdc5a42f944847fb645dcadfcad7489bb7577e46d42da715	t	2026-04-02 11:04:14.241232+00	2026-03-26 11:04:14.242697+00
4ec5090d-8aaa-4552-b65b-3427c491e65c	a2375bac-4a9f-4ed8-b674-a1807543c744	2aHoqpH-1HPWYxQRaDLPjngiaKc6kmvQSFAXqpWqHao	5464ad42dcd147c9737a4fbf56295d1556ecbf5186e299b2688d23cce92b2b3c	f	2026-04-02 11:43:46.046029+00	2026-03-26 11:43:46.047382+00
e8c3c269-e8be-43cc-932c-da400478beea	a2375bac-4a9f-4ed8-b674-a1807543c744	1BN8dmNI5B_QKVObTHAFLH5Rpe_dmbQxxXTHwuum1nI	ae9586cb2a4c907c73a2a24f65c8e562e9dc38195f2b4ec9fe35005e282c5f46	t	2026-04-02 11:39:13.372502+00	2026-03-26 11:39:13.373437+00
4660a24c-c9be-4f0f-ba4e-6d64db65e93a	a2375bac-4a9f-4ed8-b674-a1807543c744	WzL7fxYWHDSDlVwBHtlt3Vfxh9lGTmPirP595-LiJRY	24dc72d82669634d11863d2c4bccbcdfb4b46a7d10da421194d1e2e4593ebfdf	t	2026-04-02 11:47:23.188123+00	2026-03-26 11:47:23.188817+00
b46eee56-b701-4ede-9b59-825bd56a550e	a2375bac-4a9f-4ed8-b674-a1807543c744	rCHM54ugVzQWIY0qW1uOC1sySjV30kdXD76iSFvk9vo	7d799bd84c53b168f0bbc663683082ceda161ef01f32b7968088e3c32153e478	t	2026-04-02 11:52:40.310448+00	2026-03-26 11:52:40.321348+00
66fe2a6a-affb-40df-8547-18731b41dbec	49a1c5f5-2d47-4ad6-8549-13c781a16223	eLflNVYjxPIcJvaZ84rjRRp-e25dsPP1hS05nXXspFs	3dfc3ae172f1c2d5c0367be99bda379c714b60d615f1f3cc5fcf13330b17ca09	f	2026-04-02 12:01:28.769803+00	2026-03-26 12:01:28.79041+00
9837d6ab-a12d-4078-9657-34e950b4eeb2	a2375bac-4a9f-4ed8-b674-a1807543c744	NXJWxbGAgz80zp5I0XISwSLOp83IbWqboESTJL1WJO8	daf5219bce11c3edea71e1e45bc27fe2c4ed73a92a7890de6845ccae304d9e1d	t	2026-04-02 12:13:47.924103+00	2026-03-26 12:13:48.091531+00
5ce46714-5dcf-431d-9bd4-52aa17f68078	49a1c5f5-2d47-4ad6-8549-13c781a16223	f_ChFlrKoPVikF-Zw0W4-CkaWOIOwpyWK7__fWyOa1o	53b9ddd67b3b0e04afd604620fa6cabcff176c5dd226d457e2aad7b4aab3dcc5	t	2026-04-02 12:17:09.510142+00	2026-03-26 12:17:09.573129+00
aaf9a864-9fb7-44c8-99a6-9e3b6e753767	a2375bac-4a9f-4ed8-b674-a1807543c744	6Pv4liqpj6jrZa2RAS_K0Q2lisosYOwAJ9pUbRaniSM	588ad9954ad9b758f422b2aab24d807b59c3be5d5a5a1cc71f366b7482a987e2	t	2026-04-02 12:17:36.97657+00	2026-03-26 12:17:36.977057+00
5491db1d-149d-4590-84dc-69485b63794c	a2375bac-4a9f-4ed8-b674-a1807543c744	PDrysSZDD23mNESjOkCxHB_J-KuBij5RIWKG2wdvwhk	3abcb204852d7a77b1b9180f318f8256d43c2e64a43f98558129f8f306aafb8b	t	2026-04-02 13:03:20.602628+00	2026-03-26 13:03:20.629955+00
3f3521eb-9601-4bdb-82d7-0cb32e8f70f4	a2375bac-4a9f-4ed8-b674-a1807543c744	KVHbfENTmdjJHNxarlxCDXysjfZU-nNJaGjil-pblik	91c8aaf4369db85eabbb1a71c72648577faf292e562025193579b83088f091da	f	2026-04-02 13:26:59.862978+00	2026-03-26 13:26:59.864297+00
fc93dd1f-84e2-4887-950a-d0dabbc06c99	a2375bac-4a9f-4ed8-b674-a1807543c744	yD5ZNrlDS5Bwi0y6jJuVj1_dNnETwZxm4P4mVSsPqRY	c1d2f0e7bd08323a01d44a35e75f707fd3eedb6652e9ce021ef2ff740480f5cd	t	2026-04-02 13:24:57.420786+00	2026-03-26 13:24:57.434551+00
e69bd3a3-ba5b-4bbd-980d-32166d9d53df	a2375bac-4a9f-4ed8-b674-a1807543c744	L4B9BYL3QcAFY41TagAPMVXGSKl0OgCd7C1tgUmsAi4	e7fd44351207bb2e7cdc79015da00babc7acc12088f57c4cafdb0fbc03c1a962	f	2026-04-02 13:27:23.300594+00	2026-03-26 13:27:23.30229+00
b838f62b-6cea-4a1d-81c8-bd8c9c2ea1af	a2375bac-4a9f-4ed8-b674-a1807543c744	4iGb9jbz4Xi--9mH9oRZjj7cuvXPXd7yoSt9AoUwx4g	e9a4cc1406dc361a4ad63d6cb15c0c6fd25cef11cd0aa7c0ed973f51e51ade78	t	2026-04-02 13:26:59.87249+00	2026-03-26 13:26:59.87295+00
18c99972-8d87-4af0-8bf6-77cc540ebeb1	a2375bac-4a9f-4ed8-b674-a1807543c744	qGWTjN7frpn8bLs1IfhBiYmj8AH3Xx25Ej6SaSEaznk	058631b0a1378642ce82f7fbaa160e1e4188b46f4cdcf82643b999159f38c175	t	2026-04-02 13:50:28.455722+00	2026-03-26 13:50:28.45623+00
560598de-4ec0-4c33-930d-070aa8499212	a2375bac-4a9f-4ed8-b674-a1807543c744	s8_5ct4r6xSkYyAc_IfFKxD9X-jJCblXfp4y9CkX35Q	349b7b5ab7c195635c042250bd57ad62744ec7bb79cf4b509627ddd7bb9d5837	f	2026-04-02 13:50:29.133942+00	2026-03-26 13:50:29.134475+00
72e49bc7-88ac-4b09-96b7-6e32858a32dd	a2375bac-4a9f-4ed8-b674-a1807543c744	G_YxCdGPw3b_xJqyeaSobZDJer9JGi7d7KR1jhrOMA4	317478e7eba41e1b9a65eed934ac01ced79362b6a92dd4c78c1a7f1e2392e4d2	t	2026-04-02 13:50:28.776895+00	2026-03-26 13:50:28.777289+00
c9e97de4-8baf-4101-99aa-361d2691a904	a2375bac-4a9f-4ed8-b674-a1807543c744	TDmthWnRzOAOWDcKOtZTShnxsfloqB7VLTrQCSwfqfg	cbf0941b8edfffd8969e710f047bf832d3321fceea838014721b9ee7460b6cc5	f	2026-04-02 13:52:35.492031+00	2026-03-26 13:52:35.498422+00
8e089711-a49b-45eb-b456-f3f6527bd8e0	a2375bac-4a9f-4ed8-b674-a1807543c744	7aSa-truDMJW22CDu1KbHk6Flf4Jf7YBE1P52hB0bFQ	16b343d6929f27d7a746ddeb30c27e8e5090f81132b73f841fbf7b6d3e5c45e0	t	2026-04-02 13:50:29.142227+00	2026-03-26 13:50:29.142981+00
9d3a19e3-4443-43cb-8678-b0aef255dde1	a2375bac-4a9f-4ed8-b674-a1807543c744	fs-HyGoZfWWK6klY7TCQVBVa945Rs0-SgVwoy99eziA	d9457fd86e7f222265816cb1df063a6c78623bd2b82676238788d6f8f3aece39	f	2026-04-02 13:53:25.933505+00	2026-03-26 13:53:25.934647+00
64b6c45a-2964-4e30-aa2a-ba0fc5f5f375	a2375bac-4a9f-4ed8-b674-a1807543c744	070pPtIbH2DKwrlF_CkG5sHnU0vILe62ze-MIspQLMA	9dc98a4eb29e4bf0435b7b55bcf1ee66cbe2023329aceb49a352b60af85471ea	t	2026-04-02 13:52:35.513922+00	2026-03-26 13:52:35.514457+00
2c72a771-ade6-42e3-a2e2-080e48b6ee0f	a2375bac-4a9f-4ed8-b674-a1807543c744	xMVt50AyQ04xTm8nn9PXzLuBrMPzMHtq7PNU6z8ms3g	f4c401df27e2e6ee2d1dca5ec5df87cb6c4f6c416fd694f901392b180a031dba	t	2026-04-02 13:53:25.949621+00	2026-03-26 13:53:25.950355+00
41861195-ea30-4ceb-85af-a991fcae7eec	a2375bac-4a9f-4ed8-b674-a1807543c744	5LWEqvE5HXXhTJ70H1rOL2OpVgy_49bJpj8WX815AMA	7b542968f463bbbc3e02ac3b33c6abceada13fa40de1ef3f7d14b0a13a31276d	t	2026-04-03 08:54:59.209874+00	2026-03-27 08:54:59.210267+00
e9f11068-8180-43d4-ba29-4f54420905fb	49a1c5f5-2d47-4ad6-8549-13c781a16223	QdBrwCNDSGt61vKrap_Ytg861jn-PKRX8MtztCv87ms	f50cbb114d37d8cbe6fb8151b16a78ed190f948300621a12d12ab93d58e92602	f	2026-04-02 14:07:10.928614+00	2026-03-26 14:07:10.940695+00
e4e231b3-e183-494b-bdaa-d55f3ed0efdc	49a1c5f5-2d47-4ad6-8549-13c781a16223	pO5wkEdD3ZTcb6R24YK98LwnHOMDZ5DFB9hcDFsbxzk	058d4697a80c8531bc1351c7ed7fbd655e132ad6626b853588e7af1f4b0d2fad	t	2026-04-02 13:56:53.94178+00	2026-03-26 13:56:53.944067+00
3d96aded-a0b6-45bb-b43c-27c97b80ba16	49a1c5f5-2d47-4ad6-8549-13c781a16223	HhSnZnc-3svQJkWU5lL61qM3hpelldkTEA8zxWadEBE	46eaa575d4e17d6bd5fe351cab9cb3ed003f71350eecff82cebede5ee2378c56	f	2026-04-02 14:17:34.416592+00	2026-03-26 14:17:34.442844+00
c1e7f7ba-d2ad-48f2-9805-6ca5f93ee873	49a1c5f5-2d47-4ad6-8549-13c781a16223	CXwyjj9sL7OE3UKq6_eDBctpUwRi_LUAxsFv5glAltU	e919cb0dc58717655dd581ac82960642d45448f8c9ef59140ff54f8e40ac3e9c	t	2026-04-02 14:07:10.965395+00	2026-03-26 14:07:10.966177+00
3f4abe23-3aee-4e3a-ac65-b07ff9f9e418	a2375bac-4a9f-4ed8-b674-a1807543c744	vLFg7DiMiQmUz4ntpc735cVtyAA2uiO32czKoalkeJA	6f933c9d7e9bfa6b36a34ffb8bc9170917029e50153445506e94129d7390d7c7	t	2026-04-03 11:08:15.984648+00	2026-03-27 11:08:15.984924+00
cec2010f-c2ed-4f4b-b5f3-491e12bd5fad	49a1c5f5-2d47-4ad6-8549-13c781a16223	LSjyB-yMimNCQD4OAsEISNZHI3VbjV3rgdAzrNLJ3E8	895b76218a3856a9d9f8d72c51620d572ef567d6a75eab13af0447993bccbc4f	f	2026-04-02 14:18:03.830002+00	2026-03-26 14:18:03.834804+00
d4fd8f3c-4012-4b7f-9985-ce64f3b09bcd	49a1c5f5-2d47-4ad6-8549-13c781a16223	HOf_3yFhj_tEub6SPp7Tt2zL5dNRopR3oiHninQthXY	8c1dfe7ab430583240b867ef6add71513f5e5761523064358440db190a576c4b	t	2026-04-02 14:17:34.483569+00	2026-03-26 14:17:34.484641+00
145a487b-8c40-4946-9413-83cbc9e52558	a2375bac-4a9f-4ed8-b674-a1807543c744	rfpfOiPa_Clcu5Pkh8chLlNtJeY_tWuiXIsspHcFSWk	07bf1f764bd61218679be3a47145cee45c16e7b7813c8803c86f3dafbae8462a	f	2026-04-03 10:52:08.912676+00	2026-03-27 10:52:08.914874+00
aea1ea63-1d44-4e7b-87a0-7ca7247044b9	49a1c5f5-2d47-4ad6-8549-13c781a16223	ICd5T6ayielZmwxM8a994GD3uq8HKmhDaExTPJBUYEQ	ad83f658fca5cd7334bdeea00f4c98005e8ea11645a6369c7e9df00351687b07	f	2026-04-02 14:36:38.876272+00	2026-03-26 14:36:38.879934+00
0abf8475-89bb-4634-a1d0-a307543377d0	49a1c5f5-2d47-4ad6-8549-13c781a16223	jV2azFTsx_UU92yd-3TZyOmpD8K2BclRiB32_IWl8bk	b38eb50917619517b1aac168bbbe6749c09e6a3c799177e10a59cc48717e8b6c	t	2026-04-02 14:18:03.849777+00	2026-03-26 14:18:03.850263+00
d6f97512-5d9e-4128-b6e1-b993e1090e45	a2375bac-4a9f-4ed8-b674-a1807543c744	nSXjnnrcQF1QMFNbMzprjO5H7WO3egWiluZPCx4B-Ns	77e654f32f2459c873daf077caa5120186aa0de27f7de492e08af92e9f8ce7e5	t	2026-04-03 09:02:45.953342+00	2026-03-27 09:02:45.955111+00
fb3e5c5c-c26a-4162-b226-073f7d2c6cec	49a1c5f5-2d47-4ad6-8549-13c781a16223	x-Fg_xeuaNjG_dGQ7rww2sozXDWqUQmGhe02iKgK9cA	b129342cbd7e2871468bee5228528fbec0fd55b06a9917d7c0c0876e7223034b	f	2026-04-02 15:04:14.598235+00	2026-03-26 15:04:14.603258+00
78be1f33-e37a-492d-a913-a7dd2e5baf39	49a1c5f5-2d47-4ad6-8549-13c781a16223	DbJta_90ArcqvyMIQCpn9ZdRnM2UlMoVD0prwFtKNvM	c67ef36fe425fd7e39553ff051a70e2dab0f2425677a15a4cee581a819dd30cc	t	2026-04-02 14:36:38.907322+00	2026-03-26 14:36:38.908554+00
f74c8f17-9cdb-4965-9728-5c80ebafb625	49a1c5f5-2d47-4ad6-8549-13c781a16223	yqGlpX4-RkdzAqcwLcWfLcrfXA49VTWVq4tIBCA1q6E	de0ccad02331e7b9b42566304f192197c3fc87a29708faad8ac27c11b7022d4f	t	2026-04-02 15:04:14.618075+00	2026-03-26 15:04:14.618881+00
70cb8637-2340-40f4-a9d1-c9aab915b4d4	a2375bac-4a9f-4ed8-b674-a1807543c744	Am1uestB1xUtTYfEcN3YZFiFKONhDovhheL-FQnDJaQ	04e3f68e20424ff2a15df0d7c882537be1c5a5a56eff9706eae4513d32509b58	t	2026-04-02 15:12:32.946047+00	2026-03-26 15:12:32.971616+00
564fe322-99d7-4cac-9724-2d08bba3623d	49a1c5f5-2d47-4ad6-8549-13c781a16223	979oCMyZc6WLBtNuHdNQbi81RFw0hOLAQr4P5AfVj24	f2809ebcd6ba2ebacbb9852e9fc7fba6d73347c5df4fb6fd10a6256357a9d8be	f	2026-04-02 15:20:14.782346+00	2026-03-26 15:20:14.795114+00
ee015f3b-a8b2-4dee-bbc3-414b7532bd8b	49a1c5f5-2d47-4ad6-8549-13c781a16223	ZzPJ6W022AdoqqG61WTkiyy9ruAFDao3thgmo1Ccqvk	b6b3bf33e3ad6bae81faef27f849c931eea61edc489ef20c5be0c69d8a315738	t	2026-04-02 15:15:47.272034+00	2026-03-26 15:15:47.276223+00
d552c409-8d78-48e2-a48e-8494c69df8f9	49a1c5f5-2d47-4ad6-8549-13c781a16223	tF3valyHe8Th7sc-JTjLwXGR0wiDATYM-sGI7Z1vKTg	91add7c73e80458414f1f0bcccaf4fe8e54dbb5aec51a02bdd69e1e58d05a926	f	2026-04-02 15:20:14.825725+00	2026-03-26 15:20:14.826965+00
86d6b702-5383-402b-9be6-91a0ace24caf	49a1c5f5-2d47-4ad6-8549-13c781a16223	RXSh7HAEmncNG3-UgEo0hxBSS-cDqbT-mLIO6e_T5Wg	b6085a5cd4fc08edefd3a321121a5deb1c2e6fafb813bc80b310fddc961abd75	t	2026-04-02 15:28:57.74276+00	2026-03-26 15:28:57.74481+00
aa103f52-359f-44ab-94d2-e5b4819f3b1a	a2375bac-4a9f-4ed8-b674-a1807543c744	p5ttBo1uWrHyTKU3CG92eNcaL_e3usQMvIdxIh4VSyk	587b29804bc17c579df84172fcc9c91e38a606b43c2a0901813457db28f5c38e	f	2026-04-03 11:02:15.775739+00	2026-03-27 11:02:15.779044+00
4aea3a12-61d8-4eb7-90db-ad8768718d4d	a2375bac-4a9f-4ed8-b674-a1807543c744	taARSRee30mVFfnaL8-QIFuSfpn7LrIah7fMtFxrQKc	e8fb19a0e8c831e6e02abdb7c2619ad11bf4d7e33417928b03ed505687a31c76	f	2026-04-03 08:54:30.0476+00	2026-03-27 08:54:30.050214+00
6c656889-9b17-4f0a-953c-a12f5a641de6	a2375bac-4a9f-4ed8-b674-a1807543c744	RDAxOU10bDdBanU7WZmG3EPuu2cfKpOTlKT2OVPE4Cc	51a508c226ad0e26bb7b1bf59e3447ff3a87743f7357ac99923bd39158ce1dd1	t	2026-04-02 15:29:27.852198+00	2026-03-26 15:29:27.853001+00
258007e4-2d5e-4b7b-b5e0-c23085e93522	a2375bac-4a9f-4ed8-b674-a1807543c744	3wq-0cl4ekVprRsAFqNzoYR6BT29TV6c63iCTyRCFks	83129d2209140f04abbf3e59972b5e23e51067f7aaf60eb1a0580a3159fb2671	f	2026-04-03 10:57:16.721801+00	2026-03-27 10:57:16.728196+00
54a62ac1-44e0-4ea0-9ff2-17ff33423823	a2375bac-4a9f-4ed8-b674-a1807543c744	cSfcqGDBGrfmeiAtVYg7cHFfWa-CfmllAwTs019lBCo	921c5ef02204805fb484ae9cd172caa35ad2e8acaee939805b96dcc5ad3a5a2a	f	2026-04-03 08:54:59.197435+00	2026-03-27 08:54:59.200721+00
e635ba4d-e2ff-4489-83ec-bec6b1cd29e9	a2375bac-4a9f-4ed8-b674-a1807543c744	jsNOEPFFgVTbplLoWyv0BDlPqJtpxvKiPoYdBt4KQb8	5f61b6ee9e5b66a8920410846b84277d0d93035419262a67a23d99ca81f149f0	t	2026-04-03 08:54:30.06715+00	2026-03-27 08:54:30.067764+00
3d4f2784-2eec-478a-9287-f5cd3fa17b29	a2375bac-4a9f-4ed8-b674-a1807543c744	m6-DiALoez-7K2dPzMUR1ZsQFRH6kj07SlwDXwT1OUg	97d3b752b0d04a521b4d513e1b06179437ed36fcc8e34fd3932094966313fa44	t	2026-04-03 10:52:08.923008+00	2026-03-27 10:52:08.923416+00
72476770-1a1c-455c-97df-5afa8857def4	a2375bac-4a9f-4ed8-b674-a1807543c744	HJahlGT3ZZWXFwFUAxEaOO9MgQQKooAZmIV6tKAZI9U	51d0968596136b257fd9ff879e96b2e46f365ec18a5938c5ab8acc4e69306af8	t	2026-04-03 10:59:46.476825+00	2026-03-27 10:59:46.477177+00
b4b62131-572b-4933-aa2b-f3e6084b95fc	a2375bac-4a9f-4ed8-b674-a1807543c744	QT1G8_WP142d612mt6Ncs91mmvTObuOxTEBAkx-4H4E	923fcc26d4a2e205696acdb7c6804e4a029bd3a18a1177682d6da01ba00bae26	f	2026-04-03 10:57:59.799342+00	2026-03-27 10:57:59.799843+00
e3a8bb81-dde4-4b2e-b6bf-497dbf0a63c1	a2375bac-4a9f-4ed8-b674-a1807543c744	P8342uS8gnn669VUUdzG8O2SmPfQLMJB-K8mBNUIva0	1ddeb89550644dca756df2a7c049a656c3ad05dbd65cc089c533aab9e024cae0	t	2026-04-03 10:57:16.742247+00	2026-03-27 10:57:16.742602+00
e3c46c48-d7bd-4478-b700-d3eb2c6b1d5d	a2375bac-4a9f-4ed8-b674-a1807543c744	ciGhV2zwZTnD9uh1sQjA7QuJeLFfbP-t2Cy0BJTQmM8	aa3eab6999807fc8c618c29fdf6acb5c9a2ae466362f79b67ec61593890de88a	f	2026-04-03 10:59:46.470305+00	2026-03-27 10:59:46.470866+00
d9f060f4-69b6-4467-9e5e-671a6f0951da	a2375bac-4a9f-4ed8-b674-a1807543c744	niwRCC-1xwJtxRtKraHLQNf3bSeygfTdpbCH6yfm4Xo	bcf9b001d42d35815caf8c470f3f8f325f6881697a3b46e48c15eef5ca4970c3	t	2026-04-03 10:57:59.80687+00	2026-03-27 10:57:59.808284+00
ea0135e8-5a4e-4b57-ae19-89f6d15b3faf	a2375bac-4a9f-4ed8-b674-a1807543c744	ZRcXOyweHpAUc4P7vMIJQqivUZ7pZuHmJZccueDixto	701084daff026ae9273038295c80ef285e02d8f6583f1fa4a1b4e58c3983d2e4	t	2026-04-03 11:02:15.789441+00	2026-03-27 11:02:15.789739+00
5d3eb9b0-0b84-43eb-883d-6439addc5123	a2375bac-4a9f-4ed8-b674-a1807543c744	htxQWBNzKAk7FL2o17_APdcNuja8E7schLWMkdKUt2I	ce4cbf0bcdc5d7aeae622e4ec7b6a35487441cb9c61e8c41e778a5a7d49e702a	t	2026-04-03 11:02:47.417495+00	2026-03-27 11:02:47.417806+00
2131f750-7dce-422c-9282-6b7d4f34e4ec	a2375bac-4a9f-4ed8-b674-a1807543c744	uZu3nUMotbDIID3Dldh3YOqJwQe4MCW9G-pQVWz2F1E	5c392a3a8341f9ff4813b2246f3bbe0edee0dd3977e316d6a32dac0043dd4a39	f	2026-04-03 11:08:15.971747+00	2026-03-27 11:08:15.974329+00
63542f06-beaf-4ebf-b6ce-541fca6a6907	a2375bac-4a9f-4ed8-b674-a1807543c744	y3UDi9eHkNm4guzh0ZetSMxyhxH3UqdYvgWf41Op-so	8a301ea1fdfd8027c02bf86adf9c78f192e37457331c0f5d93de0c4b1a3cf85d	t	2026-04-03 11:02:47.852131+00	2026-03-27 11:02:47.852464+00
0ba2baa1-f026-41ed-b410-423acff64270	a2375bac-4a9f-4ed8-b674-a1807543c744	TiANfb3f5noWX7Hhh0BfnN5VWkeM0W87x7uD4jOQb-g	8de1b97e68c70a5f4b5d4a8135e0608aec34c1cc955e35f830fd1647a5f4ad10	f	2026-04-03 12:10:02.325399+00	2026-03-27 12:10:02.326208+00
603cc996-aa6e-4583-88fa-53f435ae2a66	a2375bac-4a9f-4ed8-b674-a1807543c744	IvQibYHz81Tn5dqmoyQCBoie2d5fdegna-QOlPPziVs	cebbaee516e8735996a4ddf5514bcf2b2d752abf27385a2ac380257f67921412	t	2026-04-03 11:16:43.059246+00	2026-03-27 11:16:43.063316+00
757324bc-56b2-47c3-9c7c-fe664ba1f56c	a2375bac-4a9f-4ed8-b674-a1807543c744	GbCCTKHHODI9WpearvfTLdVoP_whIDp-FzU0CsS7BEE	d09194df3112fad2aef1671da2a293efb385aec52d7f5338297b5b95fffc8d54	f	2026-04-03 13:24:49.25733+00	2026-03-27 13:24:49.259282+00
9d28b73a-f95b-4a77-960d-ea03d45d7e68	a2375bac-4a9f-4ed8-b674-a1807543c744	lo9Hxyq-0yIInuqmW3y05BQEdDmD8hBO-yseoy44HBQ	6fe5315803bbabffabf1a6ffdda23d57ea915ac8d0e4d54b2654f1974b857b55	t	2026-04-03 12:10:02.331157+00	2026-03-27 12:10:02.331445+00
8748b4c0-00ec-4235-b2b4-4efc7ca74541	a2375bac-4a9f-4ed8-b674-a1807543c744	a5c2Pov89kil-0UBarth4UdWxlCpBvBx5mDbXbO1Aqs	3d83796001a9c5ed7d5d5e6d234a473244f65835f4f3e1ec56faf40b844ca51c	f	2026-04-03 13:34:25.917249+00	2026-03-27 13:34:25.920816+00
6af9c11c-f5f6-4867-a4a6-8390c3800f4d	a2375bac-4a9f-4ed8-b674-a1807543c744	te-njRWLHYGVhH4fNAWJ8z_aHAIY2mWrSJrHeYp90jU	3fc47c400cc11503478fe347d5686b986f4fcb63d84d1ff69c3e3aa8db0c88e5	t	2026-04-03 13:24:49.292846+00	2026-03-27 13:24:49.294195+00
11532fe9-e016-4f4c-bd06-278e1a7c9955	a2375bac-4a9f-4ed8-b674-a1807543c744	i2Na6xRTySYNTvqW-bViHO_oXltvTa20SS-M2iTLOps	af01065e435ca5b679f018ee10c2157ce7207e2f959ffab357f5b520ff6260e1	f	2026-04-06 10:50:18.087776+00	2026-03-30 10:50:18.09747+00
2156dcff-cab6-4de4-977f-26eb30185b79	a2375bac-4a9f-4ed8-b674-a1807543c744	UY1O2kS8w1e3FGoRo7h-rvuan8_wfgqsQ68C5hZEVmg	942fa6edb7c1fdf0cc8ae18a5142ce88b14a426d32e6d4a28211e3c10442a255	f	2026-04-03 13:41:44.131675+00	2026-03-27 13:41:44.135219+00
2d0fb4b4-37d3-4d64-a110-dac803b3e1ea	a2375bac-4a9f-4ed8-b674-a1807543c744	n13VEzL-CeCqPP6YnWQga5X4_ztKxX5xG-5fWiX_3OQ	f0b51ce63547d3ff911e94ba203848922c75a298f573c88661c430cc4e1a3e05	t	2026-04-03 13:34:25.942468+00	2026-03-27 13:34:25.942955+00
88d66de3-1d4b-4f93-bb94-96bf28c11d1e	a2375bac-4a9f-4ed8-b674-a1807543c744	AEIMAzhU0m1mDq37cYKNK8y5Fx3JQaEcOdkfsv6drtI	155452a28b466b0d7c50bf598a44580c98067f69cd22306aad834b15bb356e0b	t	2026-04-03 13:41:44.147543+00	2026-03-27 13:41:44.147955+00
f2b99fed-5743-4e85-98d8-44643364500c	a2375bac-4a9f-4ed8-b674-a1807543c744	p1PpDgnPICQMxFNbuH8BYHvNTunT4mNAVSSQRh3kbTQ	110c4bec1ecb9d2c876692a4d910ceb4e833988e11c0926138c0addea2d3c3e0	f	2026-04-03 15:27:03.697329+00	2026-03-27 15:27:03.708342+00
0faaeaa3-3dd6-4eb2-a626-6532e2baf44f	a2375bac-4a9f-4ed8-b674-a1807543c744	hrpHiuD1OUgScd7ffQaCY9ELH0inWVNKiOwgUsGaW_E	f47e92cc053fe293c26e7af85a7d4ca9cc5571acff028837d12801a1b09cd90c	f	2026-04-03 14:08:47.390364+00	2026-03-27 14:08:47.402309+00
7fa42579-aa13-43d7-afd4-9497bd19e8d6	a2375bac-4a9f-4ed8-b674-a1807543c744	_fGFUEcoeTfzQIOJNDaaoNXya2d2_12inttihKrtiZ4	4cc9477563e24ee1944d486b9d3cd09754c0954d9c2775dedacbd8fb990cd4d4	t	2026-04-03 13:43:17.938711+00	2026-03-27 13:43:17.943741+00
a93dc497-8c7f-4e69-874a-c90a3d12055e	a2375bac-4a9f-4ed8-b674-a1807543c744	GyurnvMghKUOabV2KG5UrktM2TbzkS1JlDLRTybW4DU	b87944695291ac4f25bb6b3345fb9240ce4e5dc3244a8041b7412de0e5d914cf	t	2026-04-03 15:16:58.526684+00	2026-03-27 15:16:58.527006+00
cade808d-a41f-48c7-bf1c-bdaf0bfe66ee	a2375bac-4a9f-4ed8-b674-a1807543c744	sEI8xo2hOgGz6UAwXWAOfVhHk3BsFhw2l2Etwjl63L8	37f7e24b66ab224e5ec495a9916a35197a44e10a1cbd62d82196c28b6f3fa5ab	f	2026-04-03 14:13:49.652217+00	2026-03-27 14:13:49.662276+00
533bdfd7-bd8b-48e4-9179-6865ca45290d	a2375bac-4a9f-4ed8-b674-a1807543c744	X79rcj-ELR5wa5TQgRAcUDVucHhX5PbnEvO-qQ28EuQ	8e93e407c5a85c1cea1b267a607f8a76db1c0665cf8417a13d82cff562974827	t	2026-04-03 14:08:47.424394+00	2026-03-27 14:08:47.424991+00
31e790ea-2d35-4f86-9966-58f0aabf4e55	a2375bac-4a9f-4ed8-b674-a1807543c744	uY7srZyPxoJcutUz6A_jnu_728f51qWtblDYIEttbN0	6ed237e4ab6b6f7bafc8d5dc7174c45089c7bd077d67c9efc1dd3738d535a2b3	f	2026-04-03 14:16:34.965204+00	2026-03-27 14:16:34.968591+00
d082f232-d14b-4dc3-bcef-5efdca11d7dd	a2375bac-4a9f-4ed8-b674-a1807543c744	1bXzJBHRZ4ImCgLKDqq5P4Gtz5xYVpkiAhQ13gSQ6EE	837bbd4d1cbd83fef605219cbf98d4d8a1cfa90499b850b818ea986035d09bfd	t	2026-04-03 14:13:49.689411+00	2026-03-27 14:13:49.689719+00
0d3bc992-bdb9-4ae5-9aa3-4cb4eeef164d	a2375bac-4a9f-4ed8-b674-a1807543c744	hO-9WEbRgVEk5P1vtHIjWF_8ZhQSCedpIholRX944eI	f8bdb9ae8b8ad01900737d2145cf7982f2d2f2bfdb82786050eae9c70505185c	t	2026-04-06 10:44:22.858323+00	2026-03-30 10:44:22.858923+00
d0ffa946-5af3-4981-84d6-66c15da93705	a2375bac-4a9f-4ed8-b674-a1807543c744	7n-QT2Fc9pPVdCnldscuvb7Ub_utGKRsHiE58ybGRO4	cf3afd159b7ed723063b91c6871b38e79d9cf4bcd5c7579897389f916f7e3681	f	2026-04-03 14:38:34.188145+00	2026-03-27 14:38:34.223572+00
f3ddc91e-dc71-4787-8a91-4c7af7a73520	a2375bac-4a9f-4ed8-b674-a1807543c744	4h26wxf5feYWbcDjjevaOiqXUKBl-C1T4oxg0UbsQ-k	3ab530a9bb721983ea0d4567745692493766c736b42645e0194515e40f64553c	t	2026-04-03 14:16:34.983264+00	2026-03-27 14:16:34.983843+00
ac18f8d5-2f75-42d1-8db4-00f36523a9c6	a2375bac-4a9f-4ed8-b674-a1807543c744	yoh0v7Tg5LrMq02XHyPBSDTlYEAnBGVxQOGatJPD7F4	f1d7d6273f74266ba5d422bd20a92ba9c18484e4025212c4f3d810cf5479940a	t	2026-04-03 14:38:34.273503+00	2026-03-27 14:38:34.274873+00
b6bab8a7-0ba6-420d-8a29-8936d7520b0c	a2375bac-4a9f-4ed8-b674-a1807543c744	9KFn9_ExH_3CRurSvCkDsvzFxn5VoD4A1cDGfrH5-r4	497ea86a9041a522dc2a7eea05b3c13dd888374ef5a3324ca3c4d75d1a21ca5d	f	2026-04-06 08:38:54.919383+00	2026-03-30 08:38:54.921635+00
30779b9b-3db1-4690-9ab8-03e2d7f50b13	a2375bac-4a9f-4ed8-b674-a1807543c744	F4G-qqVf_d-PfCPZy_grOaNcZQXKljkcHfIVHu6ORBI	f2c23108f797211a2c96f0dc129d553b664be9a998c5e90ea8be2cafac40dde1	f	2026-04-03 14:42:33.700897+00	2026-03-27 14:42:33.712528+00
7239b1ee-5ce8-41eb-8429-36a06218e805	a2375bac-4a9f-4ed8-b674-a1807543c744	mmFwnGui9fDN9LA6StVnLINxCUXAcTNn5G3LpWpgzIY	1a9afb81932dc3e3e9a43319bf452d2b5217f4bea00e9477f27e761439875263	t	2026-04-03 14:39:14.398459+00	2026-03-27 14:39:14.399969+00
4ab7667a-e78b-4fe7-8f76-db26a930988c	a2375bac-4a9f-4ed8-b674-a1807543c744	k9NbVxz50b8kN9C2EYdDLoVtGwOBBY8aN-xmHVULvLE	d4ecb851ab2ca700763dc759b34eacd05700ee1b6eae79d6a0930a7fbc0e3fb4	t	2026-04-03 14:42:33.744294+00	2026-03-27 14:42:33.744653+00
cadd7b75-9628-4ca7-9438-ec6ab7d24848	a2375bac-4a9f-4ed8-b674-a1807543c744	HAoj16IoI-QwI-QDppwneQlJ-QHpRxJsZ74JmUvxJI8	6058a4c29ed597492d38fc969c8885c2d019d54b5362edfb82fba8bb24df1dc0	t	2026-04-03 15:27:03.74243+00	2026-03-27 15:27:03.742779+00
ded8e9de-2f38-4c7c-a542-8fac49d2fdd4	a2375bac-4a9f-4ed8-b674-a1807543c744	xl2Qq-3S2wssnyRCQufmlD6UWss5T7k9Ms8VwZrDc0M	7d0cbe24431624caf4d493f13634f09a9bd8f2eaac5cd69278c4db53cbae5cb1	f	2026-04-03 14:56:41.1663+00	2026-03-27 14:56:41.168343+00
d171bfa7-ed91-4966-bdc2-2177c2b21509	a2375bac-4a9f-4ed8-b674-a1807543c744	OK8okEvojq0Bu9EuA3PjPr5d5gPE5lcCNLp1IC1GsbI	4484b55ae62e77ef1594556c18907ccef0c1ad9cb038b46acc340ec403195b26	t	2026-04-03 14:45:25.486844+00	2026-03-27 14:45:25.494219+00
f70483dc-d6b2-4229-b6f4-d5fb13f71bd3	a2375bac-4a9f-4ed8-b674-a1807543c744	gKuOrioOXtX0ka1RR9Ptv4dKl0KwdQ4Nr4xuF3erzOQ	20cf9b176f252762c4b8cbb4c2c9cad7dda3c22d510bfa07e24029d0e2a9f9d1	f	2026-04-03 15:11:58.932321+00	2026-03-27 15:11:58.938361+00
cc91052e-c74b-4696-b458-60d0fc545b6c	a2375bac-4a9f-4ed8-b674-a1807543c744	xOp5d5ykOk1iUeP7lRDvItGffldxaDV1lIyVHN6VXVg	a031636a592f27c9d87d25e4c5139e5457465915f95242af71d49910aa15658d	t	2026-04-03 14:56:41.179043+00	2026-03-27 14:56:41.179707+00
eb46cd7f-1b11-41f1-a922-576c7e533007	a2375bac-4a9f-4ed8-b674-a1807543c744	6jRDeKjVZ_upML4GDvql8874_Bqo4DePapQPMJciLZY	5a30bd90d70b37349e2f7b6686a6f577a4782e631fbe7d0e527c9d2f7992c562	t	2026-04-06 08:38:54.934439+00	2026-03-30 08:38:54.93541+00
1e4eb5fe-9e41-40ed-a098-f9361866eab4	a2375bac-4a9f-4ed8-b674-a1807543c744	8zNRh4K7auDPXSxjUaKvyNIpe15dLNQyjmDu0nQLc-Y	bc90f2ccdba7d25fcc12f8d40c481a2f585c80e46616c70e247102be58fe7924	f	2026-04-03 15:16:58.512394+00	2026-03-27 15:16:58.517077+00
f089b20c-e5c5-456e-818f-d3a496b3599d	a2375bac-4a9f-4ed8-b674-a1807543c744	GEWSGWlaReC20akCEDfyb48T-JS0vCLXvDw5Kqr0ES4	dafcf41ee8133fb4c2ac3d17fba8d0308b513bafd63f25e22372e2e8f7959185	t	2026-04-03 15:11:58.953738+00	2026-03-27 15:11:58.95415+00
12ebfd0e-4166-464f-af29-1064b41199d9	a2375bac-4a9f-4ed8-b674-a1807543c744	ka8a78E8J_S_1Ky4xWArAeT6IKwGi4RQU7aWnid9QrY	f213e1abcc7dc93f0cf97a2c0126c2813553e8484a9ac724ed9eb498c3b70fd8	t	2026-04-06 08:39:31.481401+00	2026-03-30 08:39:31.481978+00
f537ed3b-2b0e-40e7-b8ac-fb78324b9d24	a2375bac-4a9f-4ed8-b674-a1807543c744	0f3k4OubIaPBfAD9EUlUTB-Ht34jV4GpO2PGJTEaSps	32fd8cc1312149d604bc9a6e1675f7928be06d80b4d9532a340d9fd627096a63	f	2026-04-06 10:44:22.831576+00	2026-03-30 10:44:22.8358+00
e8459188-8b84-48c6-870b-bc49fe388c46	a2375bac-4a9f-4ed8-b674-a1807543c744	ObLKPMQG0DztFVk6fB4ExEqUEFe_ln_g4iHm35bOuMg	4e7f6dc348af25357d943a8a673d293b50ebcf9669e8ecacaccfa359d33cedeb	t	2026-04-06 10:41:04.296197+00	2026-03-30 10:41:04.29868+00
4107c6c5-9946-4bd2-9199-bab9de033258	a2375bac-4a9f-4ed8-b674-a1807543c744	ZlP-2fGqo11HLqSAlkkTu1S8PFqX1dApq56aOfy3Hqc	82bd78e0e53a621fc82c439d80f1139ae550d8c95696dee654cf0e8592a893ba	f	2026-04-06 11:25:39.502992+00	2026-03-30 11:25:39.505128+00
dd6e3227-7122-4dbb-8977-fe31ec2d7296	a2375bac-4a9f-4ed8-b674-a1807543c744	YL_S8Ao6EQag8JKXsgwstv9GToWU_UbSi0UFEWjlH_0	44886fca8a1c77006e59aa91d1c5842ac63304c47b5e2316e5aa342d62ed8b1b	f	2026-04-06 10:59:01.021401+00	2026-03-30 10:59:01.022672+00
60ee1961-63c3-46bb-9b63-330a86782664	a2375bac-4a9f-4ed8-b674-a1807543c744	7EGlsM7tZQ5efT0PVBea3dpiFwOI3b7JH32xk1QXZ38	61f6fec22503796cf40fc5e55bce197b0c65a6657fa454af6c2d582ea73b6358	t	2026-04-06 10:50:18.116889+00	2026-03-30 10:50:18.11737+00
73502afa-5347-444b-9f77-9a7f8d191d19	a2375bac-4a9f-4ed8-b674-a1807543c744	PVIHdkzutNTcDizUCfAotHICO1urhPFuT1krv_xKwmg	c76c24382f40981e1cab2d8f3e6275e50539b5812ef73d6dba8f2668cba80186	t	2026-04-06 11:15:24.002207+00	2026-03-30 11:15:24.002616+00
5675712f-0378-473c-b966-afc7047c4487	a2375bac-4a9f-4ed8-b674-a1807543c744	6pP1YXBPZxVQDDUpEgr45aC0S61jRNXHpxNUx0kTqs8	8d05de8c8229085aa68ac893a79ec7b2308572c0e24bdd5aaebdee4c9df28960	f	2026-04-06 11:15:23.991839+00	2026-03-30 11:15:23.992847+00
8084e1df-471f-4940-aa70-d84f3a1bf1bc	a2375bac-4a9f-4ed8-b674-a1807543c744	taOwaZzhImcGo6_BaKw48wOkuMVbWFoKMrLd7t37PBU	9bb2563a0b4460c92dbcb1a9a895684c92345d82addae0b36060f370eb4ab68f	t	2026-04-06 10:59:01.038436+00	2026-03-30 10:59:01.039038+00
b4353684-3b0f-424b-b1c8-5601913ff335	a2375bac-4a9f-4ed8-b674-a1807543c744	k1_kHdhyXyT80sWCj-BGn7w6yzcYMqrsrgujlIBxCLM	33774d2d027be7e0a40eb8bdf6cf1928d9a03cdc6713769fa7e0e590e24463f1	f	2026-04-06 11:32:36.689731+00	2026-03-30 11:32:36.691429+00
fae65190-3147-41a5-a3b6-a6b2d9a6e8c9	a2375bac-4a9f-4ed8-b674-a1807543c744	aQ50BNzY19qewrns26nvnRt95tbA_SW2h0aRpDYLwts	243cdf37236015dfc0860802a0706f9f6b6077956b0dcc34c6aa9284c4bdd551	t	2026-04-06 11:25:39.522634+00	2026-03-30 11:25:39.523731+00
969844d1-bc62-4a3c-85da-cc8fbb6e09a7	a2375bac-4a9f-4ed8-b674-a1807543c744	CYAc2XaXlHCxjvTvQSiIujZryFq1b33SAZkUHCMOfxE	9581c640562b9bdd43725aa9c16b1739f63df817154b31ebf34b8bd3ac113d07	f	2026-04-06 11:48:54.074864+00	2026-03-30 11:48:54.078161+00
4f7aff0e-8882-435b-8202-f358a8d797b1	a2375bac-4a9f-4ed8-b674-a1807543c744	bG7SAWJpQzhPbxB1EXqYS_UUrwIxBny-_eYiBEyPoDI	0390f0845e41de456c294d587f9de1236a9ffc140ac6a57d6f7eb56a15a7c32a	t	2026-04-06 11:32:36.701702+00	2026-03-30 11:32:36.70227+00
edf6936b-8db1-4c50-92b7-086966858833	a2375bac-4a9f-4ed8-b674-a1807543c744	gPYA2rGL0gPjORdTkuw6htvBsNurqTLJ0iEhomD37MQ	9f168b5422dc1384cd59c575284c7b2e9cc433e007c255e2481fcff81190755a	t	2026-04-06 15:05:43.430107+00	2026-03-30 15:05:43.430993+00
a628497f-f854-44eb-a414-fdb4f96dc6d4	a2375bac-4a9f-4ed8-b674-a1807543c744	rMl2lYj3ClN5MnMz0-ERqowI-iMiAbzuzr53RwCiEnc	f2806fb3458889d58b36cff737a9e20ffc6363771973bc6aca4dd5067b41362e	f	2026-04-06 11:51:18.298348+00	2026-03-30 11:51:18.30045+00
4eaf740c-76ea-4de4-bf6e-2dbd056472d6	a2375bac-4a9f-4ed8-b674-a1807543c744	OBvNIFfgFzLeiJx0XHd-jlNm-Tdld9RIczKxofs_o5g	6120df3db01844333aa5dfc7a62b9312227c1797030e11fe0cbf5df8de848153	t	2026-04-06 11:48:54.088978+00	2026-03-30 11:48:54.089739+00
f7e461b7-cf61-4f73-ab5d-d23f4535e424	a2375bac-4a9f-4ed8-b674-a1807543c744	GuHUUuxMsIZvpODVaNJIbhmGFb32BYpo4FfeEjj_mj8	958465c9ed6fb9ae779a61e043eb1ac8c3e9f8317d41d87643b748d7f114e668	f	2026-04-06 13:42:41.895133+00	2026-03-30 13:42:41.896553+00
d31d47d6-96c5-46cc-b003-aff1e6ba4a2a	a2375bac-4a9f-4ed8-b674-a1807543c744	YG0KAoPnravEHGHNUCUE36I9eWNknMx-NsyE8tnVQZE	d6b761a213f6468486aa4e38db5a62f5c356efc9fc1d5e87f7649559daf943f8	f	2026-04-06 12:12:13.068331+00	2026-03-30 12:12:13.070125+00
e0c7cbbe-3956-4285-a407-49c8db958636	a2375bac-4a9f-4ed8-b674-a1807543c744	Jb9nO0w53RJHeTrYb6luV8K3FvLjE7OMtdrIwlibhCI	db070b8e94fdd940b8b1ccce1e364868bacfac8f5a23f473f60a53fd3f1c2950	t	2026-04-06 11:51:18.322148+00	2026-03-30 11:51:18.322851+00
ce8f3e70-87c4-4029-bcf2-438070deb194	a2375bac-4a9f-4ed8-b674-a1807543c744	7zzlZrFDvxxAU3THPxprIUJWA1FUjzR3KHAjigNGg5k	f8615bbfe71ef14a88ef7ce229479cc31533619a6bfd58b1f145cc1071266c51	t	2026-04-06 13:14:51.026731+00	2026-03-30 13:14:51.027331+00
7feb949b-4fcc-416f-a53b-0c55b1ca066f	a2375bac-4a9f-4ed8-b674-a1807543c744	0Pz6TRKSA8jQM5dzy1j5ffyA3n7nF8zthVw_7594MdM	4e82489c68ca749b79053a10b08c8de3aab8f8cd3b7fc47cae1ed43ec94a5678	f	2026-04-06 12:25:02.1693+00	2026-03-30 12:25:02.170665+00
b67e0312-bd36-4f39-80da-52beb9af6b60	a2375bac-4a9f-4ed8-b674-a1807543c744	UxSF2cyGAfYvlMWnn8guucWKsgGEYMgfVd4iKchFxY4	9518766a304a4f7942e536e25f106c18884636bbde654deea78ebb4f3e2ddfb3	t	2026-04-06 12:12:13.07938+00	2026-03-30 12:12:13.079859+00
cfc18f86-720e-43f1-9cf8-afba88d98f59	a2375bac-4a9f-4ed8-b674-a1807543c744	Sjv-i5PM2G6xTr7whlmjTL8e9_Zf9rde7T5Qj7jPCGw	ed562869e2ba78511f1efb0781aa0265cfa7204b57ebb19180a1fd47aff5ac4e	f	2026-04-06 12:30:46.616152+00	2026-03-30 12:30:46.617432+00
c7e99cca-a6ad-4e4d-999c-f2a3519d81fa	a2375bac-4a9f-4ed8-b674-a1807543c744	b2RMy6cUS3wKfh0zC0p9tcm65l-xr9wz2mVN5wHmq_w	ea16e0a0882cb12184bbe3dec5efdaf02d62c9b9ddcff9fec0a7e02ca052de0a	t	2026-04-06 12:25:02.187226+00	2026-03-30 12:25:02.187942+00
0bf06491-4fcb-45ab-b7c4-fc263d688172	a2375bac-4a9f-4ed8-b674-a1807543c744	Ll7VjPL1G4epiS3YIi-E_VCIWsnyCzwM3f2XJrAFTxI	a719dfd0fc821b812f490574c8a48e761e540849e4c9bb38077c7bd190e0f103	f	2026-04-06 14:15:03.689811+00	2026-03-30 14:15:03.694585+00
3fe5ac6d-426c-4ef0-a910-5d0afa678651	a2375bac-4a9f-4ed8-b674-a1807543c744	jh-UDT-lQg3KULgtPyJf7YH-5X6RUiNV4blx867cnfw	063504047e13f3d0201bc61ea3374225b50a69c4305bb61ca6ccc7faa3341dea	f	2026-04-06 12:36:56.978875+00	2026-03-30 12:36:56.980343+00
1c14c4bc-cf33-4b09-82ab-a9e8d5d58707	a2375bac-4a9f-4ed8-b674-a1807543c744	bZug20J9p-9xLjg8W-2yXCFmcMY28wfzqpX2WQ22C_c	752c86e21da1adbd9a911381c41f5b78bc02cc9fe4777e9c0cf05d6083601d77	t	2026-04-06 12:30:46.634799+00	2026-03-30 12:30:46.635486+00
37efa014-4296-44d8-815c-6b30f2fb61ff	a2375bac-4a9f-4ed8-b674-a1807543c744	UE5FRomk5AvIp0QR3L5JvyE9tyyRFxz5AdLYeoPmoUA	11c2bb3314e38c27fb9d6b01d9d27b534da0b96fc5d9f012cf8f8f2c0fe4a41e	f	2026-04-06 13:55:11.109557+00	2026-03-30 13:55:11.122217+00
19275df6-e996-497d-b026-c0fdb1e5ab1e	a2375bac-4a9f-4ed8-b674-a1807543c744	ELo8Sd_c_6lvbkBH_83qikHt0gmJw-Sga0vT06i7WlA	1d4a3af921428e5c8899d42af40c1eed38a6584bd73f1eb59f82d193dfeea3eb	f	2026-04-06 12:44:28.177097+00	2026-03-30 12:44:28.178377+00
2ef4ff54-6d90-4fd7-bc7f-9b47c54559ae	a2375bac-4a9f-4ed8-b674-a1807543c744	gkYIVlKlI2OlgQ6is346EjUWgtON0WaYDagrgkMwOgc	f18a22eedf541615dea486e7b00f9cfd88d4c14d9443a72d6f7836f53b95b409	t	2026-04-06 12:36:56.988955+00	2026-03-30 12:36:56.989716+00
2b38b04e-bb50-487f-bdc1-1a4a48964414	a2375bac-4a9f-4ed8-b674-a1807543c744	0wIhAcrZtZkonfkrNLmc1MyBzw2NKB5dCyZyc3sAJC4	5bdc8b045387ea3a657442862e32528e34f09fdd90fe7eb527bac4960f67e517	t	2026-04-06 13:42:41.913262+00	2026-03-30 13:42:41.914109+00
8d18318a-cf9a-4c8f-ae25-e9e7933701ca	a2375bac-4a9f-4ed8-b674-a1807543c744	mUdU3pwV67XBMavy7DEtndsUVUvFYP_kk-apn9CYGmk	30c17c3279ae80bd13043762d2007a50b90eac77b6272bc32e008ffeed2c365c	f	2026-04-06 13:07:29.976825+00	2026-03-30 13:07:29.987456+00
141da022-70e2-4e94-8cd0-30f14d149a36	a2375bac-4a9f-4ed8-b674-a1807543c744	8ufsay1F8gSoHeyf2rtBefcMYzOBoOJTa4Xsj34GONQ	9ca0420a803b3977f393caafbd1e372630126c42b75ccb28fd533c5373863b28	t	2026-04-06 12:44:28.189981+00	2026-03-30 12:44:28.191985+00
d755b377-4978-4f69-b55e-5b9f82cf2ff8	a2375bac-4a9f-4ed8-b674-a1807543c744	rxAEVWWVpNqMR7Yo8eCnRS5SIz9xpOm6FouibUcIda0	e1d505c71ec57f4bced17cd91267e4fc060b62a9155047f2f89cb46887ec5c90	f	2026-04-06 13:10:58.810993+00	2026-03-30 13:10:58.817212+00
672789c1-25b2-4453-b741-4399a64b1a6c	a2375bac-4a9f-4ed8-b674-a1807543c744	sp4hjImGfmcLywm4BBqk5_Z16Xwk_r4FVbxKfazlg4I	2ad81e4f8f59a4c6838a15dc73577f85f00c4b9a2b9abb53733926e14f027320	t	2026-04-06 13:07:30.014967+00	2026-03-30 13:07:30.015566+00
0fb68933-ea9a-4fb7-b1c6-2f8e73aad728	a2375bac-4a9f-4ed8-b674-a1807543c744	gWX7EeUU5cAyvlMj4KjW0JvK8MypxuvGqImVPgMjgys	80bb4e0254a896419f7b454a019abcda42ca2d240b726cb548106ea53762a4bf	t	2026-04-06 14:08:46.530948+00	2026-03-30 14:08:46.531614+00
d601f109-9739-496a-acbf-a6b1e0662dd6	a2375bac-4a9f-4ed8-b674-a1807543c744	BD8N0SbG2RYL05bo2KAeUvQ8w-kS_EDWrfhGVunLE3Y	d88b9a123d8ea9c12da304d5c7a094e4b559e5183af6245dbc4cdcb4be89f4e1	f	2026-04-06 13:14:50.2369+00	2026-03-30 13:14:50.23824+00
ebdd44a0-d633-4b41-81ec-37a72d3bfa76	a2375bac-4a9f-4ed8-b674-a1807543c744	OETeDzb7rsL76Muh4Ii_UbosQjwr4gYfXmtwe9IU6II	0a14d20d3fa90540e6dfd4327e3ee3b56f8d5b9a9a56f64783c515bd02fb9e2a	t	2026-04-06 13:10:58.836503+00	2026-03-30 13:10:58.83743+00
40254846-f9a7-421d-99d0-d89f97c03154	a2375bac-4a9f-4ed8-b674-a1807543c744	zwl3NYZxBsphNhm9HZmO9ET0uCUTJR7LZoSALafNd-4	6c45529670b7b62fbc3d36faed32376dbaa461b2eeb848e56fbfb9c7610d5907	f	2026-04-06 13:56:29.910874+00	2026-03-30 13:56:29.912427+00
ecbe1761-e272-408b-acbb-18c4407752ef	a2375bac-4a9f-4ed8-b674-a1807543c744	JPGQ_iscyoEFzHR_8sVNbpMsTDfWPkWIpcWcdMeCL4A	bd21cdf8e230c20926e677f1ee0540a86bb80098afbdcd3ba64f27b6731bd904	f	2026-04-06 13:14:51.017628+00	2026-03-30 13:14:51.018113+00
cc85bd7e-f456-4fdf-85b7-35b6e9c60abd	a2375bac-4a9f-4ed8-b674-a1807543c744	NkwIJKaOjxfRHj6PJ4MQO-P57g2u4hslnhzErRt40Bo	db2b97fd3ce6747f25339c897b61fbd5a37ce15e49261342ee4bb8e96d8962ef	t	2026-04-06 13:14:50.248799+00	2026-03-30 13:14:50.24943+00
169e12d4-73e8-41d7-b778-bbf269ee71ad	a2375bac-4a9f-4ed8-b674-a1807543c744	120AOdOjjePSj1ILd7FT_jBbf0VThZZMkA041E6KDR8	e9f5fcd73d03ca0553e6b76bb5bdaacee25732bbe6ed2100335047ba70890bdb	t	2026-04-06 13:55:11.148286+00	2026-03-30 13:55:11.149269+00
d48d99c8-2ca1-40da-87fa-6353ed981219	a2375bac-4a9f-4ed8-b674-a1807543c744	3baD4wroUCzIVuGQpJIrQeHZMGNbArTOC_hPIgh-wYk	cf04741b0fdc2822900bdb53c0b471d214a214291c62b47f3d0c29530c2dd8ca	f	2026-04-06 13:59:33.044335+00	2026-03-30 13:59:33.049445+00
bf8b762e-76b3-4402-933b-170867db5c8a	a2375bac-4a9f-4ed8-b674-a1807543c744	2zNFg8VluOEkQwYsXrPjG8m1lTo8PT8zzQjMerhGmiU	d42bfb657287fac10f7b89895c8bb3dde5dd7dc4d6b7b2e47f0b41aa37b17e3a	t	2026-04-06 13:56:29.923663+00	2026-03-30 13:56:29.924032+00
d9af6e41-09e4-438c-a127-1b947121a933	a2375bac-4a9f-4ed8-b674-a1807543c744	pEr7fcC_hg_kmLhX_SqyznoAyYc-8jLSCBUxUQJABkM	d68dfeec9aca30b7e612fc09045ccd5d7c546b7f70d917504e0ef06fc68c4f59	f	2026-04-06 14:08:46.499639+00	2026-03-30 14:08:46.504887+00
8cbf1c5d-6fdf-42aa-b4f0-396d98a8d668	a2375bac-4a9f-4ed8-b674-a1807543c744	h_Si8UvawX0RaaJwf9-mCPv8Ljda_uZI4IpOhiPdLto	807d71e1664f8117c28c1990b338d4edcf253162a2e9ffe8879ee1c86c15f353	t	2026-04-06 13:59:33.063814+00	2026-03-30 13:59:33.064184+00
18b2c2a2-87ce-4944-ac23-9d34ef91b103	a2375bac-4a9f-4ed8-b674-a1807543c744	y__ySakjDK5WFdQcsfetWkoAKyhTcN3AdlXjdue3VsA	565affbeef8c604fdacbc4ed0f74e9e6126b981c192774ff6a786bcb011ac9ec	f	2026-04-06 15:05:43.393431+00	2026-03-30 15:05:43.395011+00
5f560148-4a6f-43dc-ba5b-b8c81c81de91	a2375bac-4a9f-4ed8-b674-a1807543c744	rG2p--3UbR-c-o2lBwtDmlwrhqpoDZ_-5d4DFLAnio8	37632a8208e475da95a4152ad5d4e77271fe3c9f922b1efe45f87c89f6bb0979	t	2026-04-06 14:15:03.708823+00	2026-03-30 14:15:03.709169+00
a7518e6f-3c6d-40c7-ae0d-d2efdba127f9	a2375bac-4a9f-4ed8-b674-a1807543c744	XdrKGEBgVFmTZct8OcvIl4Bs2pmlX8Rv7rppKzRoiLA	b9a21548a068210cb7e9c258ee798b2c0d63f1242505fb5b318b5ec26fc44040	t	2026-04-06 15:12:50.115842+00	2026-03-30 15:12:50.119681+00
2e407686-6cb2-4a33-b3ca-f314b58e5fa6	a2375bac-4a9f-4ed8-b674-a1807543c744	ndDgcySmS6q1W46p5Qu7O0j6P3xlVRg3XTpvW57GSuw	f9ba2732453a35b2b809e23bddf004c2a010cca90a2902613b3fe9451d561493	f	2026-04-06 16:00:56.509308+00	2026-03-30 16:00:56.511105+00
4cb62ed5-e403-4a99-8865-b3f96e0e475f	a2375bac-4a9f-4ed8-b674-a1807543c744	CBSlINyL_5k2LbIUhJl8P4v1TOnhbNiZAdGz4jultfc	3a757183f9d2daecae9a27e98d3f6d730de273f85cdca39d22d9a161d8797339	t	2026-04-06 15:18:33.507723+00	2026-03-30 15:18:33.513982+00
61848019-768d-4016-8c39-9c1cb611c22e	a2375bac-4a9f-4ed8-b674-a1807543c744	qryl3lVPfi3JADq5_zXA1qn4KvobDRY6AdAE3H2x-Wk	98f21691886815fd5969fa8e27ebce838c580b04e1a097d9eab3e15ce4703baf	f	2026-04-07 08:43:34.359914+00	2026-03-31 08:43:34.374172+00
02833032-d988-4949-98c2-0a0691a69189	a2375bac-4a9f-4ed8-b674-a1807543c744	WWEU2yj9z5oXoCzTAdVuQyatFQjj_7g3e79GPaeiw4M	1629a854ac2f7d138b349c8e9ce917eb944688fc72f6d97911d6f3fed8f5c23c	t	2026-04-06 16:00:56.520154+00	2026-03-30 16:00:56.520519+00
b6b19b80-9e63-47f1-9dbf-dfaa3700016d	a2375bac-4a9f-4ed8-b674-a1807543c744	8CM0ZvTjrd2qDAtW7iahMRXicTo_TL7ytiatMGoVlIg	51c3f21a73376868916a68ddd2b37c83ec7b7dfdb719bd90fdbccc8843bfa3e7	t	2026-04-07 08:43:34.402151+00	2026-03-31 08:43:34.403062+00
a5323132-a1c5-4624-94a6-21cb5a690f71	a2375bac-4a9f-4ed8-b674-a1807543c744	pSuITjyB-SDqooNc81RT60o7WsI52zbVdzSIiyEptXE	cefd622d4a797ccd7e5c16f1b5ba6957062994f909fbaf9e758e44768f5a4b64	f	2026-04-07 08:52:04.142503+00	2026-03-31 08:52:04.146604+00
8b761dcc-acc5-422e-b343-bc51b604190f	a2375bac-4a9f-4ed8-b674-a1807543c744	QdPMGFQVwl3v7lMiOTuX_wk0W4oSCDnWWvwzNDSes2o	9fe1a3d140b3e3dbb378cd239136a8a0c62f224c1f3c04861a1fcf63f183ef41	t	2026-04-07 08:52:04.161381+00	2026-03-31 08:52:04.161688+00
2094f2f2-9dfa-44f7-8d9f-c95033e30d99	a2375bac-4a9f-4ed8-b674-a1807543c744	TA3WO4I_TzbOblFPIfBnHHLBuaZ7idZcbZ0y2QQ6E_Y	013a77f4ecc9bbb325f3fc91fccde41fe147f4d0710e9ec835955807e685af77	f	2026-04-07 09:09:49.853055+00	2026-03-31 09:09:49.854275+00
cd76b5f5-f536-428e-9b0b-c45ee75036fa	a2375bac-4a9f-4ed8-b674-a1807543c744	2tnneBpYbdvysAsJap4q1a7S-L39-Hc-mE9K7hFnZSM	e49e67250969be2f0712441a9899cf3e9037c61b3435ff1aae1e4a36a7a4844b	t	2026-04-07 08:55:47.527415+00	2026-03-31 08:55:47.528082+00
b00ff841-6519-419d-a920-8bc52463a092	a2375bac-4a9f-4ed8-b674-a1807543c744	k8GjhsvGy8ewgl8Wypx1OO7bGsPMBv3N13d6fyH9ND4	3d1b4024981b4d39ba038e3a7335c4be7772d73d5f7b3786a976e0ab9c91eaf6	f	2026-04-07 09:36:12.318665+00	2026-03-31 09:36:12.321162+00
5d14ee23-43b6-4416-a18e-a3c136cb7deb	a2375bac-4a9f-4ed8-b674-a1807543c744	coDXZBciiZzGuk0zDuNGDaUHUlgObrnfWbGYke6Yn0Y	73608f57bc1729cdab0b5e5cb2ea262783665aa321b279848da08a3a29c31158	t	2026-04-07 09:09:49.864258+00	2026-03-31 09:09:49.864647+00
00529790-fd8e-41cc-908c-ebda1759a6a4	a2375bac-4a9f-4ed8-b674-a1807543c744	OsadTbZ-9g-Y-47nOt-IB1mOcgMoaMJBQ9BfDaz-9Fc	c9480669b44645ebba781cc943e4c93e08e9350d8ddac3e8ed602d7559ba0d90	f	2026-04-07 10:02:54.536972+00	2026-03-31 10:02:54.538428+00
a177d06d-ed98-4395-8467-891b264073f3	a2375bac-4a9f-4ed8-b674-a1807543c744	qhneFw980x9A6b15sDWK4imlNg_u7VnuBA1a-p0j8NQ	bfb417e8c8436920f58b08936ff3e47be689b828608a0b729c083c34acb5ee6a	t	2026-04-07 09:36:12.340792+00	2026-03-31 09:36:12.341829+00
f2def482-f922-4d54-96ba-d6fa58b74f3b	a2375bac-4a9f-4ed8-b674-a1807543c744	t1NxK75WC3IijuKzs4FwgPznxDr3wbnLaSvrCvbfbSg	f7903f0eacec6a8a54b833794d45d794c1558ea9aa57c79ff25eb80ef5384dd9	f	2026-04-07 10:10:55.109221+00	2026-03-31 10:10:55.11023+00
4c21407b-2a3c-45ec-98fc-b3dab915fcb2	a2375bac-4a9f-4ed8-b674-a1807543c744	XzypmV1xSdWW-w4IHGCCjcKwWHpWex2_B9D_ieiiOgg	9c4e962f22ae39a71cae221804f3c3e3ebf244bd43ef8cd7b90e98d756683690	t	2026-04-07 10:02:54.554954+00	2026-03-31 10:02:54.556064+00
54276b41-bb30-42de-8fec-9a8d4766b5f5	a2375bac-4a9f-4ed8-b674-a1807543c744	1HAe3qYaEQ9d2GylbDqchIaEid6yuBfWNIAZa7h33pg	35adc7c7f29f813238ba9233c83bf219c1641b282501370e35ebc02f4a3cd852	t	2026-04-07 10:10:55.119386+00	2026-03-31 10:10:55.119764+00
fa2d08d4-82b7-4c25-b95e-90b9a9a75cdc	a2375bac-4a9f-4ed8-b674-a1807543c744	K6FNi5mr_n4zMK3ISbAlxEB02XEnqh0TztNxHnNPKCM	c3e566f6b8aa09ea13fceb405b43ff46cf08e3a61af504d0b8dfc01938e10b87	t	2026-04-07 10:32:31.595426+00	2026-03-31 10:32:31.600587+00
b7b58772-d9d9-4437-af46-864f7cf0a933	a2375bac-4a9f-4ed8-b674-a1807543c744	UDVOX3gaZiClSZUaEU5eyaWCgHsL3DmTPf9S5MmWo2E	193cd457707e770a78477f7128c6a55d3cd2dad5f0826c8a36443d5e4f6dab64	t	2026-04-07 10:37:44.336495+00	2026-03-31 10:37:44.337393+00
a937fd39-851d-4b17-8c0f-7490c4fe585a	a2375bac-4a9f-4ed8-b674-a1807543c744	BIVqBTHqBao0HKTxJxqiibNUHLHuazf6TVNYAYCJurw	4ef19d7d05fe2fa201b987c622f45de8d98f2bce805eed249514b7cf1e4acda5	f	2026-04-07 12:32:18.294661+00	2026-03-31 12:32:18.318455+00
d4110155-1d7f-4597-bed6-ec39809c9bb1	a2375bac-4a9f-4ed8-b674-a1807543c744	-lydS4B05cZKZuhYlLav6hnf-HI0OB0H6Z-G8oa_dys	6a15f0069495ac9fddafb1d8ddfd03c77acd7424154a11a04d50e204e7ebcd93	t	2026-04-07 11:32:04.8873+00	2026-03-31 11:32:04.995374+00
8c85d6ac-c81d-4bc0-8c52-b217faa274ab	a2375bac-4a9f-4ed8-b674-a1807543c744	nBl7DqpUWQq52bu2Zopa3WBRYJzNTiogduAeJPVu5D4	625127b2b6a128a3730afdb824ebf240bbb39067577fc080f73cb146c82d13c2	t	2026-04-07 12:32:18.353703+00	2026-03-31 12:32:18.35432+00
c5616147-ad5d-4e73-a64f-ffe9e3c7781d	a2375bac-4a9f-4ed8-b674-a1807543c744	ib2aPr9whbyU2p-8CQChfMr66hHRkSjkFGZEt-YtHas	c71ae1c473de3662b2e83e447408d6ea70abfd9f5b2d93278a81f5050954fca9	t	2026-04-07 12:35:41.797928+00	2026-03-31 12:35:41.888575+00
7a1a4680-42d1-4aad-89a5-0ca5e82c8844	a2375bac-4a9f-4ed8-b674-a1807543c744	KL3ZIbpCW0PwmaS2BRBiRueaV5yQuvDon_wNOlrLX_8	eb37cb519540661130d2f868f281b0679fb2de387dcc69956b212f42ef6c5fe0	t	2026-04-07 12:36:08.310326+00	2026-03-31 12:36:08.313828+00
4d784bc9-2b38-4518-a426-ceef458352e5	a2375bac-4a9f-4ed8-b674-a1807543c744	9ji_ZXKK9tcroVKGwdeMQCaTaCkdLl2_AjvWzyfjoMY	66f045a1840c6defe8f4e33ff7dc566fd05d9696e24b78501bb3a3c4bab3d0b8	f	2026-04-07 13:37:59.50753+00	2026-03-31 13:37:59.509856+00
e6b19578-30e4-404a-97d1-f2d413f2b639	a2375bac-4a9f-4ed8-b674-a1807543c744	vFQwJNclQiaB4ztKkIjVuvyoO6l12ZZ5BxT9ZsJvus8	bc2a0dc2776bcf08d06bdb19066bc60ceed51e74f68b5a372e4a733be56360c5	t	2026-04-07 13:40:05.928132+00	2026-03-31 13:40:05.965979+00
d05b3011-5b3c-4f98-81f5-6ffe664dca03	a2375bac-4a9f-4ed8-b674-a1807543c744	_TzIr6_9lrGU8o6YXhyIOvdB_I68pxjhnpPep2CNTac	cd420c8165973afc7c5b493eb83febdeb17c39dede25e10ac72ba0d36ffc94bd	t	2026-04-09 15:28:13.284427+00	2026-04-02 15:28:13.295958+00
288615be-b0bf-4672-8ade-adcfa6fe1575	a2375bac-4a9f-4ed8-b674-a1807543c744	Z3GqNO5ivKi1n3RH_ebRYYiuNZMKKmDI-KDxrUzy4fw	4dd2420585176dc00c7a0acff733574548805c4853e9af0378d4c8105f58ceed	t	2026-04-07 13:45:51.784013+00	2026-03-31 13:45:51.785369+00
dd55bcca-0664-41d8-818c-230695a0b8f7	a2375bac-4a9f-4ed8-b674-a1807543c744	FVx8ksRA8kUE5fTKep9dzoyoTYi26g0gh2nvVg1xp6s	cc038f76f5a68f961e886d7e0af2dd511c29bfee6dbe0e5022a02375ac4d45b0	t	2026-04-07 13:53:06.902252+00	2026-03-31 13:53:06.90407+00
417a425c-6d43-4dfd-bb1d-6f70e9301128	a2375bac-4a9f-4ed8-b674-a1807543c744	MnMm_QA-s6uRJ0opYMo1HCQv3yMcGlbetxUNiFFqbKM	67d93fa15fed880f41e89a3b9bd88c98ae97214d808d2231becc3a4c91a61a78	t	2026-04-07 14:01:36.469563+00	2026-03-31 14:01:36.495704+00
e2941062-dc19-42c7-b5cb-f8d42079df77	a2375bac-4a9f-4ed8-b674-a1807543c744	3lZ-7hfL75XGrNDQ456IIam6RD65avA4SoJiNRc5S9k	57be8d5c8643e1343da39ef8f746bd681f1d4dc5b50076e83bc09789eee90be5	f	2026-04-10 08:34:37.328778+00	2026-04-03 08:34:37.361136+00
db2592af-8d3c-468c-b050-9525e8ee370d	a2375bac-4a9f-4ed8-b674-a1807543c744	E5rgWy99ehmii5PCHi5_A15fkIdpl-o-vbdCiD3n3kU	61e377e89e533f8b57c223cede0d658984036163dc0068689b71b5f885663643	t	2026-04-07 14:01:38.308304+00	2026-03-31 14:01:38.308778+00
41102620-27e4-49fa-9053-6c0d863aaf19	a2375bac-4a9f-4ed8-b674-a1807543c744	x5uL0fIb-7oH-Ax55lKnPDalHHPwGId2th9WqbO3Ync	b87750aa47d6f138dde6fd6ff5d5dda5cc3aebdc19f80697ac28813f00893456	f	2026-04-07 14:03:14.495594+00	2026-03-31 14:03:14.508223+00
538bcab8-bc76-4178-a1ce-c83b7eec8b84	a2375bac-4a9f-4ed8-b674-a1807543c744	NQW8Ipqe8oLhscCReFJpO3J46VXmuEcgp6MKBQUCCT8	7e416dc826cbbd5af9e9e047dfe6a9bd2515cdf8aa2932669f496f228f55d724	f	2026-04-07 14:26:11.470963+00	2026-03-31 14:26:11.480564+00
299b66cf-daca-48f7-bfb9-6584def0ffca	a2375bac-4a9f-4ed8-b674-a1807543c744	HhxJ2eZ6AJtwhDP0F2Lu11xIG754MUTZvo2fqKQUm9w	1da02acaaeacc7fafcdb6b5ffa32f04a799a71b14ceac3dc3817f1449f799262	f	2026-04-07 14:28:46.411451+00	2026-03-31 14:28:46.431144+00
8980d9cc-63bd-4b00-882d-ea43ed542485	a2375bac-4a9f-4ed8-b674-a1807543c744	k5zuP7DRY2UkCEzOUFCo26Lg-2SyNp4kLUlAGZRcwiY	a615c3fb87ca1e5eb439a4d2fee3d70137fab3eb8cf34e4e49d3b1fc98a88f21	t	2026-04-10 09:50:58.064507+00	2026-04-03 09:50:58.072477+00
fe21dfb8-c74d-4fee-b6c2-16b10e64298e	a2375bac-4a9f-4ed8-b674-a1807543c744	H3ognA3Kwrw3tWp67fSlyEtDGJAih9jXoXDLCe4oSd4	07601c4c113b16a17d59627bc8660e8a06701347ed8ff794c81441b976784af8	f	2026-04-07 14:49:26.700425+00	2026-03-31 14:49:26.723486+00
62b44f04-66e9-4968-aafe-d497c738f63c	a2375bac-4a9f-4ed8-b674-a1807543c744	GfVUQzMwH_VZTW3-hQZe588Nrm5jsh15JT4u6rKPN4M	05b03f123210501acb66a34393b2c2a83dcd8752cfcdc0cd5de31763fa9fc831	t	2026-04-07 14:42:37.96499+00	2026-03-31 14:42:37.982859+00
ac911792-1f6c-4a23-ba4a-fe37af9c3d95	a2375bac-4a9f-4ed8-b674-a1807543c744	myXAxbzKHqF6b5I_BC3SHQp3pUlyFO6xwaQdsU3UiHc	868cbc9b2ce1b08838fc366ec92d92a4c686fe4ae418574015f94e1936ceb44e	f	2026-04-07 14:58:30.721706+00	2026-03-31 14:58:30.724606+00
caec38fb-9c4b-44b9-8cb1-0e2b2886c294	a2375bac-4a9f-4ed8-b674-a1807543c744	d-M7-neU38IBN-AyD-t9PWlBmxP5tK4wnnWg7k0eE1U	8769f549fb95a47945e42747dc1498d66a86cfaf78ae7298cae0a3631450fecf	f	2026-04-07 15:26:51.552587+00	2026-03-31 15:26:51.582094+00
8740407c-1271-4085-9ece-9534f7f87878	a2375bac-4a9f-4ed8-b674-a1807543c744	0fJaFApq_5BMKP26QI0yz5kKP9h97gpziC-o4Hrs_7I	d3996f111bf33bb1ddf55907d5b668cc9af4172668b0f8cb42521512e4e5ef11	t	2026-04-07 15:46:54.056171+00	2026-03-31 15:46:54.091093+00
fd749d86-f692-48fd-96b5-8aaa9309936e	a2375bac-4a9f-4ed8-b674-a1807543c744	uHSrdoZfzBxl6O33CY1Qp7M3Kaq6IlszKCTP5qPdlps	ac5e1961311ce4588ffc9ceeaf85586aae4869e9965bda544b5a8f82befdffa8	f	2026-04-09 08:24:43.869445+00	2026-04-02 08:24:43.877485+00
0a36fc27-f65e-46bd-94fe-b1dcc11c2dba	a2375bac-4a9f-4ed8-b674-a1807543c744	v2F55aTBp9CAu9Tri_AW9W0EJ0A79iASBHGLMrcOr84	c742ea6bace991c07ec0244967c33d0940ac9554cc3186201d07fd0c9a8a27dc	t	2026-04-09 08:39:50.169141+00	2026-04-02 08:39:50.177448+00
3cedfc20-5fdf-459f-a649-e68226e01fa8	a2375bac-4a9f-4ed8-b674-a1807543c744	1xq202efHFQdERj280EshR6zsLJzcxYtRIIdAchV57Y	226e1aab521500d4a824d670655238a8e0f6a110b5188ee2c7e05250d03dc8a9	f	2026-04-09 09:59:30.205843+00	2026-04-02 09:59:30.213275+00
fa36ab75-7df9-4fda-9c94-a7345be7630a	a2375bac-4a9f-4ed8-b674-a1807543c744	UQioSMSnQe7oedVGK2M5KNa13wszTGNro2_wlI05l7M	d0c226f502b81cdd3c80b089f9bea123310af29ae059dce5d1b9e061f713cdb4	t	2026-04-09 11:20:13.056095+00	2026-04-02 11:20:13.061942+00
d32e3db2-c91a-4bd0-a286-a5f6661674ad	a2375bac-4a9f-4ed8-b674-a1807543c744	qYAWKwMHeQyBBFbSCXB89WUFfKDMUbRtBsDkUf8Vufo	88c4b8a50ffa7a8aeffbd3697ed00750ecee3bee1bc2d8b5332305737f7a57b2	t	2026-04-09 12:18:13.334638+00	2026-04-02 12:18:13.350348+00
5d758933-09d0-469c-b3ef-9a65a31b2650	a2375bac-4a9f-4ed8-b674-a1807543c744	zwZKsIChkXQjMScB9OYppKnQn06dX3zVkQxXwl7L1HA	3c75da15173fd8442c7c5297c3dae54298f70a56fc2901f83b882e4b4871365b	f	2026-04-09 12:38:12.916801+00	2026-04-02 12:38:12.933509+00
6e378589-6730-4077-a7bd-8ea3d700f9b0	a2375bac-4a9f-4ed8-b674-a1807543c744	zukNwNfrhEPeT8fUdDSdaHBa0J6YhXa3vrbB-Hb6ZIY	1ed618c8a30060b481f1ba9271b3cfa05b720480d6887356e2399f17fdf04d2f	t	2026-04-09 13:13:12.669961+00	2026-04-02 13:13:12.675052+00
c1e51d91-bc87-4baa-af67-552c7867e6ec	a2375bac-4a9f-4ed8-b674-a1807543c744	HjPBL0yzd800oCK2p7nT_zvstXBoMMnKmeto3A2xB7Y	cb7a2213fd1666e847ccbe8175edd2934af7b99a6b73483c1d5e5c0641ffbfae	t	2026-04-09 14:15:12.78079+00	2026-04-02 14:15:12.816954+00
d34eb971-6554-4fb4-8f48-a00b21e9c486	a2375bac-4a9f-4ed8-b674-a1807543c744	10cheRRID3iEUOhVjmyHFoyl8HM_qWAG-b8yJsRZVqU	d1635897943458916c4380eed849894cb531784b0f40a20a97ea519782aae087	t	2026-04-10 12:43:22.931756+00	2026-04-03 12:43:22.942351+00
6a0dbf31-42b6-4f2a-b72d-642467bba0e4	a2375bac-4a9f-4ed8-b674-a1807543c744	rx-NxsxUdCI3rIgcv_e_snD1xQxl3kWJEEHvqU2ON5M	a167c55d48f67c7b2dd9f5e78191d84abee56eb9cd27e4eee2cf61cd6d145a89	f	2026-04-10 12:43:25.368034+00	2026-04-03 12:43:25.368378+00
adeae821-ce9f-45ab-928a-e8972d720974	a2375bac-4a9f-4ed8-b674-a1807543c744	fU_eYN1Sm0YdWyG2jvMc8WuRJPQNwf47IkSiun4Knro	edf69d5901711561372d00ff31587acc186a040b33c1ae12d71c90fe858a3077	t	2026-04-10 12:43:26.417446+00	2026-04-03 12:43:26.41794+00
f73c44b2-db13-4b54-9302-a279ab867126	a2375bac-4a9f-4ed8-b674-a1807543c744	b8UbV-57afigusO4VHOY2EBdPtiBoUrPKGBM4cLhJe0	da04adbc02dc57a755d2dcff325c8c494cbd83f79d68f695a9b46ceea72b27ad	t	2026-04-10 12:43:27.121646+00	2026-04-03 12:43:27.121997+00
00a329ad-6057-49ef-ad7e-157fcabd5cff	a2375bac-4a9f-4ed8-b674-a1807543c744	YlqNQsSU0Wm8at1Z-YlS_uIxHIClwRR-AeQNgkY3YZg	f7cf90dc3878eb14683e6944bdd92ea61f42c1193526b536315d9805bed1cab9	t	2026-04-10 12:43:48.656704+00	2026-04-03 12:43:48.657217+00
84d5b02e-ab96-4050-aa3e-85ecdd0ad48b	a2375bac-4a9f-4ed8-b674-a1807543c744	7pVpSjh_LinP0qCiHIAH-lxAqe_YvE3XHH5aI2qhTeg	275a660fabc2bb01065310bbade07935e2e30579d292dc40b1b1dd4f2a834802	t	2026-04-13 16:17:55.438644+00	2026-04-06 16:17:55.440876+00
bb69da06-8bf5-42f7-a984-2e7086b077b9	a2375bac-4a9f-4ed8-b674-a1807543c744	tnZtstXpfeEgszmS966uV926XdbK2czAkz2urtb2Ljc	804572ceca2f23c25473e78257788474883b0bb048080fc39c89974966bffabb	t	2026-04-10 13:36:30.788561+00	2026-04-03 13:36:30.798392+00
66da4e0e-226f-4534-ae2a-8d6f2755f39b	a2375bac-4a9f-4ed8-b674-a1807543c744	SOgoijXdBIPS029TngbXQ3ToCX7UJPOvlbKkaqiWjwY	1e8a7ef69d305bf2ea8f8ca6415a3b867d6bd129802728b60cd299f90018b2ea	f	2026-04-13 16:16:47.489995+00	2026-04-06 16:16:47.530093+00
0b78773e-73e2-4583-991e-faff5ea5bfdd	a2375bac-4a9f-4ed8-b674-a1807543c744	IXM3Y4LRbd4i5b3ss_WoOF5sFFwzcr7G-v89vJg0FKs	2d2aa78b5467e46c59e2af3011695054b9988163eba8eb96180b3e1212333e38	f	2026-04-13 16:54:00.085022+00	2026-04-06 16:54:00.144907+00
3eede409-8039-46dd-91b5-4ecb327cca4e	a2375bac-4a9f-4ed8-b674-a1807543c744	U7XsI2bKSo9Y8jid3xbGUktRf0IBBbzJWzM5dHtWGFM	593800a9e28194e063c2d81d2a8d2528d6a2f9f5a41e65b7be238e4270177aaf	t	2026-04-15 12:48:37.505389+00	2026-04-08 12:48:37.522946+00
5d21fad1-0445-4709-96d1-4e8efda61dec	a2375bac-4a9f-4ed8-b674-a1807543c744	9JSbmTv-7IhXko4RwbNmuOAgM0FEGXVpOgBxcjFm3x4	8ed5206108a5ad96d6d427371e453458468e694cc46185c82f7be3d276c87041	f	2026-04-15 14:02:19.3198+00	2026-04-08 14:02:19.323714+00
1a139805-1784-4cc1-b52c-637b21a815ee	a2375bac-4a9f-4ed8-b674-a1807543c744	5OIriLGi_8iU6P7QMBjnzyUkVfF4duNaZopCyyNPxu0	fbfe93d18aa43e09e818b5fdb4b2b00aa8bdcae327b3cedcecafd94c393c6ce3	t	2026-04-15 14:06:06.652811+00	2026-04-08 14:06:06.653239+00
d960a3bd-9018-47e9-a135-563a7a64c776	a2375bac-4a9f-4ed8-b674-a1807543c744	aYJ1zMAX_WL3Nj3lQZMWeE9SXkOXBiRcQwYK3XByHRs	c9333e71681960685735c277a8a907e8ee671a9222389828f6efdcf725163649	t	2026-04-15 15:26:48.754201+00	2026-04-08 15:26:48.76169+00
d64d0678-df7d-4df9-bbb1-5fb9cc0f888e	a2375bac-4a9f-4ed8-b674-a1807543c744	daaoBBmCE6i0abA3PjgxzPkhd0R2PoPBgF7XW6R2GMc	d101e49581f61e2f375593a4565cb704ba35c62aaba836b66b90cf791b43912e	t	2026-04-15 17:06:48.794351+00	2026-04-08 17:06:48.804546+00
337f1804-3146-4ae7-978a-04c7c69ff9e7	a2375bac-4a9f-4ed8-b674-a1807543c744	SwUnoezSHpQbPb27WJRvWe3ryDuBwml7GValZjMcxls	42b4f1e01f5fd6949930d97dafacda3bf7e88134f7bef2f93c8d56d23eadf211	t	2026-04-15 17:46:48.592686+00	2026-04-08 17:46:48.602701+00
ff71d7cf-20cb-445b-ae9e-9d6bb9a202a2	a2375bac-4a9f-4ed8-b674-a1807543c744	8fQ46Mfpwu0dSBTOnylcCetc9RdtlN3Yz_DpYGE_CT4	df4c2186314289269dc27e644b8e67469ee9ec89cd74274bcfa516e826131374	t	2026-04-15 18:06:48.522701+00	2026-04-08 18:06:48.529623+00
2d37a9c4-4faa-4ef2-99a9-049f89ce98d7	a2375bac-4a9f-4ed8-b674-a1807543c744	sAY-lSntXEYcAbzfcQ9y1zx9n3opLMLuAvCP0On_dUQ	927d47a1073b5866aa5013e3b74a7aad062a79e61b8f398992bada4e87558aab	f	2026-04-07 13:37:59.529351+00	2026-03-31 13:37:59.531224+00
9f1f5bea-56f5-40ca-875a-5b277293aaf3	a2375bac-4a9f-4ed8-b674-a1807543c744	U9AwXy--UcMFrvcLaI-Lq4xnIkMfcBDZXV14EFhmBT0	8095c5a9f7b742ac45adec65c110bc42a1ec12990e184b94b5c36e1951925793	t	2026-04-15 14:26:09.053136+00	2026-04-08 14:26:09.073687+00
e3b99a47-935b-4d31-87d7-fc73821aae47	a2375bac-4a9f-4ed8-b674-a1807543c744	YpUm5tFwOZ2K8LLolVsmd-9-RR6X1x2RfAGPWMj1xvc	3d3ae2887b51d6e254662b4ee863d2dfbbf7cc03a423de1c1df266bbcfebab51	f	2026-04-07 13:45:49.468757+00	2026-03-31 13:45:49.470052+00
360eeac2-087a-4af8-a295-59c2acf8d8c9	a2375bac-4a9f-4ed8-b674-a1807543c744	eqFrPvts1WEVi8Bnr2sIAy-hQK2gdmTtxxQplcljEvQ	07523a8cae07be1a0f1e6931fba9de5614a2e5d0a5f94cd68a59f2bf7d9ad10d	t	2026-04-07 13:45:47.410349+00	2026-03-31 13:45:47.4246+00
6862de09-396e-41a3-9f4e-d21fe1454b1e	a2375bac-4a9f-4ed8-b674-a1807543c744	fqucYxs8RcS8XWaX4EK_J8wOSQe4LS6KO92pep8gPlI	2a6018db0bcd30c0f4067aa4b32dd01f4c72ba51c5835fe18860f7b34c810317	f	2026-04-07 13:45:50.498632+00	2026-03-31 13:45:50.499707+00
4e7ffacc-3075-4cd4-9a82-2e18903d3221	a2375bac-4a9f-4ed8-b674-a1807543c744	mRlzBY4IsQHuZH8XoHXNH6xcuujFRxB7JeK09XDunIw	5263153c4843a3f38ed0948b37f8b044b9b39b7324bacf058bd88e0c8db816dc	f	2026-04-07 13:48:58.458646+00	2026-03-31 13:48:58.460348+00
c2399d0d-5435-4c1c-87fb-5733e553203e	a2375bac-4a9f-4ed8-b674-a1807543c744	hNW7ix9O1fl66AY7TbUYFHVJoK6iRl6_r7RkmFp61LI	cbc88b18b21b15d06c8cee451db9637fe96935b402291096c1652419d468d690	f	2026-04-07 14:01:39.173143+00	2026-03-31 14:01:39.232757+00
3da6363e-56b5-47df-b404-1181a09c1248	a2375bac-4a9f-4ed8-b674-a1807543c744	7f8hUcl0XZX-TVvsZYNhU8YiIiQbAXU3sg5o-1eC8Co	dc963cb3cae97a7b3f437371a5d9246ee723dad22aca67fdad442046579186a0	t	2026-04-10 08:34:37.441351+00	2026-04-03 08:34:37.464775+00
265f9777-371e-48b5-9e22-d73c065afc34	a2375bac-4a9f-4ed8-b674-a1807543c744	9gbix8zHOZmF-FMP3SbaSkKMJm5IQ-yRNTMSmTOzOWU	4cf83cc08eb5cae6eeae270887da0158e031a7cd40d05368fe235d76f0b50307	t	2026-04-07 14:03:14.538711+00	2026-03-31 14:03:14.548031+00
244f5d27-b6d0-4d17-8e56-e74a1887ad8a	a2375bac-4a9f-4ed8-b674-a1807543c744	jHexCRK3chbr2aWUfWj7LoaNTbmODocI2h1QovoWSsI	d265f52fd2bfec3642ea58ae88e2f42a375b4a9eaf189eed46b70e361f67c33d	t	2026-04-07 14:26:11.529523+00	2026-03-31 14:26:11.547736+00
e2628d7d-33e8-46f8-9738-791fa601a599	a2375bac-4a9f-4ed8-b674-a1807543c744	tBWN7voATPYeak4wsxeX1tt3wS5ROjoQVxCgaIsPIdo	267413fb68c2f9e10710e333b289dc8cf2f354bd0a681a2e87abb40b70697051	t	2026-04-07 14:49:26.807137+00	2026-03-31 14:49:26.894818+00
a5e1983a-e597-4d71-b2a6-78e90dd02155	a2375bac-4a9f-4ed8-b674-a1807543c744	0w-AqEjV769KoO7sBuKfQu6_UZdKqpoREsXLY-UPPUI	47b0806d77b9256ec19117dcfc95b90815bdc6f0bee507b4d2ffd14c5fc1d3dd	t	2026-04-07 14:58:30.751309+00	2026-03-31 14:58:30.754213+00
29957411-38a1-4163-93ab-dac72e58054d	a2375bac-4a9f-4ed8-b674-a1807543c744	0yImQ9D1IaTecfGPEISBwvzvKfbbGJ1aYTalMTHyI4M	b6c141bf48ab0997c8df5e1c01bff619d3817478cb99de6ece19947ffb847e01	f	2026-04-07 15:21:49.55324+00	2026-03-31 15:21:49.576778+00
9051d45e-e484-417d-81de-4c49eb2035d3	a2375bac-4a9f-4ed8-b674-a1807543c744	u39I-9GVq0sFIKmkUlXDB6U3swxoBJaMMkeMzlfjDlc	39445d41c0aa18da519683096a1b2472a1e1716a68a2d79acb6e0df64bde4bf3	t	2026-04-07 15:26:51.666233+00	2026-03-31 15:26:51.728176+00
9f164ca9-be0a-405f-b57f-48ffbb7feecb	a2375bac-4a9f-4ed8-b674-a1807543c744	Ch3yaZA_bPftS5bhUrr-1IQcRgXRTqxPobXWChC_RAU	0d4f8059d976bd97eaf5e9ec3d37c4c23bfd47978be40b14cae124f3888a8675	t	2026-04-10 10:07:04.140824+00	2026-04-03 10:07:04.147894+00
4b394ccf-6e14-4e60-86c5-55ad5ed4261a	a2375bac-4a9f-4ed8-b674-a1807543c744	MI2uvPCFURAlYA3vtj__YxXKzWkMOVO8sKHrRwybB_8	2fef6fd1fcb460a7fed9ef1f3eed7486c84a4b3e0be9a452e6f802e7ad0be915	t	2026-04-07 16:07:27.148347+00	2026-03-31 16:07:27.173214+00
bdc71adb-5cf0-47e2-bdf2-140435c5b878	a2375bac-4a9f-4ed8-b674-a1807543c744	lBtGi02tLOoExBrC_QiL7tdvn7YW5bapfPIsjw9Cc_E	07c1281575e0b10f4c32136f82fdabae504babb21dc32e88b3c53016d38a3a15	t	2026-04-09 08:24:43.896289+00	2026-04-02 08:24:43.904298+00
026c563d-419b-4830-a5f2-c0782651d5e3	a2375bac-4a9f-4ed8-b674-a1807543c744	7C-glYVtwdNoG4s0EFU_hwE1ga89EG9lrNJrDTpHcKk	59a3cad69e900e9e30b44648f3171297b9bbf960e251c411de8e06e2df09e267	t	2026-04-09 08:27:40.785823+00	2026-04-02 08:27:40.794962+00
7e9e468c-c616-469a-b08f-b285d288356a	a2375bac-4a9f-4ed8-b674-a1807543c744	IZjKCeeTEZgCON-J8fAVf38AoL97mx2DQPvHXJKoxvE	1f0b068180626f8a351f14c96f6811d684e9afe3fa438dd06f4021e41eaeb905	t	2026-04-09 08:59:51.826055+00	2026-04-02 08:59:51.853916+00
fd18a060-0969-4762-9fc3-0dfa84167fd9	a2375bac-4a9f-4ed8-b674-a1807543c744	K0vsCJKZF1xCP3iaTZnj8hpVDW_WHVQTu8cDHpE4tzQ	2247921e204e808c8879d71dd0189199289539644efcefa3110810851dd7c25d	t	2026-04-10 14:01:47.45061+00	2026-04-03 14:01:47.536269+00
1bc0c711-2222-4352-a49b-6febecb4b644	a2375bac-4a9f-4ed8-b674-a1807543c744	o_2YvnGTsVlS0uKPu6cJBHQ8jWOcm2u8GB_ZytRlol0	297c2e822e30bbfd4d5a5cfec0def1109e46c2658d504f3fcc34622f92689045	t	2026-04-09 09:20:12.838429+00	2026-04-02 09:20:12.852608+00
dce5196c-bd43-4cb4-9fe7-bf797e04631f	a2375bac-4a9f-4ed8-b674-a1807543c744	qExwrMDWU_XhI1Im7YBHw4n-4iSboh2xnKMtbxYaLN0	7f897ea729b6e23c22225d5954d571ed59f38b8cccba78b388c7eb27c2075ec0	t	2026-04-09 09:59:30.233907+00	2026-04-02 09:59:30.241026+00
e1bcc8be-c6e2-45ea-a578-cdbd1f7c7dd9	a2375bac-4a9f-4ed8-b674-a1807543c744	yRz1Tz8d_oPaCDyee-QZQso7JCx0MLjv2LQ02fxUFx0	8262219c2a7866deeddbf78e2f55f4ed9ea3db1253ef09335cbe1800636141ed	f	2026-04-09 12:38:12.989343+00	2026-04-02 12:38:12.990077+00
13f511f9-55c3-4d64-849b-9f35e0f40aa5	a2375bac-4a9f-4ed8-b674-a1807543c744	m39-wzk0Cl3GCSgb50sJeyhCaJfi0hWAyPCGTQSS67k	8cfcde91fcad196e42c5c9ab5cc9f860cd675b7fff805b0d46d6caeb0c7a5552	t	2026-04-09 14:13:13.408146+00	2026-04-02 14:13:13.426952+00
fcf53566-d553-43f4-8f8a-e3ba96916e12	a2375bac-4a9f-4ed8-b674-a1807543c744	N4GoEL-zpKCRZgUHiaBA6TckbqvNg6rlkpv2sl1S-OE	e96e228c60c1c5f9afe6b18651bf4e06adf9a8d3a5986cda0cb0697623574416	f	2026-04-09 14:33:13.637021+00	2026-04-02 14:33:13.658148+00
81c0835d-91ce-4e22-a4f3-05d9d3cade44	a2375bac-4a9f-4ed8-b674-a1807543c744	KebDBvV7aZ0_YCpxNRlqvM5a-tBQFIWRHyy1n-4q0KA	2319bc6c9b2ec34a9013a15d9b380ee43d3e8a3ea463a924749f671339da36b7	t	2026-04-10 14:22:11.596269+00	2026-04-03 14:22:11.62996+00
b9ad230b-63d3-483e-a6d3-cfd30c81e071	a2375bac-4a9f-4ed8-b674-a1807543c744	WWjA8RYe-wfBVLWLmGDHd8IcLaCilSoTxerkQAhdpbc	a4c5112baf21f09cf8ff5a8a68c7fea57993e275d029eb841347e43ecbbe24dd	t	2026-04-10 14:42:12.011897+00	2026-04-03 14:42:12.032315+00
06211fdf-0f43-422a-8666-bfbe7217c263	a2375bac-4a9f-4ed8-b674-a1807543c744	PaQnB6j3uUW0Yt4EWSXiHe_NdfGSwEMaibtiMNaBMQE	e6ed0d8ab76c008bb9aa6c4b2db8e7016b77de90c0acc5102269a4b02e3aa7f6	t	2026-04-15 12:29:11.454218+00	2026-04-08 12:29:11.457568+00
6861e3cf-b994-4b08-89b6-dbf2513a162b	a2375bac-4a9f-4ed8-b674-a1807543c744	ztuFgapm52G00QjURzFcGi8ZSLPmmJOD1ZXHX12b61s	c92f046847362061045bf0535b92d8b5f0cb262b62052263c0cfa492fc3627b2	t	2026-04-13 16:16:47.622347+00	2026-04-06 16:16:47.650396+00
4b3eab5b-1321-4430-92f1-07e1fcb6307e	a2375bac-4a9f-4ed8-b674-a1807543c744	oryxRVRi2yWzQ1GhUF5TekOFW17G86nyQrTQfo9o6oU	72338d0aa973af40515329bf19ea3ab6b8e8e69b1b29cba01d9692efd7aea6bc	t	2026-04-13 16:37:58.703579+00	2026-04-06 16:37:58.720651+00
0eb818ee-2baa-4a47-8e07-196f2ed195ca	a2375bac-4a9f-4ed8-b674-a1807543c744	ffKNkzHdPu2oNobiFqyatDIXhH8Fg7O9hk1DSgMOs-c	da48de311a11258c25a5b279d89afa3daf676aecbb78be371cca9a59990c5af9	t	2026-04-15 13:08:40.023935+00	2026-04-08 13:08:40.036221+00
82da72ba-15c4-479b-9c65-052831a32cd2	a2375bac-4a9f-4ed8-b674-a1807543c744	l5edk6pHGHcgEd8LQuJIfncTYnuDto-hMg7gvcE7MsE	dc0e38e0b0e5cef36e3fe21e4d676351b993fb501cb16fe416117a0b3fe31c4c	t	2026-04-15 13:28:49.167942+00	2026-04-08 13:28:49.196241+00
6a0b2691-a00a-4d00-859c-1fbd315bd43d	a2375bac-4a9f-4ed8-b674-a1807543c744	JTj5a8VwVM5vPdCxn0pmmOobmo_08BIvVyukjzAalP0	9e65793e011e57e099d808022f47e176914f05d3ab70e7f6404dc423245b6546	t	2026-04-15 14:02:19.34726+00	2026-04-08 14:02:19.350324+00
d85affec-2452-41c2-af4f-7d901462a774	a2375bac-4a9f-4ed8-b674-a1807543c744	qKtymy_YPHwQ_5e3IH1CjPDOTpfaTUlaSL6XwQfwFpE	92557daa84ddddd8711dabeaef99d92d6ec8d3d890956e75eb06db9a66017bcc	t	2026-04-15 14:46:40.720421+00	2026-04-08 14:46:40.735792+00
362c8c2e-573f-4f5c-8a4c-283e1be6ee8f	a2375bac-4a9f-4ed8-b674-a1807543c744	7KXN8059bapteu8jAZWTWFYYMBQ4gXB4lK9FZz16hO8	3c144adf49258e7c3bf51093c72076d34fa6793404ca44fdc1a214135bbefd88	t	2026-04-15 15:46:48.86199+00	2026-04-08 15:46:48.884512+00
c2be73f3-a6ca-483b-814b-128d1aba81a9	a2375bac-4a9f-4ed8-b674-a1807543c744	g1TamgvPBmRtQFCFxa7nsfQA4am2eDd0RHUkdgxV82A	17ed472cdb02cc1276f107562158643bbe8d5a50fe3319e0f54110c17a4c6b52	t	2026-04-15 16:06:49.077623+00	2026-04-08 16:06:49.092971+00
f9f1940f-4126-488c-8763-fedb7a0b4510	a2375bac-4a9f-4ed8-b674-a1807543c744	nSwYpn22UNufx86uPjBnKZGxeBHlnjgeNnbK1D-lZtw	16d74028bc81e88b78ffdf89b6036948bcee2c2a456fe9c5d2675f22de022908	t	2026-04-15 19:26:48.480925+00	2026-04-08 19:26:48.488981+00
7d977c14-ecd0-442f-a5ce-f51f5a199fb1	a2375bac-4a9f-4ed8-b674-a1807543c744	bzTEjlb7ro6--zNXLPv980nHWDYQvFeu9XsvASFJrq0	c9b77f98dd5a05bbbd65a923130c5fce3f2646c36d3ec30dcad207dccc600506	t	2026-04-15 20:06:48.379664+00	2026-04-08 20:06:48.386267+00
6cf6cb42-d524-4999-a55c-895dd22cc9fe	a2375bac-4a9f-4ed8-b674-a1807543c744	FXOj-dpFuIXrMYo6QZHv5OC-YJws2osLrCotQdTweZ0	6db7c7c45a16739600835bf113fb6b9cc12338a3a73d2fc7a3d4388b2583813a	t	2026-04-15 20:46:48.454555+00	2026-04-08 20:46:48.4618+00
03709d09-0935-4616-a1ef-25b3d86652df	a2375bac-4a9f-4ed8-b674-a1807543c744	R4O3r1fTg7ecVlblU85vxnzHxig1nYz26M66QL0rcmI	64628458b5566c2861925a768a00a2d02ace3c8715836892fd4a3fbe0ed962b4	t	2026-04-15 21:06:48.453713+00	2026-04-08 21:06:48.465362+00
5795fa54-e0e9-4d81-ad4d-178661c89608	a2375bac-4a9f-4ed8-b674-a1807543c744	CZytuXTIeAD4mJdFhjQrAlG3LLUjngI2rxbV3FfI55Q	5c47f1a0d980828a301875aaad0251f146e24ad4fbcff0c6525439488647c254	t	2026-04-15 21:26:48.385875+00	2026-04-08 21:26:48.403088+00
276a3bb1-b209-4cdf-9ec7-65640b7c5f11	a2375bac-4a9f-4ed8-b674-a1807543c744	gel_TZi_FCbs_xhi-vqYGJG8waKgt41XBiEPGE7kXUQ	a500f4b5e74849b4810c7717d6bac5867ee9c160079c1bf05341c43025b1eb21	f	2026-04-07 13:37:59.542946+00	2026-03-31 13:37:59.543378+00
5bdfb233-af7d-4bd5-b7e7-fb11f600abd3	a2375bac-4a9f-4ed8-b674-a1807543c744	v7bQcLYZYmRk1M2fkeeU8V8py-sEcMBOsyqd7q02tng	dec4362fa4974bac4db855acc6dadab4678a84cd5b5630bd6592f9eea581e547	t	2026-04-09 13:53:13.157621+00	2026-04-02 13:53:13.162256+00
ae64d015-1426-482c-bd95-256599bd5971	a2375bac-4a9f-4ed8-b674-a1807543c744	cGL9otn87ZC13nrRxxQwKwmfiB6e7EICAZ4y4UhK9_Y	b6baf6e5c95f3b903a080b24642a3a45f7708f48d437e0cd7b8f0772ec043ab2	f	2026-04-07 13:45:50.510316+00	2026-03-31 13:45:50.512499+00
43e71718-1afe-4f68-a9ec-b72ad60ff85e	a2375bac-4a9f-4ed8-b674-a1807543c744	4DQyEr5cTFJ1CJfB0f9Or163WwcI2eIJGsjALnLDyaM	48f03421aec2062f90db3601274c21b7b7722cb5f0e8bfee89005957b624c24c	t	2026-04-07 13:45:49.52915+00	2026-03-31 13:45:49.560747+00
fbdddd28-5135-45ae-8c5f-f32e0dccdce1	a2375bac-4a9f-4ed8-b674-a1807543c744	CJzhBV1RyJXPL43hg-izg5C0rzx7l8qItAgHhadms5w	56d233b8561fcfcc64b0d0ba0153c963c7ff597186724bc57b5039a6c942ac34	t	2026-04-09 13:55:12.168518+00	2026-04-02 13:55:12.16972+00
3e5be1aa-a3df-49a8-a875-bef02bc5c871	a2375bac-4a9f-4ed8-b674-a1807543c744	fL-HQdyRJPND1B2Nl7AJv4hxnLXMFl4wtc3hzcIyd6M	edc07e70e88d5792545703370a7fa4e58cf93936116167ec3a7f9ccbf5210e55	t	2026-04-07 13:48:58.476071+00	2026-03-31 13:48:58.479973+00
61daea7f-6843-4be0-9c83-c46aed63d960	a2375bac-4a9f-4ed8-b674-a1807543c744	S7j531usqGTYgQW8w7ZnCz7dSp5Cm5DT6x8uo5c5e4k	85a96c0cfbe4c498f69d55464503508c4cfdc925fcac40850d0434e1af645d07	f	2026-04-07 14:01:39.337849+00	2026-03-31 14:01:39.411909+00
847ad301-2073-4626-a464-3816d23fc02d	a2375bac-4a9f-4ed8-b674-a1807543c744	o_i5jcnPBCvkWu4opSLUinpdl9UgOQG77Tsm_RlJ0rQ	d309aa3aca0fe05c9426d71d2580ea454669d958156209c7c3d00c550ae6425e	f	2026-04-07 14:12:35.779889+00	2026-03-31 14:12:35.783097+00
e8e7ca52-c5d0-4822-bb84-392eff57da4f	a2375bac-4a9f-4ed8-b674-a1807543c744	vSpv7yIQ2TnwghWRRcruudZdcXgEmVWNadAt8qXrUbE	6f1fa02f8fbd0ed107612a7419c0b20d94f8b7a7ff8075edf02a7202335aba2f	t	2026-04-07 14:28:46.54654+00	2026-03-31 14:28:46.575243+00
502caf2c-7979-477c-8a70-f198493451c6	a2375bac-4a9f-4ed8-b674-a1807543c744	1_9tJw-EEWkaPkR2TrrGp1B07BSq_w50Tqbo9TH8Yz8	706c3fb2df0000d92c1f6e9d2728cb8a7893a6870b8e8d15bd254577f238c0d6	f	2026-04-07 14:56:44.656054+00	2026-03-31 14:56:44.686938+00
a4ee6e27-ce13-4e88-87a9-a1336623d388	a2375bac-4a9f-4ed8-b674-a1807543c744	NBshqEYtH4qSqCyZQQpgRhwN12QAtYeoUU0Hk5HqoiE	d903ed25393be9a6d45b55409fad6bce4aaf6466a3c03bd05f633e68e9c40dcd	t	2026-04-09 14:33:13.7626+00	2026-04-02 14:33:13.81539+00
a4e62149-f1f6-4daf-b6cf-ea45b1b56e51	a2375bac-4a9f-4ed8-b674-a1807543c744	ho11_lqFwJTIdBhUsprDUnuF5ki4_3rMxLWcPWte7Rc	bd1ae46e8c1e5ab91d6269744c5fc4343a1b06e4abed79672cfb510185973676	t	2026-04-07 15:18:35.957434+00	2026-03-31 15:18:36.065224+00
739092e7-285e-4da8-8608-a9465ba660b1	a2375bac-4a9f-4ed8-b674-a1807543c744	HX43fV4PYbkmDQrXj5-cBObicNEUbKH-SlxXq6Cms2U	e66c18daf4a00347b19feecc93d2ad94b20d04a5cd4eafe8487fa3ba6dc940ee	t	2026-04-09 08:25:05.70069+00	2026-04-02 08:25:05.703998+00
d46cf400-4998-4f30-a3a5-0d05e7d050b6	a2375bac-4a9f-4ed8-b674-a1807543c744	fSXnjW3db2Z0VYqA_REESd0aMSDgoBKQKfYHi5MRuiE	4695eb028bbbccea16eda15e896e2e36281f4b4be0ccfbe2e723592dfabd859a	t	2026-04-09 10:19:32.028237+00	2026-04-02 10:19:32.045471+00
4b5ba70d-c63a-4573-9c89-5f628e25db5e	a2375bac-4a9f-4ed8-b674-a1807543c744	Ezt5TU2ZDGLKf7QZHPh_8kKZ8Woqi5UssS3bX4oebLE	7fe728fea385c6654d0f5d9ec0d59f78c697a6419bea62a30a3cbddafcbb9ca9	t	2026-04-09 11:00:13.732955+00	2026-04-02 11:00:13.746358+00
c36c8159-d948-49ae-9dc3-3c3a8aeb3994	a2375bac-4a9f-4ed8-b674-a1807543c744	9W4gowmHUMcWNs2481Y7GIOoqeC6DKBj8KeImwEnvQw	75e6ea64fb0dbfbc92dfa1e5f508bed4bee26e389b33f36337689cee2bc9a869	t	2026-04-09 11:37:58.542405+00	2026-04-02 11:37:58.571257+00
e876e313-fd90-4bcc-abe8-74798f9c7b96	a2375bac-4a9f-4ed8-b674-a1807543c744	VrE2oTaDvZMGmAoQIouEctsyplr_Ag9cTAaAeJFAZt8	6c290a58d13c3ca59d288873fb93968d156f0c78bff29327347ca2eeb81d0b7e	t	2026-04-09 11:40:12.675212+00	2026-04-02 11:40:12.675594+00
5f599aad-e551-4697-be05-c732d90bd6a7	a2375bac-4a9f-4ed8-b674-a1807543c744	ZcjZ1HDN-c90sF0QXZbmCDzbXlEy4K5hATNxcQvqPGM	db498ee8e1e78ad487bccfdd68547c2c908f141028adc111946c51fa4926588a	t	2026-04-09 11:58:12.707108+00	2026-04-02 11:58:12.720758+00
aa497d13-43c7-4628-8e69-9710c78c2fd7	a2375bac-4a9f-4ed8-b674-a1807543c744	qC4ZW_bpnbHJIooR4KQimqbyLsVUgSwdP6E4j-1LLdE	e00f813ac3d25afd894dfa900cc85644c9828262c41337cc496833a00b2dcfad	t	2026-04-09 12:00:12.218087+00	2026-04-02 12:00:12.219274+00
82339e69-a3ef-442d-b5cf-f32a18245a6f	a2375bac-4a9f-4ed8-b674-a1807543c744	SyP2_y4h3rGmk0WDqvuRPhGhw7X09S3F1HL-Ga1WCUg	21323b31f6d8a8d5e5f0226323cbbabf17d6ab4b56e80662da087674ac5adb05	t	2026-04-09 12:38:13.024104+00	2026-04-02 12:38:13.034161+00
1d8ff9f7-18c8-44f3-8e88-5f14ddb7f32e	a2375bac-4a9f-4ed8-b674-a1807543c744	Trg9VIQr_F4-s3HE5s9O7Sp8L22TgfcTkLawLR1dYYI	225e8f918afbb2a9b15e3d6851cc91d2f4782213d0648b946d7deb3b4690dbe2	t	2026-04-09 12:55:12.889513+00	2026-04-02 12:55:12.906662+00
ac7225c9-317f-4d02-8f3d-5967077b86a5	a2375bac-4a9f-4ed8-b674-a1807543c744	J47_ucNxBmzJcFFTWqeLO2gWdnku6drQ6JI6etvloik	0a407bd3a3bcf8b139a718b300fefd2091a00b9e01a8554489b37c4bd369c7cf	t	2026-04-09 13:15:12.235392+00	2026-04-02 13:15:12.23839+00
d82cc706-f201-41d2-af72-fb2a06f1b2f9	a2375bac-4a9f-4ed8-b674-a1807543c744	2lUeUe0ajHDVs16qoiR0JpLBIR8JT2uXlILquzhOX90	119918631b75a985eb515e9d50c3c991f8edac34c22fd70806ab8b9648426a95	t	2026-04-09 13:35:12.923377+00	2026-04-02 13:35:12.924217+00
25f92795-6cd1-459f-a67f-80a62209c8a6	a2375bac-4a9f-4ed8-b674-a1807543c744	6-8mN9bc8hJgOSXLZMjO4jG6dznDaunqOTlGO4nxUBs	b3836b837d26e0354a78c88bbdd2ba9b41ecbb1f270d340d7dd758bbec83d7a7	t	2026-04-09 14:50:12.775189+00	2026-04-02 14:50:12.79808+00
dbc63f19-4b33-4905-9c5e-9ee81d9599b3	a2375bac-4a9f-4ed8-b674-a1807543c744	CvNpBYe4p81-_cLZ_BySD_RoPKR7egrIsl2du2YZLRk	ed60ffeb799c52f058a71d35c0c7be2167c637d6ccd6bbaef7841426c74cd71e	t	2026-04-09 15:08:13.046837+00	2026-04-02 15:08:13.052849+00
2966ac04-b780-4f38-92d4-17edc9cb5265	a2375bac-4a9f-4ed8-b674-a1807543c744	AIr9WIjCSB76WCy1mVrLFnrZ9UX6-VWpLeFb_T71Iaw	40b399410a1ae594a164e21d06e7d1518f8c31ba9c35d851cb0909f319aad9e0	f	2026-04-10 08:35:17.956859+00	2026-04-03 08:35:17.962926+00
185d9507-db3d-4f2e-9190-e0471af058ea	a2375bac-4a9f-4ed8-b674-a1807543c744	7wppfVSoKUmQMWy6Xeg6GGZ3QBFxxog8OQ2QGuLWgUw	55d2dbcc2433771ed64db04074e0bab6b677ccbddde75cecd388ee13453e4e35	t	2026-04-10 08:55:19.367062+00	2026-04-03 08:55:19.377802+00
c5ac5d4d-7d85-4246-accc-76b68b9ad511	a2375bac-4a9f-4ed8-b674-a1807543c744	ncAgeYkcCYRP2z25sJWC-uDkyALOO2ih33GMFOJvoS4	4579b2364213c55da8b188b9353425cd8ca3894540ca741bcc49e5585842f445	t	2026-04-10 09:15:18.760564+00	2026-04-03 09:15:18.764572+00
7819e7c0-6df6-4802-8137-2a86df024775	a2375bac-4a9f-4ed8-b674-a1807543c744	Qx3np7KSRIzgX_0zIpcIOjbUHcuNDLiMkc7T3GWf_-k	fa58ef006370db6b2729b7ca7e0e46bd79a8ffb9dcf24b8ef24ed7f93f074d35	t	2026-04-10 10:25:18.818219+00	2026-04-03 10:25:18.828372+00
af82b16b-3f54-4ae1-94ca-96cc51725443	a2375bac-4a9f-4ed8-b674-a1807543c744	SvsdHpjU1kW93GmC_F44jy6RGFX_DfjAnWMxCmoe8QE	f96cfe54a5891ae44a231b78bb9f0ed2b4a90a4b7d2fdca2acdc6489830e7999	t	2026-04-10 15:02:11.017815+00	2026-04-03 15:02:11.048302+00
085d1e39-b218-4b8e-913b-8c9d6c076164	a2375bac-4a9f-4ed8-b674-a1807543c744	mMK45Y_p6E7G9wwm14IcILUM9vNFWKhND33GsfYhBdo	c141d050f288c3238f553e62620a41217d8db75179ebd857e49f24cd2bb39c1f	f	2026-04-10 13:36:30.759942+00	2026-04-03 13:36:30.767027+00
15fa11b3-e4f2-4ab8-af85-287bba576e50	a2375bac-4a9f-4ed8-b674-a1807543c744	bny5QjzB7kNfd9oEF87-FG7Vg_Hr_wMKFqAyLDVU4lk	a73357bdc293025671d305decbb4876d31df066840d56feaa07890dd86bd9956	t	2026-04-10 12:43:24.493589+00	2026-04-03 12:43:24.531619+00
47b3f000-41bd-4ad6-a89f-da9ba87d1ddf	a2375bac-4a9f-4ed8-b674-a1807543c744	bXw4qW3LPpFLcsGJQxqWBA_8pKMedjoPHdkxWPoGnQM	db8eeaf31d2f38fd748b80aa98521fa2adcb37e061d3471ac850057bf327cd97	t	2026-04-10 12:43:27.903901+00	2026-04-03 12:43:27.90432+00
10f0d81f-ccb0-43b2-83dc-299cb5a9f664	a2375bac-4a9f-4ed8-b674-a1807543c744	mcRCZDubalzNZelPQOTa38W7KLcwTiAeMkljXd_JOH4	7c3c14f352824b5c60727ac223292edec9975d168be43b671113236c4bf38645	t	2026-04-10 13:20:27.133828+00	2026-04-03 13:20:27.148631+00
7e547672-9c6e-4ad9-8665-05dff9ef787c	a2375bac-4a9f-4ed8-b674-a1807543c744	-wZeUoVbC5sbQGNwSL8cbWlxX456amCPLo8QeLc4vqM	9d5609cb4579e6cfdb92fac71a73949cf56a0129fc9e9eeb5fe018ec63984c5a	f	2026-04-10 13:20:27.074248+00	2026-04-03 13:20:27.089279+00
e7967fed-b595-4ae7-9ed4-8267422a0611	a2375bac-4a9f-4ed8-b674-a1807543c744	Uvdfl1vFGCow0YUowNB278v6EISzyj_AR3GMZtRfTdE	d91b22a560dccca432e938aeff4f388cab107428cb7c216b3ce6751980fcdebb	t	2026-04-10 13:03:50.358946+00	2026-04-03 13:03:50.368494+00
8df81915-e9bc-4fe5-b29a-e85116c3c178	a2375bac-4a9f-4ed8-b674-a1807543c744	6ltEME747QiBTDTf39ANAhIct81xjWySBRCmPhBTAoM	60aed90e146d2f6ec0b3e15a18497daba043d48fdb9f0a90fbf694e0b8290fc1	f	2026-04-10 13:41:44.052174+00	2026-04-03 13:41:44.062267+00
a44948a2-4ea6-4aa2-933c-23c0e36eab1e	a2375bac-4a9f-4ed8-b674-a1807543c744	um7rkWtDJb8IDIKLqOaV8uH72pK62oq8dE6ss3wNE5w	ae5941b83e60d805049fd35439e75ad2f095b9d16851923569dd5e5288b677c7	t	2026-04-10 15:22:10.912309+00	2026-04-03 15:22:10.924147+00
17b873d0-7adb-48df-81ee-b547b28f1f27	a2375bac-4a9f-4ed8-b674-a1807543c744	vKDW0VOdyOl0FFbY0wa8xbYqigCG3ozIzvQWf82O5K4	44d268172d048609e7f7ba0f9d91dbe2331c0c862343f0bfd3ce87b5267837ae	t	2026-04-10 15:41:51.562477+00	2026-04-03 15:41:51.573609+00
c0a2dccd-099d-4770-882f-af0ad641b2c4	a2375bac-4a9f-4ed8-b674-a1807543c744	1QhwJcbcA9uSrQQ6IMsbNgM6FvZmFZcd5RcVEqPJQOY	db4e81fa2bc994218b859dd6de38443f25b349c80d46a6699d8b28b53ec22af0	f	2026-04-13 16:17:54.368585+00	2026-04-06 16:17:54.38827+00
01ea9718-3d96-4ae8-a09b-d6636cb739c6	a2375bac-4a9f-4ed8-b674-a1807543c744	OtnS9x9W9IGnzRn5SMAhaOp1sN0AC0WtN-6RDjO2TXA	7ea5013845c17211280b0739f394e67724d579fe778246ed5e0f711ccb605d7b	t	2026-04-07 13:37:59.552763+00	2026-03-31 13:37:59.554925+00
691743cc-ae54-42de-bac1-08ec575252b6	a2375bac-4a9f-4ed8-b674-a1807543c744	9Vvdbdpc1Ww3W-h-gFoMKT3rf0kwcHXLvlTSrFxj5m8	c4c497dab537276c06d0cd3150acf6200a892d1f2c326742b3154bcf7a344afb	t	2026-04-10 12:43:25.475946+00	2026-04-03 12:43:25.508532+00
77b56825-bf54-4e20-87f8-0c4bf58a397a	a2375bac-4a9f-4ed8-b674-a1807543c744	w4GGNi_5znUqk9zDXSekaPev9ftk1YfUxT6e_cAfcxw	e669cbb6779e702f431c8a13906a676f731a761bd07c0f399d74d5aca8ddb58c	f	2026-04-07 13:45:51.771669+00	2026-03-31 13:45:51.772878+00
981e0449-e9bc-4b95-9829-9489254e456a	a2375bac-4a9f-4ed8-b674-a1807543c744	CtdNSJRPpg6ZIw1agC4UGp01cikykXOPzUoPvHXkYps	cf4ff8598366bfd8204a2d7b1f45307845455b61fc3948fd45a72518b76ea0c9	t	2026-04-07 13:45:50.547525+00	2026-03-31 13:45:50.570308+00
b42c685e-6eba-450d-b2e4-2100aab6de7d	a2375bac-4a9f-4ed8-b674-a1807543c744	s_HgQdRyVuPJ36ur-nLzGDE8gkALN7dNmc19aWwKrYg	f60c6676276023359092e18b591cc612c0a82fdebaddc03111774513eb31d2e8	f	2026-04-07 13:53:06.885687+00	2026-03-31 13:53:06.887474+00
8c8f7f72-936d-4a4e-a76c-28bad843d146	a2375bac-4a9f-4ed8-b674-a1807543c744	bang9A90q2EZ8aZDpBdnb4TGlrA1sK4dIrCHJQTr_og	67791c63a202ac62533cdde661b2787b37e06d963044d57f17c1e14881173dfd	t	2026-04-07 14:01:39.481611+00	2026-03-31 14:01:39.538386+00
6f6a7695-8ff9-4be5-ac44-6f01b77d96ba	a2375bac-4a9f-4ed8-b674-a1807543c744	bP4eLMHTtMXW48wwzxTBAwQaGTJq2XvXeN-A8rJyjcQ	9287bd679a7a44ec78257896c8da647a7dfcc3cd482dbfec4778f2ece3914233	t	2026-04-10 13:41:44.100035+00	2026-04-03 13:41:44.115992+00
a5438bce-0390-414b-b32b-afb6252ebe71	a2375bac-4a9f-4ed8-b674-a1807543c744	LlSe_jJttnqIvJT0obOZU1K0K5f5dgbY1zQo2EOCYHI	8f34ab94c6232722c351ae975a3e72142dff3d38a905c21c913956cf09148a12	t	2026-04-07 14:12:35.808758+00	2026-03-31 14:12:35.814398+00
b93c3e21-762b-426a-9546-6b10b2023e8c	a2375bac-4a9f-4ed8-b674-a1807543c744	i1PZ-TnU48RkfVqADuyONfoqnKHEuJd8-9VbJNEYqSU	7e5856e6728cf14b4dec58026b0ddab4293778d0f48ed9a4e0673916c78787fa	f	2026-04-07 14:42:37.933814+00	2026-03-31 14:42:37.941995+00
e7354cac-639a-4f61-8397-5b9f1227f7cd	a2375bac-4a9f-4ed8-b674-a1807543c744	7akG7isACb7gPjB1BJCvYQK58OtXU228RAGIsmctPg8	63d900d13f70f640b7541d0707033d4ed9b97dba6df0d96e6ece3ab28df99530	t	2026-04-07 14:56:50.351295+00	2026-03-31 14:56:50.375337+00
9eeb30a2-8851-4583-8b58-7fcf00a9874a	a2375bac-4a9f-4ed8-b674-a1807543c744	0O9xRVHxragpuwH7mwujj2ssbxUqQYn2MnNdIpPwXRE	028a28e48e28fcefcb31a8940141824c3056aa4b952dbb7af28db29fdb01484c	t	2026-04-13 16:17:54.429561+00	2026-04-06 16:17:54.448517+00
d8d73e12-582f-46e2-b275-56e78090f1e1	a2375bac-4a9f-4ed8-b674-a1807543c744	q5nDiaQp8y4_AX093GbNcmahXU1xfwwicMyIOhVGCKs	0e62c64f6d3f0e2cfdfded46f765efb921ae210612542ee9dca300079d62442e	t	2026-04-07 15:21:49.627744+00	2026-03-31 15:21:49.648919+00
c65f5dbe-2697-4eb8-b9d2-879cefcd26e4	a2375bac-4a9f-4ed8-b674-a1807543c744	yvkEFHQqZGAeppwbsdGwwfEEKh7hmYDXtbjYcHaAOFE	6f1afcf35c4ac154c67dbda61bb87e0b49c3782e393d514bbe28b58e25e33cf1	f	2026-04-09 08:39:50.128128+00	2026-04-02 08:39:50.136255+00
2c12e71a-df6d-4983-88dc-e4444505acb3	a2375bac-4a9f-4ed8-b674-a1807543c744	-qwTrh3h6Im-ui1rLXOPnvzbqMM7-sc4P98gF2Erso4	3f1cfb519a365ba4a78ec27e847b411e85cb37e311910098ad6005b85cc57b8a	t	2026-04-09 10:40:12.73713+00	2026-04-02 10:40:12.743796+00
9c47a8e6-3f05-4742-a4b8-b883b9bb7453	a2375bac-4a9f-4ed8-b674-a1807543c744	WSl-lLsU-oTXHpHIDkqI-V8YQDzoJp8MxC_IXxeAi7w	4d4db695a2d0bd777d57b643454813e5b20adb8063811a4a858eeff43f00c396	f	2026-04-13 16:53:59.981204+00	2026-04-06 16:54:00.003813+00
ff77631b-26f1-46ea-9885-a3185095aade	a2375bac-4a9f-4ed8-b674-a1807543c744	y9-hay5ZqgyF39Bh1kt2myRI4E6ojBgAEVWar1iUJlM	d62ca4332cc92dfa643a7a58137e9fb841ae6c2c2832a553ec821d8d815e60ab	f	2026-04-15 12:48:37.415443+00	2026-04-08 12:48:37.4434+00
1ce7b007-9199-4e62-ae13-72be7846a258	a2375bac-4a9f-4ed8-b674-a1807543c744	2-YSxwtCgsTXS6WQUPfeSEKJ_wZPGwmymkFy44dm794	069c82d8696ccacec4a84ad5ab2dd833a4aa28b5553c3c118fd38db3372da5e9	t	2026-04-09 12:20:13.029158+00	2026-04-02 12:20:13.034558+00
776a9c79-26d5-457f-b463-9b0ebac3f56b	a2375bac-4a9f-4ed8-b674-a1807543c744	Mxs8gNySn2aqikB_SrD6Nr4MGolc-82qojrmrxfbG1Q	5bf2d7262569840b22efde62e5366c0fe3271b9097cba4030ac10a63b010c4b2	t	2026-04-09 13:33:12.843176+00	2026-04-02 13:33:12.848726+00
5d321f11-f313-4678-88d9-2592226abba4	a2375bac-4a9f-4ed8-b674-a1807543c744	C1IrO9jC0t_f8lGe4F-9oItIGPxU3NpwlVvd96y0s5M	3dcd1bc901c4f40d6993c1140cb3a0f5c28b193ef099456be0f9b5232c674d10	t	2026-04-09 15:10:13.016871+00	2026-04-02 15:10:13.018062+00
2a722874-643b-4901-90d7-0aa3e89ae4b2	a2375bac-4a9f-4ed8-b674-a1807543c744	S8-8EvXoq3hyTXwEw-xnNrt7nTddCNc_QqlgUws9d2E	354d594bd35f149f3bda8f5ceafdf873e80a106396a96cd864f711db06f27f6a	t	2026-04-09 15:30:13.414994+00	2026-04-02 15:30:13.423981+00
0122769a-f88f-4db4-abd7-d16c70753224	a2375bac-4a9f-4ed8-b674-a1807543c744	Oh_OZh6Mj8hq8PnKxE0kr2_XJGfchxoajgenfMtf2UA	5eee94d0eb55784da96868c361201170f341f16c0a2891e399ab7924e6f728c7	t	2026-04-10 08:35:17.982945+00	2026-04-03 08:35:17.984986+00
cef1796d-4599-495e-94b0-62f68e39f4e4	a2375bac-4a9f-4ed8-b674-a1807543c744	SD5lug5TcFiZA3754tNr8LHYK8AlkiiwB2JW_ZvPqVs	e6d190296db365527300b8853083c50c9bbcda51cd7d061c045200b5be3a9a15	t	2026-04-10 09:31:59.312395+00	2026-04-03 09:31:59.322924+00
82ef072a-67f5-4022-a67b-f8811df96c07	a2375bac-4a9f-4ed8-b674-a1807543c744	xgXAu7lZ8YV7j2bd_6fNJf5hWq6ooyAOS19Xl8osz-Y	fafe28d85f309d012ca02cbb3e5bd581ec8cb44558ca1b9ae617d6da34f009a9	f	2026-04-10 12:43:25.417723+00	2026-04-03 12:43:25.433363+00
25d26d74-8096-4bad-b17d-30d20c027ea6	a2375bac-4a9f-4ed8-b674-a1807543c744	2SF2fqL8GJD7U0RzQTsgBswmGOOni49m2DsBhfGey8Y	14be0f64dad2c8fb753a7899b06600f7314ae53b5952ebf799fda44500093aef	t	2026-04-15 18:26:48.765045+00	2026-04-08 18:26:48.773791+00
35a9d270-5ed9-4bc2-a43e-ec936e2981bb	a2375bac-4a9f-4ed8-b674-a1807543c744	eYgAhXNOvnorZIMh8zBbccCzXbdIpq8Z66x2urhtIbw	be2d8fa482f8d16eaafcc2a28a8de4caccd508aea41d72ed282abf2740e24ce7	t	2026-04-15 13:48:48.873666+00	2026-04-08 13:48:48.910826+00
612c38a1-335e-4230-aa80-bf2a5ade04ea	a2375bac-4a9f-4ed8-b674-a1807543c744	824H-HQvasIOLBeYkWqmikhlhOOtq543ODR9qFdcjaM	3290578d36df96a90a2067fa64009f7eae37a20a0a67c23b35e57d9bd3e1a88b	f	2026-04-15 14:06:06.638105+00	2026-04-08 14:06:06.639657+00
45c7b469-20b7-4010-bc80-7f11c13ccc5b	a2375bac-4a9f-4ed8-b674-a1807543c744	0X2aFmtoJg02V9YBaWsmiassyhIcJ-BauDnsd0YPTGs	634e88cb830a4233d8e8259aa9e054ecf39415e13bc1dc74a7cff5b73fa35d12	t	2026-04-15 15:06:49.268631+00	2026-04-08 15:06:49.303276+00
6f682a67-47d1-4cf8-b4fe-f88dcc363046	a2375bac-4a9f-4ed8-b674-a1807543c744	_UGRfag-H2iSlB932pmQWzzRMpMqbzoTK--LKhEukOA	ee96ed7450492300bda8e45e6c4082d8a68a9ba40138b77882a90da021c90aa2	t	2026-04-15 16:26:48.581348+00	2026-04-08 16:26:48.595437+00
1d0feb8b-628f-418f-b71b-b9f2113f7f38	a2375bac-4a9f-4ed8-b674-a1807543c744	okTz-6FcwaMn7iMlNqLI30iFEjnG7-zDXZ6y874LLzY	3ab7e30807d5b83bdb169e2c26f4d69c13402f46eff15ca69af17ae0e5961f74	t	2026-04-15 16:46:48.696371+00	2026-04-08 16:46:48.711749+00
a6edac8b-f194-4621-83e8-74ab5c21019a	a2375bac-4a9f-4ed8-b674-a1807543c744	ygXeoOpLQSLFebaNmVirj8LUzTEN2hn-Iw-6DcX7jJs	76482071d07ce0a074117b9f03b4bfaee1854415496315cb2d461f937c7ae323	t	2026-04-15 17:26:48.889656+00	2026-04-08 17:26:48.895716+00
53949d70-f47e-4296-9131-5cec5d6b76e1	a2375bac-4a9f-4ed8-b674-a1807543c744	plCueMVeet6Wmrj1sRgEsqwKSMP2kLRZ9--duTdHqBY	c21e5bda0370c3fd37e8d8f05d62d354e98d086659b363b29b541ca2555662d6	t	2026-04-15 18:46:48.428604+00	2026-04-08 18:46:48.438878+00
f34968ab-1c13-41aa-bc4a-f6a3e004b2dd	a2375bac-4a9f-4ed8-b674-a1807543c744	9s1ilcDbQoNJO8K2_dED_OBldAQ1DxBhCdP_H-ouanY	32ea14298a4e5c7cf8cfea08a27e4b6e729c0a49059df4ea555f9a8c5fbd0c1a	t	2026-04-15 19:06:48.722227+00	2026-04-08 19:06:48.727688+00
8ea0b861-f002-4ffa-913e-91336ead1e88	a2375bac-4a9f-4ed8-b674-a1807543c744	xLhmExvK_LSAWfxVzRd6ba2AFMhqVOw04_wIe3y2QtA	b2d4b7897585dbb592a8cf3624c3f4d4a44917cd7a0615bdeb0d95d9af720e3c	t	2026-04-15 19:46:48.475917+00	2026-04-08 19:46:48.480471+00
d7b80165-0dd7-46e9-ac9f-369d93859654	a2375bac-4a9f-4ed8-b674-a1807543c744	nhyyyLX9uXBiT_8UruRvWZ5uSkIikv6aFo7V2r3S8nk	63237f681c12a0f789f5510af26bda6250df77cef52a442c9cdc37a7224c2fe7	t	2026-04-15 20:26:48.581167+00	2026-04-08 20:26:48.58638+00
6df8ea43-a2af-46ec-8665-562c6bb8418e	a2375bac-4a9f-4ed8-b674-a1807543c744	uSIUo37T9d1vmo3B26SEenBmR9_eCvw5-G64jSmdopw	491e2881c3abe32c28b3c76e852d5c18e86688a85b042464efd01864438f83f1	t	2026-04-15 21:46:48.511325+00	2026-04-08 21:46:48.520268+00
f9c59618-03f6-4dd4-862c-98f2ae59dae4	a2375bac-4a9f-4ed8-b674-a1807543c744	rP2zNneKIjwPiiw5bcmPVCNS--gEGCZhjPymNAuB60o	a365a583831b384d68d3315bf8624c89002eb4efadc67803a197e1b8ad81ba0a	t	2026-04-15 22:06:48.437542+00	2026-04-08 22:06:48.443816+00
16867e20-a02d-46ee-aea8-0868133b9868	a2375bac-4a9f-4ed8-b674-a1807543c744	rETCZ5_OBgZTryKi-AAcp-QWsSb-a7-o02AodUj4Ohk	10f350e3f40a4ea000b90ca5ec543d37a5a42dc100ea7e7d0ae10894754762c2	t	2026-04-15 22:26:48.837894+00	2026-04-08 22:26:48.856416+00
aea2b7db-9e5e-44c8-9f27-6c6330986c4c	a2375bac-4a9f-4ed8-b674-a1807543c744	Tvw2bff0YB_Q67JuhBHZ6KxsPnb4rvALR5LUpznFmnM	2331bc13ad5e2ee682d494f6fd309389e32160bdf280bffc1c3c42490966f607	t	2026-04-15 22:46:48.539963+00	2026-04-08 22:46:48.546462+00
2b6a727c-c73e-4a86-91ae-b3402638765d	a2375bac-4a9f-4ed8-b674-a1807543c744	LxTFd7-SEvJm-IoCUeBmPhNLDZeuJTaKu1fQcsoruRc	3bc8f7b587bdc12e29742355947472997571524d79a40d1573e967469252c0a0	t	2026-04-15 23:06:48.576804+00	2026-04-08 23:06:48.58639+00
339c6516-62a3-418c-b550-a660d220d97c	a2375bac-4a9f-4ed8-b674-a1807543c744	BF-MBUvmUJNMJ1GpJc66ggmFcbfRrVJQ_3UM9EVzs7Q	a1decd9e1aa4c988579c286928496911591c4f3e468f83f1c25ebef496428014	t	2026-04-15 23:26:48.608981+00	2026-04-08 23:26:48.613623+00
acce9f00-c692-4c7e-bca2-a016f41fb38c	a2375bac-4a9f-4ed8-b674-a1807543c744	1wTJDmjtQGRc0lE92KP4PVDuJTyEBihUSKIoOjrYn_E	231430d50b521c4b4450e6d13d081378aa5bbbf1b21976e30d83f2e319697729	t	2026-04-15 23:46:48.498112+00	2026-04-08 23:46:48.506388+00
36cb50f5-c218-4484-bf2c-14f1952c5794	a2375bac-4a9f-4ed8-b674-a1807543c744	iK4iTuI6ha8nTISi24QlsFlNlvC-V2xUKACOwvNJ_9E	a38361a4f7aad3afc4e3d0fd239c970f280c706f88f9d4aac271d93ce94c6606	t	2026-04-16 00:06:48.280091+00	2026-04-09 00:06:48.28932+00
0da19fd3-aa1d-4209-bcbe-71d141da2163	a2375bac-4a9f-4ed8-b674-a1807543c744	ATtVBLscqQMn2EfUG1Hj_YD3Jp7O1JMiVWzQsKUBWn4	94c58502b90a1adaad4bdf867c264e07d5455925bc9c3543112e9dab50e8b4f7	t	2026-04-16 00:26:48.952645+00	2026-04-09 00:26:48.959999+00
23966aab-ac66-4a68-8c65-9a4b63ecd8b2	a2375bac-4a9f-4ed8-b674-a1807543c744	YdtvIerYJM9u6cB6fIVF6ZT631SNkkg5lPVzltWtVuM	41cdc420f47b073ee869b149df96d78625fc4ee171f8ac76d8b77bbdfbc16d86	t	2026-04-16 01:06:48.524761+00	2026-04-09 01:06:48.533554+00
c934aaa6-d63f-404e-bf1d-581852c751cb	a2375bac-4a9f-4ed8-b674-a1807543c744	5ogMDss682db-TI2e2I7AKZ_tyc5NEao9Qd8I1Vszys	def743c94abf147ca00d878c53a3f3a8352c9df2d0209e95c78afb59c24d97b7	t	2026-04-16 01:26:48.276487+00	2026-04-09 01:26:48.280775+00
90ad17ea-7d62-434f-9212-bee43a03bf98	a2375bac-4a9f-4ed8-b674-a1807543c744	8gCNRM2DRu-pA89i3lgdParpv1JiCj0upyonALG7ed8	ed7c489c791d88b3d965059317c4b63a69d86356ee6bef348ae1678f243f1e35	t	2026-04-16 02:06:48.696774+00	2026-04-09 02:06:48.70387+00
bf92c482-9943-4072-ac66-ad9e92d1959b	a2375bac-4a9f-4ed8-b674-a1807543c744	9Krm25g3PujP9MLzTpyJe_usJbOFZHqjhSfjr_y_cCk	1a1b8980b5f379e29d10e3b5a8883f85548f6f1ea339ff14247bb91c2ae3ddad	t	2026-04-16 00:46:48.458582+00	2026-04-09 00:46:48.463404+00
24000ce0-9841-41ab-bfa7-8be74f87ed0b	a2375bac-4a9f-4ed8-b674-a1807543c744	smHi7xYAbfYHIG3VzkX4q845kexV95MZWPmNbQUc1IE	d736f01bdfceaf5a0093d4ee27f6ecd27a1b750cf1b850e731748f2b66bda032	t	2026-04-16 01:46:48.706535+00	2026-04-09 01:46:48.713734+00
0b0f9ec2-97b6-439a-8922-f1e8366c3a4b	a2375bac-4a9f-4ed8-b674-a1807543c744	_9pSUSFboiRlriyGnPR9hb6owbrYCVbfgUO7JMVZDts	b296d0957db5c84b0cee67d3e626cd726af2cc5541c591539df3d6584966ee2a	t	2026-04-16 02:26:48.381511+00	2026-04-09 02:26:48.387009+00
1d731a94-4a80-45ea-a71a-57dfcfc2c004	a2375bac-4a9f-4ed8-b674-a1807543c744	kKn02mkc9osp_e3-1-ZK0LHPhFIYre1-ZfOB2tWUbRg	940edb1197ffb53a7d4940ad916b0fcd5a86ce73e66af9e1f2f345b4a39c5e37	t	2026-04-16 02:46:48.241116+00	2026-04-09 02:46:48.250109+00
b051e931-7e10-48c3-882e-0146e3c68b0b	a2375bac-4a9f-4ed8-b674-a1807543c744	VEG3NL_g0p1_tLOsezWjae9U8k5nauJqPQlsExFBk4E	dd60bd43bb758157d3b798f07e60902fb75815b290b94540c4cc83d2cd58e8ea	t	2026-04-16 03:06:48.608462+00	2026-04-09 03:06:48.615524+00
6b4927c3-68b3-4985-b2bd-b608a971d614	a2375bac-4a9f-4ed8-b674-a1807543c744	j0nUdLlYRSA2RvuUcNJE0VT2xQwB4i8-tllpbSmSISo	8209c026a9b0215428db276cce18ec499c3dbabe4b24bdff057e9a53d44abc9b	t	2026-04-16 03:26:48.718665+00	2026-04-09 03:26:48.728579+00
80990d57-9add-4751-b6ed-657a45a78745	a2375bac-4a9f-4ed8-b674-a1807543c744	VUDqjTIB_BmtUzO7HQEdGRH7Mu6V47PzQC54BBI-Lsg	77fe5db411ba22246a55d42b74a60354abc025d71d94b9de36bcbbccfc876208	t	2026-04-16 03:46:48.658645+00	2026-04-09 03:46:48.665645+00
d542487f-9198-49eb-b278-b3e96bb52e5c	a2375bac-4a9f-4ed8-b674-a1807543c744	4wrmXi5hqhoDnjdajrFXVfzJEpWrLHaIpvZsLgqe2is	2ccfff03858b5d3bdbe2d1800be5a5d7b243df613b3182d94f7c4aae1397bb42	t	2026-04-16 04:06:48.714063+00	2026-04-09 04:06:48.717767+00
8e8df454-6d42-48f1-8e91-a85493aaa6cd	a2375bac-4a9f-4ed8-b674-a1807543c744	yYF5LdgPPSk_T-nIRTOLXDrjBf1xnhnXNQphs2W3SDk	f66c3a25db3ca524a33785ad8ea3cc569739442b3f8cf231c75c8c861ee1e9fb	t	2026-04-16 04:26:48.909677+00	2026-04-09 04:26:48.916316+00
fd44c9b2-7189-45d9-b09f-262c8434d077	a2375bac-4a9f-4ed8-b674-a1807543c744	Moi62hsLaJXN4f89WaEV0rLA7lphj2JYSEExruN-Rak	0d245ed80ed822e6571c0816055c6dd12f2cda562a14ab6bb62bc3ba00ec0e98	t	2026-04-16 04:46:48.984584+00	2026-04-09 04:46:49.000257+00
2dec3146-3f6b-4b5d-ac74-8b4e5a4a44a1	a2375bac-4a9f-4ed8-b674-a1807543c744	D1T6DK61gL9GyeH7457RUP0CkRj2BRlHifqVV4iUIj8	e73ff438cd21edb497814a1739ce43301b36031186a39098e148624d08c4daa8	t	2026-04-16 05:06:48.846787+00	2026-04-09 05:06:48.850411+00
24e3359d-105c-41e5-900f-aabe19986a22	a2375bac-4a9f-4ed8-b674-a1807543c744	B6NO0VcbJ-37okFyWGGDWioP8O4gTX1ZyJ6K6PooJLo	3e4216e4156d218d9327adc644337e72482338f8f691ea5ea2ccf3f99ddaf38f	t	2026-04-16 05:26:48.904877+00	2026-04-09 05:26:48.90874+00
c9e5363b-2d52-4b4c-a2f1-da1414943e99	a2375bac-4a9f-4ed8-b674-a1807543c744	oa18b5yvraJpqcjBFb5iOfTkd7-j3u4FGDt0d1aHvDY	dc7ac37e95289e5a75e766eefde617352fe5008b8389ddb0d44e48a1393a4cb2	t	2026-04-16 05:46:48.916407+00	2026-04-09 05:46:48.926045+00
efea5b8f-6b18-4a98-ac34-9ff1c889643f	a2375bac-4a9f-4ed8-b674-a1807543c744	pOnLE9ExG-EiYTQ8bV_FfDShhJMUHN8QEx8PPF3X_RM	9a5bd7591127aca6dac016cf69cf7b4a8745f71912e5be53020f2123881cf24b	t	2026-04-16 06:06:49.082961+00	2026-04-09 06:06:49.092565+00
6aa1e9e5-02a3-49ad-bed5-b2b158b1f0c6	a2375bac-4a9f-4ed8-b674-a1807543c744	Zl9qHHtQW425ULYfLVuALhnsPlCa7FbcqzZ3wQ58UK4	dcb81d80a5b9ed16c74fd476356c05ce5ebeb81c3965ed457dfd52e66adc2713	t	2026-04-16 06:26:49.093509+00	2026-04-09 06:26:49.097849+00
cafe95d2-a0f1-42b5-a542-e3238eb5833d	a2375bac-4a9f-4ed8-b674-a1807543c744	bwdmPawMV6qir1xm-bJmFKEf8n-hQmLr-48kPCzVUKY	7820e10a584d506fb3ab97f6d7b05ec481fca738b8d58fc634ea8e20acb997dc	t	2026-04-16 06:46:49.017898+00	2026-04-09 06:46:49.024494+00
64f6b03d-3720-4bdb-ad1c-d8239298aa13	a2375bac-4a9f-4ed8-b674-a1807543c744	7cIITtHIAvhL3CZIopkVJ8Qfd0gjsr4mgxgRo6SlIeM	54212c91d57dc7c77cfd71ccb1ec749b91711f07e725ec04f706cc76d9fac3f3	t	2026-04-16 07:06:49.00826+00	2026-04-09 07:06:49.015157+00
8b919bcf-56f7-4f7d-861d-5832b6648282	a2375bac-4a9f-4ed8-b674-a1807543c744	kX1SMUReTx5xY-s4hcA4ZvTP6tgBepOwr71Uxe1duBA	d12549ad4697d8fcfbb059aa09b61d0f9461916b43ea1b18e565125a44045f8d	t	2026-04-16 07:26:49.107124+00	2026-04-09 07:26:49.116526+00
601ecfd9-d50f-4e17-a57b-f03a470932f4	a2375bac-4a9f-4ed8-b674-a1807543c744	sKzFXR9rhyOtnjbFKagvWLRtmDlRIy0syH2qZtlzR0E	63398b9af88fa480cba89b0b4f0c71e05bb79d056956db3af83a8f1dfa9dbacd	t	2026-04-16 07:46:49.089683+00	2026-04-09 07:46:49.097218+00
faa873cf-c458-443e-8627-c6e3c79d27f6	a2375bac-4a9f-4ed8-b674-a1807543c744	5CwfR66Pml6pFZHBcMvBdaDNshnPaNQZOFUrKD3efbY	090135839889cd273ce7047565756540dbc175c70f01fd35359b93a6efc4e8ed	t	2026-04-16 08:06:49.124001+00	2026-04-09 08:06:49.136178+00
8dec6ee3-970a-49a7-b46e-d98cb864698b	a2375bac-4a9f-4ed8-b674-a1807543c744	wWn1hF_0OOyFGLrvrlJbNl12LtCGZTZIgABg06ocDp8	ce8c2638f764a83cc33f839fa77259baf362bce330d37eb7a7b7f4b4f33839fd	t	2026-04-16 08:26:38.380441+00	2026-04-09 08:26:38.388413+00
ea9866f8-274d-478b-853c-95e774aba7f6	a2375bac-4a9f-4ed8-b674-a1807543c744	EA6aqG-bpANgDzLcLNEaBiddIghoXRy3Mf2KlXxi0aY	c1743942b005debdbaa84b94dc00d469105724a7e0933128c043c4739077962c	t	2026-04-16 08:46:49.19017+00	2026-04-09 08:46:49.205152+00
613f2c7d-9fef-425a-8fcd-ea02700ce878	a2375bac-4a9f-4ed8-b674-a1807543c744	rnJpLDiH_Tyg97LEt2w4GIl5qO_6defVmS3a7I9Hyds	4a37887a0d555b78e72a0be4c97ebfcfafe5a00e6ee805146269701be2c2138b	t	2026-04-16 09:06:50.490011+00	2026-04-09 09:06:50.524917+00
0267d993-caf3-42e2-9b9e-20114b14e94a	a2375bac-4a9f-4ed8-b674-a1807543c744	_iQt7VxFtUHwXeSSBDO-nNwgtnR0VHNDEYL8tCHq__E	5598cde314dd107cd0f9b289a911be4c3cd49b392a437330c0184f7b2d5d79ec	t	2026-04-16 09:26:51.170954+00	2026-04-09 09:26:51.201368+00
8335c5b3-ae82-4daf-8b45-5edfc0fce70d	a2375bac-4a9f-4ed8-b674-a1807543c744	-6Ms-4TSLhadMEPqPg--0SbR7lqalHj4Wv3elOzYYP8	8bef44b8cec7c8a7b5a84658aff3930efefa4bdaa683bd07395cf218540abdcd	t	2026-04-16 09:46:49.478443+00	2026-04-09 09:46:49.496949+00
feea9932-7f6f-47b2-ad43-deb17d537629	a2375bac-4a9f-4ed8-b674-a1807543c744	0wLFQE6gOeolBGiWisMv1KzuRu2SqvyuHTB1NXyKwMs	362ba9896b9dc483de2570857be068d8464a11986ee6376805fd663581137749	t	2026-04-16 10:06:49.479563+00	2026-04-09 10:06:49.492771+00
84efad41-d222-4724-ad1f-7420608f392b	a2375bac-4a9f-4ed8-b674-a1807543c744	QqJER65wSCwwmutLxucUailTwk1K87-TcFS92sMvY9s	ff73b6e2f5702817db0116fcd98353ad599206413578636d4355bf1776f6ee27	t	2026-04-16 10:26:49.447115+00	2026-04-09 10:26:49.458658+00
414b774b-1e5a-411f-bae0-7d7caf4c03d0	a2375bac-4a9f-4ed8-b674-a1807543c744	8viFnDe7gJVZcRAIa5JsRKwtjbyOeUoGmJI_y2asUbo	0d4931db15ce70f2c2c2314a623802fa371f8d2588eb9191d1c8911fb6f84733	t	2026-04-16 10:46:49.11097+00	2026-04-09 10:46:49.119672+00
7b896116-dbb0-471b-828a-fef4c95aa118	a2375bac-4a9f-4ed8-b674-a1807543c744	d4Ug0jZryfRVywc7EDpFKvdfvt7ygQyI-tGUmLX1Px0	8a8666f6a81215af848b8643f4337141c01b662c822b48128a1b57ba8d594e04	t	2026-04-16 11:06:49.654444+00	2026-04-09 11:06:49.673379+00
4a04bb75-d2a9-49fd-b28e-661e42ef0c77	a2375bac-4a9f-4ed8-b674-a1807543c744	lmWoemfQfoiSh-B33WnwG7n1f3gm2_Xmc4kDGrFPQoA	d65c472c04186f1cb69889890eca050af926172eee4858feb3c1932e66e6011d	t	2026-04-16 11:26:49.925597+00	2026-04-09 11:26:49.946178+00
54bec3d1-cd7e-4657-85ec-a7c8a4613dd9	a2375bac-4a9f-4ed8-b674-a1807543c744	5gmJHqGBcLKlL_aB6wPjVSQOsRIgXO0tBgqzXzAuADI	c9f671e76ff1c7ae4aa39de220efcc16ad5a6962e1498a797733cdb98b4f7a24	t	2026-04-16 11:46:49.813125+00	2026-04-09 11:46:49.829601+00
349e7d9d-f8ae-405d-9b45-42f26884f15f	a2375bac-4a9f-4ed8-b674-a1807543c744	TYoPP8b9Xn_1Q8CLwTe9sVutR-PuyhQYjEiu42UdoRc	488ddb9c290ec73b551adaf7b34f530e8444ff7f65d681c698db7b5c986968ac	t	2026-04-16 12:22:51.678673+00	2026-04-09 12:22:51.736643+00
6cee8963-b862-4b42-9737-9afa82c553d1	a2375bac-4a9f-4ed8-b674-a1807543c744	QA7UWvpr0WdZdtBi2RH2V62AQfSPmy51pfBIqp8ieJ4	194b32afd53a4265a0d0486ddc11429519cd6915151cc8d8bf016ae3b56dd2eb	f	2026-04-16 12:22:51.342072+00	2026-04-09 12:22:51.384885+00
8b4d5903-7013-41f5-9d7e-4f7bbd7c12af	a2375bac-4a9f-4ed8-b674-a1807543c744	Pob4Tvxa_fCykHiV7GiOHtrOA-65yhKOXHPAe2Va4Q8	3d9cc2b3e5ddf6694408ed34bf9067d5f91df347bbdb0024d5eead7be4ee5f60	f	2026-04-16 12:22:51.501159+00	2026-04-09 12:22:51.561591+00
2b1018ae-c8e2-458b-aef0-6475eaddee11	a2375bac-4a9f-4ed8-b674-a1807543c744	XkvKd9Yi04UFQYTFkner_wU9Q1xXtaZE0zbDkyXQt5s	2e1485ce4e393b83cb65598dcf80d60a23ead54a00d0796b08355a299c07d6fb	t	2026-04-16 12:06:49.835035+00	2026-04-09 12:06:49.850428+00
e55755eb-4e34-4444-81d9-23f690138251	a2375bac-4a9f-4ed8-b674-a1807543c744	QXP5tfxgURii-05_Nk7sos98Ybxn0A0HLW2FIhQvVzA	7ee12016e2a5fed4e1800991f84e850ab89d585feb065f63a319c26d81c13a9f	t	2026-04-16 12:41:50.195551+00	2026-04-09 12:41:50.210224+00
26b75046-411c-4d1b-b555-a81bd24b8d96	a2375bac-4a9f-4ed8-b674-a1807543c744	NPUDXhVvSwxHgtvSqdsToS6QfGGt9dSuL4c1bqB1J5g	c511c29281eb5f0c73b2f2428eb68fef9b8fe9650b395e475486c2dc2c90b32a	t	2026-04-16 13:01:51.119309+00	2026-04-09 13:01:51.13235+00
b5498c6d-da77-4890-a2f1-ebfa487e212b	a2375bac-4a9f-4ed8-b674-a1807543c744	Nl7JWR7U9CulTUhCT-0EZ0mCdqPoVqI3lUmI3uGQtBM	81476ea6ef3715458b7491dbdc41d7b862b2577bb6833197c3d2dbac47b7fc34	t	2026-04-16 13:21:50.969291+00	2026-04-09 13:21:51.004341+00
7d75e565-9eb9-4651-b65b-8d844e5ab86f	a2375bac-4a9f-4ed8-b674-a1807543c744	-fozmMVskWib4tbveDoD3SD7rGGxm_CZauqBvQs3jPg	083a56bb2ea543e626f1329918442951e2c2c1d9a10bfdb59f0b349cbdc92c8d	t	2026-04-16 13:41:51.167818+00	2026-04-09 13:41:51.203159+00
58b912d4-a104-45e7-9f0e-3685d1664306	a2375bac-4a9f-4ed8-b674-a1807543c744	QYfXMULzuii2elxiKXQa4VQXzhrbEhfggPwxpCHkEnU	15f1f6ad6bcbc2e9b01c7e727ff3f03b691d1c2bdedcd5065d15db69214789a7	t	2026-04-16 14:01:50.295497+00	2026-04-09 14:01:50.330426+00
75b7551d-757f-4f28-9f25-59c3fb4a10a0	a2375bac-4a9f-4ed8-b674-a1807543c744	B2ADT2mAA0oicPmIpHBYDr437_He2iwm95PQuP4cDPc	8f4f264cba01ce5df7088b5685f0b643c0a795c4dc9cc42c369424387592bc68	t	2026-04-16 14:21:50.44504+00	2026-04-09 14:21:50.457396+00
5641c99e-08d2-4a0d-a8cc-e19ef87a2926	a2375bac-4a9f-4ed8-b674-a1807543c744	6CXfvWhLx1mfxc3zqYSWkkiC8zHrjEgPiA7H1XqriMw	95ccd8399b0f61aedefd38680b17d39730fed9b0a52a9969a6fd221996ed2a92	t	2026-04-16 14:41:50.064586+00	2026-04-09 14:41:50.096244+00
53e7f182-c6f5-4bdb-8119-f53cc4069d13	a2375bac-4a9f-4ed8-b674-a1807543c744	AmKVl25ITIjSpR4P8yDZoxp9Pml4BCIYrt_xLpqjZSU	410b7b9299863970f0f4abe55013c220a853ffb4444a3d1af3a818737ae46b06	t	2026-04-16 15:01:50.202894+00	2026-04-09 15:01:50.220265+00
2c9da6ff-5c9b-4f47-ade8-2f17d42e6369	a2375bac-4a9f-4ed8-b674-a1807543c744	cNpoJVqy3zsoqdl8ZxqEjO5S6lc7P8tzW6K83XONos8	71abc52aa8d544f9d47f64f9cfee94d6701b4ed67bdafcc156d69bfc8aa88ece	t	2026-04-17 10:00:45.112513+00	2026-04-10 10:00:45.126817+00
9e200292-a836-4b5a-9954-fc47b40a979c	a2375bac-4a9f-4ed8-b674-a1807543c744	N23kW8Tl7Gfq-oZdRp2rQtlpedu4TT1JDIWQN3DVo5s	b93164665f3cb6b67104a6553160f2f0809b543409fe8ae6dba5129ac05cf11d	f	2026-04-17 07:59:55.679139+00	2026-04-10 07:59:55.680964+00
c7aa2c22-8a89-47d2-a40a-ccd9d25315d7	a2375bac-4a9f-4ed8-b674-a1807543c744	wFv38UHe6Sl_XQvOoddcpW7Fa8Jzw_lSoUry7bWlayc	b99a73f96840013333ec6b488a91ae0ea000415d7a3ad881b6630df862a18b11	t	2026-04-16 15:21:50.353766+00	2026-04-09 15:21:50.367166+00
f39a7cea-38ce-4a36-8447-8e69398ca3dc	a2375bac-4a9f-4ed8-b674-a1807543c744	mVwlGKcVUMAReSz0Fu3bliWXUu-fgonwBEKzWeJD_HM	65fc66ad957ff7463e4496422c9c49a4a7764ac663fa22494c983ad3fa0a7575	t	2026-04-17 07:59:55.694539+00	2026-04-10 07:59:55.69733+00
a802f429-59fe-46e8-a7eb-4e26066bf6cc	a2375bac-4a9f-4ed8-b674-a1807543c744	0C30r52MTjN3HyPS2DXdzBQEVmgtMexgdy1Rm8nNhzk	707e6f589f7d37a477b913147f4a7b3ef52a0a7ab5801bb9e72a1733bd7e4ecc	t	2026-04-17 08:19:57.100692+00	2026-04-10 08:19:57.114779+00
009bd7cd-f6c3-4f3c-ad2f-e5668808f969	a2375bac-4a9f-4ed8-b674-a1807543c744	OfTd86cUa5rDYDkRbQG4ifmBrX2q5qKpPLPsFtjcr40	486238d3bd613dd60a81e40c6a640dfb74d8342222cf74be4cacc316a7cae6ae	t	2026-04-17 08:40:45.626878+00	2026-04-10 08:40:45.657268+00
29b3c7e7-0b49-470e-a12d-842e41925821	a2375bac-4a9f-4ed8-b674-a1807543c744	wiVDY9qJ-41KaK5HbJ5YU20An3eil8CPAYc0OZbB_dM	10b508f2164157cf5db7ea65ab1c8c0abf6f6393fe36d9cdc0460c855b2f5874	t	2026-04-17 08:45:45.444886+00	2026-04-10 08:45:45.469722+00
43ec831b-9280-4b0d-a3a9-6c4d99cff231	a2375bac-4a9f-4ed8-b674-a1807543c744	3kwTcOwWaJEpewxnkpVTd1GD2aiV4cEJxoKMd8uyc-g	df4dd766a14d132d7f61d457de6ec5b4061e1004a6cec9aa2f6c5bf073c0ceb1	t	2026-04-17 08:50:44.947242+00	2026-04-10 08:50:44.954941+00
568f2da7-c538-49f2-a98e-adbcaba63dc0	a2375bac-4a9f-4ed8-b674-a1807543c744	4xLiA20USiPJuIbrkhZD5hTTE0J2Zzq6k7ujnEISOoI	a255499c3e6b3875259befbbf401afad7355eac3620fb865bcf944545e8ac7d1	t	2026-04-17 08:55:45.398171+00	2026-04-10 08:55:45.405297+00
7f4babc5-067d-4c77-901b-b058b2dcf4f9	a2375bac-4a9f-4ed8-b674-a1807543c744	RbBEoK2SRGoV04hU9TIFlfFPVX2A8hqgOGvv-4XCTq4	9f4b90dad4f8a8a6b5a81e9a78167b1ed9be959e35d60ce2d90f2f89c390528f	t	2026-04-17 09:00:44.948781+00	2026-04-10 09:00:44.954271+00
05199252-fa96-4a2c-a0a2-df9a99d2607a	a2375bac-4a9f-4ed8-b674-a1807543c744	qqWu7HfYNpvGJ6OJPWoHvtQk6TOIKRjupx7XTvVOLyM	1cd35491c62e28307f21c3adb67889af9d6b0b2c44c739f3d32194a2834eb5a3	t	2026-04-17 09:05:45.382489+00	2026-04-10 09:05:45.392647+00
eaaa0c5d-65e8-4349-9ee4-be0cc251528e	a2375bac-4a9f-4ed8-b674-a1807543c744	auAk5xxRLlcARZuP3CNXxmdGyNTjC_UIVwTkK1xx-Lg	345d69b0a754f3ab29643bdf8c371aa42e721890b7e78ff90a15d3cbcd4c36af	f	2026-04-17 09:15:45.302784+00	2026-04-10 09:15:45.36171+00
9985e465-35d1-434a-be0e-3ca2480117a5	a2375bac-4a9f-4ed8-b674-a1807543c744	6cQqqOwW7lE8S4sZrgvxmielc3fopaDdp0ImrFA42qc	6b2d9f114f33b7ea2c53064fe8b09c855ad7c4b1b9fd557d8e141b528740f3d7	t	2026-04-17 10:05:45.375127+00	2026-04-10 10:05:45.390078+00
0c91d6d6-abd4-4065-9e74-f8ed3169acc7	a2375bac-4a9f-4ed8-b674-a1807543c744	_mmgJdATlOyjQUYDl5CnnGMrBJZKOHY-UXd8Fh8E5a8	9cb1c7e67e862c53ab4c310b1795d911233a09f35a05f0032937f10d88c81c2e	f	2026-04-17 09:15:45.417128+00	2026-04-10 09:15:45.429982+00
eef553b7-6929-4d0a-a551-48e165b87553	a2375bac-4a9f-4ed8-b674-a1807543c744	gaqWsbOWvHu9-GAE7Q82yTeKig9i2fObhOUwClEg1pM	40eb2af65dadd5590fac79672a7502e108ebe7800bd6c20ee704a88bc6982ff7	t	2026-04-17 09:10:45.160905+00	2026-04-10 09:10:45.172223+00
90874a0e-7eb8-4f0e-b686-1aa691ec4e75	a2375bac-4a9f-4ed8-b674-a1807543c744	p6cHwSJnwn2G6X9wXETX9i_wCsUjvr--4qrJUuzRAJ0	84c94714ea4c2ddd7d440ee55b1745fa8658e8c36532c8bafbb08dab89ea821a	f	2026-04-17 09:35:45.913528+00	2026-04-10 09:35:45.939048+00
336bbaab-3b7e-4e66-9c8f-7b3cd24a926c	a2375bac-4a9f-4ed8-b674-a1807543c744	N96kdx0fBYa_UISKy3nO2ZMuMhLe9_ANu8vhrAf4lrw	a9ef8a520135bb0d80e9690dd76b9041733f2c62e1e9baa4d5154398cd037463	t	2026-04-17 09:15:45.554483+00	2026-04-10 09:15:45.554944+00
09a7e235-c3c5-49ba-93c9-74812ef15f90	a2375bac-4a9f-4ed8-b674-a1807543c744	zicd8GagtlcvGHVdwwwPuNIicK_SLrxCcShYDYNjryo	f766a9a17221d3504e85c7258ca4919421107f12842d8fe6c3fe8e6a663f6081	t	2026-04-17 09:35:46.036109+00	2026-04-10 09:35:46.0368+00
9a07d998-e908-434b-bb24-765963ea868b	a2375bac-4a9f-4ed8-b674-a1807543c744	k1BmIQt2KIcDo6Dy2b0HtEOqm0cs0yvhjdsnxHeQ8po	4eb82167643e9f3d34ef871fa5fdcc7a571db13b0fba3aa127e0e23af4fbbba5	t	2026-04-17 09:40:45.351614+00	2026-04-10 09:40:45.36997+00
e825d554-cb0b-4883-bcf7-dea8e5e60870	a2375bac-4a9f-4ed8-b674-a1807543c744	HCHnt9IymAcn8XUpUnecfQUIRQcFc0nnWccR7WDV1hM	fca479718bc4c0ba098c7df867245fc36ff30771029fb4b4e41605fefb7dbf2e	t	2026-04-17 09:45:45.169979+00	2026-04-10 09:45:45.186651+00
a3825c78-6553-4401-b3e4-bffce23d503e	a2375bac-4a9f-4ed8-b674-a1807543c744	nEYRYyU2g5xtn3FKlGgEJ2w1sXyMDbFwcuBKE_ZweR4	c9691e84b90cf8f35fa97e46f20a2740c5444b887c01b7386bb3955dbcd25fdb	t	2026-04-17 09:50:45.093339+00	2026-04-10 09:50:45.097914+00
b569c454-6d77-4c56-8604-3e8391bca386	a2375bac-4a9f-4ed8-b674-a1807543c744	scdYbCXCoXFq44N7BJ860uIitC27x3nHKeT_J3LBqW0	716bc6cebc489daef44adae2d1776b55206db497ee6f954b3ff23cc4a0fd7c35	t	2026-04-17 09:55:45.523591+00	2026-04-10 09:55:45.532458+00
912b63c2-8a54-4130-94e1-ff93ca64c00d	a2375bac-4a9f-4ed8-b674-a1807543c744	Zz9MsaVVW3nWf72pxv40CmouNYsoj6PbR0DYtcqvFZQ	667ebce2b63c0e7ecb346c564c81cdf4c9683f6565826b483f8481605c43c2c0	t	2026-04-17 10:10:45.094605+00	2026-04-10 10:10:45.104571+00
17f94f33-8e8e-4d4c-8ca0-5812c8904d48	a2375bac-4a9f-4ed8-b674-a1807543c744	HNsjxwJ4NiY5sMgFoqP43xsOXRlXLJsSZjq09yCk0Sk	efb033e3d67506b556b2f5211e0f24987f20d28f9f007870c8c9dc7104a28037	t	2026-04-17 10:15:45.330589+00	2026-04-10 10:15:45.341461+00
1b3c45ce-e299-46b7-a279-8d02895e31d7	a2375bac-4a9f-4ed8-b674-a1807543c744	zuwWI3ATyEFdyif2FysuVOTV1UUVZTR00qcPr13jLck	d2b52bfa3744943ea253c58a92e899be48f33bdc4cb5af15888d49214f4cdec4	t	2026-04-17 10:20:45.097347+00	2026-04-10 10:20:45.100585+00
2c635e5b-6885-4c59-aec6-f1695cb4f7f4	a2375bac-4a9f-4ed8-b674-a1807543c744	e-YrjKqcA8t-uDgWMmYMWTAh_oJ1zZwteImsZuNWlVk	5997d797bd0556ca7b1df1a978ebd3f99fb2cfc7b07b21a56d23696da54d133d	t	2026-04-17 10:25:45.420537+00	2026-04-10 10:25:45.45191+00
03896bc9-3918-41cb-9170-9fd9bb48eeb4	a2375bac-4a9f-4ed8-b674-a1807543c744	vJPtcieHMTq4WRyHVE5ARdI0q5sTBrLMUUQ4eiWQrcE	05d4e93a278bc2162e7db39121665ae94704cbf93e2cba67a2b9a58fafc77926	t	2026-04-17 10:30:45.151657+00	2026-04-10 10:30:45.16002+00
6d399669-a90f-443a-892a-e272f4ab0a7d	a2375bac-4a9f-4ed8-b674-a1807543c744	L6CuAdBhUuUSql868v6MIhVEQUzYwh-KR4NkQuhEvdI	6958ab687797b6a9130ea3319793bc575c731653ede6f479d7fec4a16b93a252	t	2026-04-17 10:35:45.173842+00	2026-04-10 10:35:45.192743+00
580b5325-20ff-400f-ae8a-74bf0ee7970d	a2375bac-4a9f-4ed8-b674-a1807543c744	Dgt0z-753B6ncEHePAG45rm-4bVkPgSAa66LV63UqBc	d59375b7ef54fdb49283e03c1e1eeea804adb3b88b6c36c7948e2c78459c9b81	t	2026-04-17 10:40:45.232717+00	2026-04-10 10:40:45.251823+00
6dd69be4-f9a3-4c50-b8b3-01c7bf5d404a	a2375bac-4a9f-4ed8-b674-a1807543c744	fe1Nx3U_jXBkUi4lrZe2iqiK1tya8JZgDXV1JyumRAM	a69f90eeecdfe6b3a03e05001066f5d4deee057a95e68b2db506ac820e7d1587	t	2026-04-17 10:45:45.028947+00	2026-04-10 10:45:45.034014+00
f24010a8-bbdb-41a0-ad30-862a46b1b7c1	a2375bac-4a9f-4ed8-b674-a1807543c744	rDqQ9brieZ0qra3eIVgaYgxpHoWp9cCyYpEMvPHpvNA	b7e4132fc6c5ac4e919c00442c97dfc05d0251bbf77d8d78f2b737a9908d774d	t	2026-04-17 10:50:45.104485+00	2026-04-10 10:50:45.108358+00
8ef3fd86-252b-4cec-8292-e7292b7b9331	a2375bac-4a9f-4ed8-b674-a1807543c744	UFijI1tTPS8jQUeS1wvS5zK6QjBuw-u0fvvOcqSHOQU	f12c5afccaa3d3db9d0ea646e42059e5d1ad874bc86c1492e62fc953c48d25c6	t	2026-04-17 10:55:45.888728+00	2026-04-10 10:55:45.909805+00
f2b9c878-b1fe-45b7-b7c2-b7b78b76a3ea	a2375bac-4a9f-4ed8-b674-a1807543c744	fqI187e1aH1FCb2kFUU0BvQh2xDg2KeHZkWAMiKbxaA	6b0ca6ae3ae0126569916f348ad0718310d66103d9e2dd7f1e2d3a566bb438f6	t	2026-04-17 11:00:45.236899+00	2026-04-10 11:00:45.249919+00
2c375007-0011-4f08-8e8f-90f67396941f	a2375bac-4a9f-4ed8-b674-a1807543c744	6Bt1-5dVGoHT_pRVi-L6lc6-C7jOBtZLcyjiMII75vw	2281c3a744dfd63e5e2ed49936a09335298d8c8894981e9174b7f5f3345633d6	t	2026-04-17 11:05:45.564315+00	2026-04-10 11:05:45.570951+00
c28b0755-25ff-4fe8-a94a-38fbad48e7a8	a2375bac-4a9f-4ed8-b674-a1807543c744	4Xm3SYBIP9AdRv66CJWahJeC-Mxay7FQ2LHJ9pGctDY	63a772b10ab66512c6ab359dae98567474d714bba895271790d837d9c779a445	t	2026-04-17 11:10:45.104099+00	2026-04-10 11:10:45.118122+00
31d220df-5d86-491d-be3d-f9a2ea66e611	a2375bac-4a9f-4ed8-b674-a1807543c744	RX1zYqvSOT34Nd9JCSeDSizSl-enNvX1B2sOpbKw8tQ	61af941c840227c2e92108f40c62d6a1c42752f793fc6d020baef7beeba0a317	t	2026-04-17 11:15:45.225816+00	2026-04-10 11:15:45.232399+00
ac22678f-b184-48da-9cd3-2a3f37c75db8	a2375bac-4a9f-4ed8-b674-a1807543c744	oVJzLc7oY86xou2BQRSes_sgaUJOGDcR1j7igi3jVRc	f2b1dedc14d9b197555ae925a24d5edfb4cc00e3b994ae459ab30ff80362b441	t	2026-04-17 11:20:44.972728+00	2026-04-10 11:20:44.976438+00
fc2b4089-f113-4cdb-b3e8-de1de3008ec2	a2375bac-4a9f-4ed8-b674-a1807543c744	Eyn9Tre6dW1p1vc_XPcPRRqvuzG2jsKV-M_mffPE7xE	14ea7669bfb753067579a21fef09743b7928d8f4b4c2d026bdc969a4fdf1c8cd	t	2026-04-17 11:25:45.090641+00	2026-04-10 11:25:45.097575+00
6819af04-6f34-407a-94b7-b1b7c0120a19	a2375bac-4a9f-4ed8-b674-a1807543c744	i7NioAywk6jwylY7Ku2JkiLQJdkbSmoimIGkrgJmz9M	8fa8844bfc076a768f9f864dad494d468e2d141722b590c63a96768bdfe64211	t	2026-04-17 11:30:44.970307+00	2026-04-10 11:30:44.974141+00
91d3ea77-782f-4aff-a571-e91085d8c061	a2375bac-4a9f-4ed8-b674-a1807543c744	mJQlqzwFQdmQOjMZMFmjGerUYrtU17kFMpyfOi0OCPk	dca6b05cbc4a454d3fb5a83fe9b0b128ccc42b72eadb9fa579d79303dc175790	t	2026-04-17 11:35:45.636306+00	2026-04-10 11:35:45.644215+00
31c42c87-e14d-4565-8847-42f63bf9bc01	a2375bac-4a9f-4ed8-b674-a1807543c744	11VRRUn_hZumVGc7RsORrAdwhImzfo4eBgG53pS9t0E	d9725f0a26b0628215b0787281977b83d8aec67d1501999ce069939120b6940c	f	2026-04-17 12:05:45.90923+00	2026-04-10 12:05:45.931335+00
f31606a5-b8a0-4220-b2e0-6974c361abd1	a2375bac-4a9f-4ed8-b674-a1807543c744	RJOIlMC_aVLU4OMgBFOlFyND-lkbTXEwjyyLQInbSCM	7e0192f3b9f5f6ced80d75c1492a5b7ca553520a2b01cdd134f069abaa95e9ad	f	2026-04-17 11:45:45.415901+00	2026-04-10 11:45:45.441289+00
86f1605d-c664-4e67-9d11-4847fb4049a0	a2375bac-4a9f-4ed8-b674-a1807543c744	PDpa0iMm6wq0zugrt_3gCt5HYMf5tAR7BQ6SiGP5peg	6c6b956748cc9b6f6452586e6a94c9988c50246d036533755448f9fd66b0d445	f	2026-04-17 11:45:45.486863+00	2026-04-10 11:45:45.492129+00
5d4a59c3-8c44-45e9-b4f4-a2a56ab24c7e	a2375bac-4a9f-4ed8-b674-a1807543c744	WOIQJRudFGkDC8goTpV6msQO4DTJlfms4LeuVIxeQKo	1d428c3212537397ddd0e1eedd5395c117910e028a1a07c381e67cc16729ab55	t	2026-04-17 11:40:45.545157+00	2026-04-10 11:40:45.551501+00
6a6eb62f-243d-4c96-97b6-3db56b16a3d9	a2375bac-4a9f-4ed8-b674-a1807543c744	iN0ctQwDbmKg4yHNoYgPYcrL6mYA-P-8lhALAAQTc5M	af46a4ae1bf623c7cf71c889a8f78946d51b1c1a3c983506b361bb411682f242	t	2026-04-17 12:15:45.521611+00	2026-04-10 12:15:45.53642+00
7393cfa3-6aee-4b6c-99c8-99d9f6b00561	a2375bac-4a9f-4ed8-b674-a1807543c744	vPR_D2ijt5CdW1GIhsHBGoZaakwsDF0dK9h8Lqm_HlA	1c89500ce8daf223bae2974c097d2aae105e9b21aef48d23800bf99cf5bd35d4	t	2026-04-17 12:20:45.281541+00	2026-04-10 12:20:45.286843+00
1e9c42c9-ece4-4d91-bfdb-c6bdfd1b224e	a2375bac-4a9f-4ed8-b674-a1807543c744	bfJHVFUNImc-wcVCSQNvfsuupt2ZNO_-LwJs8xdnq8Y	4f436959eba7717e4d234444fa5481047603ba27348c2408aae2b4107a7d2a84	t	2026-04-17 12:25:45.530149+00	2026-04-10 12:25:45.536629+00
0ce23cfd-f52c-4bbd-b265-fd72527617be	a2375bac-4a9f-4ed8-b674-a1807543c744	vVt0wvOpjdD01IyYxdnSadLuR49hMZ7EulXAvrSCUcE	15523a551b7593793ab6b66a68858fc742014d5d1e9b65bf5cea3ca1fe9d6fd5	t	2026-04-17 12:30:45.289755+00	2026-04-10 12:30:45.294289+00
7e640ea7-5736-455d-a71f-15faef9601c4	a2375bac-4a9f-4ed8-b674-a1807543c744	bf2xqJHs_R8KohvX10IW-s3pmJpz8CzlDi6J0b6WoTs	456dee03905e7b854a26da4f303e54510d06e32f3ab7d8f70c5692de2f9c873e	t	2026-04-17 12:50:45.503422+00	2026-04-10 12:50:45.509296+00
e2e9c17b-4ffe-452a-af7a-c4039302cc60	a2375bac-4a9f-4ed8-b674-a1807543c744	PdNf5f1salfu2ig-JlN4MrIx12CXXWgr69zG4joxg8M	e8f839358ebed3b4c370dce4c6076bbfb53bd0beb59a90b95919efd4f5e1c783	t	2026-04-17 11:45:45.516238+00	2026-04-10 11:45:45.530385+00
db6db027-ffc7-4bd5-a493-543e78d35d73	a2375bac-4a9f-4ed8-b674-a1807543c744	Eb-VKmoaz8TH38I04NlYHw3kpo4KaFDYR0tV5YsAO6o	9a8f37f2733f55bcdd2a46fa58984f5405e9ef29f4f0c4500866b639eaa41151	t	2026-04-17 12:45:45.263778+00	2026-04-10 12:45:45.278877+00
4e0e56ea-3748-4296-a900-6f46f27f68f8	a2375bac-4a9f-4ed8-b674-a1807543c744	72sosUxXN5bKDI49mE-xWSfMzuSbgMING2IcsoVR72U	f998b0985fefc8550efe86a9b138464e308224ea2cb70066f855ed5d9275663b	t	2026-04-17 12:05:45.97246+00	2026-04-10 12:05:45.973096+00
d21df820-b13a-4f7b-b691-147212d20b99	a2375bac-4a9f-4ed8-b674-a1807543c744	PuLne-V-hxZtouGaoomO706expr_2S_5v2ehHMXZz_U	16b54b9363679b3b0eb00e1f9b2804887a31059d52a5abc4c4aa610d499cd79c	t	2026-04-17 12:10:45.37847+00	2026-04-10 12:10:45.387219+00
499bbfc2-b6a4-4d51-a8cf-e763347f2abb	a2375bac-4a9f-4ed8-b674-a1807543c744	sbxOqnmmgaHIFatQ7TY-FvFQoI319XyQr2v1u6Ta4-8	160a65cd668481a61e684b5d111f6a4f9e2bde1769618b2ab30c4dfba17b3f33	t	2026-04-17 12:35:45.486258+00	2026-04-10 12:35:45.492303+00
ced69a6a-f5ff-4704-bfa2-fb0965c2f308	a2375bac-4a9f-4ed8-b674-a1807543c744	SzA8RiUxyIAXoN9A2pULvCkWKgFf5W2PwXwlHORkabw	37dab79653f74f3bf0dd814359daaf635a34083e7ad910eb347168aa80a2a07e	t	2026-04-17 12:40:45.234691+00	2026-04-10 12:40:45.239787+00
393af83e-a0c9-4bb2-be6c-250568feee1a	a2375bac-4a9f-4ed8-b674-a1807543c744	t0_ZcpPIKYR07IljRB8f49ijTQgBLbg6j-IH8XdVCus	d22d5da3becfffe0bf15cc90f68cdd30a638111d92709c0e6d2b094f7cd56caf	t	2026-04-17 12:55:45.570621+00	2026-04-10 12:55:45.575192+00
53645f9c-b25f-4906-9ceb-02ed4723323d	a2375bac-4a9f-4ed8-b674-a1807543c744	KtKuRSs-iU7PilJt8uYPmUv6USxsU8sT6feDOA3vos4	9aeae7a4d39637fee4fd416ef8cb9dc693f21b74968829c67a40408cb08bab04	t	2026-04-17 13:00:45.319511+00	2026-04-10 13:00:45.325623+00
6758ce9f-9231-44de-b65b-247017b70a04	a2375bac-4a9f-4ed8-b674-a1807543c744	HUK6JnBUW6i5y5svGn0TXkdjzn0gEs_H-uTIO1Akz2s	cb00fc84543fda68c6cb9503ca013c33c400610e55b75c39cb949c7254eca43e	t	2026-04-17 13:05:45.337136+00	2026-04-10 13:05:45.340609+00
419bcc1b-d127-48ae-ad77-5724f1de3ad7	a2375bac-4a9f-4ed8-b674-a1807543c744	fHzWLJLl1FUXgh6Ne8kPIDJE__b862RZoYU4MoJSP4M	01338ae9518db76722a11fc554c12e855a5f1b57e405f5ec4f031e6d0de2a7f8	t	2026-04-17 13:10:45.50557+00	2026-04-10 13:10:45.51157+00
035978e1-deed-46b2-a2a8-2a2c3492e249	a2375bac-4a9f-4ed8-b674-a1807543c744	pwsceRuBGbSz-339Bin8RORXenKQ9EiOO1-4QYIwe_s	e810ba62c645aa178ac013eb6d347a17e608f80560e4a00e8fd24c345cd016ee	t	2026-04-17 14:15:47.930439+00	2026-04-10 14:15:47.970504+00
bcfd8748-a03d-4677-8b1a-639f1426ef39	a2375bac-4a9f-4ed8-b674-a1807543c744	kEKnbRPz7-4PHkmRI6cGPUSar_uei3jOWxiKiD_pEVk	869ce3ba2812935cee087f594b19dcba9e6caabbd82d46d27e9d312ede51bf1b	f	2026-04-17 13:20:46.384423+00	2026-04-10 13:20:46.399628+00
81a566d4-991e-499f-a92c-e9e7f263d71f	a2375bac-4a9f-4ed8-b674-a1807543c744	e0LhYTN4IATzz_VByrk5LBLJ3edTjReV2EsNaBRHSm0	f2cad03fc7d59c35e69495a69b68aa9fa614ae70f8380ce05dc4381a7fee6ec5	t	2026-04-17 13:15:45.749496+00	2026-04-10 13:15:45.755552+00
054a592e-c71c-4079-b4b8-689927c027eb	a2375bac-4a9f-4ed8-b674-a1807543c744	HsT-Z4md4r5XgaAArmLuvfsWfkz9fnFTIBLQKWEHLPc	15b14a645e5fdca934512543592fb141a50531328ec2f32b7010172e7550c0a6	t	2026-04-17 13:20:46.448815+00	2026-04-10 13:20:46.449671+00
6aa4e08b-8790-43dc-a5c9-d9f8dba7f68f	a2375bac-4a9f-4ed8-b674-a1807543c744	Z6fiFM_WZCC0TbFvLza7w4sh1x7n_L7nWQ8QCBtXiUQ	4e47e67cea68cf3dbbe7c9de689cc33b39668683db6f763675bdb02e956fee00	t	2026-04-17 13:25:45.760191+00	2026-04-10 13:25:45.76714+00
1fa6e146-26d9-4500-8e27-a9ab92487dea	a2375bac-4a9f-4ed8-b674-a1807543c744	k7j4zM1pmWNIDXRMPdEvu3tVLPOQPoSmq5l-8j6vaAQ	b8a428321479b241dfb18ecaa23b38bd333a5df813783ea3bf1fdf0569b13791	t	2026-04-17 13:30:45.403934+00	2026-04-10 13:30:45.409977+00
8c2a9fb0-f4a3-4e03-847d-2a2e68f6ff3f	a2375bac-4a9f-4ed8-b674-a1807543c744	qH6nTdOmY1hztKdLzhJuugBgufBcwPGIhSZ-Zi4EIP0	b16c207ca34421fc92cd197c28316452a6b9ee91f6894d1e2dbaae375dcb1f19	t	2026-04-17 13:35:45.572005+00	2026-04-10 13:35:45.58767+00
21b24262-9532-4567-b03d-2ac0f4704bfa	a2375bac-4a9f-4ed8-b674-a1807543c744	nnogmECI_4zPoJqd7se0bop38nH1E5IbKB2IqQnnUy4	85aebe4c4ddfab9aae1d19ea187e356d64af6dd3f6d1bbce537d06467fbfaf26	t	2026-04-17 13:40:45.939332+00	2026-04-10 13:40:45.976619+00
a246cc72-7ff5-4a4a-ae32-4927b56106ef	a2375bac-4a9f-4ed8-b674-a1807543c744	m1E4TxoMqN7FceB80OqorsQNy-CYNX5y_p5Y6AEvTWI	2e8c4532935971ed8036c1465cefaebc3e2fc671d1f03017d799ce3c2e1c9d25	t	2026-04-17 13:45:45.584895+00	2026-04-10 13:45:45.595562+00
5dd192e5-df2b-4a49-a7e7-c05db2249045	a2375bac-4a9f-4ed8-b674-a1807543c744	WaZSdQ0dzjJVjHL0pI37dRkrBSTFtMH45ygsSjY1Ue0	352e0877b447aef71b746e2f85c8a8c9f5c65ec209de1f4c17053268244e73ba	f	2026-04-17 13:55:46.369548+00	2026-04-10 13:55:46.410003+00
1f7497c6-0fb2-4ed2-ba50-df911b2a300c	a2375bac-4a9f-4ed8-b674-a1807543c744	qxjItHu2CDZVFfwJfFQBbJmaDhYWiiTpLfzDqU-5Zr8	cd5614c32ece59c8e1c198cf04f03448e8593060476bdfaa30240042e2537725	t	2026-04-17 13:50:45.507285+00	2026-04-10 13:50:45.513038+00
c90327a1-c2ca-48ce-a747-3637b5e8b223	a2375bac-4a9f-4ed8-b674-a1807543c744	hNTGxypVYWOhFbcoLy0SU109zB7n2E-DQpK70yv1OFQ	6d6d9292cf99f9f824ba851e9c9326f00a7f630ce0764aa948eef3b066102da9	t	2026-04-17 14:35:45.905312+00	2026-04-10 14:35:45.913624+00
8cb7404e-3f4a-4dd6-8d94-e325e6a1eaf0	a2375bac-4a9f-4ed8-b674-a1807543c744	HGyb9MSq5nkRIAJElGeKQX7OnKRVXVhzrJBOR_u0YcU	c4d9d5ccafbf9147aaa0c668b3cfb3b1eba69e7fd22f2be67cb23def718aafd9	f	2026-04-17 14:15:47.293772+00	2026-04-10 14:15:47.334359+00
f38d4042-4ce8-4d23-9072-328a386c4933	a2375bac-4a9f-4ed8-b674-a1807543c744	sGHo8PRpnmcbxcDTrMyH-7aa5vFRBa3dEAnvm8LILi0	6772db96207eb89231c87c70757fd0180c8442a5cba594461e66802ec6fc6eda	f	2026-04-17 14:15:47.545994+00	2026-04-10 14:15:47.58363+00
538e08e8-951e-4cf1-83aa-96421c3ffa13	a2375bac-4a9f-4ed8-b674-a1807543c744	k70iTvNJbE_lYTgJKYkFNMZ2OphMqetC3NuDfh2kuZo	042e535283927b742441f2b485cb08109e6adf899a1655f2077d7e96fa626a4d	t	2026-04-17 14:40:45.650171+00	2026-04-10 14:40:45.656058+00
baa32bc9-8ba8-45dc-ac6e-43d070c37848	a2375bac-4a9f-4ed8-b674-a1807543c744	Qe23bZRgzAbmdk5qnwc1so4k7S5u5k4Gr8fx-CrjE64	30a80229f4a1271c08ed789bfb1b0d297d453583df8067484fe54a5b51bf6b90	f	2026-04-17 14:15:47.74912+00	2026-04-10 14:15:47.834264+00
9191a898-a430-47c2-ade8-b6289c7bd173	a2375bac-4a9f-4ed8-b674-a1807543c744	HYJBm72TLz4YWFBXsZxJsGrBRee15HeOCG6wkuE5BBg	e3dbe97b4474bac532f3f3df7322ae64f43691ae8d1e58caa39c1cd3f830aa06	t	2026-04-17 13:55:46.569492+00	2026-04-10 13:55:46.623525+00
77133b71-7cc7-4da5-9e1c-d1e52fab2ee3	a2375bac-4a9f-4ed8-b674-a1807543c744	ETsNAt6hsWwlxR6aHf-qfsd1AYTISvXg0PZ584ytsUk	cd0ea5a59f1237e0605bdcf96e82ec3ac94d99378d5813f023cd8845dda6103e	t	2026-04-17 14:45:45.89873+00	2026-04-10 14:45:45.904275+00
a29e3c23-7eba-4f53-812c-45f452296b22	a2375bac-4a9f-4ed8-b674-a1807543c744	KzhDQ9W6kqn8zQhIDZIJ60nDoCdVPwoLLcn7mgHRRqw	70e350ea767b001478f85d90e069878c28505b60bc1b94a17474405fa5d2b74e	t	2026-04-17 14:50:45.88221+00	2026-04-10 14:50:45.899588+00
6d6cb661-08b0-4b1d-8c0b-80a7386783b8	a2375bac-4a9f-4ed8-b674-a1807543c744	Uz9Bxz7KVl2yKbxvtJq2Z2RSFVhN8qyswJYW89ZGEGo	d9505eb3424d17bf5d7fab886d6b604cb6f4dbab28946846b425cd268b7b4f31	t	2026-04-17 14:55:46.364551+00	2026-04-10 14:55:46.387212+00
a4751816-2690-4f6b-89d2-0691ca54e347	a2375bac-4a9f-4ed8-b674-a1807543c744	QcdGUyFlZOvudzdDiSzE1OryqC4nhKX1zV1dKBqyDWk	06b80c37754b872c7dc57567c70979862a9aae8847477d2a31b9e4ccc9ca9229	t	2026-04-17 15:00:45.570476+00	2026-04-10 15:00:45.577644+00
06fcd994-403f-4f72-aa3e-9677d63dfa5a	a2375bac-4a9f-4ed8-b674-a1807543c744	Cg30HgaSS0yWG4vzVUqlND2bZURR60pqt8rV0BCv-6k	aad8a712e339e1960159f8dd0ca639bfac2e87d57094d7e0d0c4947b7e992c63	t	2026-04-17 15:05:45.6947+00	2026-04-10 15:05:45.703749+00
37b1f9c0-9721-42c2-be82-9623cde32949	a2375bac-4a9f-4ed8-b674-a1807543c744	pmtixdad_Mqo5UCw6P7yij-fwbyTDceB3jSrP5NRN5I	34bd5d5fdcd61b7f06dd9261b9059c215f90310ffdfaa0241d98125f6a9f0e2c	t	2026-04-17 15:10:46.848013+00	2026-04-10 15:10:46.869194+00
6f7568b6-b410-40ce-8d82-cdb1d5956f84	a2375bac-4a9f-4ed8-b674-a1807543c744	oabMrHZ93eVQtqluZsLrnMGRBhNBRXsP9xl74XQMyVY	c66c849bf435a9c87b7d110cdbd68cc7ae9c0385bb6d4cc7d21a9472a5cb4b9b	t	2026-04-17 15:15:45.596317+00	2026-04-10 15:15:45.602047+00
97b43e61-d52e-4c9a-8550-73292e18ae44	a2375bac-4a9f-4ed8-b674-a1807543c744	Hm3dfLiFMKjY2Fz0TKOW-9v8hSl6LqqNLkPZFP1fa9I	162e5963b2546a2d47945b61433678880f441e1ecc849ccca12181e91a1b4a93	t	2026-04-17 15:20:46.118084+00	2026-04-10 15:20:46.147687+00
9406e97c-a55b-4c71-bce1-4a0cbac0dfae	a2375bac-4a9f-4ed8-b674-a1807543c744	f-49qPf5ycRT4ywNYwdEHJXvlZExZhrSjdDv4VXYV3s	f67cdabe840a69f0ca7522595ddf7bf20a3b17427c2d74ddc3070d674a5703ca	t	2026-04-19 09:40:57.944522+00	2026-04-12 09:40:57.95858+00
f21dd715-1c48-486c-9ded-26fba982ce73	a2375bac-4a9f-4ed8-b674-a1807543c744	Gbk0pym6nwkcq96KHtFKM_WRcd9eKsWDk1PlVttW6zU	32172e3057ed57dcb8a835d08140065b80a3458f089aa216a8ffb5dd54955116	f	2026-04-17 15:30:45.95655+00	2026-04-10 15:30:45.990752+00
3f50701b-ca07-4975-beb2-60ae78a8698b	a2375bac-4a9f-4ed8-b674-a1807543c744	aT_Lt5n_HTzelZx7YbZiMZ3GcTmioRx2195XthdPh7g	96e53ca1c6b87387eb4fc09b74cf4c34443de73eaebe38e3ca5e16a12c76cf2e	t	2026-04-17 15:25:45.671147+00	2026-04-10 15:25:45.678784+00
7e2f18eb-7fca-4c80-b8e9-724b3438d16a	a2375bac-4a9f-4ed8-b674-a1807543c744	HlZnmoE1I8iS4veoGLpaA01TlIL-oC4707aZc85EsbQ	8fb732d4b85420331aab46021422a873a609e3f30d34f9541fd9b667b051e4ae	f	2026-04-19 09:42:26.934932+00	2026-04-12 09:42:26.950806+00
ea8a7529-d9fe-40bc-bda7-c664cd7d9bfb	a2375bac-4a9f-4ed8-b674-a1807543c744	KsVfmRNwDXYp1HkjkROj-H_kHI05U_Y44O5FYZg9gc4	4200a2f682ec77226ade6633a0416cbb8d110264ecee3fa4d97454ac73db8991	f	2026-04-19 09:40:57.892309+00	2026-04-12 09:40:57.900912+00
65682829-fd96-4fe9-b0bf-71563467e068	a2375bac-4a9f-4ed8-b674-a1807543c744	wsWHnYuIt7XA1Vc42rNDBk1KoEvykb0_RujTYgnd3uA	02a040c3fb4c3156aee4ed3f104510e11d6f0f5c7f6c2fc1955517379dabda6e	t	2026-04-17 15:30:46.21394+00	2026-04-10 15:30:46.237057+00
9d3a5d8a-396c-4a70-8239-ab36668ab3e4	a2375bac-4a9f-4ed8-b674-a1807543c744	fVUtyfGnRGtMyP-cpdmUSvqF6d0Z9M1QtkkIqoMrUKg	fbe551edea127a784f7892b8c53178cbaa572b5c91f027ea36c4aa05fe88b73e	t	2026-04-19 09:42:42.904189+00	2026-04-12 09:42:42.906148+00
f6e0ccc4-b7a6-48bb-b193-a1d5bd2a20e6	a2375bac-4a9f-4ed8-b674-a1807543c744	lGDC1uT0M-VxF-HCREWTUFmy1dj8px63bBzmoS_s50g	929e312864d44f0df7168e7c302b21e86ac4f41a5917fe6a0b3cd80ef7fc9c0a	t	2026-04-19 09:59:25.258534+00	2026-04-12 09:59:25.274341+00
517114b5-e95c-4d28-beb7-8d028ab4b948	a2375bac-4a9f-4ed8-b674-a1807543c744	IL-jeDwyjz8cZnyDnOzxAtlqEEbqr_OsUGHXwA_iYqE	6e51cf97cf4ed990d82f7313739c216f5009991c4df794441111355cbcef762b	t	2026-04-19 10:17:44.264575+00	2026-04-12 10:17:44.267928+00
0bd54983-256a-40c0-b450-f6ba0c03cca6	a2375bac-4a9f-4ed8-b674-a1807543c744	L3iWCneWZRMQmiZA1dryaplBtX2Qj1UTVUTIlRosC5M	1e1b71d9dc47628143a2ec17e6fe41fb40480d9cc6c1b9fcb18a915976428579	t	2026-04-19 10:33:48.568232+00	2026-04-12 10:33:48.571809+00
12740b15-af5f-4504-a33d-5c189f5ae9cb	a2375bac-4a9f-4ed8-b674-a1807543c744	DnbzjBO-Q3_JPmTuu3pGDuOnvaIJUuDQBxMbjyu3v6Q	d4b9550b3b5e29b0c01cf15a14685b26b5171a8401a5124534133a0386e3d74d	t	2026-04-19 10:33:49.674421+00	2026-04-12 10:33:49.675002+00
bfff3e6d-58e3-4c81-92b8-caff56e52f94	a2375bac-4a9f-4ed8-b674-a1807543c744	zDHv26ddXvmLUzoUa47zY_RaRrf1_-b-LV6us21wgtc	d97679ed0262d598d3e7a7ce59f2ce260f93c1ec025de06ff4f6ccb5b8f5b35e	t	2026-04-19 10:33:50.746549+00	2026-04-12 10:33:50.749013+00
1c92c37b-d3f2-4bdf-8207-25d79575cab5	a2375bac-4a9f-4ed8-b674-a1807543c744	BCsLb6me72596-dC49KkT5Y1yb6UFgARLYEbaEvj000	a91b859d66b041ca532ee9abeb2713fadce23c486a5fc27112a6a6bcd233e2f7	t	2026-04-19 10:34:01.594812+00	2026-04-12 10:34:01.614038+00
dd19838c-a7e9-46af-8185-4cae9b953c48	a2375bac-4a9f-4ed8-b674-a1807543c744	SWJmmwI_YNtF7s8DdasoZwrjAuG8ovwl4SvVzk9mtiw	2833fe08fa0b1f035bc1a10c76baae86ee58b14e99f676835f91fa862c4471a6	t	2026-04-19 10:34:03.697406+00	2026-04-12 10:34:03.698585+00
9c9cad3f-03aa-4c36-9100-81bb836f6457	a2375bac-4a9f-4ed8-b674-a1807543c744	Y-uM5bpSPQIhiJAmWxTfIOUYt7t0sP872P1cPGlTz8E	8a7b53c35cce9cf99f4d312c2dfd2765080e0a64031874eca4bd7ea181cb2156	t	2026-04-19 10:34:05.106125+00	2026-04-12 10:34:05.122777+00
39eb1ada-f7cf-4112-be38-b3ade3730ec9	a2375bac-4a9f-4ed8-b674-a1807543c744	BFCcfnSMGKou4zMEP1kleDfPS9TocQyqw02gHd8ztNc	6c919781c91a059c35831f0b39d44aa3c53a52a3da37849fb8a699cb16703f2a	t	2026-04-19 10:45:32.818516+00	2026-04-12 10:45:32.821445+00
ffe8d6c2-db61-4d04-bc0a-f40e189e3737	a2375bac-4a9f-4ed8-b674-a1807543c744	WsiQwABlII-MDVp3hbLtQObwZ1ZpTOE91zxazpRipWE	857b58cf81f3ebedb51fec6b3879b07e316040260e7ea155199cb97f5d0ace22	t	2026-04-20 12:07:29.504451+00	2026-04-13 12:07:29.505385+00
19c6b68c-eb34-4edd-8eca-a0b1b991ae6e	a2375bac-4a9f-4ed8-b674-a1807543c744	cpkTs1mglo60enADk-WYlZZl5FJ-Sj2SkOp1KrChKuE	3469b11b56c2dfee58a401d22261707c1d7a81652cd11c5c1a9f50fb45626bc2	f	2026-04-20 08:35:26.031418+00	2026-04-13 08:35:26.034441+00
d0b3b937-d5dd-42cd-9975-4832262ff421	a2375bac-4a9f-4ed8-b674-a1807543c744	UBL3SHchyRuqGgE8ecLdZTZbYz8ekbjPTdeQgsguXfE	05ee1db3a3bad5bbde6ed7fd8baff9ca74453be51fb30593fc5d1bccea457623	t	2026-04-19 10:58:51.474776+00	2026-04-12 10:58:51.483161+00
6be3799a-b695-46ac-9f3f-5506aa52b3b8	a2375bac-4a9f-4ed8-b674-a1807543c744	I8ZRx4_EukQsb8Hxxm8QxI6cdYBqbWb8SUbTxMl4EWg	16d56ad10544167d6406b5f261c993462d841c0d8ea153b4ce2623b10316d4bb	t	2026-04-20 08:35:26.054143+00	2026-04-13 08:35:26.060332+00
9c5c7577-f11f-45f8-9d0e-f25d95bc87dd	a2375bac-4a9f-4ed8-b674-a1807543c744	zb3oC6DpMmlte3oYwWdS9jAIh2nrw6SpRX3JXoQ2DHE	4d2b01482725e01f2164918ed58e49f5748a20d843ecacbdf40b9191738070c0	t	2026-04-20 08:55:28.587881+00	2026-04-13 08:55:28.606753+00
d4bd1073-b3d3-47fc-a7d5-9813ce3a0963	a2375bac-4a9f-4ed8-b674-a1807543c744	xxiKEDHLl3U3Cb13hgT9gQ8spkw-VV68VrlXLU6D5mI	a6b511c109ecb2cd43b8e3d1d3a630ef87eb82a930b1ba7d850d8b4ed4701e49	f	2026-04-20 11:59:58.614104+00	2026-04-13 11:59:58.622318+00
f4816340-1d49-44df-9212-add6e39174e0	a2375bac-4a9f-4ed8-b674-a1807543c744	ryJTzPnUjWaq_mpON8D0-g0DUVFAvnbb4Zm156cVkdE	028226e67b310e2097ef3e5f3ec8fda981abffd9c4971123249625f871feb271	f	2026-04-20 09:17:54.797556+00	2026-04-13 09:17:54.798839+00
e2412b9e-9b48-4dda-8f13-5a6e3c1a8b29	a2375bac-4a9f-4ed8-b674-a1807543c744	PEb4egckHht2uM6W4VBrb-DjcGsfnPZw_76b9cz1vDo	2e64bebf37268be65fc622aab63339d7abd79b084fb4ad614f92ee95a602bac5	t	2026-04-20 09:14:45.337722+00	2026-04-13 09:14:45.35208+00
857f56c0-778b-454c-a932-5f332338402c	a2375bac-4a9f-4ed8-b674-a1807543c744	hOsHKOrzeeaBZBR_b-4AnGwUpb-eCQxCcgb-LWgTB8o	82625002a050e017c45e8c7d3ba64ada48909acff1aabb4b145bc00ff86e5901	t	2026-04-20 09:17:54.810718+00	2026-04-13 09:17:54.812896+00
9e022250-83d4-4138-9d98-9b293be3280f	a2375bac-4a9f-4ed8-b674-a1807543c744	KJCDY-H1G92b5gGAaN9PrczYyrslM-BWHKyj9d9KqiI	f6c4856258846944cf90881250f7575dd034ab11ea18752ee8e2c4ce2e46d71b	t	2026-04-20 11:43:39.736385+00	2026-04-13 11:43:39.756087+00
4d39e199-c4e0-47fe-af92-966ed1a2fb3c	a2375bac-4a9f-4ed8-b674-a1807543c744	KJ0ckj947kfERvQs8qc1U8QnhcTlQ_U7qlQEW7_WiqA	b872eda1a6e28caa7ca7e907e95728bad5a3f70aaf4b4a8e1b5ab7cbc73547de	t	2026-04-20 11:55:51.199262+00	2026-04-13 11:55:51.227014+00
67886c4f-2095-4b2b-9224-d3e2d0295800	a2375bac-4a9f-4ed8-b674-a1807543c744	PHGhQfvx31NoCHkCodW5Ez66xYnHacLlgzSetlM9eik	ef14c0898776f7a530aed8b90a7cf0e591c2717ad7e9083b31dfe78f350df2ea	f	2026-04-20 11:44:58.909056+00	2026-04-13 11:44:58.909405+00
c96bc223-4fcf-4a98-9e07-bba82d15833b	a2375bac-4a9f-4ed8-b674-a1807543c744	FCOr3x_iY9klcCUbOOSnlL0ywYDzg600Bpayir3EO7A	d7f3cfa5c6c63fe36a72d7d16bf50676d9b453bc6f487a78eb870ad10a5cc190	t	2026-04-20 11:44:57.160736+00	2026-04-13 11:44:57.164466+00
3ac99d81-2665-44f9-9c93-08408115f8f6	a2375bac-4a9f-4ed8-b674-a1807543c744	SMdN4C4TIRIhNn2mF-PzpLazcISPFjDXRnjEIHztPVw	7dece57e9dbd09ddae942f0df4f4a4b5f09b95e54314c2eb8a151420715a3198	f	2026-04-20 11:49:36.599707+00	2026-04-13 11:49:36.601871+00
1de815c2-b9f8-4e8b-a160-8f178ec196ed	a2375bac-4a9f-4ed8-b674-a1807543c744	nyuOYnziPem5r4oedazrjuTMO6WO1mxSc1cRuPh75r4	4b6fee4358bd37ee8d7985ddbd46c65e0f77857287470a8545da808270bb6acf	t	2026-04-20 11:44:58.949804+00	2026-04-13 11:44:58.956085+00
d91ff925-9fd9-48f5-b890-2d9d049a2b6e	a2375bac-4a9f-4ed8-b674-a1807543c744	TCp3a9XOvPyMLfIKj0-j3rzZzPwRYbcQI6DdCeiw-aw	08debcbc224c01f4b3561378a9bcdb53394a8e0b0b2dcbd06584e5f244160d3c	t	2026-04-20 11:49:36.617204+00	2026-04-13 11:49:36.619177+00
0732615c-2a7a-4418-822f-45fce8503e2c	a2375bac-4a9f-4ed8-b674-a1807543c744	0wQlOEbaLYv5LilSh5dC9eRdQ6XH4okb4jHSE1VRT8s	ff10465eb42d7a3fe8d536780e13d44038b563e165aca7d3d9f705c91f38f111	f	2026-04-20 11:55:46.414815+00	2026-04-13 11:55:46.436247+00
b5b466b0-2426-4311-b7a6-12550eec2aa5	a2375bac-4a9f-4ed8-b674-a1807543c744	YG2rDUVXbbay92Oiu3NKNf8R4q4RKBVhfBM6-zynBBw	b6e83a1a02e2f6e60e3affa3af17d54e2268491e01bba480f33966e905725180	t	2026-04-20 11:59:58.657837+00	2026-04-13 11:59:58.679021+00
9caec60b-7c01-4060-9864-98c3f576d3e3	a2375bac-4a9f-4ed8-b674-a1807543c744	MMpj4ruf1of5CdAjqv1C2n8nKg7S7v1LXZV_faJXTdM	8e2f1da69312f9f2242da51a63beeb66e9f493e12a28ee9c9e25d1528010245e	t	2026-04-20 12:07:24.363725+00	2026-04-13 12:07:24.385951+00
5149fe4c-20ae-4150-8389-d37e892d5518	a2375bac-4a9f-4ed8-b674-a1807543c744	z_1LAeDlxcvBZ9jpizQZ9ah5ZbGGIV4xTTsUYU9W_ho	881463d184cdddf311ec4486217ab36d57240615aed06eda89bad71d8674dc23	f	2026-04-20 12:07:27.781565+00	2026-04-13 12:07:27.796974+00
5e7938bf-0d41-4449-8c9a-87f0bc8a6660	a2375bac-4a9f-4ed8-b674-a1807543c744	kkG6OYdKqZtpuWwTV0kRMlXL8wko3FPKevvGqi0bMbo	c5635cc866226bb3f86dff6684f6823280e4508b8c89eb28b8d5448c28fd39b1	t	2026-04-20 12:07:26.241778+00	2026-04-13 12:07:26.260436+00
813688ee-3908-43f1-9cdd-9660b4a5f8ca	a2375bac-4a9f-4ed8-b674-a1807543c744	-nDSPZYVXbTz9Cle_DhwrCpdFc_1-VOPoueWK30xKM4	df24702326153a04ef47c6fc8771361d99e08121959fb2af5fd92c80be36d450	t	2026-04-20 12:07:27.830843+00	2026-04-13 12:07:27.844906+00
a791eea9-66e7-45a9-b2fb-2bed84a6fd61	a2375bac-4a9f-4ed8-b674-a1807543c744	PFb4oqjuGt2qceQb6Wh0iLRy7jy8iRg_OibOy9mI5Vk	8fd9bfaa10d110a1002393c699826c7a2d7d27b64abbab8c53f840ba6e80871e	t	2026-04-20 12:23:52.177613+00	2026-04-13 12:23:52.182274+00
fb9e439c-6a8a-449b-bb73-d736312b89db	a2375bac-4a9f-4ed8-b674-a1807543c744	6Fa03bNiWEDJp2xtupBV9Ip2pbXj2ZxnqrT1o5TxznY	1029fb427e44780e082f6d1f0c69f3cb14dfd0718fc5172363d12c06c6260c02	f	2026-04-20 12:07:29.49697+00	2026-04-13 12:07:29.497354+00
949cd7b5-28bb-4b9e-a5f1-4823aa3262e5	a2375bac-4a9f-4ed8-b674-a1807543c744	iZNhlO1I0WEidXYGn4e0RxiQF8ppEe9UJFSNu2IL2Iw	fe240d62715a2cc38a68b1d3fce96dd0368841ebc97043edf081299bd9333ec4	t	2026-04-20 12:07:28.778529+00	2026-04-13 12:07:28.778895+00
7807c336-316b-4e03-a479-06ac8a91d02b	a2375bac-4a9f-4ed8-b674-a1807543c744	Gih9lojCUOa1cDZW-sa2wJrU7w0RSzufSpvA71l0FFo	b4938c6b8db4d1ac3be7e021c6c9b38cc363dfdef4d95ec3c941582d88f3cdc0	f	2026-04-20 12:07:35.402036+00	2026-04-13 12:07:35.402409+00
b0fff978-f766-404e-9171-b01440aca90c	a2375bac-4a9f-4ed8-b674-a1807543c744	1yTAoPQBbz26dZJ2na2HXq__H17eoj2Xo3-TXF1xXck	dd46d50ee4d2494373c7010407c3a192e02493d15125b05288f23859e6d00665	t	2026-04-20 12:07:29.89284+00	2026-04-13 12:07:29.893141+00
0c49463e-e741-4a53-af8b-29d4e613c71a	a2375bac-4a9f-4ed8-b674-a1807543c744	a5xrCjacWnWBSN1BXEeHS4jUdz79aTyEIzjUmw31QP4	7c64667eccdd13598d37d69ce06a5edc362e27da7475954b3bd3266fe9e625f9	f	2026-04-20 12:23:52.161632+00	2026-04-13 12:23:52.165011+00
4b326869-5faf-41de-9bab-9f985c447cec	a2375bac-4a9f-4ed8-b674-a1807543c744	efhXgazl3ZNrf79FJTbceBq5nLlNlKGVZ0yUfRIC4wk	79af1b09606e0af34a422d89cb1940e331a64f359e744994d06c19c8dd3e9954	t	2026-04-20 12:07:35.408781+00	2026-04-13 12:07:35.409078+00
4c205f8f-d820-44ee-ac87-274337786d7c	a2375bac-4a9f-4ed8-b674-a1807543c744	BukiUp5jONem8TfjJAkfb8Hb3eBTI37uCemelv7LU4g	ae780f5d74dfcaac80191df615641435125e495494739b378a4a943d323fc62d	t	2026-04-20 12:43:54.507221+00	2026-04-13 12:43:54.595787+00
88c10837-e7ba-40fc-a9bd-3861018463d4	a2375bac-4a9f-4ed8-b674-a1807543c744	BBOvm4R1aYcmPqP6dIev_zJnW41ef7xH1SS6CcZ231E	d5e50b18b328e792d9f78387f97beb10c4161a8c396cb27df52c91cd8c29ae9a	t	2026-04-20 13:04:38.027931+00	2026-04-13 13:04:38.04186+00
5e7d55e6-d082-4e32-bcd1-dbe2652d0d05	a2375bac-4a9f-4ed8-b674-a1807543c744	tVa0MgbPOC8wuayzLPfPSmrmpjfgfsRIcqqidZwAxc4	2f37e07c9707a4d83dfc1103f24ffcb5d6866c3ad4a1f1e17bfe0e5f4dcebee4	t	2026-04-20 13:24:37.701522+00	2026-04-13 13:24:37.706254+00
d0380947-4513-4572-ba4a-43c5b7f8df17	a2375bac-4a9f-4ed8-b674-a1807543c744	MPx9AjUnZMWAtMpYVrXBMCTElMen5flJVH6NMZO7oao	d8d7bc7277db5b369c3ea7b5d5e916972bc7005cbf2a5047e7d5b59e79a7a211	t	2026-04-20 13:44:22.765836+00	2026-04-13 13:44:22.780556+00
ddee49d1-222a-441b-b487-56219d73adff	a2375bac-4a9f-4ed8-b674-a1807543c744	6JsJGV1ecNTxdv7CY6TTQnpeffx398bMW3gAaIMW7OE	c8eafd0cedcdf1437c3c133f3af9b2bab98a035805409ce44ced3d54fd0c4521	t	2026-04-20 14:43:59.133597+00	2026-04-13 14:43:59.150183+00
c7c9f639-3796-4d95-aecf-82c42cfd54a5	a2375bac-4a9f-4ed8-b674-a1807543c744	e2WZtUt13uVu3RnN9ItmW5waMenKGGn-OqF-OtCTMoc	3b2aa0ac317abab65bea6af3c5be91c09f79f2063016aeec758186172f860ed2	t	2026-04-20 14:44:00.36997+00	2026-04-13 14:44:00.370531+00
2ac04075-2a46-48f6-9d58-b4052f391f13	a2375bac-4a9f-4ed8-b674-a1807543c744	baXfOyTTNIKZUTT391oWiLjwvM34VdhbqKSwDptFZuo	6657e6d1d6e0ca2be3e89c58a7aead6813e1ab5facd01ce84d43f90aece421dd	f	2026-04-20 14:44:03.222592+00	2026-04-13 14:44:03.237069+00
799f433b-88c5-4804-ab2c-1676c50d04d3	a2375bac-4a9f-4ed8-b674-a1807543c744	qMHLOygsYN666qES82x3cuiACMdaIPCXWquw07HyXDQ	b0875fefbf9350a6fcd75bf4a96a98950b537cf290cdee7ad667c3d1ce2f0724	t	2026-04-20 14:44:01.046693+00	2026-04-13 14:44:01.047038+00
74f63987-7cf4-44f0-989f-5b1e4a42c62e	a2375bac-4a9f-4ed8-b674-a1807543c744	SyzZ9ICd9kSrZkkFZpL6hN5XR4r41B1UElWRIxA5mC0	34ff0979098fec07eb35296e1890f8961873f73979e9854dc46f2f0b86237ccd	t	2026-04-20 14:44:02.063521+00	2026-04-13 14:44:02.063926+00
2d2cec39-e40c-47a0-8135-75abb92b19e4	a2375bac-4a9f-4ed8-b674-a1807543c744	gTyflpOAfJ8e8Zes7E1xF1AUUTZhjtwYlNIRk1DTnSM	4fb6613f9a886ba2a9d7f59aced39550821d8a96b6f9a6bbfc401005aad64090	t	2026-04-20 14:44:02.898771+00	2026-04-13 14:44:02.941875+00
\.


--
-- Data for Name: remboursements_transport; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.remboursements_transport (id, numero_remboursement, instance, type_reunion, nature_reunion, nature_travail, lieu, date_reunion, heure_debut, heure_fin, montant_total, requisition_id, created_by, created_at, trans_titre_officiel_hist, trans_label_gauche_hist, trans_nom_gauche_hist, trans_label_droite_hist, trans_nom_droite_hist, signataire_g_label, signataire_g_nom, signataire_d_label, signataire_d_nom, reference_numero, pdf_path) FROM stdin;
96dbc622-acfe-4486-8543-1296dd2c538d	REM-ONEC-CPK-2026-0001	cpk	bureau	test	["test"]	siege	2026-03-20 00:00:00+00	13:41	14:42	50.00	7f97d337-7e1e-45c7-807f-d173e7431c58	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-20 12:42:39.122111+00	\N	\N	\N	\N	\N	\N	\N	\N	\N	REM-ONEC-CPK-2026-0001	/uploads/tenants/056909a8-ee0f-454f-9b6b-728c73077d55/remboursements-transport/2026/04/REM-ONEC-CPK-2026-0001.pdf
\.


--
-- Data for Name: requisition_annexes; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.requisition_annexes (id, requisition_id, file_path, filename, file_type, file_size, upload_date) FROM stdin;
1b006357-3d6a-4763-ac01-f88c16d0238e	349d8fc1-c86a-445d-b77c-728c27259ae8	/uploads/tenants/056909a8-ee0f-454f-9b6b-728c73077d55/requisitions/2026/04/REQ-ONEC-CPK-2026-0008-annex-1.pdf	27012026 ONEC CPK Offre d'emploi 2026 V260126 1030.pdf	application/pdf	104593	2026-04-13 11:50:30.920092+00
\.


--
-- Data for Name: requisition_approvers; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.requisition_approvers (id, user_id, active, notes, added_by, added_at) FROM stdin;
\.


--
-- Data for Name: requisition_status_history; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.requisition_status_history (id, requisition_id, old_status, new_status, comment, changed_by, changed_at) FROM stdin;
1	7f97d337-7e1e-45c7-807f-d173e7431c58	EN_ATTENTE	AUTORISEE	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-26 13:56:38.939659+00
2	7f97d337-7e1e-45c7-807f-d173e7431c58	AUTORISEE	APPROUVEE	\N	49a1c5f5-2d47-4ad6-8549-13c781a16223	2026-03-26 13:57:02.857678+00
\.


--
-- Data for Name: requisitions; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.requisitions (id, numero_requisition, objet, mode_paiement, type_requisition, status, montant_total, created_by, validee_par, validee_le, approuvee_par, approuvee_le, payee_par, payee_le, motif_rejet, a_valoir, instance_beneficiaire, notes_a_valoir, created_at, updated_at, req_titre_officiel_hist, req_label_gauche_hist, req_nom_gauche_hist, req_label_droite_hist, req_nom_droite_hist, signataire_g_label, signataire_g_nom, signataire_d_label, signataire_d_nom, reference_numero, pdf_path, is_deleted, deleted_at, deleted_by, import_source, service_id, signed_by_id, signed_at, dossier_id, examen_status, examen_commentaire, examen_par, examen_le, organisation_id) FROM stdin;
7f97d337-7e1e-45c7-807f-d173e7431c58	REQ-ONEC-CPK-2026-0001	Remboursement transport - test - siege - 20/03/2026	cash	remboursement_transport	APPROUVEE	50.00	a2375bac-4a9f-4ed8-b674-a1807543c744	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-26 13:56:38.943547+00	49a1c5f5-2d47-4ad6-8549-13c781a16223	2026-03-26 13:57:02.857793+00	\N	\N	\N	f	\N	\N	2026-03-20 12:42:38.667597+00	2026-03-26 13:57:02.857796+00	\N	\N	\N	\N	\N	\N	\N	\N	\N	REQ-ONEC-CPK-2026-0001	\N	f	\N	\N	\N	\N	\N	\N	\N	EXAMINE	ok	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-26 13:55:09.409008+00	1
238a97a0-7b38-4eef-a504-e2de13865da5	REQ-ONEC-CPK-2026-0002	test	cash	classique	EN_ATTENTE_COMMISSION	10.00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	\N	\N	\N	\N	\N	\N	f	\N	\N	2026-03-26 13:30:15.836487+00	2026-03-30 15:22:14.654653+00	\N	\N	\N	\N	\N	\N	\N	\N	\N	REQ-ONEC-CPK-2026-0002	/uploads/tenants/056909a8-ee0f-454f-9b6b-728c73077d55/requisitions/2026/03/REQ-ONEC-CPK-2026-0002-bon.pdf	f	\N	\N	\N	1	\N	\N	\N	EXAMINE	ok	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-03-30 15:22:14.654646+00	1
46724f95-6834-4ce6-acd2-7a8b22f7eab5	REQ-ONEC-CPK-2026-0003	test	cash	classique	BROUILLON	110.00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	\N	\N	\N	\N	\N	\N	t	Conseil National		2026-04-13 09:18:36.423522+00	2026-04-13 09:18:36.423533+00	\N	\N	\N	\N	\N	\N	\N	\N	\N	REQ-ONEC-CPK-2026-0003	\N	f	\N	\N	\N	1	\N	\N	\N	NON_EXAMINE	\N	\N	\N	1
fe7b6a01-380c-4ff2-b99e-f9709f1e8726	REQ-ONEC-CPK-2026-0004	test	cash	classique	BROUILLON	110.00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	\N	\N	\N	\N	\N	\N	t	Conseil National		2026-04-13 09:18:48.176012+00	2026-04-13 09:18:48.176015+00	\N	\N	\N	\N	\N	\N	\N	\N	\N	REQ-ONEC-CPK-2026-0004	\N	f	\N	\N	\N	1	\N	\N	\N	NON_EXAMINE	\N	\N	\N	1
177705c7-efc8-406d-8351-06889f5ea59b	REQ-ONEC-CPK-2026-0005	TEST	cash	classique	BROUILLON	10.00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	\N	\N	\N	\N	\N	\N	t	Conseil National	tt	2026-04-13 11:45:46.450858+00	2026-04-13 11:45:46.450862+00	\N	\N	\N	\N	\N	\N	\N	\N	\N	REQ-ONEC-CPK-2026-0005	\N	f	\N	\N	\N	1	\N	\N	\N	NON_EXAMINE	\N	\N	\N	1
bd22cdee-c8f6-43d6-aa98-fa67372d0faf	REQ-ONEC-CPK-2026-0006	TEST	cash	classique	BROUILLON	10.00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	\N	\N	\N	\N	\N	\N	t	Conseil National	tt	2026-04-13 11:45:56.011023+00	2026-04-13 11:45:56.011034+00	\N	\N	\N	\N	\N	\N	\N	\N	\N	REQ-ONEC-CPK-2026-0006	\N	f	\N	\N	\N	1	\N	\N	\N	NON_EXAMINE	\N	\N	\N	1
4c303174-b263-412b-8f6c-7a9c10323bf4	REQ-ONEC-CPK-2026-0007	TEST	cash	classique	BROUILLON	10.00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	\N	\N	\N	\N	\N	\N	t	Conseil National	tt	2026-04-13 11:46:43.171429+00	2026-04-13 11:46:43.17144+00	\N	\N	\N	\N	\N	\N	\N	\N	\N	REQ-ONEC-CPK-2026-0007	\N	f	\N	\N	\N	1	\N	\N	\N	NON_EXAMINE	\N	\N	\N	1
349d8fc1-c86a-445d-b77c-728c27259ae8	REQ-ONEC-CPK-2026-0008	test15	cash	classique	BROUILLON	10.00	a2375bac-4a9f-4ed8-b674-a1807543c744	\N	\N	\N	\N	\N	\N	\N	t	Conseil National	test pour nous	2026-04-13 11:50:29.205742+00	2026-04-13 11:50:30.543016+00	\N	\N	\N	\N	\N	\N	\N	\N	\N	REQ-ONEC-CPK-2026-0008	/uploads/tenants/056909a8-ee0f-454f-9b6b-728c73077d55/requisitions/2026/04/REQ-ONEC-CPK-2026-0008-bon.pdf	f	\N	\N	\N	1	\N	\N	\N	NON_EXAMINE	\N	\N	\N	1
\.


--
-- Data for Name: role_permissions; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.role_permissions (role_id, permission_id) FROM stdin;
1	1
1	2
1	3
1	4
1	5
1	6
1	7
1	8
1	9
1	10
1	11
4	4
6	3
6	7
2	2
2	7
8	1
8	2
8	4
8	7
8	9
8	10
8	11
7	1
7	7
7	8
7	9
7	10
3	4
3	7
\.


--
-- Data for Name: roles; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.roles (id, code, label, description, created_at) FROM stdin;
1	admin	Administrateur	Gestion totale du système	2026-03-19 10:20:26.982965+00
2	rapporteur	Rapporteur	Avis technique et validation intermédiaire	2026-03-19 10:20:26.982965+00
3	tresorier	Trésorier	Prépare et vérifie les opérations	2026-03-19 10:20:26.982965+00
4	caissier	Caissier	Exécute les sorties de fonds	2026-03-19 10:20:26.982965+00
6	president	Président	Validation finale	2026-03-19 10:20:26.982965+00
7	secretaire_permanant	Secrétaire permanant	\N	2026-03-23 12:08:06.975109+00
8	secretaire_executif	Secrétaire Exécutif	\N	2026-03-31 09:28:33.305956+00
\.


--
-- Data for Name: rubriques; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.rubriques (id, code, libelle, description, active, created_at) FROM stdin;
\.


--
-- Data for Name: service_rubriques; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.service_rubriques (id, service_id, budget_poste_id) FROM stdin;
1662	2	58
1663	2	59
1664	2	60
1665	2	61
1666	2	62
1667	2	63
1668	2	64
1669	2	65
1670	2	66
1671	2	71
1672	2	72
1673	2	73
1674	2	74
1675	2	124
1676	2	125
1677	2	126
1690	3	118
1691	3	119
1692	3	120
1693	3	121
1694	3	122
1695	3	123
1546	1	30
1547	1	31
1548	1	32
1549	1	33
1550	1	34
1551	1	35
1552	1	36
1553	1	37
1554	1	38
1555	1	39
1556	1	40
1557	1	41
1558	1	42
1559	1	43
1560	1	44
1561	1	45
1562	1	46
1563	1	47
1564	1	48
1565	1	49
1566	1	50
1567	1	51
1568	1	52
1569	1	53
1570	1	54
1571	1	55
1572	1	56
1573	1	57
1574	1	58
1575	1	59
1576	1	60
1577	1	61
1578	1	62
1579	1	63
1580	1	64
1581	1	65
1582	1	66
1583	1	67
1584	1	68
1585	1	69
1586	1	70
1587	1	71
1588	1	72
1589	1	73
1590	1	74
1591	1	75
1592	1	76
1593	1	77
1594	1	78
1595	1	79
1596	1	80
1597	1	81
1598	1	82
1599	1	83
1600	1	84
1601	1	85
1602	1	86
1603	1	87
1604	1	88
1605	1	89
1606	1	90
1607	1	91
1608	1	92
1609	1	93
1610	1	94
1611	1	95
1612	1	96
1613	1	97
1614	1	98
1615	1	99
1616	1	100
1617	1	101
1618	1	102
1619	1	103
1620	1	104
1621	1	105
1622	1	106
1623	1	107
1624	1	108
1625	1	109
1626	1	110
1627	1	111
1628	1	112
1629	1	113
1630	1	114
1631	1	115
1632	1	116
1633	1	117
1634	1	118
1635	1	119
1636	1	120
1637	1	121
1638	1	122
1639	1	123
1640	1	124
1641	1	125
1642	1	126
1643	1	127
1644	1	128
1645	1	129
1646	1	130
1647	1	131
1648	1	132
\.


--
-- Data for Name: services; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.services (id, code, libelle, is_active, responsable_id, organisation_id) FROM stdin;
3	STAG	Commission de Stage & Examens	t	\N	1
5	STAG	Commission de Stage & Examens	t	\N	8
6	STAG	Commission de Stage & Examens	t	\N	9
7	STAG	Commission de Stage & Examens	t	\N	10
8	FORCO	Commission Formation Continue	t	\N	8
9	FORCO	Commission Formation Continue	t	\N	9
10	FORCO	Commission Formation Continue	t	\N	10
11	ADMIN	Administrations	t	\N	8
12	ADMIN	Administrations	t	\N	9
13	ADMIN	Administrations	t	\N	10
14	CT	Commission Tableau	t	\N	8
15	CT	Commission Tableau	t	\N	9
16	CT	Commission Tableau	t	\N	10
4	CT	Commission Tableau	t	f7829ef1-a8ac-42c8-8028-039ff34576b2	1
17	BR	BUREAU	t	\N	1
1	ADMIN	Administrations	t	774b00b8-1c8c-4317-987d-1b5df9fb552e	1
2	FORCO	Commission Formation Continue	t	1192cc31-6978-4393-99bf-273c6362a388	1
\.


--
-- Data for Name: sorties_fonds; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.sorties_fonds (id, type_sortie, requisition_id, rubrique_code, montant_paye, date_paiement, mode_paiement, reference, motif, beneficiaire, piece_justificative, commentaire, created_by, created_at, budget_poste_id, reference_numero, statut, motif_annulation, pdf_path, exchange_rate_snapshot, annexes, service_id, budget_poste_code, budget_poste_libelle, annulee_le, canal, compte_bancaire_id, devise, organisation_id, is_reconciled, reconciled_at, reconciled_by_id, bank_statement_ref) FROM stdin;
872afc61-6a74-40ca-b15b-fd514af8677a	remboursement	7f97d337-7e1e-45c7-807f-d173e7431c58	\N	50.00	2026-04-12 00:00:00+00	cash	\N	;;,;;;,,,,,,,,,,,,n	ki	\N	\N	a2375bac-4a9f-4ed8-b674-a1807543c744	2026-04-12 10:11:23.300868+00	99	PAY-ONEC-CPK-2026-0001	VALIDE	\N	/uploads/tenants/056909a8-ee0f-454f-9b6b-728c73077d55/sorties-fonds/2026/04/PAY-ONEC-CPK-2026-0001-bon.pdf	225.0000	\N	\N	II.2.11	IMPREVUS	\N	CAISSE	1	USD	1	f	\N	\N	\N
\.


--
-- Data for Name: standard_classifications; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.standard_classifications (id, organisation_id, raw_label, assigned_account, confidence_score, occurrence_count, last_used) FROM stdin;
\.


--
-- Data for Name: subscriptions; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.subscriptions (id, organisation_id, plan_id, status, trial_end, current_period_end, fedapay_transaction_id, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: system_events; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.system_events (id, organisation_id, level, code, message, metadata, created_at) FROM stdin;
4a690b8b-f2e4-41ff-9f38-1c74e3c278f6	1	warning	IMPERSONATION	Super admin impersonated user	{"target_email": "alainluka@onecrdc.com", "target_user_id": "f7829ef1-a8ac-42c8-8028-039ff34576b2", "organisation_slug": "cpk"}	2026-03-24 14:36:11.995744+00
\.


--
-- Data for Name: system_settings; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.system_settings (id, email_expediteur, email_president, emails_bureau_cc, smtp_host, smtp_port, updated_by, updated_at, smtp_password, email_tresorier, emails_bureau_sortie_cc, email_validation_1, email_validation_final, max_caisse_amount, last_weekly_report_sent_at, last_weekly_report_status, last_weekly_report_error, last_weekly_report_success_at, last_weekly_report_failure_at, organisation_id, whatsapp_api_url, whatsapp_api_key, whatsapp_agents) FROM stdin;
4c132f55-2566-4968-8595-23cacb69d3d1	cpk@onecrdc.com	kidikala@gmail.com	kidikala@onecrdc.com	smtp.gmail.com	465	\N	2026-03-30 15:20:11.24196+00	xhys kuze sqyn mraz					0	2026-03-30 15:20:11.24196+00	success		2026-03-30 15:20:11.24196+00	\N	1			
b8e9b988-0dd0-4d7d-b19d-e99cdc1ca0c6				smtp.gmail.com	465	\N	2026-03-19 12:40:43.134821+00						0	\N	never		\N	\N	1			
6da9a407-21f3-4d08-b0a2-4e124fc9b33d				smtp.gmail.com	465	\N	2026-03-25 12:03:38.967642+00						0	\N	never		\N	\N	9			
1de81377-b9db-4126-a81a-1582a4fce547				smtp.gmail.com	465	\N	2026-03-25 12:37:45.480115+00						0	\N	never		\N	\N	8			
d84a8b33-ff4e-401a-80de-73f03fbaf919				smtp.gmail.com	465	\N	2026-03-25 12:49:27.101354+00						0	\N	never		\N	\N	10			
\.


--
-- Data for Name: tenant_signups; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.tenant_signups (id, organisation_name, slug, admin_email, admin_phone, plan_id, status, reference, fedapay_transaction_id, error_message, created_at, updated_at, organisation_id, billing_months) FROM stdin;
\.


--
-- Data for Name: transactions; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.transactions (id, tenant_id, amount, currency, status, provider, external_reference, metadata_json, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: transferts_internes; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.transferts_internes (id, source_type, source_id, destination_type, destination_id, montant, devise, reference, date_transfert, execute_par) FROM stdin;
\.


--
-- Data for Name: user_roles; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.user_roles (id, user_id, role, created_by, created_at) FROM stdin;
\.


--
-- Data for Name: user_services; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.user_services (user_id, service_id) FROM stdin;
a2375bac-4a9f-4ed8-b674-a1807543c744	1
a2375bac-4a9f-4ed8-b674-a1807543c744	2
a2375bac-4a9f-4ed8-b674-a1807543c744	3
a2375bac-4a9f-4ed8-b674-a1807543c744	4
f7829ef1-a8ac-42c8-8028-039ff34576b2	1
49a1c5f5-2d47-4ad6-8549-13c781a16223	1
49a1c5f5-2d47-4ad6-8549-13c781a16223	2
49a1c5f5-2d47-4ad6-8549-13c781a16223	3
49a1c5f5-2d47-4ad6-8549-13c781a16223	4
49a1c5f5-2d47-4ad6-8549-13c781a16223	17
774b00b8-1c8c-4317-987d-1b5df9fb552e	1
774b00b8-1c8c-4317-987d-1b5df9fb552e	2
774b00b8-1c8c-4317-987d-1b5df9fb552e	3
774b00b8-1c8c-4317-987d-1b5df9fb552e	4
774b00b8-1c8c-4317-987d-1b5df9fb552e	17
1192cc31-6978-4393-99bf-273c6362a388	2
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: christian
--

COPY public.users (id, email, nom, prenom, hashed_password, role, active, must_change_password, created_at, updated_at, is_first_login, is_email_verified, otp_code, otp_created_at, otp_attempts, role_id, service_id, organisation_id) FROM stdin;
f7829ef1-a8ac-42c8-8028-039ff34576b2	alainluka@onecrdc.com	LUKA	Alain	$2b$12$UDwQ4ip2gA8/Q22SWFgmP.JLn7Lf1tfJFU8E55tnq.mL9mk909h7O	secretaire_permanant	t	t	2026-03-23 12:18:22.905672+00	2026-03-23 12:18:22.905676+00	t	f	\N	\N	0	7	1	1
a2375bac-4a9f-4ed8-b674-a1807543c744	kidikala@gmail.com	KIDIKALA	Christian	$2b$12$xC.6x21v3mhNd4wrdnu2pOsJn/boiG0jFtkQonrIllV8DD7gq6u2u	super_admin	t	f	2026-03-19 10:46:17.123027+00	2026-03-23 11:29:34.452464+00	f	t	\N	\N	0	1	\N	1
3d7b1905-4793-4c89-a581-4c2a7e7f9e44	kidikala@gmail.com	KIDIKALA	Christian	b2/.aX5uqnY4lhvTjHed4CiK	super_admin	t	f	2026-03-25 10:42:42.243451+00	2026-03-25 15:27:53.883888+00	f	t	\N	\N	0	\N	\N	8
49a1c5f5-2d47-4ad6-8549-13c781a16223	kidikala@onecrdc.com	KIDIKALA	Christian	$2b$12$CK81PN9/N2DcSKIQQQ2Ad.JZuGYcgEjqZ8nISnyxNKQcNCA5gxm6G	admin	t	f	2026-03-26 11:54:04.719221+00	2026-03-26 12:14:50.718932+00	f	t	163609	2026-03-26 12:14:50.717375+00	0	1	\N	1
774b00b8-1c8c-4317-987d-1b5df9fb552e	constantmoro@onecrdc.com	MORO	Constant	$2b$12$eYf6xT4yVfBVbFYOZLhFlOUrA/VP0NamG0CjMHzk//th7D4kpmU4u	admin	t	t	2026-03-31 09:26:41.782549+00	2026-03-31 09:26:41.782553+00	t	f	\N	\N	0	1	\N	1
1192cc31-6978-4393-99bf-273c6362a388	josephvangu71@gmail.com	VANGU	Joseph	$2b$12$QP.wBloibd5P0wkJQ0mmUONb8OQq3wnbLuGJARuQCmPeyCuI8lLQ.	president	t	t	2026-03-31 09:49:57.40193+00	2026-03-31 09:49:57.40194+00	t	f	\N	\N	0	6	2	1
\.


--
-- Name: audit_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.audit_logs_id_seq', 201, true);


--
-- Name: banques_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.banques_id_seq', 1, true);


--
-- Name: budget_audit_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.budget_audit_logs_id_seq', 30, true);


--
-- Name: budget_exercices_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.budget_exercices_id_seq', 7, true);


--
-- Name: budget_lignes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.budget_lignes_id_seq', 151, true);


--
-- Name: caisse_centrale_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.caisse_centrale_id_seq', 290, true);


--
-- Name: clotures_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.clotures_id_seq', 1, true);


--
-- Name: commission_members_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.commission_members_id_seq', 6, true);


--
-- Name: comptes_bancaires_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.comptes_bancaires_id_seq', 3, true);


--
-- Name: denominations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.denominations_id_seq', 14, true);


--
-- Name: organisation_settings_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.organisation_settings_id_seq', 4, true);


--
-- Name: organisations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.organisations_id_seq', 10, true);


--
-- Name: payment_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.payment_logs_id_seq', 1, false);


--
-- Name: permissions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.permissions_id_seq', 11, true);


--
-- Name: plans_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.plans_id_seq', 3, true);


--
-- Name: platform_settings_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.platform_settings_id_seq', 1, false);


--
-- Name: rec_num_seq_1_2026; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.rec_num_seq_1_2026', 52, true);


--
-- Name: requisition_status_history_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.requisition_status_history_id_seq', 2, true);


--
-- Name: roles_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.roles_id_seq', 8, true);


--
-- Name: service_rubriques_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.service_rubriques_id_seq', 1695, true);


--
-- Name: services_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.services_id_seq', 17, true);


--
-- Name: standard_classifications_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.standard_classifications_id_seq', 1, false);


--
-- Name: transferts_internes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: christian
--

SELECT pg_catalog.setval('public.transferts_internes_id_seq', 1, false);


--
-- Name: organisations organisations_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.organisations
    ADD CONSTRAINT organisations_pkey PRIMARY KEY (id);


--
-- Name: saas_platform_metrics; Type: MATERIALIZED VIEW; Schema: public; Owner: christian
--

CREATE MATERIALIZED VIEW public.saas_platform_metrics AS
 SELECT o.id AS org_id,
    o.nom AS org_nom,
    o.slug,
    o.plan_type,
    o.status_abonnement,
    o.date_expiration_abonnement,
    ( SELECT count(*) AS count
           FROM public.users u
          WHERE (u.organisation_id = o.id)) AS total_users,
    COALESCE(sum(e.montant_paye) FILTER (WHERE (e.created_at > (now() - '30 days'::interval))), (0)::numeric) AS volume_encaisse_30j,
    ( SELECT count(*) AS count
           FROM (public.payment_transactions pt
             JOIN public.encaissements ee ON ((ee.id = pt.encaissement_id)))
          WHERE ((ee.organisation_id = o.id) AND ((pt.status)::text = 'FAILED'::text) AND (pt.created_at > (now() - '24:00:00'::interval)))) AS echecs_paiement_24h,
    max(e.created_at) AS derniere_activite
   FROM (public.organisations o
     LEFT JOIN public.encaissements e ON ((o.id = e.organisation_id)))
  GROUP BY o.id
  WITH NO DATA;


ALTER MATERIALIZED VIEW public.saas_platform_metrics OWNER TO christian;

--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: banques banques_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.banques
    ADD CONSTRAINT banques_pkey PRIMARY KEY (id);


--
-- Name: budget_audit_logs budget_audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_audit_logs
    ADD CONSTRAINT budget_audit_logs_pkey PRIMARY KEY (id);


--
-- Name: budget_exercices budget_exercices_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_exercices
    ADD CONSTRAINT budget_exercices_pkey PRIMARY KEY (id);


--
-- Name: budget_postes budget_lignes_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_postes
    ADD CONSTRAINT budget_lignes_pkey PRIMARY KEY (id);


--
-- Name: caisse_centrale caisse_centrale_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.caisse_centrale
    ADD CONSTRAINT caisse_centrale_pkey PRIMARY KEY (id);


--
-- Name: category_changes_history category_changes_history_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.category_changes_history
    ADD CONSTRAINT category_changes_history_pkey PRIMARY KEY (id);


--
-- Name: payment_history ck_payment_history_mode_paiement; Type: CHECK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE public.payment_history
    ADD CONSTRAINT ck_payment_history_mode_paiement CHECK (((mode_paiement)::text = ANY (ARRAY[('cash'::character varying)::text, ('mobile_money'::character varying)::text, ('virement'::character varying)::text]))) NOT VALID;


--
-- Name: payment_history ck_payment_history_montant_positive; Type: CHECK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE public.payment_history
    ADD CONSTRAINT ck_payment_history_montant_positive CHECK ((montant > (0)::numeric)) NOT VALID;


--
-- Name: sorties_fonds ck_sorties_fonds_mode_paiement; Type: CHECK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE public.sorties_fonds
    ADD CONSTRAINT ck_sorties_fonds_mode_paiement CHECK (((mode_paiement)::text = ANY (ARRAY[('cash'::character varying)::text, ('mobile_money'::character varying)::text, ('virement'::character varying)::text]))) NOT VALID;


--
-- Name: sorties_fonds ck_sorties_fonds_montant_paye_nonneg; Type: CHECK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE public.sorties_fonds
    ADD CONSTRAINT ck_sorties_fonds_montant_paye_nonneg CHECK ((montant_paye >= (0)::numeric)) NOT VALID;


--
-- Name: clotures clotures_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.clotures
    ADD CONSTRAINT clotures_pkey PRIMARY KEY (id);


--
-- Name: commission_members commission_members_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.commission_members
    ADD CONSTRAINT commission_members_pkey PRIMARY KEY (id);


--
-- Name: comptes_bancaires comptes_bancaires_numero_compte_key; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.comptes_bancaires
    ADD CONSTRAINT comptes_bancaires_numero_compte_key UNIQUE (numero_compte);


--
-- Name: comptes_bancaires comptes_bancaires_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.comptes_bancaires
    ADD CONSTRAINT comptes_bancaires_pkey PRIMARY KEY (id);


--
-- Name: denominations denominations_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.denominations
    ADD CONSTRAINT denominations_pkey PRIMARY KEY (id);


--
-- Name: document_sequences document_sequences_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.document_sequences
    ADD CONSTRAINT document_sequences_pkey PRIMARY KEY (id);


--
-- Name: dossiers_requisition dossiers_requisition_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.dossiers_requisition
    ADD CONSTRAINT dossiers_requisition_pkey PRIMARY KEY (id);


--
-- Name: dossiers_requisition dossiers_requisition_reference_key; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.dossiers_requisition
    ADD CONSTRAINT dossiers_requisition_reference_key UNIQUE (reference);


--
-- Name: encaissements encaissements_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.encaissements
    ADD CONSTRAINT encaissements_pkey PRIMARY KEY (id);


--
-- Name: experts_comptables experts_comptables_numero_ordre_key; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.experts_comptables
    ADD CONSTRAINT experts_comptables_numero_ordre_key UNIQUE (numero_ordre);


--
-- Name: experts_comptables experts_comptables_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.experts_comptables
    ADD CONSTRAINT experts_comptables_pkey PRIMARY KEY (id);


--
-- Name: imports_history imports_history_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.imports_history
    ADD CONSTRAINT imports_history_pkey PRIMARY KEY (id);


--
-- Name: lignes_requisition lignes_requisition_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.lignes_requisition
    ADD CONSTRAINT lignes_requisition_pkey PRIMARY KEY (id);


--
-- Name: organisation_settings organisation_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.organisation_settings
    ADD CONSTRAINT organisation_settings_pkey PRIMARY KEY (id);


--
-- Name: organisations organisations_slug_key; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.organisations
    ADD CONSTRAINT organisations_slug_key UNIQUE (slug);


--
-- Name: organisations organisations_uuid_key; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.organisations
    ADD CONSTRAINT organisations_uuid_key UNIQUE (uuid);


--
-- Name: participants_transport participants_transport_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.participants_transport
    ADD CONSTRAINT participants_transport_pkey PRIMARY KEY (id);


--
-- Name: payment_history payment_history_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.payment_history
    ADD CONSTRAINT payment_history_pkey PRIMARY KEY (id);


--
-- Name: payment_logs payment_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.payment_logs
    ADD CONSTRAINT payment_logs_pkey PRIMARY KEY (id);


--
-- Name: payment_transactions payment_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.payment_transactions
    ADD CONSTRAINT payment_transactions_pkey PRIMARY KEY (id);


--
-- Name: payment_transactions payment_transactions_provider_ref_key; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.payment_transactions
    ADD CONSTRAINT payment_transactions_provider_ref_key UNIQUE (provider_ref);


--
-- Name: permissions permissions_code_key; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_code_key UNIQUE (code);


--
-- Name: permissions permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_pkey PRIMARY KEY (id);


--
-- Name: plans plans_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.plans
    ADD CONSTRAINT plans_pkey PRIMARY KEY (id);


--
-- Name: platform_settings platform_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.platform_settings
    ADD CONSTRAINT platform_settings_pkey PRIMARY KEY (id);


--
-- Name: print_settings print_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.print_settings
    ADD CONSTRAINT print_settings_pkey PRIMARY KEY (id);


--
-- Name: refresh_tokens refresh_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_pkey PRIMARY KEY (id);


--
-- Name: refresh_tokens refresh_tokens_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_token_hash_key UNIQUE (token_hash);


--
-- Name: remboursements_transport remboursements_transport_numero_remboursement_key; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.remboursements_transport
    ADD CONSTRAINT remboursements_transport_numero_remboursement_key UNIQUE (numero_remboursement);


--
-- Name: remboursements_transport remboursements_transport_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.remboursements_transport
    ADD CONSTRAINT remboursements_transport_pkey PRIMARY KEY (id);


--
-- Name: requisition_annexes requisition_annexes_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisition_annexes
    ADD CONSTRAINT requisition_annexes_pkey PRIMARY KEY (id);


--
-- Name: requisition_approvers requisition_approvers_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisition_approvers
    ADD CONSTRAINT requisition_approvers_pkey PRIMARY KEY (id);


--
-- Name: requisition_status_history requisition_status_history_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisition_status_history
    ADD CONSTRAINT requisition_status_history_pkey PRIMARY KEY (id);


--
-- Name: requisitions requisitions_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisitions
    ADD CONSTRAINT requisitions_pkey PRIMARY KEY (id);


--
-- Name: role_permissions role_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (role_id, permission_id);


--
-- Name: roles roles_code_key; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_code_key UNIQUE (code);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: rubriques rubriques_code_key; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.rubriques
    ADD CONSTRAINT rubriques_code_key UNIQUE (code);


--
-- Name: rubriques rubriques_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.rubriques
    ADD CONSTRAINT rubriques_pkey PRIMARY KEY (id);


--
-- Name: service_rubriques service_rubriques_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.service_rubriques
    ADD CONSTRAINT service_rubriques_pkey PRIMARY KEY (id);


--
-- Name: services services_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_pkey PRIMARY KEY (id);


--
-- Name: sorties_fonds sorties_fonds_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.sorties_fonds
    ADD CONSTRAINT sorties_fonds_pkey PRIMARY KEY (id);


--
-- Name: standard_classifications standard_classifications_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.standard_classifications
    ADD CONSTRAINT standard_classifications_pkey PRIMARY KEY (id);


--
-- Name: subscriptions subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_pkey PRIMARY KEY (id);


--
-- Name: system_events system_events_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.system_events
    ADD CONSTRAINT system_events_pkey PRIMARY KEY (id);


--
-- Name: system_settings system_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_pkey PRIMARY KEY (id);


--
-- Name: tenant_signups tenant_signups_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.tenant_signups
    ADD CONSTRAINT tenant_signups_pkey PRIMARY KEY (id);


--
-- Name: transactions transactions_external_reference_key; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_external_reference_key UNIQUE (external_reference);


--
-- Name: transactions transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (id);


--
-- Name: transferts_internes transferts_internes_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.transferts_internes
    ADD CONSTRAINT transferts_internes_pkey PRIMARY KEY (id);


--
-- Name: banques uq_banques_org_nom; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.banques
    ADD CONSTRAINT uq_banques_org_nom UNIQUE (organisation_id, nom);


--
-- Name: budget_exercices uq_budget_exercices_org_annee; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_exercices
    ADD CONSTRAINT uq_budget_exercices_org_annee UNIQUE (organisation_id, annee);


--
-- Name: clotures uq_clotures_reference_numero; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.clotures
    ADD CONSTRAINT uq_clotures_reference_numero UNIQUE (reference_numero);


--
-- Name: commission_members uq_commission_member_role; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.commission_members
    ADD CONSTRAINT uq_commission_member_role UNIQUE (service_id, user_id, role_type);


--
-- Name: document_sequences uq_doc_type_year_tenant; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.document_sequences
    ADD CONSTRAINT uq_doc_type_year_tenant UNIQUE (doc_type, year, tenant_id);


--
-- Name: encaissements uq_encaissements_org_numero; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.encaissements
    ADD CONSTRAINT uq_encaissements_org_numero UNIQUE (organisation_id, numero_recu);


--
-- Name: plans uq_plans_name; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.plans
    ADD CONSTRAINT uq_plans_name UNIQUE (name);


--
-- Name: requisitions uq_requisitions_numero; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisitions
    ADD CONSTRAINT uq_requisitions_numero UNIQUE (numero_requisition);


--
-- Name: service_rubriques uq_service_rubrique; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.service_rubriques
    ADD CONSTRAINT uq_service_rubrique UNIQUE (service_id, budget_poste_id);


--
-- Name: services uq_services_org_code; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT uq_services_org_code UNIQUE (organisation_id, code);


--
-- Name: standard_classifications uq_std_class_org_label; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.standard_classifications
    ADD CONSTRAINT uq_std_class_org_label UNIQUE (organisation_id, raw_label);


--
-- Name: tenant_signups uq_tenant_signups_reference; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.tenant_signups
    ADD CONSTRAINT uq_tenant_signups_reference UNIQUE (reference);


--
-- Name: users uq_users_org_email; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_org_email UNIQUE (organisation_id, email);


--
-- Name: user_roles user_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (id);


--
-- Name: user_services user_services_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.user_services
    ADD CONSTRAINT user_services_pkey PRIMARY KEY (user_id, service_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: idx_saas_platform_metrics_org_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE UNIQUE INDEX idx_saas_platform_metrics_org_id ON public.saas_platform_metrics USING btree (org_id);


--
-- Name: ix_audit_logs_action; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_audit_logs_action ON public.audit_logs USING btree (action);


--
-- Name: ix_audit_logs_created_at; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_audit_logs_created_at ON public.audit_logs USING btree (created_at);


--
-- Name: ix_audit_logs_entity_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_audit_logs_entity_id ON public.audit_logs USING btree (entity_id);


--
-- Name: ix_audit_logs_entity_type; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_audit_logs_entity_type ON public.audit_logs USING btree (entity_type);


--
-- Name: ix_audit_logs_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_audit_logs_organisation_id ON public.audit_logs USING btree (organisation_id);


--
-- Name: ix_audit_logs_target_table; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_audit_logs_target_table ON public.audit_logs USING btree (target_table);


--
-- Name: ix_audit_logs_user_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_audit_logs_user_id ON public.audit_logs USING btree (user_id);


--
-- Name: ix_banques_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_banques_organisation_id ON public.banques USING btree (organisation_id);


--
-- Name: ix_budget_audit_logs_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_budget_audit_logs_organisation_id ON public.budget_audit_logs USING btree (organisation_id);


--
-- Name: ix_budget_exercices_annee; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_budget_exercices_annee ON public.budget_exercices USING btree (annee);


--
-- Name: ix_budget_exercices_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_budget_exercices_organisation_id ON public.budget_exercices USING btree (organisation_id);


--
-- Name: ix_budget_lignes_code; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_budget_lignes_code ON public.budget_postes USING btree (code);


--
-- Name: ix_budget_lignes_exercice_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_budget_lignes_exercice_id ON public.budget_postes USING btree (exercice_id);


--
-- Name: ix_budget_postes_is_deleted; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_budget_postes_is_deleted ON public.budget_postes USING btree (is_deleted);


--
-- Name: ix_budget_postes_is_global; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_budget_postes_is_global ON public.budget_postes USING btree (is_global);


--
-- Name: ix_budget_postes_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_budget_postes_organisation_id ON public.budget_postes USING btree (organisation_id);


--
-- Name: ix_budget_postes_parent_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_budget_postes_parent_id ON public.budget_postes USING btree (parent_id);


--
-- Name: ix_caisse_centrale_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_caisse_centrale_organisation_id ON public.caisse_centrale USING btree (organisation_id);


--
-- Name: ix_category_changes_history_created_at; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_category_changes_history_created_at ON public.category_changes_history USING btree (created_at);


--
-- Name: ix_category_changes_history_expert_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_category_changes_history_expert_id ON public.category_changes_history USING btree (expert_id);


--
-- Name: ix_clotures_caissier_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_clotures_caissier_id ON public.clotures USING btree (caissier_id);


--
-- Name: ix_clotures_date_cloture; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_clotures_date_cloture ON public.clotures USING btree (date_cloture);


--
-- Name: ix_clotures_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_clotures_organisation_id ON public.clotures USING btree (organisation_id);


--
-- Name: ix_clotures_reference_numero; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_clotures_reference_numero ON public.clotures USING btree (reference_numero);


--
-- Name: ix_commission_members_email; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_commission_members_email ON public.commission_members USING btree (email);


--
-- Name: ix_commission_members_matricule; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_commission_members_matricule ON public.commission_members USING btree (matricule);


--
-- Name: ix_commission_members_service_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_commission_members_service_id ON public.commission_members USING btree (service_id);


--
-- Name: ix_commission_members_user_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_commission_members_user_id ON public.commission_members USING btree (user_id);


--
-- Name: ix_comptes_bancaires_banque_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_comptes_bancaires_banque_id ON public.comptes_bancaires USING btree (banque_id);


--
-- Name: ix_comptes_bancaires_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_comptes_bancaires_organisation_id ON public.comptes_bancaires USING btree (organisation_id);


--
-- Name: ix_denominations_devise; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_denominations_devise ON public.denominations USING btree (devise);


--
-- Name: ix_document_sequences_tenant_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_document_sequences_tenant_id ON public.document_sequences USING btree (tenant_id);


--
-- Name: ix_dossiers_requisition_created_by; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_dossiers_requisition_created_by ON public.dossiers_requisition USING btree (created_by);


--
-- Name: ix_dossiers_requisition_reference; Type: INDEX; Schema: public; Owner: christian
--

CREATE UNIQUE INDEX ix_dossiers_requisition_reference ON public.dossiers_requisition USING btree (reference);


--
-- Name: ix_dossiers_requisition_status; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_dossiers_requisition_status ON public.dossiers_requisition USING btree (status);


--
-- Name: ix_encaissements_budget_ligne_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_encaissements_budget_ligne_id ON public.encaissements USING btree (budget_poste_id);


--
-- Name: ix_encaissements_compte_bancaire_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_encaissements_compte_bancaire_id ON public.encaissements USING btree (compte_bancaire_id);


--
-- Name: ix_encaissements_date_encaissement; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_encaissements_date_encaissement ON public.encaissements USING btree (date_encaissement);


--
-- Name: ix_encaissements_expert_comptable_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_encaissements_expert_comptable_id ON public.encaissements USING btree (expert_comptable_id);


--
-- Name: ix_encaissements_is_deleted; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_encaissements_is_deleted ON public.encaissements USING btree (is_deleted);


--
-- Name: ix_encaissements_is_reconciled; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_encaissements_is_reconciled ON public.encaissements USING btree (is_reconciled);


--
-- Name: ix_encaissements_numero_recu; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_encaissements_numero_recu ON public.encaissements USING btree (numero_recu);


--
-- Name: ix_encaissements_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_encaissements_organisation_id ON public.encaissements USING btree (organisation_id);


--
-- Name: ix_encaissements_service_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_encaissements_service_id ON public.encaissements USING btree (service_id);


--
-- Name: ix_encaissements_statut_paiement; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_encaissements_statut_paiement ON public.encaissements USING btree (statut_paiement);


--
-- Name: ix_encaissements_type_client; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_encaissements_type_client ON public.encaissements USING btree (type_client);


--
-- Name: ix_experts_comptables_active; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_experts_comptables_active ON public.experts_comptables USING btree (active);


--
-- Name: ix_experts_comptables_numero_ordre; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_experts_comptables_numero_ordre ON public.experts_comptables USING btree (numero_ordre);


--
-- Name: ix_experts_comptables_type_ec; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_experts_comptables_type_ec ON public.experts_comptables USING btree (type_ec);


--
-- Name: ix_imports_history_category; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_imports_history_category ON public.imports_history USING btree (category);


--
-- Name: ix_imports_history_created_at; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_imports_history_created_at ON public.imports_history USING btree (created_at);


--
-- Name: ix_lignes_requisition_budget_ligne_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_lignes_requisition_budget_ligne_id ON public.lignes_requisition USING btree (budget_poste_id);


--
-- Name: ix_lignes_requisition_requisition_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_lignes_requisition_requisition_id ON public.lignes_requisition USING btree (requisition_id);


--
-- Name: ix_organisation_settings_org_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_organisation_settings_org_id ON public.organisation_settings USING btree (organisation_id);


--
-- Name: ix_organisations_slug; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_organisations_slug ON public.organisations USING btree (slug);


--
-- Name: ix_organisations_sort_order; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_organisations_sort_order ON public.organisations USING btree (sort_order);


--
-- Name: ix_payment_history_created_at; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_payment_history_created_at ON public.payment_history USING btree (created_at);


--
-- Name: ix_payment_history_encaissement_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_payment_history_encaissement_id ON public.payment_history USING btree (encaissement_id);


--
-- Name: ix_payment_history_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_payment_history_organisation_id ON public.payment_history USING btree (organisation_id);


--
-- Name: ix_payment_logs_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_payment_logs_organisation_id ON public.payment_logs USING btree (organisation_id);


--
-- Name: ix_payment_transactions_encaissement_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_payment_transactions_encaissement_id ON public.payment_transactions USING btree (encaissement_id);


--
-- Name: ix_payment_transactions_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_payment_transactions_organisation_id ON public.payment_transactions USING btree (organisation_id);


--
-- Name: ix_print_settings_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_print_settings_organisation_id ON public.print_settings USING btree (organisation_id);


--
-- Name: ix_refresh_tokens_jti; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_refresh_tokens_jti ON public.refresh_tokens USING btree (jti);


--
-- Name: ix_refresh_tokens_user_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_refresh_tokens_user_id ON public.refresh_tokens USING btree (user_id);


--
-- Name: ix_requisition_annexes_requisition_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE UNIQUE INDEX ix_requisition_annexes_requisition_id ON public.requisition_annexes USING btree (requisition_id);


--
-- Name: ix_requisition_approvers_active; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisition_approvers_active ON public.requisition_approvers USING btree (active);


--
-- Name: ix_requisition_status_history_changed_at; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisition_status_history_changed_at ON public.requisition_status_history USING btree (changed_at);


--
-- Name: ix_requisition_status_history_changed_by; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisition_status_history_changed_by ON public.requisition_status_history USING btree (changed_by);


--
-- Name: ix_requisition_status_history_requisition_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisition_status_history_requisition_id ON public.requisition_status_history USING btree (requisition_id);


--
-- Name: ix_requisitions_created_by; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisitions_created_by ON public.requisitions USING btree (created_by);


--
-- Name: ix_requisitions_dossier_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisitions_dossier_id ON public.requisitions USING btree (dossier_id);


--
-- Name: ix_requisitions_examen_status; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisitions_examen_status ON public.requisitions USING btree (examen_status);


--
-- Name: ix_requisitions_is_deleted; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisitions_is_deleted ON public.requisitions USING btree (is_deleted);


--
-- Name: ix_requisitions_numero; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisitions_numero ON public.requisitions USING btree (numero_requisition);


--
-- Name: ix_requisitions_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisitions_organisation_id ON public.requisitions USING btree (organisation_id);


--
-- Name: ix_requisitions_service_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisitions_service_id ON public.requisitions USING btree (service_id);


--
-- Name: ix_requisitions_signed_by_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisitions_signed_by_id ON public.requisitions USING btree (signed_by_id);


--
-- Name: ix_requisitions_status; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_requisitions_status ON public.requisitions USING btree (status);


--
-- Name: ix_rubriques_code; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_rubriques_code ON public.rubriques USING btree (code);


--
-- Name: ix_service_rubriques_budget_poste_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_service_rubriques_budget_poste_id ON public.service_rubriques USING btree (budget_poste_id);


--
-- Name: ix_service_rubriques_service_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_service_rubriques_service_id ON public.service_rubriques USING btree (service_id);


--
-- Name: ix_services_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_services_organisation_id ON public.services USING btree (organisation_id);


--
-- Name: ix_sorties_fonds_budget_ligne_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_sorties_fonds_budget_ligne_id ON public.sorties_fonds USING btree (budget_poste_id);


--
-- Name: ix_sorties_fonds_compte_bancaire_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_sorties_fonds_compte_bancaire_id ON public.sorties_fonds USING btree (compte_bancaire_id);


--
-- Name: ix_sorties_fonds_created_by; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_sorties_fonds_created_by ON public.sorties_fonds USING btree (created_by);


--
-- Name: ix_sorties_fonds_date_paiement; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_sorties_fonds_date_paiement ON public.sorties_fonds USING btree (date_paiement);


--
-- Name: ix_sorties_fonds_is_reconciled; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_sorties_fonds_is_reconciled ON public.sorties_fonds USING btree (is_reconciled);


--
-- Name: ix_sorties_fonds_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_sorties_fonds_organisation_id ON public.sorties_fonds USING btree (organisation_id);


--
-- Name: ix_sorties_fonds_requisition_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_sorties_fonds_requisition_id ON public.sorties_fonds USING btree (requisition_id);


--
-- Name: ix_sorties_fonds_service_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_sorties_fonds_service_id ON public.sorties_fonds USING btree (service_id);


--
-- Name: ix_standard_classifications_label; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_standard_classifications_label ON public.standard_classifications USING btree (raw_label);


--
-- Name: ix_standard_classifications_org; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_standard_classifications_org ON public.standard_classifications USING btree (organisation_id);


--
-- Name: ix_subscriptions_fedapay_transaction_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_subscriptions_fedapay_transaction_id ON public.subscriptions USING btree (fedapay_transaction_id);


--
-- Name: ix_subscriptions_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_subscriptions_organisation_id ON public.subscriptions USING btree (organisation_id);


--
-- Name: ix_subscriptions_plan_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_subscriptions_plan_id ON public.subscriptions USING btree (plan_id);


--
-- Name: ix_system_events_created_at; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_system_events_created_at ON public.system_events USING btree (created_at);


--
-- Name: ix_system_events_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_system_events_organisation_id ON public.system_events USING btree (organisation_id);


--
-- Name: ix_system_settings_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_system_settings_organisation_id ON public.system_settings USING btree (organisation_id);


--
-- Name: ix_tenant_signups_admin_email; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_tenant_signups_admin_email ON public.tenant_signups USING btree (admin_email);


--
-- Name: ix_tenant_signups_fedapay_transaction_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_tenant_signups_fedapay_transaction_id ON public.tenant_signups USING btree (fedapay_transaction_id);


--
-- Name: ix_tenant_signups_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_tenant_signups_organisation_id ON public.tenant_signups USING btree (organisation_id);


--
-- Name: ix_tenant_signups_plan_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_tenant_signups_plan_id ON public.tenant_signups USING btree (plan_id);


--
-- Name: ix_tenant_signups_slug; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_tenant_signups_slug ON public.tenant_signups USING btree (slug);


--
-- Name: ix_transactions_tenant_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_transactions_tenant_id ON public.transactions USING btree (tenant_id);


--
-- Name: ix_user_roles_user_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_user_roles_user_id ON public.user_roles USING btree (user_id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_organisation_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_users_organisation_id ON public.users USING btree (organisation_id);


--
-- Name: ix_users_role_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_users_role_id ON public.users USING btree (role_id);


--
-- Name: ix_users_service_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE INDEX ix_users_service_id ON public.users USING btree (service_id);


--
-- Name: uq_remboursements_transport_reference_numero; Type: INDEX; Schema: public; Owner: christian
--

CREATE UNIQUE INDEX uq_remboursements_transport_reference_numero ON public.remboursements_transport USING btree (reference_numero);


--
-- Name: uq_requisition_approvers_user_id; Type: INDEX; Schema: public; Owner: christian
--

CREATE UNIQUE INDEX uq_requisition_approvers_user_id ON public.requisition_approvers USING btree (user_id);


--
-- Name: uq_requisitions_reference_numero; Type: INDEX; Schema: public; Owner: christian
--

CREATE UNIQUE INDEX uq_requisitions_reference_numero ON public.requisitions USING btree (reference_numero);


--
-- Name: uq_sorties_fonds_reference_numero; Type: INDEX; Schema: public; Owner: christian
--

CREATE UNIQUE INDEX uq_sorties_fonds_reference_numero ON public.sorties_fonds USING btree (reference_numero);


--
-- Name: uq_user_roles_user_role; Type: INDEX; Schema: public; Owner: christian
--

CREATE UNIQUE INDEX uq_user_roles_user_role ON public.user_roles USING btree (user_id, role);


--
-- Name: audit_logs audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: budget_audit_logs budget_audit_logs_budget_ligne_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_audit_logs
    ADD CONSTRAINT budget_audit_logs_budget_ligne_id_fkey FOREIGN KEY (budget_poste_id) REFERENCES public.budget_postes(id);


--
-- Name: budget_audit_logs budget_audit_logs_exercice_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_audit_logs
    ADD CONSTRAINT budget_audit_logs_exercice_id_fkey FOREIGN KEY (exercice_id) REFERENCES public.budget_exercices(id);


--
-- Name: budget_postes budget_lignes_exercice_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_postes
    ADD CONSTRAINT budget_lignes_exercice_id_fkey FOREIGN KEY (exercice_id) REFERENCES public.budget_exercices(id);


--
-- Name: clotures clotures_caissier_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.clotures
    ADD CONSTRAINT clotures_caissier_id_fkey FOREIGN KEY (caissier_id) REFERENCES public.users(id);


--
-- Name: commission_members commission_members_service_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.commission_members
    ADD CONSTRAINT commission_members_service_id_fkey FOREIGN KEY (service_id) REFERENCES public.services(id) ON DELETE CASCADE;


--
-- Name: commission_members commission_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.commission_members
    ADD CONSTRAINT commission_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: comptes_bancaires comptes_bancaires_banque_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.comptes_bancaires
    ADD CONSTRAINT comptes_bancaires_banque_id_fkey FOREIGN KEY (banque_id) REFERENCES public.banques(id) ON DELETE RESTRICT;


--
-- Name: audit_logs fk_audit_logs_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT fk_audit_logs_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE SET NULL;


--
-- Name: banques fk_banques_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.banques
    ADD CONSTRAINT fk_banques_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: budget_audit_logs fk_budget_audit_logs_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_audit_logs
    ADD CONSTRAINT fk_budget_audit_logs_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: budget_exercices fk_budget_exercices_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_exercices
    ADD CONSTRAINT fk_budget_exercices_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: budget_postes fk_budget_lignes_parent_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_postes
    ADD CONSTRAINT fk_budget_lignes_parent_id FOREIGN KEY (parent_id) REFERENCES public.budget_postes(id) ON DELETE SET NULL;


--
-- Name: budget_postes fk_budget_postes_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.budget_postes
    ADD CONSTRAINT fk_budget_postes_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: caisse_centrale fk_caisse_centrale_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.caisse_centrale
    ADD CONSTRAINT fk_caisse_centrale_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: category_changes_history fk_category_changes_expert; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.category_changes_history
    ADD CONSTRAINT fk_category_changes_expert FOREIGN KEY (expert_id) REFERENCES public.experts_comptables(id) ON DELETE CASCADE;


--
-- Name: clotures fk_clotures_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.clotures
    ADD CONSTRAINT fk_clotures_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: comptes_bancaires fk_comptes_bancaires_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.comptes_bancaires
    ADD CONSTRAINT fk_comptes_bancaires_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: document_sequences fk_document_sequences_tenant_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.document_sequences
    ADD CONSTRAINT fk_document_sequences_tenant_id FOREIGN KEY (tenant_id) REFERENCES public.organisations(id) ON DELETE CASCADE;


--
-- Name: encaissements fk_encaissements_budget_ligne_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.encaissements
    ADD CONSTRAINT fk_encaissements_budget_ligne_id FOREIGN KEY (budget_poste_id) REFERENCES public.budget_postes(id);


--
-- Name: encaissements fk_encaissements_compte_bancaire_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.encaissements
    ADD CONSTRAINT fk_encaissements_compte_bancaire_id FOREIGN KEY (compte_bancaire_id) REFERENCES public.comptes_bancaires(id) ON DELETE SET NULL;


--
-- Name: encaissements fk_encaissements_expert; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.encaissements
    ADD CONSTRAINT fk_encaissements_expert FOREIGN KEY (expert_comptable_id) REFERENCES public.experts_comptables(id) ON DELETE SET NULL;


--
-- Name: encaissements fk_encaissements_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.encaissements
    ADD CONSTRAINT fk_encaissements_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: encaissements fk_encaissements_service_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.encaissements
    ADD CONSTRAINT fk_encaissements_service_id FOREIGN KEY (service_id) REFERENCES public.services(id);


--
-- Name: encaissements fk_encaissements_source_proforma; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.encaissements
    ADD CONSTRAINT fk_encaissements_source_proforma FOREIGN KEY (source_proforma_id) REFERENCES public.encaissements(id) ON DELETE SET NULL;


--
-- Name: lignes_requisition fk_lignes_requisition_budget_ligne_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.lignes_requisition
    ADD CONSTRAINT fk_lignes_requisition_budget_ligne_id FOREIGN KEY (budget_poste_id) REFERENCES public.budget_postes(id);


--
-- Name: payment_history fk_payment_history_encaissement; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.payment_history
    ADD CONSTRAINT fk_payment_history_encaissement FOREIGN KEY (encaissement_id) REFERENCES public.encaissements(id) ON DELETE CASCADE;


--
-- Name: payment_history fk_payment_history_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.payment_history
    ADD CONSTRAINT fk_payment_history_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: payment_transactions fk_payment_transactions_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.payment_transactions
    ADD CONSTRAINT fk_payment_transactions_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: print_settings fk_print_settings_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.print_settings
    ADD CONSTRAINT fk_print_settings_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: requisitions fk_requisitions_dossier_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisitions
    ADD CONSTRAINT fk_requisitions_dossier_id FOREIGN KEY (dossier_id) REFERENCES public.dossiers_requisition(id) ON DELETE SET NULL;


--
-- Name: requisitions fk_requisitions_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisitions
    ADD CONSTRAINT fk_requisitions_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: requisitions fk_requisitions_service_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisitions
    ADD CONSTRAINT fk_requisitions_service_id FOREIGN KEY (service_id) REFERENCES public.services(id);


--
-- Name: requisitions fk_requisitions_signed_by_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisitions
    ADD CONSTRAINT fk_requisitions_signed_by_id FOREIGN KEY (signed_by_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: services fk_services_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT fk_services_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: services fk_services_responsable_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT fk_services_responsable_id FOREIGN KEY (responsable_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: sorties_fonds fk_sorties_fonds_budget_ligne_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.sorties_fonds
    ADD CONSTRAINT fk_sorties_fonds_budget_ligne_id FOREIGN KEY (budget_poste_id) REFERENCES public.budget_postes(id);


--
-- Name: sorties_fonds fk_sorties_fonds_compte_bancaire_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.sorties_fonds
    ADD CONSTRAINT fk_sorties_fonds_compte_bancaire_id FOREIGN KEY (compte_bancaire_id) REFERENCES public.comptes_bancaires(id) ON DELETE SET NULL;


--
-- Name: sorties_fonds fk_sorties_fonds_created_by; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.sorties_fonds
    ADD CONSTRAINT fk_sorties_fonds_created_by FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: sorties_fonds fk_sorties_fonds_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.sorties_fonds
    ADD CONSTRAINT fk_sorties_fonds_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: sorties_fonds fk_sorties_fonds_requisition; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.sorties_fonds
    ADD CONSTRAINT fk_sorties_fonds_requisition FOREIGN KEY (requisition_id) REFERENCES public.requisitions(id) ON DELETE SET NULL;


--
-- Name: sorties_fonds fk_sorties_fonds_service_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.sorties_fonds
    ADD CONSTRAINT fk_sorties_fonds_service_id FOREIGN KEY (service_id) REFERENCES public.services(id);


--
-- Name: system_settings fk_system_settings_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT fk_system_settings_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: tenant_signups fk_tenant_signups_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.tenant_signups
    ADD CONSTRAINT fk_tenant_signups_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE SET NULL;


--
-- Name: users fk_users_organisation_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_users_organisation_id FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE RESTRICT;


--
-- Name: users fk_users_role_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_users_role_id FOREIGN KEY (role_id) REFERENCES public.roles(id);


--
-- Name: users fk_users_service_id; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_users_service_id FOREIGN KEY (service_id) REFERENCES public.services(id);


--
-- Name: organisation_settings organisation_settings_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.organisation_settings
    ADD CONSTRAINT organisation_settings_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE CASCADE;


--
-- Name: participants_transport participants_transport_expert_comptable_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.participants_transport
    ADD CONSTRAINT participants_transport_expert_comptable_id_fkey FOREIGN KEY (expert_comptable_id) REFERENCES public.experts_comptables(id) ON DELETE SET NULL;


--
-- Name: participants_transport participants_transport_remboursement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.participants_transport
    ADD CONSTRAINT participants_transport_remboursement_id_fkey FOREIGN KEY (remboursement_id) REFERENCES public.remboursements_transport(id) ON DELETE CASCADE;


--
-- Name: payment_logs payment_logs_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.payment_logs
    ADD CONSTRAINT payment_logs_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE CASCADE;


--
-- Name: payment_transactions payment_transactions_encaissement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.payment_transactions
    ADD CONSTRAINT payment_transactions_encaissement_id_fkey FOREIGN KEY (encaissement_id) REFERENCES public.encaissements(id);


--
-- Name: refresh_tokens refresh_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: requisition_annexes requisition_annexes_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisition_annexes
    ADD CONSTRAINT requisition_annexes_requisition_id_fkey FOREIGN KEY (requisition_id) REFERENCES public.requisitions(id) ON DELETE CASCADE;


--
-- Name: requisition_approvers requisition_approvers_added_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisition_approvers
    ADD CONSTRAINT requisition_approvers_added_by_fkey FOREIGN KEY (added_by) REFERENCES public.users(id);


--
-- Name: requisition_approvers requisition_approvers_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisition_approvers
    ADD CONSTRAINT requisition_approvers_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: requisition_status_history requisition_status_history_changed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisition_status_history
    ADD CONSTRAINT requisition_status_history_changed_by_fkey FOREIGN KEY (changed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: requisition_status_history requisition_status_history_requisition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.requisition_status_history
    ADD CONSTRAINT requisition_status_history_requisition_id_fkey FOREIGN KEY (requisition_id) REFERENCES public.requisitions(id) ON DELETE CASCADE;


--
-- Name: role_permissions role_permissions_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE CASCADE;


--
-- Name: role_permissions role_permissions_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: service_rubriques service_rubriques_budget_poste_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.service_rubriques
    ADD CONSTRAINT service_rubriques_budget_poste_id_fkey FOREIGN KEY (budget_poste_id) REFERENCES public.budget_postes(id) ON DELETE CASCADE;


--
-- Name: service_rubriques service_rubriques_service_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.service_rubriques
    ADD CONSTRAINT service_rubriques_service_id_fkey FOREIGN KEY (service_id) REFERENCES public.services(id) ON DELETE CASCADE;


--
-- Name: standard_classifications standard_classifications_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.standard_classifications
    ADD CONSTRAINT standard_classifications_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);


--
-- Name: subscriptions subscriptions_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE CASCADE;


--
-- Name: subscriptions subscriptions_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.plans(id) ON DELETE RESTRICT;


--
-- Name: system_events system_events_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.system_events
    ADD CONSTRAINT system_events_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id) ON DELETE SET NULL;


--
-- Name: tenant_signups tenant_signups_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.tenant_signups
    ADD CONSTRAINT tenant_signups_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.plans(id) ON DELETE RESTRICT;


--
-- Name: user_roles user_roles_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: user_roles user_roles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: user_services user_services_service_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.user_services
    ADD CONSTRAINT user_services_service_id_fkey FOREIGN KEY (service_id) REFERENCES public.services(id) ON DELETE CASCADE;


--
-- Name: user_services user_services_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: christian
--

ALTER TABLE ONLY public.user_services
    ADD CONSTRAINT user_services_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: christian
--

REVOKE USAGE ON SCHEMA public FROM PUBLIC;


--
-- Name: saas_platform_metrics; Type: MATERIALIZED VIEW DATA; Schema: public; Owner: christian
--

REFRESH MATERIALIZED VIEW public.saas_platform_metrics;


--
-- PostgreSQL database dump complete
--

\unrestrict VV2KksmCdSMZYLMvu60OTjNQNJavPI36tN965evDBqH3z0Mc9lZshxHJLtsLhUo

