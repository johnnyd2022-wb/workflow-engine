"""Load a mobile-copy source snapshot into the local work-board PostgreSQL index.

Existing mobile decisions survive line moves. Changed text is reset for review,
and entries absent from the latest complete scan are removed.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

FILES = (
    ("pages", "page_key,template_name,route_patterns,page_kind,page_title,source_commit"),
    (
        "text",
        "page_key,node_key,container_key,source_line,element_tag,text_source,desktop_text,word_count,"
        "suggested_mobile_treatment,source_commit",
    ),
    ("relations", "page_key,included_page_key,relation,source_commit"),
)


def load_sql(folder: Path) -> str:
    parts = ["BEGIN;"]
    for name, columns in FILES:
        parts.append(
            f"CREATE TEMP TABLE stage_{name} (LIKE work.mobile_copy_{'pages' if name == 'pages' else name} INCLUDING DEFAULTS) ON COMMIT DROP;"
        )
        parts.append(f"COPY stage_{name} ({columns}) FROM STDIN WITH (FORMAT csv, HEADER true);")
        parts.append((folder / f"{name}.csv").read_text().rstrip("\n"))
        parts.append("\\.")
    parts.extend(
        (
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM stage_pages) OR NOT EXISTS (SELECT 1 FROM stage_text) THEN RAISE EXCEPTION 'empty mobile copy scan'; END IF; END $$;",
            """CREATE TEMP TABLE legacy_text_decisions ON COMMIT DROP AS
               SELECT page_key,element_tag,text_source,desktop_text,mobile_treatment,mobile_text,review_state,
                 count(*) OVER (PARTITION BY page_key,element_tag,text_source,desktop_text) AS matches
               FROM work.mobile_copy_text
               WHERE review_state <> 'unreviewed' OR mobile_treatment IS NOT NULL OR mobile_text IS NOT NULL;""",
            """CREATE TEMP TABLE legacy_container_decisions ON COMMIT DROP AS
               SELECT c.page_key,c.mobile_treatment,c.mobile_text,c.review_state,
                 md5(coalesce(string_agg(t.text_source || ':' || t.desktop_text, ' · '
                   ORDER BY t.text_source,t.desktop_text) FILTER (WHERE t.text_source='visible'),'')) AS content_key
               FROM work.mobile_copy_containers c
               LEFT JOIN work.mobile_copy_text t ON t.page_key=c.page_key AND t.container_key=c.container_key
               WHERE c.review_state <> 'unreviewed' OR c.mobile_treatment IS NOT NULL OR c.mobile_text IS NOT NULL
               GROUP BY c.page_key,c.container_key,c.mobile_treatment,c.mobile_text,c.review_state;""",
            """CREATE TEMP TABLE stage_container_keys ON COMMIT DROP AS
               SELECT page_key,container_key,
                 md5(coalesce(string_agg(text_source || ':' || desktop_text, ' · '
                   ORDER BY text_source,desktop_text) FILTER (WHERE text_source='visible'),'')) AS content_key
               FROM stage_text GROUP BY page_key,container_key;""",
            """INSERT INTO work.mobile_copy_pages(page_key,template_name,route_patterns,page_kind,page_title,source_commit,scanned_at)
               SELECT page_key,template_name,route_patterns,page_kind,page_title,source_commit,now() FROM stage_pages WHERE true
               ON CONFLICT(page_key) DO UPDATE SET template_name=excluded.template_name,
                 route_patterns=excluded.route_patterns,page_kind=excluded.page_kind,page_title=excluded.page_title,
                 source_commit=excluded.source_commit,scanned_at=now();""",
            """INSERT INTO work.mobile_copy_text(page_key,node_key,container_key,source_line,element_tag,text_source,
                 desktop_text,word_count,suggested_mobile_treatment,source_commit,scanned_at)
               SELECT page_key,node_key,container_key,source_line,element_tag,text_source,desktop_text,word_count,
                 suggested_mobile_treatment,source_commit,now() FROM stage_text WHERE true
               ON CONFLICT(page_key,node_key) DO UPDATE SET container_key=excluded.container_key,
                 source_line=excluded.source_line,element_tag=excluded.element_tag,text_source=excluded.text_source,
                 desktop_text=excluded.desktop_text,word_count=excluded.word_count,
                 suggested_mobile_treatment=excluded.suggested_mobile_treatment,
                 review_state=CASE WHEN work.mobile_copy_text.desktop_text IS DISTINCT FROM excluded.desktop_text
                   THEN 'unreviewed' ELSE work.mobile_copy_text.review_state END,
                 mobile_treatment=CASE WHEN work.mobile_copy_text.desktop_text IS DISTINCT FROM excluded.desktop_text
                   THEN NULL ELSE work.mobile_copy_text.mobile_treatment END,
                 mobile_text=CASE WHEN work.mobile_copy_text.desktop_text IS DISTINCT FROM excluded.desktop_text
                   THEN NULL ELSE work.mobile_copy_text.mobile_text END,
                 source_commit=excluded.source_commit,scanned_at=now();""",
            """INSERT INTO work.mobile_copy_relations(page_key,included_page_key,relation,source_commit)
               SELECT page_key,included_page_key,relation,source_commit FROM stage_relations WHERE true
               ON CONFLICT(page_key,included_page_key,relation) DO UPDATE SET source_commit=excluded.source_commit;""",
            """INSERT INTO work.mobile_copy_containers(page_key,container_key,desktop_text,word_count,dynamic_count,
                 suggested_mobile_treatment,source_commit,scanned_at)
               SELECT page_key,container_key,
                 coalesce(string_agg(desktop_text, ' · ' ORDER BY source_line,node_key)
                   FILTER (WHERE text_source='visible'),''),
                 coalesce(sum(word_count) FILTER (WHERE text_source='visible'),0)::integer,
                 count(*) FILTER (WHERE text_source IN ('x-text','x-html')),
                 CASE WHEN coalesce(sum(word_count) FILTER (WHERE text_source='visible'),0) >= 60 THEN 'collapse'
                      WHEN coalesce(sum(word_count) FILTER (WHERE text_source='visible'),0) >= 25 THEN 'shorten'
                      WHEN count(*) FILTER (WHERE text_source IN ('x-text','x-html')) > 0 THEN 'review_dynamic'
                      ELSE 'keep' END,
                 max(source_commit),now()
               FROM stage_text GROUP BY page_key,container_key
               ON CONFLICT(page_key,container_key) DO UPDATE SET desktop_text=excluded.desktop_text,
                 word_count=excluded.word_count,dynamic_count=excluded.dynamic_count,
                 suggested_mobile_treatment=excluded.suggested_mobile_treatment,
                 review_state=CASE WHEN work.mobile_copy_containers.desktop_text IS DISTINCT FROM excluded.desktop_text
                   THEN 'unreviewed' ELSE work.mobile_copy_containers.review_state END,
                 mobile_treatment=CASE WHEN work.mobile_copy_containers.desktop_text IS DISTINCT FROM excluded.desktop_text
                   THEN NULL ELSE work.mobile_copy_containers.mobile_treatment END,
                 mobile_text=CASE WHEN work.mobile_copy_containers.desktop_text IS DISTINCT FROM excluded.desktop_text
                   THEN NULL ELSE work.mobile_copy_containers.mobile_text END,
                 source_commit=excluded.source_commit,scanned_at=now();""",
            """UPDATE work.mobile_copy_text t SET mobile_treatment=l.mobile_treatment,
                 mobile_text=l.mobile_text,review_state=l.review_state
               FROM legacy_text_decisions l
               WHERE t.review_state='unreviewed' AND l.matches=1
                 AND t.page_key=l.page_key AND t.element_tag=l.element_tag
                 AND t.text_source=l.text_source AND t.desktop_text=l.desktop_text
                 AND (SELECT count(*) FROM stage_text s WHERE s.page_key=t.page_key
                   AND s.element_tag=t.element_tag AND s.text_source=t.text_source
                   AND s.desktop_text=t.desktop_text)=1
                 AND EXISTS (SELECT 1 FROM stage_text s WHERE s.page_key=t.page_key AND s.node_key=t.node_key);""",
            """UPDATE work.mobile_copy_containers c SET mobile_treatment=l.mobile_treatment,
                 mobile_text=l.mobile_text,review_state=l.review_state
               FROM legacy_container_decisions l,stage_container_keys s
               WHERE c.review_state='unreviewed' AND c.page_key=s.page_key
                 AND c.container_key=s.container_key AND s.page_key=l.page_key
                 AND s.content_key=l.content_key
                 AND (SELECT count(*) FROM legacy_container_decisions l2 WHERE l2.page_key=l.page_key
                   AND l2.content_key=l.content_key)=1
                 AND (SELECT count(*) FROM stage_container_keys s2 WHERE s2.page_key=s.page_key
                   AND s2.content_key=s.content_key)=1;""",
            """DELETE FROM work.mobile_copy_text t WHERE NOT EXISTS
               (SELECT 1 FROM stage_text s WHERE s.page_key=t.page_key AND s.node_key=t.node_key);""",
            """DELETE FROM work.mobile_copy_containers c WHERE NOT EXISTS
               (SELECT 1 FROM stage_text s WHERE s.page_key=c.page_key AND s.container_key=c.container_key);""",
            """DELETE FROM work.mobile_copy_relations r WHERE NOT EXISTS
               (SELECT 1 FROM stage_relations s WHERE s.page_key=r.page_key
                AND s.included_page_key=r.included_page_key AND s.relation=r.relation);""",
            """DELETE FROM work.mobile_copy_pages p WHERE NOT EXISTS
               (SELECT 1 FROM stage_pages s WHERE s.page_key=p.page_key);""",
            "COMMIT;",
        )
    )
    return "\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--db-container", default="workflow-engine-terraform-state-db-1")
    parser.add_argument("--database", default="bize_dev")
    args = parser.parse_args()
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            args.db_container,
            "psql",
            "-X",
            "-q",
            "-U",
            "bize_dev_admin",
            "-d",
            args.database,
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            "-",
        ],
        input=load_sql(args.folder),
        text=True,
        check=True,
    )


if __name__ == "__main__":
    main()
