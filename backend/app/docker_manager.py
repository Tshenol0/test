"""
Handles the "Build application -> Docker container -> Deploy" steps.

Talks to the *host's* Docker daemon over the socket mounted into this
container (docker-compose mounts /var/run/docker.sock). This is the
standard "sibling containers" pattern used by self-hosted PaaS tools
(Dokku, Coolify, CapRover): the backend is itself a container, but the
containers it creates for tenant sites are siblings on the host, not
nested inside it.

Security note: giving a container access to the host's Docker socket is
equivalent to giving it root on the host. That's fine for a personal/demo
PaaS; a production version would put a narrowly-scoped build/deploy
service behind this instead of talking to the socket directly.
"""

import os

import docker
import psycopg2
from docker.errors import NotFound

BASE_DOMAIN = os.getenv("BASE_DOMAIN", "yourpaas.localhost")
WEB_NETWORK = os.getenv("WEB_NETWORK", "paas_web")
GENERATED_APPS_DIR = os.getenv("GENERATED_APPS_DIR", "/generated-apps")

APPS_DB_HOST = os.getenv("APPS_DB_HOST", "apps-db")
APPS_DB_PORT = os.getenv("APPS_DB_PORT", "5432")
APPS_DB_ADMIN_USER = os.getenv("APPS_DB_ADMIN_USER", "apps_admin")
APPS_DB_ADMIN_PASSWORD = os.getenv("APPS_DB_ADMIN_PASSWORD", "appspassword")


def _docker_client():
    return docker.from_env()


def project_dir(subdomain: str) -> str:
    return os.path.join(GENERATED_APPS_DIR, subdomain)


def write_files(subdomain: str, files: dict) -> str:
    target_dir = project_dir(subdomain)
    for relative_path, contents in files.items():
        full_path = os.path.join(target_dir, relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(contents)
    return target_dir


def create_app_database(db_name: str, init_sql: str) -> None:
    """Creates a fresh database on the shared apps-db instance and runs
    the generated app's schema/seed script against it."""

    admin_conn = psycopg2.connect(
        host=APPS_DB_HOST,
        port=APPS_DB_PORT,
        user=APPS_DB_ADMIN_USER,
        password=APPS_DB_ADMIN_PASSWORD,
        dbname="postgres",
    )
    admin_conn.autocommit = True  # CREATE DATABASE can't run in a transaction
    try:
        with admin_conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            cur.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        admin_conn.close()

    app_conn = psycopg2.connect(
        host=APPS_DB_HOST,
        port=APPS_DB_PORT,
        user=APPS_DB_ADMIN_USER,
        password=APPS_DB_ADMIN_PASSWORD,
        dbname=db_name,
    )
    app_conn.autocommit = True
    try:
        with app_conn.cursor() as cur:
            cur.execute(init_sql)
    finally:
        app_conn.close()


def drop_app_database(db_name: str) -> None:
    admin_conn = psycopg2.connect(
        host=APPS_DB_HOST,
        port=APPS_DB_PORT,
        user=APPS_DB_ADMIN_USER,
        password=APPS_DB_ADMIN_PASSWORD,
        dbname="postgres",
    )
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    finally:
        admin_conn.close()


def build_and_run(subdomain: str, source_dir: str, db_name: str) -> tuple[str, str]:
    """Builds the image from source_dir and (re)starts the container,
    attached to the shared network with Traefik routing labels.
    Returns (container_name, url).
    """

    client = _docker_client()
    image_tag = f"paas-app-{subdomain}:latest"
    container_name = f"paas-app-{subdomain}"
    router_name = subdomain.replace(".", "-")

    client.images.build(path=source_dir, tag=image_tag, rm=True)

    try:
        old = client.containers.get(container_name)
        old.remove(force=True)
    except NotFound:
        pass

    db_url = (
        f"postgresql://{APPS_DB_ADMIN_USER}:{APPS_DB_ADMIN_PASSWORD}"
        f"@{APPS_DB_HOST}:{APPS_DB_PORT}/{db_name}"
    )

    labels = {
        "traefik.enable": "true",
        f"traefik.http.routers.{router_name}.rule": f"Host(`{subdomain}.{BASE_DOMAIN}`)",
        f"traefik.http.routers.{router_name}.entrypoints": "web",
        f"traefik.http.services.{router_name}.loadbalancer.server.port": "8000",
    }

    client.containers.run(
        image_tag,
        name=container_name,
        detach=True,
        network=WEB_NETWORK,
        labels=labels,
        environment={"DATABASE_URL": db_url},
        restart_policy={"Name": "unless-stopped"},
    )

    url = f"http://{subdomain}.{BASE_DOMAIN}"
    return container_name, url


def stop_and_remove(container_name: str) -> None:
    client = _docker_client()
    try:
        container = client.containers.get(container_name)
        container.remove(force=True)
    except NotFound:
        pass
