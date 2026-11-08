"""Load a mobile-copy source snapshot into the local work-board PostgreSQL index.

Existing mobile decisions are preserved on refresh. Rows from older commits remain
queryable with their source_commit, so reviewers can reconcile changed copy.
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
                 source_commit=excluded.source_commit,scanned_at=now();""",
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
