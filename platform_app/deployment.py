"""Native server configuration, one-time administrator setup and Waitress entry point."""
import argparse
from contextlib import closing
import getpass
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import uuid
import sys

from flask import abort, request
from werkzeug.security import generate_password_hash, check_password_hash

from . import store


def validate_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 200 or password == 'LocalDemo2026!':
        raise ValueError('Use a new password of 12–200 characters; the demo password is forbidden.')


def initialize_admin(data_dir, username, name, password):
    validate_password(password)
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,64}', username) or not name.strip():
        raise ValueError('Invalid administrator username or name.')
    data_dir = Path(data_dir).resolve()
    if data_dir.exists():
        raise ValueError('Initialization requires a new data directory; existing data is never reset.')
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.initialize-', dir=data_dir.parent))
    try:
        store.initialize(temporary, mode='production')
        with closing(store.connect(temporary / 'platform.sqlite3')) as db, db:
            db.execute('INSERT INTO users(id,username,name,password_hash,role) VALUES(?,?,?,?,?)',
                       (uuid.uuid4().hex, username, name.strip(), generate_password_hash(password), 'admin'))
            db.execute("INSERT OR REPLACE INTO settings VALUES('ai_paused','1')")
        shutil.rmtree(temporary / 'backups', ignore_errors=True)
        temporary.rename(data_dir)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def default_password_users(data_dir):
    with closing(store.connect(Path(data_dir) / 'platform.sqlite3')) as db:
        return [dict(row) for row in db.execute('SELECT id,username,role,password_hash FROM users WHERE active=1')
                if check_password_hash(row['password_hash'], 'LocalDemo2026!')]


def configure_lan_admin(data_dir, password):
    """Replace only a still-default demo admin; disable other still-default demo accounts."""
    validate_password(password)
    with closing(store.connect(Path(data_dir) / 'platform.sqlite3')) as db, db:
        db.execute('BEGIN IMMEDIATE')
        rows = list(db.execute('SELECT * FROM users WHERE active=1'))
        admins = [r for r in rows if r['role'] == 'admin']
        if not any(check_password_hash(r['password_hash'], 'LocalDemo2026!') for r in admins):
            raise ValueError('Administrator is already configured. Use existing member management to change accounts.')
        for row in rows:
            if check_password_hash(row['password_hash'], 'LocalDemo2026!'):
                if row['role'] == 'admin':
                    db.execute('UPDATE users SET password_hash=?,credential_version=credential_version+1 WHERE id=?',
                               (generate_password_hash(password), row['id']))
                else:
                    db.execute('UPDATE users SET active=0,credential_version=credential_version+1 WHERE id=?', (row['id'],))


def load_config(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding='utf-8'))
    if set(config) != {'data_dir', 'log_dir', 'hosts', 'listen', 'trusted_proxy'}:
        raise ValueError('Configuration must contain exactly data_dir, log_dir, hosts, listen, trusted_proxy.')
    for key in ('data_dir', 'log_dir'):
        if not Path(config[key]).is_absolute():
            raise ValueError(key + ' must be an absolute path outside the release directory.')
    hosts = config['hosts']
    if not isinstance(hosts, list) or not hosts or any(not isinstance(h, str) or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', h) or h.endswith('.') for h in hosts):
        raise ValueError('Set exact hostnames or IPv4 addresses; wildcards and ports are forbidden.')
    if not re.fullmatch(r'127\.0\.0\.1:(\d{1,5})', config['listen']):
        raise ValueError('Formal Web must listen behind the local TLS reverse proxy at 127.0.0.1:port.')
    port = int(config['listen'].rsplit(':', 1)[1])
    if not 1024 <= port <= 65535 or port == 8848:
        raise ValueError('Choose an unprivileged port other than 8848.')
    if config['trusted_proxy'] is not None and str(ipaddress.ip_address(config['trusted_proxy'])) != '127.0.0.1':
        raise ValueError('Only the explicitly configured local reverse proxy is supported.')
    return config


def application(config):
    from .web import create_app
    data = Path(config['data_dir'])
    if not (data / 'platform.sqlite3').is_file():
        raise ValueError('Run init before starting Web or worker.')
    app = create_app(data, initialization_mode='production', embedded_worker=False)
    if default_password_users(data):
        raise ValueError('Active default demo credentials must be replaced or disabled before server use.')
    app.config.update(TRUSTED_HOSTS=config['hosts'], SESSION_COOKIE_SECURE=True, DEMO_LOGIN=False)

    @app.before_request
    def require_https():
        # Waitress applies only its explicitly trusted proxy's forwarded scheme.
        forwarding = {k for k in request.environ if k.startswith('HTTP_X_FORWARDED_') or k == 'HTTP_FORWARDED'}
        if forwarding - {'HTTP_X_FORWARDED_PROTO'}:
            abort(400, 'Unexpected forwarding headers.')
        forwarded = bool(forwarding)
        if forwarded and request.remote_addr != config['trusted_proxy']:
            abort(400, 'Untrusted forwarding headers.')
        if not request.is_secure:
            abort(400, 'HTTPS reverse proxy required.')

    return app


def configure_logging(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / 'service.log', maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'web', 'worker', 'worker-stop', 'worker-status', 'import-public'])
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--username')
    parser.add_argument('--name')
    parser.add_argument('--password-stdin', action='store_true', help='Read secret line(s) from an explicit private pipe; never pass a password argument.')
    args = parser.parse_args(argv)
    def read_password(prompt):
        return sys.stdin.readline().rstrip('\r\n') if args.password_stdin else getpass.getpass(prompt)
    try:
        config = load_config(args.config)
        if args.action == 'init':
            username = args.username or input('Administrator username: ')
            name = args.name or input('Administrator name: ')
            password = read_password('New administrator password (12–200 characters): ')
            if password != read_password('Repeat password: '):
                raise ValueError('Passwords differ.')
            initialize_admin(config['data_dir'], username, name, password)
            print('Administrator initialized. No demo accounts or sample records were created.')
            return
        if args.action == 'import-public':
            from portable.public_batch import import_public
            username = args.username or input('Authorized administrator username: ')
            print(json.dumps(import_public(config['data_dir'], username, read_password('Password: ')), ensure_ascii=False))
            return
        if args.action.startswith('worker'):
            from .worker_service import command
            command(args.action, config)
            return
        from waitress import serve
        configure_logging(config['log_dir'])
        proxy = config['trusted_proxy']
        from .worker_service import process_lock
        with process_lock(Path(config['data_dir']) / '.web.lock'):
            app = application(config)
            serve(app, listen=config['listen'], threads=6, trusted_proxy=proxy,
                  trusted_proxy_count=1, trusted_proxy_headers={'x-forwarded-proto'} if proxy else set(),
                  clear_untrusted_proxy_headers=False, ident='ResearchCommons')
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
