-- Task-tracking database only (bize_dev.work), not an application migration.
-- Static source copy is indexed here; no tenant or customer data is included.

CREATE TABLE IF NOT EXISTS work.mobile_copy_pages (
    page_key text PRIMARY KEY,
    template_name text NOT NULL,
    route_patterns text NOT NULL DEFAULT '',
    page_kind text NOT NULL,
    page_title text NOT NULL DEFAULT '',
    source_commit text NOT NULL,
    scanned_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS work.mobile_copy_text (
    page_key text NOT NULL REFERENCES work.mobile_copy_pages(page_key) ON DELETE CASCADE,
    node_key text NOT NULL,
    container_key text NOT NULL,
    source_line integer NOT NULL,
    element_tag text NOT NULL,
    text_source text NOT NULL,
    desktop_text text NOT NULL,
    word_count integer NOT NULL,
    suggested_mobile_treatment text NOT NULL,
    mobile_treatment text,
    mobile_text text,
    review_state text NOT NULL DEFAULT 'unreviewed',
    source_commit text NOT NULL,
    scanned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (page_key, node_key)
);

CREATE TABLE IF NOT EXISTS work.mobile_copy_relations (
    page_key text NOT NULL REFERENCES work.mobile_copy_pages(page_key) ON DELETE CASCADE,
    included_page_key text NOT NULL REFERENCES work.mobile_copy_pages(page_key) ON DELETE CASCADE,
    relation text NOT NULL,
    source_commit text NOT NULL,
    PRIMARY KEY (page_key, included_page_key, relation)
);

CREATE TABLE IF NOT EXISTS work.mobile_copy_containers (
    page_key text NOT NULL REFERENCES work.mobile_copy_pages(page_key) ON DELETE CASCADE,
    container_key text NOT NULL,
    desktop_text text NOT NULL,
    word_count integer NOT NULL,
    dynamic_count integer NOT NULL,
    suggested_mobile_treatment text NOT NULL,
    mobile_treatment text,
    mobile_text text,
    review_state text NOT NULL DEFAULT 'unreviewed',
    source_commit text NOT NULL,
    scanned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (page_key, container_key)
);

CREATE INDEX IF NOT EXISTS mobile_copy_text_container_idx
    ON work.mobile_copy_text(page_key, container_key);
CREATE INDEX IF NOT EXISTS mobile_copy_text_review_idx
    ON work.mobile_copy_text(review_state, suggested_mobile_treatment, word_count DESC);
CREATE INDEX IF NOT EXISTS mobile_copy_text_search_idx
    ON work.mobile_copy_text USING gin (to_tsvector('english', desktop_text || ' ' || coalesce(mobile_text, '')));
CREATE INDEX IF NOT EXISTS mobile_copy_containers_review_idx
    ON work.mobile_copy_containers(review_state, word_count DESC);
CREATE INDEX IF NOT EXISTS mobile_copy_containers_search_idx
    ON work.mobile_copy_containers USING gin (to_tsvector('english', desktop_text || ' ' || coalesce(mobile_text, '')));

CREATE OR REPLACE VIEW work.mobile_copy_page_progress AS
SELECT p.page_key, p.template_name, p.route_patterns, p.page_kind,
       count(c.container_key) AS containers,
       coalesce(sum(c.word_count), 0) AS visible_words,
       count(c.container_key) FILTER (WHERE c.review_state = 'unreviewed') AS unreviewed,
       count(c.container_key) FILTER (WHERE c.review_state = 'proposed') AS proposed,
       count(c.container_key) FILTER (WHERE c.review_state = 'implemented') AS implemented,
       count(c.container_key) FILTER (WHERE c.review_state = 'verified') AS verified,
       count(c.container_key) FILTER (WHERE c.mobile_treatment IS NOT NULL) AS treatment_recorded
FROM work.mobile_copy_pages p
LEFT JOIN work.mobile_copy_containers c USING (page_key)
GROUP BY p.page_key, p.template_name, p.route_patterns, p.page_kind;
