from core.request_context import get_request_method, is_primary_requested

class PrimaryReplicaRouter:
    """
    A router to control all database operations on models to route 
    read operations from GET requests to the 'replica' database.
    """
    def db_for_read(self, model, **hints):
        """
        Reads go to 'replica' if it's a GET request.
        Otherwise, reads go to the primary ('default') to avoid replication lag on writes.
        Can be overridden by 'use_primary' hint or X-Use-Primary-DB header.
        """
        if hints.get('use_primary'):
            return 'default'
            
        try:
            if is_primary_requested():
                return 'default'
            if get_request_method() == 'GET':
                return 'replica'
        except LookupError:
            # Context var not set (e.g., in management commands or tasks)
            pass
        return 'default'

    def db_for_write(self, model, **hints):
        """
        Writes always go to 'default'.
        """
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        """
        Relations between objects are allowed if they are in either primary or replica databases.
        Django requires allowing relations across identically structured DBs.
        """
        db_set = {'default', 'replica'}
        if obj1._state.db in db_set and obj2._state.db in db_set:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        All non-auth models end up in this pool.
        Ensure migrations are applied to both default and replica if needed, 
        but usually replicas are read-only and mirroring default.
        """
        return True
