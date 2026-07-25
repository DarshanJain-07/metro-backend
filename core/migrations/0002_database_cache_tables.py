# Generated manually to keep Django database cache setup in migrations.

from django.db import migrations


CREATE_CACHE_TABLES = """
CREATE TABLE IF NOT EXISTS metro_cache_default (
    cache_key varchar(255) PRIMARY KEY,
    value text NOT NULL,
    expires timestamp with time zone NOT NULL
);
CREATE INDEX IF NOT EXISTS metro_cache_default_expires
    ON metro_cache_default (expires);

CREATE TABLE IF NOT EXISTS metro_cache_throttle (
    cache_key varchar(255) PRIMARY KEY,
    value text NOT NULL,
    expires timestamp with time zone NOT NULL
);
CREATE INDEX IF NOT EXISTS metro_cache_throttle_expires
    ON metro_cache_throttle (expires);
"""

DROP_CACHE_TABLES = """
DROP TABLE IF EXISTS metro_cache_throttle;
DROP TABLE IF EXISTS metro_cache_default;
"""


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(CREATE_CACHE_TABLES, DROP_CACHE_TABLES),
    ]
