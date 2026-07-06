from django.db import connection


def set_database_actor(user):
    """
    Make the authenticated app user visible to Postgres triggers in the
    current transaction. Must be called inside transaction.atomic().
    """
    user_id = str(user.id) if user and getattr(user, "is_authenticated", False) else ""
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('metro.current_user_id', %s, true)", [user_id])
