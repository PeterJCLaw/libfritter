
from datetime import datetime, timedelta
import json

class KeyedSqliteThing(object):

    _id_key = 'id'
    _db_required_props = []
    _db_optional_props = []

    def __init__(self, connector, id = None, auto_props = []):
        self._id = id
        self._connector = connector
        self._conn = None
        self._db_auto_props = auto_props
        self._props = {}
        self._in_db = False
        if id is not None:
            self._load()

    def __repr__(self):
        tname = type(self).__name__
        return "{0}({1}, {2})".format(tname, self._id, self._props)

    def __getattr__(self, name):
        if name not in self._db_props:
            raise AttributeError("No property '%s'" % (name))

        return self._props.get(name, None)

    def __setattr__(self, name, value):
        if name in self._db_props:
            self._props[name] = value
        else:
            super(KeyedSqliteThing, self).__setattr__(name, value)

    def _get_connection(self):
        if self._conn is None:
            self._conn = self._connector()
        return self._conn

    def _exec(self, statement, arguments):
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(statement, arguments)
        conn.commit()
        return cur.lastrowid

    def _fetchone(self, statement, arguments):
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(statement, arguments)
        return cur.fetchone()

    def _where_id(self):
        return ' WHERE {0}=?'.format(self._id_key)

    def _from_table_where_id(self):
        return ' FROM {0}{1}'.format(self._db_table, self._where_id())

    def _load(self):
        props = self._db_props + self._db_auto_props
        statement = 'SELECT ' + ', '.join(props) + self._from_table_where_id()
        row = self._fetchone(statement, (self._id,))
        if not row is None:
            for i in range(len(props)):
                if row[i] is not None:
                    self._props[props[i]] = row[i]
            self._in_db = True

    @property
    def _db_props(self):
        return self._db_required_props + self._db_optional_props

    def _missing_props(self):
        return [name for name in self._db_required_props if name not in self._props]

    @property
    def id(self):
        return self._id

    @property
    def in_db(self):
        return self._in_db

    def delete(self):
        if not self.in_db:
            raise Exception( "Cannot remove %s '%s' - not in database!" % (type(self), self.self._id) )

        self._exec("DELETE" + self._from_table_where_id(), (self._id,))
        self._in_db = False

    def save(self):
        missing = self._missing_props()
        if len(missing) > 0:
            missing_str = ', '.join(missing)
            raise Exception( "Cannot save %s '%s' - missing settings: '%s'." % (type(self), self._id, missing_str) )

        props = self._props.keys()
        values = list(self._props.values())
        if self.in_db:
            prep_statement = "UPDATE " + self._db_table + " SET " + '=?, '.join(props) + "=? " + self._where_id()
            self._exec(prep_statement, values + [self._id])
        else:
            prep_statement = "INSERT INTO {0} ({1}, {2}) VALUES (?{3})".format(
                                    self._db_table,
                                    self._id_key,
                                    ', '.join(props),
                                    ',?' * len(props)
                                )
            lastid = self._exec(prep_statement, [self._id] + values)
            if self._id is None:
                self._id = lastid
            self._in_db = True

class AgedKeyedSqliteThing(KeyedSqliteThing):
    def __init__(self, connector, birth_time_prop, id):
        super(AgedKeyedSqliteThing, self).__init__(connector, id, [birth_time_prop])
        self._birth_time_prop = birth_time_prop

    def _get_time_property(self, name):
        if name not in self._props:
            return None
        time_str = self._props[name]
        dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        return dt

    def _set_time_property(self, name, dt):
        time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
        self.__setattr__(name, time_str)

    @property
    def age(self):
        if not self.in_db:
            return timedelta()
        else:
            birth = self._get_time_property(self._birth_time_prop)
            age = datetime.utcnow() - birth
            return age

class PendingSend(AgedKeyedSqliteThing):
    @classmethod
    def Unsent(cls, connector, max_retry = 5, max_results = 50):
        conn = connector()
        cur  = conn.cursor()
        args = (max_retry, max_results)

        cur.execute("SELECT id FROM outbox WHERE retry_count<? AND sent_time is null ORDER BY request_time ASC LIMIT ?", args)
        rows = cur.fetchall()
        for row in rows:
            id = row[0]
            yield PendingSend(connector, id)

    _db_table = 'outbox'
    _db_required_props = ['toaddr', 'template_name', 'template_vars_json']
    _db_optional_props = ['last_error', 'retry_count', 'sent_time']

    def __init__(self, connector, id = None):
        super(PendingSend, self).__init__(connector, 'request_time', id)

    @property
    def retry_count(self):
        return self._props.get('retry_count', 0)

    @property
    def template_vars(self):
        raw = self._props.get('template_vars_json', None)
        if raw is not None:
            vars = json.loads(raw)
            return vars
        return None

    @template_vars.setter
    def template_vars(self, value):
        str = json.dumps(value)
        self._props['template_vars_json'] = str

    @property
    def is_sent(self):
        return self.sent_time is not None

    @property
    def sent_time(self):
        return self._get_time_property('sent_time')

    def mark_sent(self):
        self._set_time_property('sent_time', datetime.now())

    def retried(self):
        self.retry_count += 1
