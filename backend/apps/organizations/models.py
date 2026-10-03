"""Organizations app: removed.

The boilerplate's Organization model isn't used by this site. The app stays
installed only so its migration history (which deletes the table) keeps
applying cleanly on existing databases. Once every database has run
organizations.0002, this app and its migrations can be deleted along with a
squash of users' migrations.
"""
