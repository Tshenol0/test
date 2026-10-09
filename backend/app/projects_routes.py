import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from . import docker_manager, generator, schemas
from .auth import get_current_user
from .database import SessionLocal, get_db
from .models import Project, User

logger = logging.getLogger("projects")
router = APIRouter(prefix="/projects", tags=["projects"])


def _subdomain_exists(db: Session, candidate: str) -> bool:
    return db.query(Project).filter(Project.subdomain == candidate).first() is not None


def _parse_project_id(project_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("", response_model=schemas.ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    project_in: schemas.ProjectCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    subdomain = generator.make_unique_subdomain(
        project_in.name, lambda candidate: _subdomain_exists(db, candidate)
    )
    category = generator.detect_category(project_in.description)

    project = Project(
        owner_id=current_user.id,
        name=project_in.name,
        subdomain=subdomain,
        description=project_in.description,
        category=category,
        status="created",
        db_name=f"app_{subdomain.replace('-', '_')}",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    background_tasks.add_task(_deploy_project, project.id)
    return project


def _deploy_project(project_id) -> None:
    """Runs in the background: generate -> create db -> build -> run.
    Uses its own DB session since it runs outside the request lifecycle."""

    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if project is None:
            return

        try:
            project.status = "generating"
            db.commit()

            generated = generator.generate_site(project.name, project.description)
            source_dir = docker_manager.write_files(project.subdomain, generated["files"])

            project.status = "building"
            db.commit()

            docker_manager.create_app_database(project.db_name, generated["init_sql"])
            container_name, url = docker_manager.build_and_run(
                project.subdomain, source_dir, project.db_name
            )

            project.status = "running"
            project.container_name = container_name
            project.url = url
            project.status_detail = None
            db.commit()
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            logger.exception("Deploy failed for project %s", project_id)
            project.status = "failed"
            project.status_detail = str(exc)[:500]
            db.commit()
    finally:
        db.close()


@router.get("", response_model=list[schemas.ProjectOut])
def list_projects(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return (
        db.query(Project)
        .filter(Project.owner_id == current_user.id)
        .order_by(Project.created_at.desc())
        .all()
    )


@router.get("/{project_id}", response_model=schemas.ProjectOut)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .filter(Project.id == _parse_project_id(project_id), Project.owner_id == current_user.id)
        .first()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/redeploy", response_model=schemas.ProjectOut)
def redeploy_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .filter(Project.id == _parse_project_id(project_id), Project.owner_id == current_user.id)
        .first()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    project.status = "generating"
    db.commit()
    db.refresh(project)
    background_tasks.add_task(_deploy_project, project.id)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .filter(Project.id == _parse_project_id(project_id), Project.owner_id == current_user.id)
        .first()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.container_name:
        docker_manager.stop_and_remove(project.container_name)
    if project.db_name:
        docker_manager.drop_app_database(project.db_name)

    db.delete(project)
    db.commit()
    return None
