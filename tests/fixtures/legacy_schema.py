"""Remove the known post29 structures when constructing an older test fixture.

Only called on freshly generated, isolated fixtures whose later tables are
empty. The real schema30 predecessor migration has a separate public checker.
"""


def remove_post29_tables(db):
    for table in ['journal_archive_history', 'journal_compilations', 'journal_issues',
                  'journal_profiles', 'journal_covers', 'fulltext_edits', 'fulltext_jobs', 'saved_originals']:
        if db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone():
            raise AssertionError('Cannot demote a fixture containing later journal/fulltext data.')
        db.execute('DROP TABLE ' + table)
