"""Persist manual observations without treating them as safety certifications."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile


class Session:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix='session-', dir=directory))
        self.previous = '0' * 64

    def record(self, event, data):
        record = {'time': datetime.now(timezone.utc).isoformat(), 'event': event, 'data': data,
                  'previous': self.previous, 'flash_approved': False}
        raw = json.dumps(record, sort_keys=True).encode()
        record['hash'] = hashlib.sha256(raw).hexdigest()
        with (self.path / 'events.jsonl').open('a') as log:
            log.write(json.dumps(record, sort_keys=True) + '\n')
            log.flush()
            os.fsync(log.fileno())
        self.previous = record['hash']
        return record

    @staticmethod
    def inspect(path):
        """Integrity check only. A hash chain is not an authenticated signature."""
        previous = '0' * 64
        records = []
        for line in Path(path).read_text().splitlines():
            record = json.loads(line)
            claimed = record.pop('hash')
            actual = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            if record['previous'] != previous or actual != claimed:
                raise ValueError('Session log integrity check failed')
            previous = claimed
            record['hash'] = claimed
            records.append(record)
        return records
